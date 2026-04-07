"""Balanced ARC-Aware Partitioning for hierarchical LBBD decomposition.

Replaces the naive Union-Find clustering in the original LBBD solver with a
size-controlled graph partitioning strategy.  The algorithm ensures that each
machine cluster sent to a CP-SAT subproblem contains at most
``max_ops_per_cluster`` operations, keeping circuit-graph construction at
O(N²) per machine within the CP-SAT comfort zone (≤ 40 000 arcs).

Academic basis:
    - Hooker & Ottosson (2003): LBBD framework and capacity cuts.
    - Naderi & Roshanaei (2022): Critical-path-search LBBD for FJSP.
    - Karypis & Kumar (1998): Multilevel graph partitioning (METIS idea).
    - Schlenkrich & Parragh (2023): Survey of large-scale scheduling decomposition.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from synaps.model import OperationAuxRequirement, ScheduleProblem


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def partition_machines(
    problem: ScheduleProblem,
    assignment_map: dict[UUID, UUID],
    *,
    max_ops_per_cluster: int = 200,
) -> list[set[UUID]]:
    """Partition machines into balanced clusters respecting ARC links.

    Strategy (3 phases, inspired by multilevel partitioning):

    1. **Coarsening**: Build an undirected ARC-affinity graph where vertices
       are machines and edge weights reflect the number of operations sharing
       auxiliary resources across those machines.  Merge strongly connected
       components first (guaranteed co-scheduling).

    2. **Initial partitioning**: Greedy bin-packing — assign merged super-nodes
       to clusters, splitting when the operation count would exceed
       *max_ops_per_cluster*.

    3. **Refinement**: For each over-limit cluster, sort machines by operation
       count descending and split off the heaviest machines into new clusters
       until the cap is satisfied.

    Unchanged invariant vs. the original Union-Find: operations linked by
    shared auxiliary resources are **preferentially** co-clustered.  When the
    hard cap forces a split, the cross-cluster ARC constraint becomes a
    relaxed cumulative constraint in the master problem (the caller handles
    this via nogood / capacity cuts).

    Args:
        problem: Full scheduling problem (for ARC requirements).
        assignment_map: Operation → work-center assignment from the master.
        max_ops_per_cluster: Hard cap on operations per cluster.

    Returns:
        List of machine-id sets, one per cluster.
    """
    if not assignment_map:
        return []

    ops_per_machine = _count_ops_per_machine(assignment_map)
    all_machines = set(assignment_map.values())

    if not all_machines:
        return []

    # Phase 1: Coarsening — build ARC affinity graph and merge SCCs
    arc_graph = _build_arc_affinity_graph(problem.aux_requirements, assignment_map)
    merged_groups = _merge_strongly_connected(arc_graph, all_machines)

    # Phase 2: Greedy bin-packing into clusters
    clusters = _greedy_bin_pack(merged_groups, ops_per_machine, max_ops_per_cluster)

    # Phase 3: Refinement — split over-limit clusters
    refined: list[set[UUID]] = []
    for cluster in clusters:
        cluster_ops = sum(ops_per_machine.get(m, 0) for m in cluster)
        if cluster_ops <= max_ops_per_cluster:
            refined.append(cluster)
        else:
            refined.extend(
                _split_cluster(cluster, ops_per_machine, max_ops_per_cluster)
            )

    # Remove empty clusters
    return [c for c in refined if c]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _count_ops_per_machine(assignment_map: dict[UUID, UUID]) -> dict[UUID, int]:
    """Count how many operations are assigned to each machine."""
    counts: dict[UUID, int] = defaultdict(int)
    for _op_id, wc_id in assignment_map.items():
        counts[wc_id] += 1
    return dict(counts)


def _build_arc_affinity_graph(
    aux_requirements: list[OperationAuxRequirement],
    assignment_map: dict[UUID, UUID],
) -> dict[UUID, dict[UUID, int]]:
    """Build weighted undirected graph: machine → machine → shared-ARC-op count.

    Two machines share an ARC edge if they have operations that require the
    same auxiliary resource.  Edge weight = number of such shared operations.
    """
    # aux_resource → set of machines that have ops needing it
    resource_to_machines: dict[UUID, dict[UUID, int]] = defaultdict(lambda: defaultdict(int))
    for req in aux_requirements:
        wc_id = assignment_map.get(req.operation_id)
        if wc_id is not None:
            resource_to_machines[req.aux_resource_id][wc_id] += 1

    graph: dict[UUID, dict[UUID, int]] = defaultdict(lambda: defaultdict(int))
    for _resource_id, machine_counts in resource_to_machines.items():
        machines = list(machine_counts.keys())
        for i in range(len(machines)):
            for j in range(i + 1, len(machines)):
                m1, m2 = machines[i], machines[j]
                weight = min(machine_counts[m1], machine_counts[m2])
                graph[m1][m2] += weight
                graph[m2][m1] += weight

    return dict(graph)


def _merge_strongly_connected(
    arc_graph: dict[UUID, dict[UUID, int]],
    all_machines: set[UUID],
) -> list[set[UUID]]:
    """Merge machines into super-groups via connected components on ARC graph.

    Uses iterative BFS on the ARC affinity graph.  All machines in the same
    connected component are grouped together (they share transitive ARC
    dependencies and should ideally be co-scheduled).
    """
    visited: set[UUID] = set()
    groups: list[set[UUID]] = []

    for machine in all_machines:
        if machine in visited:
            continue
        # BFS from this machine
        component: set[UUID] = set()
        frontier = [machine]
        while frontier:
            current = frontier.pop()
            if current in visited:
                continue
            visited.add(current)
            component.add(current)
            for neighbor in arc_graph.get(current, {}):
                if neighbor not in visited and neighbor in all_machines:
                    frontier.append(neighbor)
        groups.append(component)

    # Also add isolated machines (no ARC edges)
    for machine in all_machines:
        if machine not in visited:
            groups.append({machine})
            visited.add(machine)

    return groups


def _greedy_bin_pack(
    groups: list[set[UUID]],
    ops_per_machine: dict[UUID, int],
    max_ops: int,
) -> list[set[UUID]]:
    """Pack merged super-groups into clusters using first-fit-decreasing.

    Sort groups by total ops descending, then place each group into the first
    cluster that can accommodate it.  If no cluster fits, create a new one.
    Groups that are individually over the limit are added as-is (will be split
    in the refinement phase).
    """
    # Sort by group size (total ops) descending for better packing
    sorted_groups = sorted(
        groups,
        key=lambda g: sum(ops_per_machine.get(m, 0) for m in g),
        reverse=True,
    )

    clusters: list[set[UUID]] = []
    cluster_sizes: list[int] = []

    for group in sorted_groups:
        group_size = sum(ops_per_machine.get(m, 0) for m in group)

        # Try to fit into existing cluster
        placed = False
        for idx, current_size in enumerate(cluster_sizes):
            if current_size + group_size <= max_ops:
                clusters[idx].update(group)
                cluster_sizes[idx] += group_size
                placed = True
                break

        if not placed:
            clusters.append(set(group))
            cluster_sizes.append(group_size)

    return clusters


def _split_cluster(
    cluster: set[UUID],
    ops_per_machine: dict[UUID, int],
    max_ops: int,
) -> list[set[UUID]]:
    """Split an over-limit cluster into smaller pieces.

    Sort machines by operation count descending.  Greedily fill new sub-clusters.
    If a single machine exceeds the cap, it becomes its own cluster (the CP-SAT
    subproblem solver will handle it with its internal time limit).
    """
    machines_sorted = sorted(
        cluster,
        key=lambda m: ops_per_machine.get(m, 0),
        reverse=True,
    )

    result: list[set[UUID]] = []
    current_cluster: set[UUID] = set()
    current_size = 0

    for machine in machines_sorted:
        machine_ops = ops_per_machine.get(machine, 0)

        if machine_ops > max_ops:
            # Single machine exceeds cap — give it its own cluster
            if current_cluster:
                result.append(current_cluster)
                current_cluster = set()
                current_size = 0
            result.append({machine})
            continue

        if current_size + machine_ops > max_ops:
            if current_cluster:
                result.append(current_cluster)
            current_cluster = {machine}
            current_size = machine_ops
        else:
            current_cluster.add(machine)
            current_size += machine_ops

    if current_cluster:
        result.append(current_cluster)

    return result


__all__ = ["partition_machines"]
