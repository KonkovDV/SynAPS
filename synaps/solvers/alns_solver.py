"""ALNS Solver — Adaptive Large Neighborhood Search with Micro-CP-SAT repair.

Scales to 50 000+ operations by iteratively destroying and repairing
sub-regions of a schedule, using exact CP-SAT as the repair operator.

Academic basis:
    - Shaw (1998): Original LNS for VRP
    - Ropke & Pisinger (2006, Transportation Science): ALNS adaptive operator selection
    - Laborie & Godard (2007, CPAIOR): LNS + CP for scheduling
    - Matsuzaki et al. (2024, J. Supercomputing): LNS + MIP for large-scale machining
    - Deng et al. (2026, Memetic Computing): Improved ALNS for distributed scheduling
"""

from __future__ import annotations

import logging
import math
import random
import time
from collections import deque
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

from synaps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from synaps.solvers import BaseSolver
from synaps.solvers._dispatch_support import (
    MachineIndex,
    build_dispatch_context,
    find_earliest_feasible_slot,
    recompute_assignment_setups,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False
from synaps.solvers.lower_bounds import compute_relaxed_makespan_lower_bound
from synaps.solvers.sdst_matrix import SdstMatrix

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


class RepairStatus(str, Enum):
    """Structured repair status for ALNS repair operators."""

    FEASIBLE = "feasible"
    TIMEOUT = "timeout"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class RepairOutcome:
    """Explicit repair outcome carrying status, payload, and reason."""

    status: RepairStatus
    assignments: tuple[Assignment, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class AlnsIterationRecord:
    """Per-iteration ALNS metrics record for convergence diagnostics.

    Used when ``record_iteration_metrics=True`` to capture a bounded trace
    (max 500 records) of the ALNS search trajectory.
    """

    iteration: int
    operator_name: str
    destroy_size: int
    repair_status: str  # "feasible", "timeout", "infeasible"
    candidate_cost: float
    best_cost: float
    temperature: float
    accepted: bool
    improved: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for metadata embedding."""
        return {
            "iteration": self.iteration,
            "operator_name": self.operator_name,
            "destroy_size": self.destroy_size,
            "repair_status": self.repair_status,
            "candidate_cost": self.candidate_cost,
            "best_cost": self.best_cost,
            "temperature": self.temperature,
            "accepted": self.accepted,
            "improved": self.improved,
        }


# ---------------------------------------------------------------------------
# Objective evaluation
# ---------------------------------------------------------------------------


def _evaluate_objective(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    sdst: SdstMatrix,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> ObjectiveValues:
    """Compute multi-objective values from a set of assignments."""
    if not assignments:
        return ObjectiveValues()

    horizon_start = problem.planning_horizon_start
    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    # Makespan
    makespan = max((a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments)

    # Setup and material loss from machine sequences
    total_setup = 0.0
    total_material_loss = 0.0
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for wc_id, machine_assignments in by_machine.items():
        machine_assignments.sort(key=lambda a: a.start_time)
        for i in range(1, len(machine_assignments)):
            prev_state = ops_by_id[machine_assignments[i - 1].operation_id].state_id
            curr_state = ops_by_id[machine_assignments[i].operation_id].state_id
            total_setup += sdst.get_setup(wc_id, prev_state, curr_state)
            total_material_loss += sdst.get_material_loss(wc_id, prev_state, curr_state)

    # Tardiness
    order_completion: dict[Any, float] = {}
    for a in assignments:
        op = ops_by_id[a.operation_id]
        end = (a.end_time - horizon_start).total_seconds() / 60.0
        if op.order_id not in order_completion or end > order_completion[op.order_id]:
            order_completion[op.order_id] = end
    total_tardiness = 0.0
    for order in problem.orders:
        completion = order_completion.get(order.id, 0.0)
        due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
        total_tardiness += max(completion - due_offset, 0.0)

    return ObjectiveValues(
        makespan_minutes=makespan,
        total_setup_minutes=total_setup,
        total_material_loss=total_material_loss,
        total_tardiness_minutes=total_tardiness,
    )


def _objective_cost(obj: ObjectiveValues, weights: dict[str, float]) -> float:
    """Scalar cost from multi-objective values."""
    return (
        weights.get("makespan", 1.0) * obj.makespan_minutes
        + weights.get("setup", 0.3) * obj.total_setup_minutes
        + weights.get("material_loss", 0.2) * obj.total_material_loss
        + weights.get("tardiness", 0.5) * obj.total_tardiness_minutes
    )


# ---------------------------------------------------------------------------
# Incremental objective evaluation (P2.1 — avoids full re-sort every iter)
# ---------------------------------------------------------------------------


@dataclass
class _MachineObjectiveCache:
    """Per-machine cached objective components for incremental ALNS evaluation."""

    # Per-machine makespan (max end offset), setup, and material loss
    machine_makespan: dict[Any, float]
    machine_setup: dict[Any, float]
    machine_loss: dict[Any, float]
    # Aggregate totals
    total_makespan: float
    total_setup: float
    total_material_loss: float
    total_tardiness: float
    # Pre-computed order completion offsets
    order_completion: dict[Any, float]
    # Pre-computed order due offsets (minutes from horizon_start)
    order_due_offsets: dict[Any, float]


def _build_machine_objective_cache(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    sdst: SdstMatrix,
    *,
    ops_by_id: dict[Any, Any],
    horizon_start: Any,
    order_due_offsets: dict[Any, float] | None = None,
) -> _MachineObjectiveCache:
    """Build per-machine cache for incremental objective evaluation."""
    machine_makespan: dict[Any, float] = {}
    machine_setup: dict[Any, float] = {}
    machine_loss: dict[Any, float] = {}

    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)

    for wc_id, ma in by_machine.items():
        ma.sort(key=lambda a: a.start_time)
        machine_makespan[wc_id] = max(
            (a.end_time - horizon_start).total_seconds() / 60.0 for a in ma
        )
        setup = 0.0
        loss = 0.0
        for i in range(1, len(ma)):
            prev_state = ops_by_id[ma[i - 1].operation_id].state_id
            curr_state = ops_by_id[ma[i].operation_id].state_id
            setup += sdst.get_setup(wc_id, prev_state, curr_state)
            loss += sdst.get_material_loss(wc_id, prev_state, curr_state)
        machine_setup[wc_id] = setup
        machine_loss[wc_id] = loss

    total_makespan = max(machine_makespan.values()) if machine_makespan else 0.0
    total_setup = sum(machine_setup.values())
    total_material_loss = sum(machine_loss.values())

    order_completion: dict[Any, float] = {}
    for a in assignments:
        op = ops_by_id[a.operation_id]
        end = (a.end_time - horizon_start).total_seconds() / 60.0
        if op.order_id not in order_completion or end > order_completion[op.order_id]:
            order_completion[op.order_id] = end

    if order_due_offsets is None:
        order_due_offsets = {
            order.id: (order.due_date - horizon_start).total_seconds() / 60.0
            for order in problem.orders
        }

    total_tardiness = 0.0
    for order in problem.orders:
        completion = order_completion.get(order.id, 0.0)
        total_tardiness += max(completion - order_due_offsets[order.id], 0.0)

    return _MachineObjectiveCache(
        machine_makespan=machine_makespan,
        machine_setup=machine_setup,
        machine_loss=machine_loss,
        total_makespan=total_makespan,
        total_setup=total_setup,
        total_material_loss=total_material_loss,
        total_tardiness=total_tardiness,
        order_completion=order_completion,
        order_due_offsets=order_due_offsets,
    )


def _evaluate_objective_incremental(
    problem: ScheduleProblem,
    candidate: list[Assignment],
    sdst: SdstMatrix,
    *,
    ops_by_id: dict[Any, Any],
    horizon_start: Any,
    affected_machine_ids: set[Any],
    base_cache: _MachineObjectiveCache,
) -> tuple[ObjectiveValues, _MachineObjectiveCache]:
    """Recompute objective only for affected machines, reusing cached values.

    Returns the new ObjectiveValues and an updated cache for the candidate.
    """
    # Rebuild only affected machines
    affected_assignments: dict[Any, list[Assignment]] = {}
    for a in candidate:
        if a.work_center_id in affected_machine_ids:
            affected_assignments.setdefault(a.work_center_id, []).append(a)

    new_machine_makespan = dict(base_cache.machine_makespan)
    new_machine_setup = dict(base_cache.machine_setup)
    new_machine_loss = dict(base_cache.machine_loss)

    # Remove affected machines that may now be empty
    for wc_id in affected_machine_ids:
        if wc_id not in affected_assignments:
            new_machine_makespan.pop(wc_id, None)
            new_machine_setup.pop(wc_id, None)
            new_machine_loss.pop(wc_id, None)

    for wc_id, ma in affected_assignments.items():
        ma.sort(key=lambda a: a.start_time)
        new_machine_makespan[wc_id] = max(
            (a.end_time - horizon_start).total_seconds() / 60.0 for a in ma
        )
        setup = 0.0
        loss = 0.0
        for i in range(1, len(ma)):
            prev_state = ops_by_id[ma[i - 1].operation_id].state_id
            curr_state = ops_by_id[ma[i].operation_id].state_id
            setup += sdst.get_setup(wc_id, prev_state, curr_state)
            loss += sdst.get_material_loss(wc_id, prev_state, curr_state)
        new_machine_setup[wc_id] = setup
        new_machine_loss[wc_id] = loss

    total_makespan = max(new_machine_makespan.values()) if new_machine_makespan else 0.0
    total_setup = sum(new_machine_setup.values())
    total_material_loss = sum(new_machine_loss.values())

    # Recompute order completion (affected operations may change order completion)
    new_order_completion = dict(base_cache.order_completion)
    # Reset affected orders' completion to re-scan
    affected_order_ids: set[Any] = set()
    for a in candidate:
        if a.work_center_id in affected_machine_ids:
            op = ops_by_id[a.operation_id]
            affected_order_ids.add(op.order_id)

    # Re-derive completion for affected orders from all assignments
    for oid in affected_order_ids:
        new_order_completion[oid] = 0.0
    for a in candidate:
        op = ops_by_id[a.operation_id]
        if op.order_id in affected_order_ids:
            end = (a.end_time - horizon_start).total_seconds() / 60.0
            if end > new_order_completion.get(op.order_id, 0.0):
                new_order_completion[op.order_id] = end

    total_tardiness = 0.0
    order_due_offsets = base_cache.order_due_offsets
    for order in problem.orders:
        completion = new_order_completion.get(order.id, 0.0)
        total_tardiness += max(completion - order_due_offsets[order.id], 0.0)

    obj = ObjectiveValues(
        makespan_minutes=total_makespan,
        total_setup_minutes=total_setup,
        total_material_loss=total_material_loss,
        total_tardiness_minutes=total_tardiness,
    )

    new_cache = _MachineObjectiveCache(
        machine_makespan=new_machine_makespan,
        machine_setup=new_machine_setup,
        machine_loss=new_machine_loss,
        total_makespan=total_makespan,
        total_setup=total_setup,
        total_material_loss=total_material_loss,
        total_tardiness=total_tardiness,
        order_completion=new_order_completion,
        order_due_offsets=order_due_offsets,
    )
    return obj, new_cache


# ---------------------------------------------------------------------------
# Destroy operators
#   random     — uniform random removal
#   worst      — removal by machine-local setup contribution
#                (Shaw 1998; Ropke & Pisinger 2006, Transportation Science)
#   related    — Shaw relatedness removal seeded by a random anchor
#                (Shaw 1998)
#   machine_segment — contiguous segment removal from one machine
#                to break high-cost setup chains (domain heuristic)
#   precedence_chain — R8 order-based ejection chain removal
#                (Voudouris & Tsang 1999; Ropke & Pisinger 2006 §3.3)
#   critical_path — longest-path bottleneck-chain removal via topological DP
#                (Kelley & Walker 1959; Adams, Balas & Zawack 1988)
# ---------------------------------------------------------------------------


def _destroy_random(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> set[UUID]:
    """Remove a random subset of operations."""
    op_ids = [a.operation_id for a in assignments]
    k = min(destroy_size, len(op_ids))
    return set(rng.sample(op_ids, k))


def _destroy_worst(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> set[UUID]:
    """Remove operations contributing the most to setup cost (worst removal).

    Picks operations whose machine-local setup contribution (predecessor→self
    + self→successor) is highest.

    When the native accelerator is available, delegates scoring to Rust for
    parallel per-machine computation. Falls back to the Python reference loop
    when native is unavailable.
    """
    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    # --- Try native scoring path ---
    native_scores = _destroy_worst_native_scores(assignments, sdst, ops_by_id)
    op_cost_by_id: dict[UUID, float]
    if native_scores is not None:
        # native_scores is a dict[UUID, float] of per-operation costs
        op_cost_by_id = native_scores
    else:
        # --- Python reference implementation (authoritative) ---
        by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            by_machine.setdefault(a.work_center_id, []).append(a)

        op_cost_by_id = {}
        for wc_id, machine_assignments in by_machine.items():
            machine_assignments.sort(key=lambda a: a.start_time)
            for i, a in enumerate(machine_assignments):
                cost = 0.0
                op = ops_by_id[a.operation_id]
                if i > 0:
                    prev_op = ops_by_id[machine_assignments[i - 1].operation_id]
                    cost += sdst.get_setup(wc_id, prev_op.state_id, op.state_id)
                    cost += sdst.get_material_loss(wc_id, prev_op.state_id, op.state_id)
                if i < len(machine_assignments) - 1:
                    next_op = ops_by_id[machine_assignments[i + 1].operation_id]
                    cost += sdst.get_setup(wc_id, op.state_id, next_op.state_id)
                    cost += sdst.get_material_loss(wc_id, op.state_id, next_op.state_id)
                op_cost_by_id[a.operation_id] = cost

    # Sort by cost descending, add randomness to avoid deterministic loops
    ranked = sorted(op_cost_by_id.items(), key=lambda x: -x[1])
    destroyed: set[UUID] = set()
    p_worst = 0.8  # probability of picking the worst vs. random from top-50%
    for op_id, _ in ranked:
        if len(destroyed) >= destroy_size:
            break
        if rng.random() < p_worst:
            destroyed.add(op_id)
    # Fill remainder randomly if needed
    remaining_ids = [a.operation_id for a in assignments if a.operation_id not in destroyed]
    while len(destroyed) < destroy_size and remaining_ids:
        pick = rng.choice(remaining_ids)
        destroyed.add(pick)
        remaining_ids.remove(pick)
    return destroyed


def _destroy_worst_native_scores(
    assignments: list[Assignment],
    sdst: SdstMatrix,
    ops_by_id: dict[Any, Any],
) -> dict[UUID, float] | None:
    """Attempt native scoring for _destroy_worst. Returns None if unavailable.

    Builds the CSR machine-sorted structure and delegates to the native
    compute_destroy_worst_scores function. The native function computes
    setup-cost contributions only (not material loss) — matching the design
    spec for the native acceleration path.
    """
    if not _HAS_NUMPY:
        return None

    from synaps.accelerators import compute_destroy_worst_scores_native

    # Build CSR machine grouping sorted by start_time
    by_machine: dict[Any, list[tuple[int, Assignment]]] = {}
    assign_idx_map: dict[UUID, int] = {}
    for idx, a in enumerate(assignments):
        assign_idx_map[a.operation_id] = idx
        by_machine.setdefault(a.work_center_id, []).append((idx, a))

    n_assignments = len(assignments)
    n_machines = len(by_machine)

    # Build CSR offsets and indices
    machine_offsets = np.zeros(n_machines + 1, dtype=np.int64)
    assignment_indices_list: list[int] = []

    for m_idx, (_wc_id, machine_assigns) in enumerate(by_machine.items()):
        # Sort by start_time within each machine
        machine_assigns.sort(key=lambda x: x[1].start_time)
        machine_offsets[m_idx + 1] = machine_offsets[m_idx] + len(machine_assigns)
        for orig_idx, _a in machine_assigns:
            assignment_indices_list.append(orig_idx)

    assignment_indices = np.array(assignment_indices_list, dtype=np.int64)

    # Build per-assignment state indices and wc indices
    state_ids = np.zeros(n_assignments, dtype=np.int64)
    wc_indices = np.zeros(n_assignments, dtype=np.int64)

    for idx, a in enumerate(assignments):
        op = ops_by_id[a.operation_id]
        si = sdst.state_id_to_idx.get(op.state_id, -1)
        wi = sdst.wc_id_to_idx.get(a.work_center_id, -1)
        state_ids[idx] = si
        wc_indices[idx] = wi

    # Flatten SDST setup matrix to float64
    sdst_setup_flat = sdst.setup_minutes.astype(np.float64).ravel()

    result = compute_destroy_worst_scores_native(
        machine_offsets=machine_offsets,
        assignment_indices=assignment_indices,
        state_ids=state_ids,
        sdst_setup_flat=sdst_setup_flat,
        wc_indices=wc_indices,
        n_wc=sdst.n_wc,
        n_states=sdst.n_states,
    )

    if result is None:
        return None

    # Map back to operation UUIDs
    scores: dict[UUID, float] = {}
    for idx, a in enumerate(assignments):
        scores[a.operation_id] = float(result[idx])

    return scores


def _destroy_related(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> set[UUID]:
    """Remove operations that are related to a seed operation (Shaw removal).

    Relatedness = same machine assignment + low setup time + temporal proximity.
    Shaw (1998): operations are related if they share resources and have
    similar processing characteristics.
    """
    if not assignments:
        return set()

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    # Pick random seed
    seed_assignment = rng.choice(assignments)
    seed_op = ops_by_id[seed_assignment.operation_id]
    seed_wc = seed_assignment.work_center_id

    # Score relatedness (lower = more related)
    relatedness: list[tuple[float, UUID]] = []
    for a in assignments:
        if a.operation_id == seed_assignment.operation_id:
            continue
        op = ops_by_id[a.operation_id]
        score = 0.0
        # Same machine bonus
        if a.work_center_id == seed_wc:
            score -= 100.0
        # Low setup between seed and this op
        setup = sdst.get_setup(seed_wc, seed_op.state_id, op.state_id)
        score += setup
        # Similar processing time
        score += abs(op.base_duration_min - seed_op.base_duration_min) * 0.5
        # R7: Temporal proximity — operations closer in time are more related
        # (Ropke & Pisinger 2006: temporal relatedness prevents idle-time gaps
        # from decoupling structurally adjacent operations).
        time_gap_minutes = abs((a.start_time - seed_assignment.start_time).total_seconds() / 60.0)
        score += time_gap_minutes * 0.01
        relatedness.append((score, a.operation_id))

    relatedness.sort(key=lambda x: x[0])
    destroyed: set[UUID] = {seed_assignment.operation_id}
    for _, op_id in relatedness:
        if len(destroyed) >= destroy_size:
            break
        destroyed.add(op_id)
    return destroyed


def _destroy_machine_segment(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> set[UUID]:
    """Remove a contiguous segment of operations from a random machine.

    Effective for reducing setup chains: removing a sequence from one machine
    and re-optimizing the gap.
    """
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)

    # Pick a machine with enough operations
    valid_machines = [
        (wc_id, sorted(ma, key=lambda a: a.start_time))
        for wc_id, ma in by_machine.items()
        if len(ma) >= 3
    ]
    if not valid_machines:
        return _destroy_random(assignments, problem, sdst, destroy_size, rng)

    wc_id, machine_seq = rng.choice(valid_machines)
    seg_size = min(destroy_size, len(machine_seq))
    start_idx = rng.randint(0, len(machine_seq) - seg_size)
    return {machine_seq[i].operation_id for i in range(start_idx, start_idx + seg_size)}


def _destroy_precedence_chain(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> set[UUID]:
    """Remove all operations of a randomly selected order (precedence-chain removal).

    R8 — Forces complete re-sequencing of an entire work order.
    Particularly effective for large instances where a single order occupies
    multiple work centers across many time windows, creating compounding
    sequencing errors.  Voudouris & Tsang (1999) term similar moves
    "ejection chains"; Ropke & Pisinger (2006) §3.3 generalise them as
    order-based removal.
    """
    if not assignments:
        return set()

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}
    ops_by_order: dict[Any, list[UUID]] = {}
    for a in assignments:
        op = ops_by_id.get(a.operation_id)
        if op is None:
            continue
        ops_by_order.setdefault(op.order_id, []).append(a.operation_id)

    if not ops_by_order:
        return _destroy_random(assignments, problem, sdst, destroy_size, rng)

    # Prefer orders that fit fully within destroy_size (clean chain removal)
    valid_orders = [
        (oid, oids) for oid, oids in ops_by_order.items() if 1 <= len(oids) <= destroy_size
    ]
    if valid_orders:
        order_id, op_ids = rng.choice(valid_orders)
        return set(op_ids)

    # Fall back to largest order, capped at destroy_size
    order_id, op_ids = max(ops_by_order.items(), key=lambda x: len(x[1]))
    return set(rng.sample(op_ids, min(destroy_size, len(op_ids))))


def _destroy_critical_path(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> set[UUID]:
    """Remove operations on the critical path of the current schedule.

    Builds a combined DAG of precedence edges and machine-sequence edges
    (sorted by start_time), then computes the longest path via topological
    sort + dynamic programming in O(N + E) time.

    The critical path is the chain from a source node to the makespan-defining
    operation. Destroying it forces ALNS repair to focus on the bottleneck.

    Academic basis:
        - Kelley & Walker (1959): Critical Path Method (CPM)
        - Adams, Balas & Zawack (1988): shifting bottleneck + critical path
          for job-shop scheduling
    """
    if not assignments:
        return set()

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    # Build assignment lookup by operation_id
    assignment_by_op: dict[UUID, Assignment] = {a.operation_id: a for a in assignments}

    # Build machine sequences sorted by start_time
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for wc_id in by_machine:
        by_machine[wc_id].sort(key=lambda a: a.start_time)

    # Build the combined DAG as adjacency list: node -> list of (successor, edge_weight)
    # Node = operation_id (UUID)
    # Edge weight = duration of the source operation (the time it contributes)
    # The longest path length = sum of durations along the path = makespan
    #
    # We use operation duration as node weight. For longest-path DP:
    #   dist[node] = duration[node] + max(dist[successor] for each successor)
    # The critical path ends at the node with the maximum dist value.

    # Compute duration for each assigned operation (in minutes)
    op_duration: dict[UUID, float] = {}
    for a in assignments:
        duration_min = (a.end_time - a.start_time).total_seconds() / 60.0
        op_duration[a.operation_id] = duration_min

    # Build adjacency list (forward edges: predecessor -> successor)
    # Edge types:
    #   1. Precedence edges: op.predecessor_op_id -> op.id
    #   2. Machine-sequence edges: consecutive ops on same machine (by start_time)
    successors: dict[UUID, list[UUID]] = {}
    in_degree: dict[UUID, int] = {}

    assigned_op_ids = set(assignment_by_op.keys())

    # Initialize all assigned operations
    for op_id in assigned_op_ids:
        successors.setdefault(op_id, [])
        in_degree.setdefault(op_id, 0)

    # Add precedence edges
    for op_id in assigned_op_ids:
        op = ops_by_id.get(op_id)
        if op is None:
            continue
        pred_id = op.predecessor_op_id
        if pred_id is not None and pred_id in assigned_op_ids:
            successors.setdefault(pred_id, []).append(op_id)
            in_degree[op_id] = in_degree.get(op_id, 0) + 1

    # Add machine-sequence edges (consecutive operations on same machine)
    for _wc_id, machine_seq in by_machine.items():
        for i in range(len(machine_seq) - 1):
            from_op = machine_seq[i].operation_id
            to_op = machine_seq[i + 1].operation_id
            successors.setdefault(from_op, []).append(to_op)
            in_degree[to_op] = in_degree.get(to_op, 0) + 1

    # Topological sort (Kahn's algorithm)
    from collections import deque

    queue: deque[UUID] = deque()
    for op_id in assigned_op_ids:
        if in_degree.get(op_id, 0) == 0:
            queue.append(op_id)

    topo_order: list[UUID] = []
    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for succ in successors.get(node, []):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    # If topological sort didn't cover all nodes (cycle in graph), fall back
    if len(topo_order) != len(assigned_op_ids):
        return _destroy_random(assignments, problem, sdst, destroy_size, rng)

    # Longest path DP (forward pass)
    # dist[node] = longest path length ending at node (inclusive of node's duration)
    # predecessor_on_path[node] = the node that precedes this one on the longest path
    dist: dict[UUID, float] = {}
    predecessor_on_path: dict[UUID, UUID | None] = {}

    for node in topo_order:
        dist[node] = op_duration.get(node, 0.0)
        predecessor_on_path[node] = None

    for node in topo_order:
        node_dist = dist[node]
        for succ in successors.get(node, []):
            candidate_dist = node_dist + op_duration.get(succ, 0.0)
            if candidate_dist > dist[succ]:
                dist[succ] = candidate_dist
                predecessor_on_path[succ] = node

    # Find the makespan-defining operation (node with maximum dist)
    makespan_op_id = max(assigned_op_ids, key=lambda op_id: dist.get(op_id, 0.0))

    # Trace back the critical path
    critical_path: list[UUID] = []
    current: UUID | None = makespan_op_id
    while current is not None:
        critical_path.append(current)
        current = predecessor_on_path.get(current)
    critical_path.reverse()

    # Cap to destroy_size (take from the end — closer to makespan bottleneck)
    if len(critical_path) > destroy_size:
        critical_path = critical_path[-destroy_size:]

    # Extend when critical path is shorter than destroy_size:
    # Add operations adjacent (predecessor/successor in machine sequence) to
    # critical-path nodes on the same machines, sorted by their setup
    # contribution (from the SDST matrix).
    if len(critical_path) < destroy_size:
        critical_set = set(critical_path)

        # Build index: operation_id -> position in its machine sequence
        op_to_machine_pos: dict[UUID, tuple[Any, int]] = {}
        for wc_id, machine_seq in by_machine.items():
            for i, a in enumerate(machine_seq):
                op_to_machine_pos[a.operation_id] = (wc_id, i)

        # Collect candidate operations that are adjacent to critical-path nodes
        # in the machine sequence (immediate predecessor or successor)
        candidates: list[tuple[float, UUID]] = []
        seen_candidates: set[UUID] = set()

        for cp_op_id in critical_path:
            pos_info = op_to_machine_pos.get(cp_op_id)
            if pos_info is None:
                continue
            wc_id, idx = pos_info
            machine_seq = by_machine[wc_id]

            # Check immediate predecessor and successor in machine sequence
            for neighbor_idx in (idx - 1, idx + 1):
                if neighbor_idx < 0 or neighbor_idx >= len(machine_seq):
                    continue
                neighbor_a = machine_seq[neighbor_idx]
                neighbor_op_id = neighbor_a.operation_id
                if neighbor_op_id in critical_set or neighbor_op_id in seen_candidates:
                    continue
                seen_candidates.add(neighbor_op_id)

                # Compute setup contribution: predecessor→self + self→successor
                neighbor_op = ops_by_id.get(neighbor_op_id)
                if neighbor_op is None:
                    continue
                cost = 0.0
                if neighbor_idx > 0:
                    prev_op = ops_by_id.get(machine_seq[neighbor_idx - 1].operation_id)
                    if prev_op is not None:
                        cost += sdst.get_setup(wc_id, prev_op.state_id, neighbor_op.state_id)
                if neighbor_idx < len(machine_seq) - 1:
                    next_op = ops_by_id.get(machine_seq[neighbor_idx + 1].operation_id)
                    if next_op is not None:
                        cost += sdst.get_setup(wc_id, neighbor_op.state_id, next_op.state_id)
                candidates.append((cost, neighbor_op_id))

        # Sort by setup contribution descending (highest cost first)
        candidates.sort(key=lambda x: -x[0])

        # Fill up to destroy_size
        for _cost, op_id in candidates:
            if len(critical_set) >= destroy_size:
                break
            critical_set.add(op_id)

        return critical_set

    return set(critical_path)


def _destroy_due_pressure(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> set[UUID]:
    """Remove operations from orders with the highest weighted tardiness.

    Ranks orders by ``tardiness x order_weight`` (descending), then from each
    top-tardy order selects operations that are temporally latest in the order
    chain (highest ``end_time``).  Destroying the tail of an order is the
    cheapest way to recover tardiness, since the final operations are the ones
    missing the due date — moving them backward in time reduces the order's
    completion and therefore its tardiness contribution.

    Order weight follows the repository convention used by the greedy dispatcher
    (``greedy_dispatch.py``): ``priority / 500.0``, which normalises around the
    default priority of 500.

    Fallback semantics (task 2.2):
        When no orders are currently tardy, the operator falls back to orders
        with the smallest positive slack (``due_offset - latest_end_offset``).
        Smallest-slack orders are closest to becoming tardy and therefore the
        most valuable to re-optimise before they slip.  Within each such
        order, operations are selected in descending ``end_time`` order — the
        same temporally-latest-first policy used in the tardy branch.

    Successor closure (task 2.3):
        The returned set is a raw selection; callers wrap the result in
        ``_expand_successor_closure`` (see the ALNS main loop), which keeps the
        invariant that transitive successors of destroyed operations are also
        destroyed.

    Academic basis:
        - Pinedo (2012, *Scheduling: Theory, Algorithms, and Systems* §3):
          weighted tardiness is the standard tardiness objective in
          single-machine and job-shop scheduling.
        - Ropke & Pisinger (2006, Transportation Science): problem-specific
          destroy operators focused on the dominant cost component outperform
          uniform random removal in ALNS.
    """
    if not assignments:
        return set()

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    horizon_start = problem.planning_horizon_start
    orders_by_id = {order.id: order for order in problem.orders}

    # Compute per-order latest end offset (minutes from horizon_start) and
    # group assignments by order for later selection.
    order_latest_end: dict[Any, float] = {}
    assignments_by_order: dict[Any, list[Assignment]] = {}
    for a in assignments:
        op = ops_by_id.get(a.operation_id)
        if op is None:
            continue
        end_offset = (a.end_time - horizon_start).total_seconds() / 60.0
        prev = order_latest_end.get(op.order_id)
        if prev is None or end_offset > prev:
            order_latest_end[op.order_id] = end_offset
        assignments_by_order.setdefault(op.order_id, []).append(a)

    # Compute weighted tardiness per order.
    # weight = priority / 500.0 (greedy_dispatch.py convention: normalise around
    # the default priority of 500).
    weighted_tardiness: list[tuple[float, Any]] = []
    for order_id, latest_end in order_latest_end.items():
        order = orders_by_id.get(order_id)
        if order is None:
            continue
        due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
        tardiness = max(0.0, latest_end - due_offset)
        if tardiness <= 0.0:
            continue
        weight = order.priority / 500.0
        weighted_tardiness.append((tardiness * weight, order_id))

    # Task 2.2: when no orders are tardy, fall back to orders with the
    # smallest positive slack (due_offset - latest_end_offset).  Orders that
    # are closest to slipping are the most valuable to re-optimise.
    if not weighted_tardiness:
        positive_slack: list[tuple[float, Any]] = []
        for order_id, latest_end in order_latest_end.items():
            order = orders_by_id.get(order_id)
            if order is None:
                continue
            due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
            slack = due_offset - latest_end
            if slack <= 0.0:
                # No positive slack: either already tardy (handled above) or
                # exactly on the due date; skip.
                continue
            positive_slack.append((slack, order_id))

        if not positive_slack:
            return set()

        # Rank by ascending slack (smallest slack first = most urgent).
        positive_slack.sort(key=lambda x: x[0])

        slack_destroyed: set[UUID] = set()
        for _slack, order_id in positive_slack:
            if len(slack_destroyed) >= destroy_size:
                break
            order_assignments = assignments_by_order.get(order_id, [])
            order_assignments.sort(key=lambda a: a.end_time, reverse=True)
            for a in order_assignments:
                if len(slack_destroyed) >= destroy_size:
                    break
                slack_destroyed.add(a.operation_id)

        return slack_destroyed

    # Rank tardy orders by weighted tardiness (descending).
    weighted_tardiness.sort(key=lambda x: -x[0])

    # Walk top-tardy orders and, within each, destroy operations in
    # descending end_time order (temporally latest first).
    destroyed: set[UUID] = set()
    for _score, order_id in weighted_tardiness:
        if len(destroyed) >= destroy_size:
            break
        order_assignments = assignments_by_order.get(order_id, [])
        order_assignments.sort(key=lambda a: a.end_time, reverse=True)
        for a in order_assignments:
            if len(destroyed) >= destroy_size:
                break
            destroyed.add(a.operation_id)

    return destroyed


# All destroy operators (random, worst, related: Shaw/Ropke-Pisinger;
#  machine_segment: domain heuristic for setup-chain disruption;
#  precedence_chain: R8 order-based ejection for work-order level re-sequencing;
#  critical_path: Kelley/Walker & Adams-Balas-Zawack bottleneck-chain removal;
#  due_pressure: Pinedo weighted-tardiness order-tail removal with slack fallback)
DESTROY_OPERATORS = [
    ("random", _destroy_random),
    ("worst", _destroy_worst),
    ("related", _destroy_related),
    ("machine_segment", _destroy_machine_segment),
    ("precedence_chain", _destroy_precedence_chain),
    ("critical_path", _destroy_critical_path),
    ("due_pressure", _destroy_due_pressure),
]


def _expand_successor_closure(
    destroyed_op_ids: set[UUID],
    successors_by_op: dict[UUID, list[UUID]],
) -> set[UUID]:
    """Return the transitive successor closure of the destroyed set."""

    expanded = set(destroyed_op_ids)
    # Deterministic frontier order keeps same-seed runs stable across processes.
    frontier = sorted(destroyed_op_ids, key=str)
    while frontier:
        op_id = frontier.pop()
        for successor_id in successors_by_op.get(op_id, []):
            if successor_id not in expanded:
                expanded.add(successor_id)
                frontier.append(successor_id)
    return expanded


def _cap_destroy_set_preserving_successor_closure(
    destroyed_op_ids: set[UUID],
    ops_by_id: dict[UUID, Any],
    successors_by_op: dict[UUID, list[UUID]],
    max_destroy: int,
    rng: random.Random,
) -> set[UUID]:
    """Shrink a destroyed set while preserving successor closure.

    To avoid frozen successors depending on repaired predecessors, the kept set
    must remain successor-closed. We therefore remove roots, not leaves: if an
    operation leaves the destroyed set, its successors may stay destroyed and
    simply treat the predecessor as frozen.
    """

    capped = set(destroyed_op_ids)
    while len(capped) > max_destroy:
        roots = sorted(
            [
                op_id
                for op_id in capped
                if (ops_by_id.get(op_id) is None)
                or (ops_by_id[op_id].predecessor_op_id not in capped)
            ],
            key=str,
        )
        if not roots:
            break
        capped.discard(rng.choice(roots))

    if len(capped) > max_destroy:
        destroyed_list = sorted(capped, key=str)
        rng.shuffle(destroyed_list)
        capped = set(destroyed_list[:max_destroy])

    return capped


# ---------------------------------------------------------------------------
# Repair via CP-SAT (Laborie & Godard 2007: LNS + CP)
# ---------------------------------------------------------------------------


def _repair_cpsat_outcome(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    destroyed_op_ids: set[UUID],
    time_limit_s: int = 10,
    num_workers: int = 1,
    ops_by_id: dict[UUID, Any] | None = None,
    op_positions: dict[UUID, int] | None = None,
) -> RepairOutcome:
    """Repair by solving a sub-problem with CP-SAT over the destroyed operations.

    Frozen assignments constrain the machine timelines. Only the destroyed
    operations (+ their immediate predecessors if outside the set) are modeled.

    Returns explicit status for success, timeout, or infeasible outcomes.
    """
    from synaps.solvers.cpsat_solver import CpSatSolver

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}
    if op_positions is None:
        op_positions = {op.id: index for index, op in enumerate(problem.operations)}

    # Gather operations to re-schedule
    needed_ids = set(destroyed_op_ids)
    # Include predecessors that reference other destroyed ops (chain consistency)
    for op_id in list(destroyed_op_ids):
        op = ops_by_id.get(op_id)
        if op and op.predecessor_op_id and op.predecessor_op_id in destroyed_op_ids:
            needed_ids.add(op.predecessor_op_id)

    # Build sub-operations: for ops whose predecessor is NOT in the sub-problem
    # (i.e., frozen/already scheduled), clear the predecessor reference since
    # the predecessor constraint is already satisfied by the frozen assignment.
    sub_operations = []
    for op_id in sorted(needed_ids, key=op_positions.__getitem__):
        op = ops_by_id[op_id]
        if op.predecessor_op_id and op.predecessor_op_id not in needed_ids:
            # Predecessor is frozen — break the link for the sub-problem
            sub_operations.append(op.model_copy(update={"predecessor_op_id": None}))
        else:
            sub_operations.append(op)

    if not sub_operations:
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason="empty_subproblem",
        )

    all_work_center_ids = [work_center.id for work_center in problem.work_centers]
    relevant_machine_ids = {
        work_center_id
        for operation in sub_operations
        for work_center_id in (
            operation.eligible_wc_ids if operation.eligible_wc_ids else all_work_center_ids
        )
    }
    relevant_frozen_assignments = [
        assignment
        for assignment in frozen_assignments
        if assignment.work_center_id in relevant_machine_ids
    ]
    frozen_assignments_by_op = {
        assignment.operation_id: assignment for assignment in frozen_assignments
    }
    frozen_predecessor_end_offsets: dict[UUID, int] = {}
    for op_id in destroyed_op_ids:
        operation = ops_by_id.get(op_id)
        if operation is None or operation.predecessor_op_id is None:
            continue
        if operation.predecessor_op_id in needed_ids:
            continue

        frozen_predecessor = frozen_assignments_by_op.get(operation.predecessor_op_id)
        if frozen_predecessor is None:
            continue

        frozen_predecessor_end_offsets[op_id] = max(
            0,
            round(
                (frozen_predecessor.end_time - problem.planning_horizon_start).total_seconds()
                / 60.0
            ),
        )

    # Build sub-problem with the relevant operations only
    sub_problem = ScheduleProblem(
        states=problem.states,
        orders=problem.orders,
        operations=sub_operations,
        work_centers=problem.work_centers,
        setup_matrix=problem.setup_matrix,
        auxiliary_resources=problem.auxiliary_resources,
        aux_requirements=[r for r in problem.aux_requirements if r.operation_id in needed_ids],
        planning_horizon_start=problem.planning_horizon_start,
        planning_horizon_end=problem.planning_horizon_end,
    )

    # Solve the sub-problem
    solver = CpSatSolver()
    result = solver.solve(
        sub_problem,
        time_limit_s=time_limit_s,
        num_workers=max(1, int(num_workers)),
        auto_greedy_warm_start=False,
        enable_symmetry_breaking=False,
        frozen_assignments=relevant_frozen_assignments,
        frozen_predecessor_end_offsets=frozen_predecessor_end_offsets,
    )

    if result.status == SolverStatus.TIMEOUT:
        return RepairOutcome(
            status=RepairStatus.TIMEOUT,
            assignments=(),
            reason="cpsat_timeout",
        )
    if result.status not in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL):
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason=(
                f"cpsat_status_{result.status.value}"
                if hasattr(result.status, "value")
                else f"cpsat_status_{result.status}"
            ),
        )

    repaired_assignments = [a for a in result.assignments if a.operation_id in destroyed_op_ids]
    if len(repaired_assignments) != len(destroyed_op_ids):
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason="partial_assignment",
        )

    # Keep assignment order deterministic for downstream destroy operators.
    repaired_assignments.sort(key=lambda assignment: op_positions[assignment.operation_id])

    return RepairOutcome(
        status=RepairStatus.FEASIBLE,
        assignments=tuple(repaired_assignments),
        reason="ok",
    )


def _repair_cpsat(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    destroyed_op_ids: set[UUID],
    time_limit_s: int = 10,
    ops_by_id: dict[UUID, Any] | None = None,
    op_positions: dict[UUID, int] | None = None,
) -> list[Assignment] | None:
    """Compatibility wrapper preserving legacy Optional[List[Assignment]] API."""

    outcome = _repair_cpsat_outcome(
        problem,
        frozen_assignments,
        destroyed_op_ids,
        time_limit_s=time_limit_s,
        ops_by_id=ops_by_id,
        op_positions=op_positions,
    )
    if outcome.status == RepairStatus.FEASIBLE:
        return list(outcome.assignments)
    return None


def _repair_greedy_outcome(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    destroyed_op_ids: set[UUID],
    *,
    use_native_greedy_repair: bool = True,
) -> RepairOutcome:
    """Fallback greedy repair when CP-SAT is too slow for the sub-region.

    When native acceleration is available and ``use_native_greedy_repair`` is True,
    attempts the Rust greedy repair first (10-30x faster). Falls back to the Python
    IncrementalRepair path if native is unavailable, returns invalid results, or
    fails feasibility validation.
    """
    op_positions = {op.id: index for index, op in enumerate(problem.operations)}
    disrupted_op_ids = sorted(destroyed_op_ids, key=op_positions.__getitem__)

    # --- Native fast path ---
    if use_native_greedy_repair and _HAS_NUMPY and len(disrupted_op_ids) > 0:
        native_result = _try_native_greedy_repair(
            problem, frozen_assignments, disrupted_op_ids, op_positions
        )
        if native_result is not None:
            return native_result

    # --- Python fallback path ---
    from synaps.solvers.incremental_repair import IncrementalRepair

    repair_solver = IncrementalRepair()

    result = repair_solver.solve(
        problem,
        base_assignments=frozen_assignments,
        disrupted_op_ids=disrupted_op_ids,
        # radius=0: only the destroyed ops are re-placed; frozen assignments are
        # truly frozen. radius=1 caused regressions because IncrementalRepair
        # freed successor ops jointly but _repair_greedy_outcome filtered them out,
        # leaving stale successor positions that conflicted with the new placements.
        radius=0,
    )

    if result.status == SolverStatus.TIMEOUT:
        return RepairOutcome(
            status=RepairStatus.TIMEOUT,
            assignments=(),
            reason="greedy_timeout",
        )
    if result.status not in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL):
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason=(
                f"greedy_status_{result.status.value}"
                if hasattr(result.status, "value")
                else f"greedy_status_{result.status}"
            ),
        )

    repaired_assignments = [a for a in result.assignments if a.operation_id in destroyed_op_ids]
    if len(repaired_assignments) != len(destroyed_op_ids):
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason="partial_assignment",
        )

    repaired_assignments.sort(key=lambda assignment: op_positions[assignment.operation_id])

    return RepairOutcome(
        status=RepairStatus.FEASIBLE,
        assignments=tuple(repaired_assignments),
        reason="ok",
    )


def _try_native_greedy_repair(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    disrupted_op_ids: list[UUID],
    op_positions: dict[UUID, int],
) -> RepairOutcome | None:
    """Attempt native greedy repair. Returns RepairOutcome or None to fall through.

    Builds the flat numpy arrays expected by the Rust greedy_repair_batch function,
    calls it, converts results back to Assignment objects, and validates feasibility.
    Returns None if native is unavailable, input construction fails, or the result
    fails basic validation.
    """
    from synaps.accelerators import _native_greedy_repair_batch, greedy_repair_batch_native

    # Early exit: if native function is not available, don't waste time building arrays
    if _native_greedy_repair_batch is None:
        return None

    try:
        # Build index mappings
        ops_by_id = {op.id: op for op in problem.operations}
        wc_id_to_idx = {wc.id: idx for idx, wc in enumerate(problem.work_centers)}
        state_id_to_idx = {s.id: idx for idx, s in enumerate(problem.states)}
        idx_to_wc_id = {idx: wc_id for wc_id, idx in wc_id_to_idx.items()}
        n_wc = len(problem.work_centers)
        n_states = len(problem.states)
        horizon_start = problem.planning_horizon_start

        # Build per-operation arrays for the disrupted ops only (in topological order)
        n = len(disrupted_op_ids)
        # Map disrupted op IDs to local indices for predecessor resolution
        disrupted_local_idx = {op_id: i for i, op_id in enumerate(disrupted_op_ids)}

        base_durations = np.empty(n, dtype=np.float64)
        predecessor_indices = np.full(n, -1, dtype=np.int64)
        state_ids = np.empty(n, dtype=np.int64)

        # CSR for eligible machines
        eligible_offsets = np.empty(n + 1, dtype=np.int64)
        eligible_flat: list[int] = []
        eligible_offsets[0] = 0

        # Compute frozen machine availability from frozen_assignments
        # machine_available_at[m] = max end offset of frozen assignments on machine m
        machine_available_at = np.zeros(n_wc, dtype=np.float64)
        machine_last_state = np.full(n_wc, -1, dtype=np.int64)

        # Sort frozen assignments by end time per machine to get last state
        frozen_by_machine: dict[int, list[Assignment]] = {}
        for fa in frozen_assignments:
            m_idx = wc_id_to_idx.get(fa.work_center_id)
            if m_idx is not None:
                frozen_by_machine.setdefault(m_idx, []).append(fa)

        for m_idx, machine_fas in frozen_by_machine.items():
            machine_fas.sort(key=lambda a: a.end_time)
            last_fa = machine_fas[-1]
            end_offset = (last_fa.end_time - horizon_start).total_seconds() / 60.0
            machine_available_at[m_idx] = end_offset
            # Last state on this machine
            last_op = ops_by_id.get(last_fa.operation_id)
            if last_op is not None:
                si = state_id_to_idx.get(last_op.state_id, -1)
                machine_last_state[m_idx] = si

        # Predecessor end offsets from frozen assignments (for disrupted ops whose
        # predecessor is in the frozen set)
        frozen_end_offsets: dict[UUID, float] = {}
        for fa in frozen_assignments:
            end_offset = (fa.end_time - horizon_start).total_seconds() / 60.0
            frozen_end_offsets[fa.operation_id] = end_offset

        for i, op_id in enumerate(disrupted_op_ids):
            op = ops_by_id[op_id]
            base_durations[i] = float(op.base_duration_min)
            state_ids[i] = state_id_to_idx.get(op.state_id, -1)

            # Predecessor: either within disrupted set (local index) or frozen (handled
            # by adjusting machine availability). For the native function, we only track
            # predecessors within the disrupted set.
            if op.predecessor_op_id is not None:
                local_pred = disrupted_local_idx.get(op.predecessor_op_id)
                if local_pred is not None:
                    predecessor_indices[i] = local_pred
                else:
                    # Predecessor is in frozen set — its end time becomes a constraint.
                    # We encode this by setting predecessor_indices[i] = -1 (no local pred)
                    # but we need to ensure the operation starts after the frozen predecessor.
                    # The native function only respects local predecessors, so we handle
                    # frozen predecessors by adjusting the eligible machine availability.
                    # This is a simplification — we'll validate the result afterward.
                    pass

            # Eligible machines
            eligible_wc_indices = []
            for wc_id in op.eligible_wc_ids:
                wc_idx = wc_id_to_idx.get(wc_id)
                if wc_idx is not None:
                    eligible_wc_indices.append(wc_idx)
            eligible_flat.extend(eligible_wc_indices)
            eligible_offsets[i + 1] = len(eligible_flat)

        eligible_indices = np.array(eligible_flat, dtype=np.int64)

        # Build SDST flat matrix and speed factors
        sdst_setup_flat = np.zeros(n_wc * n_states * n_states, dtype=np.float64)
        for entry in problem.setup_matrix:
            wi = wc_id_to_idx.get(entry.work_center_id)
            fi = state_id_to_idx.get(entry.from_state_id)
            ti = state_id_to_idx.get(entry.to_state_id)
            if wi is not None and fi is not None and ti is not None:
                sdst_setup_flat[wi * n_states * n_states + fi * n_states + ti] = float(
                    entry.setup_minutes
                )

        speed_factors = np.array([wc.speed_factor for wc in problem.work_centers], dtype=np.float64)

        # The native function dispatches operations sequentially in the given order
        # (topological). However, it doesn't know about frozen predecessor constraints
        # or frozen machine state. We need to incorporate frozen state into the input.
        #
        # Strategy: We modify the native call to account for frozen state by:
        # 1. Pre-setting machine_available_at (done above)
        # 2. Pre-setting machine_last_state (done above)
        # 3. For ops with frozen predecessors, we inject a "virtual predecessor end"
        #    by adjusting base_durations or using a wrapper.
        #
        # Since the native function doesn't accept machine_available_at directly,
        # we handle this by inserting "virtual" predecessor constraints. For each
        # disrupted op whose predecessor is frozen, we ensure it starts after the
        # frozen predecessor's end. We do this by:
        # - Adding the frozen predecessor end offset as a minimum start constraint.
        #
        # The native function respects predecessor_indices for ordering. For frozen
        # predecessors, we can't use that mechanism. Instead, we'll call the native
        # function and then validate/adjust the result.
        #
        # Actually, the simplest correct approach: the native function starts all
        # machines at time 0. We need to offset the results by machine availability.
        # But the native function doesn't support per-machine initial availability.
        #
        # Better approach: We'll build a combined problem where:
        # - We add "phantom" operations at the start for each machine's frozen tail
        #   OR we simply accept that the native result is approximate and validate.
        #
        # For ALNS inner repair, the native result is a heuristic seed anyway.
        # We'll call native with the disrupted ops, then shift results to respect
        # frozen constraints, and validate.

        # Call native — it dispatches from time 0 with no initial machine state.
        # We'll post-process to account for frozen state.
        native_result = greedy_repair_batch_native(
            base_durations=base_durations,
            predecessor_indices=predecessor_indices,
            eligible_offsets=eligible_offsets,
            eligible_indices=eligible_indices,
            state_ids=state_ids,
            sdst_setup_flat=sdst_setup_flat,
            n_wc=n_wc,
            n_states=n_states,
            speed_factors=speed_factors,
        )

        if native_result is None:
            return None

        start_offsets, end_offsets, assigned_machine_indices = native_result

        # Post-process: shift operations to respect frozen machine availability
        # and frozen predecessor constraints.
        # We do a single forward pass in topological order (disrupted_op_ids is
        # already sorted topologically).
        op_end_offset = np.copy(end_offsets)

        for i, op_id in enumerate(disrupted_op_ids):
            op = ops_by_id[op_id]
            m = int(assigned_machine_indices[i])
            if m < 0 or m >= n_wc:
                return None  # Invalid machine assignment

            # Minimum start from frozen predecessor
            min_start = machine_available_at[m]

            # Check frozen predecessor constraint
            if op.predecessor_op_id is not None and op.predecessor_op_id not in disrupted_local_idx:
                pred_end = frozen_end_offsets.get(op.predecessor_op_id, 0.0)
                min_start = max(min_start, pred_end)

            # Check local predecessor constraint (already handled by native, but
            # we need to account for our shifts)
            if predecessor_indices[i] >= 0:
                local_pred_idx = int(predecessor_indices[i])
                min_start = max(min_start, op_end_offset[local_pred_idx])

            # Setup time from machine's last state
            setup = 0.0
            curr_state = int(state_ids[i])
            prev_state = int(machine_last_state[m])
            if (
                prev_state >= 0
                and curr_state >= 0
                and prev_state < n_states
                and curr_state < n_states
            ):
                setup = sdst_setup_flat[
                    m * n_states * n_states + prev_state * n_states + curr_state
                ]

            actual_start = max(float(start_offsets[i]), min_start + setup)
            duration = float(end_offsets[i] - start_offsets[i])
            actual_end = actual_start + duration

            start_offsets[i] = actual_start
            end_offsets[i] = actual_end
            op_end_offset[i] = actual_end

            # Update machine state for next operation on this machine
            machine_available_at[m] = actual_end
            machine_last_state[m] = curr_state

        # Convert to Assignment objects
        repaired_assignments: list[Assignment] = []
        for i, op_id in enumerate(disrupted_op_ids):
            m = int(assigned_machine_indices[i])
            mapped_wc_id = idx_to_wc_id.get(m)
            if mapped_wc_id is None:
                return None  # Can't map machine index back

            start_dt = horizon_start + timedelta(minutes=float(start_offsets[i]))
            end_dt = horizon_start + timedelta(minutes=float(end_offsets[i]))

            repaired_assignments.append(
                Assignment(
                    operation_id=op_id,
                    work_center_id=mapped_wc_id,
                    start_time=start_dt,
                    end_time=end_dt,
                )
            )

        # Quick feasibility validation: check no machine overlaps and precedence
        # constraints are satisfied among the repaired assignments + frozen.
        all_assignments = frozen_assignments + repaired_assignments
        checker = FeasibilityChecker()
        violations = checker.check(problem, all_assignments)
        if violations:
            # Native result failed validation — fall through to Python path
            return None

        # Sort by original operation position for deterministic output
        repaired_assignments.sort(key=lambda a: op_positions[a.operation_id])

        return RepairOutcome(
            status=RepairStatus.FEASIBLE,
            assignments=tuple(repaired_assignments),
            reason="native_greedy",
        )

    except Exception:
        # Any error in native path — silently fall through to Python
        return None


def _try_native_initial_seed(
    problem: ScheduleProblem,
    *,
    frozen_assignments: list[Assignment],
    ops_by_id: dict[Any, Any],
    frozen_assignments_by_op: dict[Any, Assignment],
) -> list[Assignment] | None:
    """Attempt native greedy dispatch for ALL operations as ALNS initial seed.

    Reuses greedy_repair_batch with disrupted_op_ids = all problem operations.
    Returns a list of Assignments or None if native is unavailable/fails.
    """
    from synaps.accelerators import _native_greedy_repair_batch, greedy_repair_batch_native

    # Early exit: if native function is not available, don't waste time building arrays
    if _native_greedy_repair_batch is None:
        return None

    try:
        # Build index mappings
        wc_id_to_idx = {wc.id: idx for idx, wc in enumerate(problem.work_centers)}
        state_id_to_idx = {s.id: idx for idx, s in enumerate(problem.states)}
        idx_to_wc_id = {idx: wc_id for wc_id, idx in wc_id_to_idx.items()}
        n_wc = len(problem.work_centers)
        n_states = len(problem.states)
        horizon_start = problem.planning_horizon_start

        # Build topological order of ALL operations in the problem.
        # Operations are already in topological order in problem.operations
        # (predecessor always appears before dependent).
        all_op_ids = [op.id for op in problem.operations]
        n = len(all_op_ids)
        if n == 0:
            return None

        # Map op IDs to local indices for predecessor resolution
        local_idx = {op_id: i for i, op_id in enumerate(all_op_ids)}

        base_durations = np.empty(n, dtype=np.float64)
        predecessor_indices = np.full(n, -1, dtype=np.int64)
        state_ids = np.empty(n, dtype=np.int64)

        # CSR for eligible machines
        eligible_offsets = np.empty(n + 1, dtype=np.int64)
        eligible_flat: list[int] = []
        eligible_offsets[0] = 0

        # Compute frozen machine availability from frozen_assignments
        # machine_available_at[m] = max end offset of frozen assignments on machine m
        machine_available_at = np.zeros(n_wc, dtype=np.float64)
        machine_last_state = np.full(n_wc, -1, dtype=np.int64)

        # Sort frozen assignments by end time per machine to get last state
        frozen_by_machine: dict[int, list[Assignment]] = {}
        for fa in frozen_assignments:
            m_idx = wc_id_to_idx.get(fa.work_center_id)
            if m_idx is not None:
                frozen_by_machine.setdefault(m_idx, []).append(fa)

        for m_idx, machine_fas in frozen_by_machine.items():
            machine_fas.sort(key=lambda a: a.end_time)
            last_fa = machine_fas[-1]
            end_offset = (last_fa.end_time - horizon_start).total_seconds() / 60.0
            machine_available_at[m_idx] = end_offset
            # Last state on this machine
            last_op = ops_by_id.get(last_fa.operation_id)
            if last_op is not None:
                si = state_id_to_idx.get(last_op.state_id, -1)
                machine_last_state[m_idx] = si

        # Predecessor end offsets from frozen assignments (for ops whose
        # predecessor is in the frozen set)
        frozen_end_offsets: dict[Any, float] = {}
        for fa in frozen_assignments:
            end_offset = (fa.end_time - horizon_start).total_seconds() / 60.0
            frozen_end_offsets[fa.operation_id] = end_offset

        for i, op_id in enumerate(all_op_ids):
            op = ops_by_id[op_id]
            base_durations[i] = float(op.base_duration_min)
            state_ids[i] = state_id_to_idx.get(op.state_id, -1)

            # Predecessor: within the problem set (local index)
            if op.predecessor_op_id is not None:
                local_pred = local_idx.get(op.predecessor_op_id)
                if local_pred is not None:
                    predecessor_indices[i] = local_pred
                # else: predecessor is in frozen set — handled in post-processing

            # Eligible machines (empty list = all machines eligible)
            eligible_wc_ids = (
                op.eligible_wc_ids if op.eligible_wc_ids else [wc.id for wc in problem.work_centers]
            )
            eligible_wc_indices = []
            for wc_id in eligible_wc_ids:
                wc_idx = wc_id_to_idx.get(wc_id)
                if wc_idx is not None:
                    eligible_wc_indices.append(wc_idx)
            eligible_flat.extend(eligible_wc_indices)
            eligible_offsets[i + 1] = len(eligible_flat)

        eligible_indices_arr = np.array(eligible_flat, dtype=np.int64)

        # Build SDST flat matrix and speed factors
        sdst_setup_flat = np.zeros(n_wc * n_states * n_states, dtype=np.float64)
        for entry in problem.setup_matrix:
            wi = wc_id_to_idx.get(entry.work_center_id)
            fi = state_id_to_idx.get(entry.from_state_id)
            ti = state_id_to_idx.get(entry.to_state_id)
            if wi is not None and fi is not None and ti is not None:
                sdst_setup_flat[wi * n_states * n_states + fi * n_states + ti] = float(
                    entry.setup_minutes
                )

        speed_factors = np.array([wc.speed_factor for wc in problem.work_centers], dtype=np.float64)

        # Call native — dispatches from time 0 with no initial machine state.
        # Post-process to account for frozen state.
        native_result = greedy_repair_batch_native(
            base_durations=base_durations,
            predecessor_indices=predecessor_indices,
            eligible_offsets=eligible_offsets,
            eligible_indices=eligible_indices_arr,
            state_ids=state_ids,
            sdst_setup_flat=sdst_setup_flat,
            n_wc=n_wc,
            n_states=n_states,
            speed_factors=speed_factors,
        )

        if native_result is None:
            return None

        start_offsets, end_offsets, assigned_machine_indices = native_result

        # Post-process: shift operations to respect frozen machine availability
        # and frozen predecessor constraints.
        # Single forward pass in topological order (all_op_ids is already topological).
        op_end_offset = np.copy(end_offsets)

        for i, op_id in enumerate(all_op_ids):
            op = ops_by_id[op_id]
            m = int(assigned_machine_indices[i])
            if m < 0 or m >= n_wc:
                return None  # Invalid machine assignment

            # Minimum start from frozen predecessor
            min_start = machine_available_at[m]

            # Check frozen predecessor constraint
            if op.predecessor_op_id is not None and op.predecessor_op_id not in local_idx:
                pred_end = frozen_end_offsets.get(op.predecessor_op_id, 0.0)
                min_start = max(min_start, pred_end)

            # Check local predecessor constraint (already handled by native, but
            # we need to account for our shifts)
            if predecessor_indices[i] >= 0:
                local_pred_idx = int(predecessor_indices[i])
                min_start = max(min_start, op_end_offset[local_pred_idx])

            # Setup time from machine's last state
            setup = 0.0
            curr_state = int(state_ids[i])
            prev_state = int(machine_last_state[m])
            if (
                prev_state >= 0
                and curr_state >= 0
                and prev_state < n_states
                and curr_state < n_states
            ):
                setup = sdst_setup_flat[
                    m * n_states * n_states + prev_state * n_states + curr_state
                ]

            actual_start = max(float(start_offsets[i]), min_start + setup)
            duration = float(end_offsets[i] - start_offsets[i])
            actual_end = actual_start + duration

            start_offsets[i] = actual_start
            end_offsets[i] = actual_end
            op_end_offset[i] = actual_end

            # Update machine state for next operation on this machine
            machine_available_at[m] = actual_end
            machine_last_state[m] = curr_state

        # Convert to Assignment objects
        seed_assignments: list[Assignment] = []
        for i, op_id in enumerate(all_op_ids):
            m = int(assigned_machine_indices[i])
            wc_id = idx_to_wc_id.get(m)
            if wc_id is None:
                return None  # Can't map machine index back

            start_dt = horizon_start + timedelta(minutes=float(start_offsets[i]))
            end_dt = horizon_start + timedelta(minutes=float(end_offsets[i]))

            seed_assignments.append(
                Assignment(
                    operation_id=op_id,
                    work_center_id=wc_id,
                    start_time=start_dt,
                    end_time=end_dt,
                )
            )

        return seed_assignments

    except Exception:
        # Any error in native path — silently fall through to Python
        return None


def _repair_greedy(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    destroyed_op_ids: set[UUID],
) -> list[Assignment] | None:
    """Compatibility wrapper preserving legacy Optional[List[Assignment]] API."""

    outcome = _repair_greedy_outcome(problem, frozen_assignments, destroyed_op_ids)
    if outcome.status == RepairStatus.FEASIBLE:
        return list(outcome.assignments)
    return None


# ---------------------------------------------------------------------------
# Machine overlap check (guard for CP-SAT repair sub-problem gaps)
# ---------------------------------------------------------------------------


def _has_machine_overlap(assignments: list[Assignment]) -> bool:
    """Return True if any two assignments overlap on the same machine."""
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for mc_assigns in by_machine.values():
        mc_assigns.sort(key=lambda x: x.start_time)
        for i in range(1, len(mc_assigns)):
            if mc_assigns[i].start_time < mc_assigns[i - 1].end_time:
                return True
    return False


def _violates_frozen_precedence(
    repaired_assignments: list[Assignment],
    frozen_assignments_by_op: dict[UUID, Assignment],
    ops_by_id: dict[UUID, Any],
) -> bool:
    """Return True when a repaired operation starts before its frozen predecessor ends."""

    repaired_ids = {assignment.operation_id for assignment in repaired_assignments}
    for assignment in repaired_assignments:
        operation = ops_by_id.get(assignment.operation_id)
        if operation is None or operation.predecessor_op_id is None:
            continue
        if operation.predecessor_op_id in repaired_ids:
            continue
        frozen_predecessor = frozen_assignments_by_op.get(operation.predecessor_op_id)
        if frozen_predecessor is not None and assignment.start_time < frozen_predecessor.end_time:
            return True
    return False


def _has_precedence_violation(
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Any],
) -> bool:
    """Return True when any assignment starts before its predecessor ends."""

    assignments_by_op = {assignment.operation_id: assignment for assignment in assignments}
    for assignment in assignments:
        operation = ops_by_id.get(assignment.operation_id)
        if operation is None or operation.predecessor_op_id is None:
            continue
        predecessor_assignment = assignments_by_op.get(operation.predecessor_op_id)
        if (
            predecessor_assignment is not None
            and assignment.start_time < predecessor_assignment.end_time
        ):
            return True
    return False


# ---------------------------------------------------------------------------
# SA acceptance (Ropke & Pisinger 2006 §4.3)
# ---------------------------------------------------------------------------


def _sa_accept(
    delta_cost: float,
    temperature: float,
    rng: random.Random,
) -> bool:
    """Simulated annealing acceptance criterion."""
    if delta_cost < 0:
        return True
    if temperature < 1e-12:
        return False
    prob = math.exp(-delta_cost / temperature)
    return rng.random() < prob


def _update_operator_weights_for_segment(
    operator_scores: list[float],
    operator_attempts: list[int],
    *,
    reset_mix: float,
    min_weight: float = 0.05,
) -> list[float]:
    """Refresh operator weights from the current segment and reset towards uniform."""

    n_operators = len(operator_scores)
    if n_operators == 0:
        return []

    segment_rewards = [
        operator_scores[idx] / operator_attempts[idx] if operator_attempts[idx] > 0 else 0.0
        for idx in range(n_operators)
    ]
    reward_mass = sum(max(reward, 0.0) for reward in segment_rewards)
    if reward_mass > 0:
        normalized = [max(reward, 0.0) / reward_mass for reward in segment_rewards]
    else:
        normalized = [1.0 / n_operators] * n_operators

    uniform_weight = 1.0 / n_operators
    blended = [
        max(
            min_weight,
            (1.0 - reset_mix) * normalized[idx] + reset_mix * uniform_weight,
        )
        for idx in range(n_operators)
    ]
    total = sum(blended)
    return [weight / total for weight in blended]


def _normalize_initial_operator_weights(
    raw: Any,
    operator_names: list[str],
) -> list[float]:
    """Normalize caller-supplied initial operator weights to a probability vector.

    Handles three input forms:
      - ``None`` → uniform ``[1/n]*n``
      - ``dict[str, float]`` → filter to positive finite floats matching
        *operator_names*; fill missing with mean of recognized; normalize to
        sum 1.0. If ALL names are missing/invalid → log warning, uniform.
      - ``list[float]`` (or tuple) → if length matches and all values are
        non-negative finite → normalize. Otherwise log warning, uniform.
      - Any other type → log warning, uniform.

    Returns a list of floats summing to 1.0 with length == len(operator_names).
    """
    n = len(operator_names)
    if n == 0:
        return []

    uniform: list[float] = [1.0 / n] * n

    if raw is None:
        return uniform

    if isinstance(raw, dict):
        # Extract recognized positive finite values
        recognized: list[tuple[int, float]] = []
        for idx, name in enumerate(operator_names):
            val = raw.get(name)
            if val is not None:
                try:
                    fval = float(val)
                except (TypeError, ValueError):
                    continue
                if fval > 0.0 and math.isfinite(fval):
                    recognized.append((idx, fval))

        if not recognized:
            logger.warning(
                "initial_operator_weights dict has no recognized positive finite "
                "entries for current operators — falling back to uniform weights"
            )
            return uniform

        # Fill missing names with mean of recognized values
        mean_recognized = sum(v for _, v in recognized) / len(recognized)
        recognized_indices = {idx for idx, _ in recognized}
        weights = [0.0] * n
        for idx, val in recognized:
            weights[idx] = val
        for idx in range(n):
            if idx not in recognized_indices:
                weights[idx] = mean_recognized

        weight_sum = sum(weights)
        if weight_sum <= 0.0:
            return uniform
        return [w / weight_sum for w in weights]

    if isinstance(raw, list | tuple):
        if len(raw) != n:
            logger.warning(
                "initial_operator_weights list length %d does not match "
                "operator count %d — falling back to uniform weights",
                len(raw),
                n,
            )
            return uniform

        # Validate all non-negative finite
        parsed: list[float] = []
        for val in raw:
            try:
                fval = float(val)
            except (TypeError, ValueError):
                logger.warning(
                    "initial_operator_weights list contains non-numeric value — "
                    "falling back to uniform weights"
                )
                return uniform
            if not math.isfinite(fval) or fval < 0.0:
                logger.warning(
                    "initial_operator_weights list contains negative or non-finite "
                    "value — falling back to uniform weights"
                )
                return uniform
            parsed.append(fval)

        weight_sum = sum(parsed)
        if weight_sum <= 0.0:
            return uniform
        return [w / weight_sum for w in parsed]

    # Unrecognized type
    logger.warning(
        "initial_operator_weights has unrecognized type %s — falling back to uniform weights",
        type(raw).__name__,
    )
    return uniform


def _compute_effective_temperature(
    *,
    base_temp: float,
    due_pressure: float,
    candidate_pressure: float,
    due_alpha: float,
    candidate_beta: float,
    min_temp: float,
    max_temp: float,
) -> float:
    """Compute the pressure-adjusted SA temperature, clamped to [min_temp, max_temp].

    Pure function — no side effects, no logging, no state reads. Mirrors the
    inline formula currently used in the ALNS main loop and post-calibration
    recompute.

        factor    = 1.0 + due_alpha * due_pressure + candidate_beta * candidate_pressure
        effective = base_temp * factor
        return max(min_temp, min(max_temp, effective))

    Audit note (2026-05-10): the current ALNS search behavior is that the
    effective temperature is NON-DECREASING with increasing ``due_pressure``
    (holding all else fixed) — higher pressure widens SA exploration. The
    earlier design-doc claim that temperature should decrease monotonically
    with pressure was rejected by the audit. Do not invert this formula.
    """
    factor = 1.0 + due_alpha * due_pressure + candidate_beta * candidate_pressure
    effective = base_temp * factor
    return max(min_temp, min(max_temp, effective))


def _calibrate_sa_temperature(
    problem: ScheduleProblem,
    current_assignments: list[Assignment],
    *,
    current_cost: float,
    objective_weights: dict[str, float],
    sdst: SdstMatrix,
    destroy_size: int,
    max_destroy: int,
    ops_by_id: dict[UUID, Any],
    successors_by_op: dict[UUID, list[UUID]],
    trials: int,
    acceptance_probability: float,
    seed: int,
    fallback_temperature: float,
) -> tuple[float, int]:
    """Estimate a base SA temperature from sampled worsening greedy-repair deltas."""

    if trials <= 0 or not (0.0 < acceptance_probability < 1.0):
        return fallback_temperature, 0

    calibration_rng = random.Random(seed ^ 0xA11CE)
    positive_deltas: list[float] = []

    for _ in range(trials):
        _, destroy_fn = DESTROY_OPERATORS[calibration_rng.randrange(len(DESTROY_OPERATORS))]
        destroyed_ids = destroy_fn(
            current_assignments,
            problem,
            sdst,
            destroy_size,
            calibration_rng,
            ops_by_id=ops_by_id,
        )
        if not destroyed_ids:
            continue

        destroyed_ids = _expand_successor_closure(destroyed_ids, successors_by_op)
        destroyed_ids = _cap_destroy_set_preserving_successor_closure(
            destroyed_ids,
            ops_by_id,
            successors_by_op,
            max_destroy,
            calibration_rng,
        )

        frozen = [
            assignment
            for assignment in current_assignments
            if assignment.operation_id not in destroyed_ids
        ]
        repair_outcome = _repair_greedy_outcome(problem, frozen, destroyed_ids)
        if repair_outcome.status != RepairStatus.FEASIBLE:
            continue

        candidate = frozen + list(repair_outcome.assignments)
        candidate_op_ids = {assignment.operation_id for assignment in candidate}
        if len(candidate_op_ids) != len(problem.operations):
            continue
        if _has_precedence_violation(candidate, ops_by_id):
            continue
        if _has_machine_overlap(candidate):
            continue

        candidate_obj = _evaluate_objective(problem, candidate, sdst, ops_by_id=ops_by_id)
        candidate_cost = _objective_cost(candidate_obj, objective_weights)
        delta = candidate_cost - current_cost
        if delta > 0:
            positive_deltas.append(delta)

    if not positive_deltas:
        return fallback_temperature, 0

    mean_positive_delta = sum(positive_deltas) / len(positive_deltas)
    calibrated_temperature = -mean_positive_delta / math.log(acceptance_probability)
    return calibrated_temperature, len(positive_deltas)


# ---------------------------------------------------------------------------
# Main ALNS solver
# ---------------------------------------------------------------------------


class AlnsSolver(BaseSolver):
    """Adaptive Large Neighborhood Search with Micro-CP-SAT repair.

    Designed for 5 000-50 000+ operation instances where monolithic CP-SAT
    and LBBD cannot converge in reasonable time.

    Architecture (Ropke & Pisinger 2006):
        1. Generate initial solution via greedy/beam heuristic
        2. Iteratively: destroy (remove k operations) → repair (micro CP-SAT)
        3. Accept/reject via Simulated Annealing
        4. Adapt operator selection probabilities based on success history

    Key parameters:
        max_iterations: Iteration CEILING (default 500). ``time_limit_s`` is a
            hard wall-clock deadline; whichever is hit first wins (D3/D4).
            ``min_iterations`` never overrides the deadline.
        destroy_fraction: Fraction of operations to destroy per iteration (default 0.05)
        min_destroy: Minimum destroy size (default 20)
        max_destroy: Maximum destroy size per iteration (default 300)
        repair_time_limit_s: Time limit for micro CP-SAT repair (default 10);
            clamped every iteration to the remaining wall-clock budget.
        sa_initial_temp: Starting temperature for SA (default 100.0)
        sa_cooling_rate: Geometric cooling factor (default 0.995)
        random_seed: For reproducibility (default 42)
    """

    @property
    def name(self) -> str:
        return "alns"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()

        # Parameters
        max_iterations: int = int(kwargs.get("max_iterations", 500))
        # D3: min_iterations is accepted but no longer overrides the hard
        # wall-clock deadline; time_limit_s always wins.
        _ = kwargs.get("min_iterations")
        time_limit_s: float = float(kwargs.get("time_limit_s", 300))
        destroy_fraction: float = float(kwargs.get("destroy_fraction", 0.05))
        min_destroy: int = int(kwargs.get("min_destroy", 20))
        max_destroy: int = int(kwargs.get("max_destroy", 300))
        repair_time_limit_s: int = int(kwargs.get("repair_time_limit_s", 10))
        repair_num_workers: int = max(
            1,
            int(kwargs.get("repair_num_workers", kwargs.get("num_workers", 1))),
        )
        sa_auto_calibration_enabled: bool = bool(kwargs.get("sa_auto_calibration_enabled", False))
        # R6: default raised from 5 to 15 — Pepels (2014, C&OR) recommends ≥10-50
        # worsening samples for reliable SA temperature estimation. 5 gave ≥40%
        # variance at 50K scale, reducing strict-lane reproducibility.
        sa_calibration_trials: int = max(0, int(kwargs.get("sa_calibration_trials", 15)))
        sa_initial_acceptance_probability: float = float(
            kwargs.get("sa_initial_acceptance_probability", 0.8)
        )
        sa_initial_temp: float = float(kwargs.get("sa_initial_temp", 100.0))
        sa_cooling_rate: float = float(kwargs.get("sa_cooling_rate", 0.995))
        operator_weight_segment_length: int = max(
            1,
            int(kwargs.get("operator_weight_segment_length", 50)),
        )
        operator_weight_reset_mix: float = min(
            0.95,
            max(0.0, float(kwargs.get("operator_weight_reset_mix", 0.2))),
        )
        max_no_improve_base_iters: int = int(kwargs.get("max_no_improve_iters", 0))
        dynamic_no_improve_enabled: bool = bool(kwargs.get("dynamic_no_improve_enabled", False))
        due_pressure: float = max(0.0, float(kwargs.get("due_pressure", 0.0)))
        candidate_pressure: float = max(
            0.0,
            float(kwargs.get("candidate_pressure", 0.0)),
        )
        no_improve_due_alpha: float = float(kwargs.get("no_improve_due_alpha", 0.6))
        no_improve_candidate_beta: float = float(kwargs.get("no_improve_candidate_beta", 0.4))
        dynamic_sa_enabled: bool = bool(kwargs.get("dynamic_sa_enabled", True))
        sa_due_alpha: float = float(kwargs.get("sa_due_alpha", 0.35))
        sa_candidate_beta: float = float(kwargs.get("sa_candidate_beta", 0.15))
        sa_pressure_cooling_gamma: float = float(kwargs.get("sa_pressure_cooling_gamma", 0.0015))
        sa_temp_min: float = float(kwargs.get("sa_temp_min", 50.0))
        sa_temp_max: float = float(kwargs.get("sa_temp_max", 500.0))
        no_improve_min_iters: int = int(
            kwargs.get(
                "no_improve_min_iters",
                max(1, max_no_improve_base_iters // 2) if max_no_improve_base_iters > 0 else 0,
            )
        )
        no_improve_max_iters: int = int(
            kwargs.get(
                "no_improve_max_iters",
                max_no_improve_base_iters * 4 if max_no_improve_base_iters > 0 else 0,
            )
        )
        seed: int = int(kwargs.get("random_seed", 42))
        initial_beam_op_limit: int = int(kwargs.get("initial_beam_op_limit", 60))
        frozen_initial_repair_max_ops: int = int(kwargs.get("frozen_initial_repair_max_ops", 2000))
        frozen_initial_repair_min_remaining_time_s: float = float(
            kwargs.get("frozen_initial_repair_min_remaining_time_s", 30.0)
        )
        use_cpsat_repair: bool = bool(kwargs.get("use_cpsat_repair", True))
        cpsat_max_destroy_ops: int = int(kwargs.get("cpsat_max_destroy_ops", min(20, max_destroy)))
        objective_weights: dict[str, float] = dict(
            kwargs.get(
                "objective_weights",
                {"makespan": 1.0, "setup": 0.3, "material_loss": 0.2, "tardiness": 0.5},
            )
        )
        warm_start_assignments_raw = kwargs.get("warm_start_assignments")
        frozen_assignments_raw = kwargs.get("frozen_assignments")
        frozen_assignments: list[Assignment] = list(frozen_assignments_raw or [])
        frozen_assignments_by_op = {
            assignment.operation_id: assignment for assignment in frozen_assignments
        }
        frozen_predecessor_end_offsets = {
            op_id: float(offset)
            for op_id, offset in dict(kwargs.get("frozen_predecessor_end_offsets", {})).items()
        }

        # P3.1: Variable fixing — exclude stable ops from destroy
        fixed_op_ids_raw = kwargs.get("fixed_op_ids")
        fixed_op_ids: set[UUID] = set(fixed_op_ids_raw) if fixed_op_ids_raw else set()

        # P3.2: Adaptive destroy sizing (Deng et al. 2026)
        adaptive_destroy_enabled: bool = bool(kwargs.get("adaptive_destroy_enabled", False))
        adaptive_destroy_grow_rate: float = float(kwargs.get("adaptive_destroy_grow_rate", 1.15))
        adaptive_destroy_shrink_rate: float = float(
            kwargs.get("adaptive_destroy_shrink_rate", 0.85)
        )

        # P3.3: EMA repair-time tracking
        ema_repair_alpha: float = float(kwargs.get("ema_repair_alpha", 0.3))

        # B3 (Task 7): Convergence diagnostics — per-iteration trace control
        record_iteration_metrics: bool = bool(kwargs.get("record_iteration_metrics", False))
        max_iteration_records: int = max(1, int(kwargs.get("max_iteration_records", 500)))

        # C2 (Task 12.1): Initial operator weights — dict[str, float] | list[float] | None
        initial_operator_weights_raw = kwargs.get("initial_operator_weights")

        # C4 (Task 3b.1): Cross-window operator bias — independent from telemetry flag.
        # When enabled AND cross_window_hints indicate high setup cost concentration,
        # applies a bounded boost (max 15%) to setup-disrupting operators.
        cross_window_operator_bias_enabled: bool = bool(
            kwargs.get("cross_window_operator_bias_enabled", False)
        )
        cross_window_hints = kwargs.get("cross_window_hints")

        # Task 24.1: Native initial seed — use Rust greedy_repair_batch for Phase 1.
        native_initial_seed_enabled: bool = bool(kwargs.get("native_initial_seed_enabled", True))

        max_no_improve_iters = max_no_improve_base_iters
        if dynamic_no_improve_enabled and max_no_improve_base_iters > 0:
            scaled_no_improve = round(
                max_no_improve_base_iters
                * (
                    1.0
                    + no_improve_due_alpha * due_pressure
                    + no_improve_candidate_beta * candidate_pressure
                )
            )
            max_no_improve_iters = min(
                no_improve_max_iters,
                max(no_improve_min_iters, scaled_no_improve),
            )

        destroy_size = max(min_destroy, int(len(problem.operations) * destroy_fraction))
        destroy_size = min(destroy_size, max_destroy)
        adaptive_destroy_current = destroy_size

        sa_calibrated_base_temp = sa_initial_temp
        sa_calibration_samples = 0

        sa_pressure_factor = 1.0
        if dynamic_sa_enabled:
            sa_pressure_factor += (
                sa_due_alpha * due_pressure + sa_candidate_beta * candidate_pressure
            )
        # Initial effective SA temperature via _compute_effective_temperature.
        # sa_pressure_factor is retained for the cooling-rate adjustment below
        # and for metadata/logging; the temperature clamp itself delegates to
        # the pure helper.
        effective_sa_initial_temp = _compute_effective_temperature(
            base_temp=sa_calibrated_base_temp,
            due_pressure=due_pressure,
            candidate_pressure=candidate_pressure,
            due_alpha=sa_due_alpha if dynamic_sa_enabled else 0.0,
            candidate_beta=sa_candidate_beta if dynamic_sa_enabled else 0.0,
            min_temp=sa_temp_min,
            max_temp=sa_temp_max,
        )
        effective_sa_cooling_rate = min(
            0.9999,
            max(
                0.90,
                sa_cooling_rate + (sa_pressure_cooling_gamma * max(0.0, sa_pressure_factor - 1.0)),
            ),
        )

        rng = random.Random(seed)
        n_ops = len(problem.operations)
        ops_by_id = {op.id: op for op in problem.operations}
        problem_op_ids = set(ops_by_id.keys())
        op_positions = {op.id: index for index, op in enumerate(problem.operations)}
        successors_by_op: dict[UUID, list[UUID]] = {}
        for op in problem.operations:
            if op.predecessor_op_id is not None:
                successors_by_op.setdefault(op.predecessor_op_id, []).append(op.id)
        sdst = SdstMatrix.from_problem(problem)
        checker = FeasibilityChecker()
        dispatch_context = build_dispatch_context(problem)
        lower_bound = compute_relaxed_makespan_lower_bound(problem)

        def _initial_generation_error_result(
            error_message: str,
            *,
            reason_key: str | None = None,
            time_limit_exhausted_before_search: bool | None = None,
        ) -> ScheduleResult:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return ScheduleResult(
                solver_name=self.name,
                status=SolverStatus.ERROR,
                duration_ms=elapsed_ms,
                metadata={
                    "error": error_message,
                    "initial_seed_fallback_reason": reason_key or error_message,
                    "initial_solver": initial_solver_name,
                    "warm_start_used": warm_start_used,
                    "warm_start_supplied_assignments": warm_start_supplied_assignments,
                    "warm_start_completed_assignments": warm_start_completed_assignments,
                    "warm_start_rejected_reason": warm_start_rejected_reason,
                    # C1 (Task 9.4): explicit ALNS-scoped warm-start signals for RHC
                    # telemetry. `alns_warm_start_used` mirrors `warm_start_used`
                    # but is prefixed to avoid ambiguity with RHC-owned keys.
                    # `alns_warm_start_coverage` is the fraction of operations in
                    # the current (sub-)problem that the caller-supplied warm
                    # start covered before any greedy fill or rejection.
                    "alns_warm_start_used": warm_start_used,
                    "alns_warm_start_coverage": round(
                        warm_start_supplied_assignments / max(n_ops, 1), 6
                    ),
                    "initial_solution_ms": elapsed_ms,
                    "native_initial_seed_attempted": native_initial_seed_attempted,
                    "native_initial_seed_used": native_initial_seed_used,
                    "native_initial_seed_ms": native_initial_seed_ms,
                    "native_initial_seed_fallback_reason": native_initial_seed_fallback_reason,
                    "time_limit_exhausted_before_search": (
                        bool(time_limit_exhausted_before_search)
                        if time_limit_exhausted_before_search is not None
                        else (time.monotonic() - t0) > time_limit_s
                    ),
                    "iterations_completed": 0,
                },
            )

        def _remaining_initial_seed_budget_s() -> float:
            return max(1.0, time_limit_s - (time.monotonic() - t0))

        def _initial_seed_budget_s() -> float:
            remaining_budget_s = _remaining_initial_seed_budget_s()
            repair_budget_s = max(1.0, float(repair_time_limit_s))
            # Guarantee a minimum search budget so that ALNS always gets
            # at least search_budget_reservation_s seconds after the seed.
            search_budget_reservation_s: float = float(
                kwargs.get("search_budget_reservation_s", 10.0)
            )
            reserved = remaining_budget_s - search_budget_reservation_s
            if reserved < 1.0:
                return max(1.0, remaining_budget_s * 0.1)
            # Scale seed budget proportionally to problem size and remaining
            # budget so larger windows don't exhaust their budget on seed
            # construction alone.
            #   - n_ops factor: ~0.5 ms per op (empirically observed for
            #     Python GreedyDispatch), capped at 30 s.
            #   - proportional factor: 15 % of remaining budget.
            #   - Floor at 3 s; cap to leave the search reservation intact.
            n_ops_budget = min(n_ops * 0.0005, 30.0)
            proportional = max(3.0, remaining_budget_s * 0.15)
            if time_limit_s <= 90.0:
                cap = max(1.0, min(3.0, repair_budget_s * 2.0))
            else:
                cap = max(5.0, min(max(n_ops_budget, proportional), reserved))
            return max(1.0, min(cap, reserved))

        def _initial_seed_timed_out(result: ScheduleResult) -> bool:
            metadata = result.metadata or {}
            return result.status == SolverStatus.TIMEOUT or bool(metadata.get("partial_schedule"))

        def _reanchor_against_frozen(
            assignments: list[Assignment],
        ) -> tuple[list[Assignment], int]:
            if not assignments or not frozen_assignments:
                return list(assignments), 0

            original_by_op = {assignment.operation_id: assignment for assignment in assignments}
            scheduled_assignments = [
                assignment
                for assignment in frozen_assignments
                if assignment.operation_id in ops_by_id
            ]
            external_frozen_blockers = sorted(
                [
                    (
                        assignment,
                        (assignment.start_time - problem.planning_horizon_start).total_seconds()
                        / 60.0,
                        (assignment.end_time - problem.planning_horizon_start).total_seconds()
                        / 60.0,
                        set(assignment.aux_resource_ids),
                    )
                    for assignment in frozen_assignments
                    if assignment.operation_id not in ops_by_id
                ],
                key=lambda blocker: blocker[1],
            )
            machine_index = MachineIndex(dispatch_context)
            for assignment in scheduled_assignments:
                machine_index.add(assignment)

            anchored_by_op = dict(frozen_assignments_by_op)
            pending_assignments = sorted(
                assignments,
                key=lambda assignment: (
                    assignment.start_time,
                    op_positions[assignment.operation_id],
                ),
            )
            reanchored_assignments: list[Assignment] = []

            for _ in range(len(pending_assignments) + 1):
                if not pending_assignments:
                    break

                progress_made = False
                next_pending: list[Assignment] = []

                for assignment in pending_assignments:
                    operation = ops_by_id[assignment.operation_id]
                    earliest_start = 0.0
                    required_resource_ids = {
                        requirement.aux_resource_id
                        for requirement in dispatch_context.requirements_by_op.get(
                            operation.id,
                            [],
                        )
                    }
                    if operation.predecessor_op_id is not None:
                        predecessor_assignment = anchored_by_op.get(operation.predecessor_op_id)
                        if predecessor_assignment is not None:
                            predecessor_end = (
                                predecessor_assignment.end_time - problem.planning_horizon_start
                            ).total_seconds() / 60.0
                            earliest_start = max(earliest_start, predecessor_end)
                        elif operation.predecessor_op_id in original_by_op:
                            next_pending.append(assignment)
                            continue
                        else:
                            earliest_start = max(
                                earliest_start,
                                frozen_predecessor_end_offsets.get(operation.id, 0.0),
                            )

                    slot = None
                    current_earliest_start = earliest_start
                    while True:
                        slot = find_earliest_feasible_slot(
                            dispatch_context,
                            scheduled_assignments,
                            operation,
                            assignment.work_center_id,
                            current_earliest_start,
                            machine_index=machine_index,
                        )
                        if slot is None:
                            break

                        conflicting_blocker_end = next(
                            (
                                blocker_end
                                for (
                                    blocker_assignment,
                                    blocker_start,
                                    blocker_end,
                                    blocker_resources,
                                ) in external_frozen_blockers
                                if (
                                    blocker_assignment.work_center_id == assignment.work_center_id
                                    or required_resource_ids & blocker_resources
                                )
                                and slot.start_offset < blocker_end
                                and slot.end_offset > blocker_start
                            ),
                            None,
                        )
                        if conflicting_blocker_end is None:
                            break
                        current_earliest_start = max(
                            current_earliest_start,
                            conflicting_blocker_end,
                        )
                    if slot is None:
                        next_pending.append(assignment)
                        continue

                    anchored_assignment = Assignment(
                        operation_id=operation.id,
                        work_center_id=assignment.work_center_id,
                        start_time=problem.planning_horizon_start
                        + timedelta(minutes=slot.start_offset),
                        end_time=problem.planning_horizon_start
                        + timedelta(minutes=slot.end_offset),
                        setup_minutes=slot.setup_minutes,
                        aux_resource_ids=slot.aux_resource_ids,
                    )
                    scheduled_assignments.append(anchored_assignment)
                    machine_index.add(anchored_assignment)
                    anchored_by_op[operation.id] = anchored_assignment
                    reanchored_assignments.append(anchored_assignment)
                    progress_made = True

                if not progress_made:
                    return list(assignments), 0
                pending_assignments = next_pending

            if pending_assignments:
                return list(assignments), 0

            changed_assignment_count = sum(
                1
                for assignment in reanchored_assignments
                if original_by_op[assignment.operation_id].start_time != assignment.start_time
                or original_by_op[assignment.operation_id].end_time != assignment.end_time
                or original_by_op[assignment.operation_id].work_center_id
                != assignment.work_center_id
            )
            return sorted(
                reanchored_assignments,
                key=lambda assignment: assignment.start_time,
            ), changed_assignment_count

        # ------- Phase 1: Initial solution -------
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch, GreedyDispatch

        initial_solution_t0 = time.monotonic()
        # Hard ceiling for Phase-1 seed+completion so RHC windows retain search
        # (or fall back to inline greedy) instead of burning 180-320s on seed alone.
        phase1_wall_fraction: float = max(
            0.1, min(0.9, float(kwargs.get("phase1_wall_fraction", 0.5)))
        )
        phase1_deadline = t0 + (time_limit_s * phase1_wall_fraction)

        def _phase1_budget_exhausted() -> bool:
            return time.monotonic() >= phase1_deadline

        warm_start_assignments: list[Assignment] = []
        warm_start_supplied_assignments = 0
        warm_start_completed_assignments = 0
        warm_start_used = False
        warm_start_rejected_reason: str | None = None

        if isinstance(warm_start_assignments_raw, list):
            seen_warm_start_ids: set[UUID] = set()
            for assignment in warm_start_assignments_raw:
                op_id = getattr(assignment, "operation_id", None)
                if op_id not in problem_op_ids or op_id in seen_warm_start_ids:
                    continue
                warm_start_assignments.append(assignment)
                seen_warm_start_ids.add(op_id)
            warm_start_supplied_assignments = len(warm_start_assignments)

        def _is_valid_complete_schedule(assignments: list[Assignment]) -> bool:
            combined_assignments = (
                frozen_assignments + assignments if frozen_assignments else assignments
            )
            return (
                len(assignments) == n_ops
                and len({assignment.operation_id for assignment in assignments}) == n_ops
                and not _has_machine_overlap(combined_assignments)
                and not _has_precedence_violation(assignments, ops_by_id)
                and not _violates_frozen_precedence(
                    assignments,
                    frozen_assignments_by_op,
                    ops_by_id,
                )
                and not checker.check(problem, assignments)
            )

        initial_solver_name = "greedy"
        initial_result: ScheduleResult | None = None

        if warm_start_assignments:
            warm_candidate = sorted(
                warm_start_assignments,
                key=lambda assignment: assignment.start_time,
            )
            warm_missing_ids = problem_op_ids.difference(
                assignment.operation_id for assignment in warm_candidate
            )
            if warm_missing_ids:
                if _phase1_budget_exhausted():
                    warm_start_rejected_reason = "phase1_wall_budget_exhausted"
                else:
                    warm_outcome = _repair_greedy_outcome(
                        problem,
                        warm_candidate,
                        warm_missing_ids,
                    )
                    if warm_outcome.status == RepairStatus.FEASIBLE:
                        warm_candidate = sorted(
                            warm_candidate + list(warm_outcome.assignments),
                            key=lambda assignment: assignment.start_time,
                        )
                        warm_start_completed_assignments = len(warm_outcome.assignments)
                    else:
                        warm_start_rejected_reason = warm_outcome.reason

            if _is_valid_complete_schedule(warm_candidate):
                recompute_assignment_setups(warm_candidate, dispatch_context)
                initial_solver_name = "warm_start"
                warm_start_used = True
                initial_result = ScheduleResult(
                    solver_name=self.name,
                    status=SolverStatus.FEASIBLE,
                    assignments=warm_candidate,
                )
            elif frozen_assignments:
                reanchored_warm_candidate, _ = _reanchor_against_frozen(warm_candidate)
                if _is_valid_complete_schedule(reanchored_warm_candidate):
                    recompute_assignment_setups(
                        reanchored_warm_candidate,
                        dispatch_context,
                    )
                    initial_solver_name = "warm_start"
                    warm_start_used = True
                    initial_result = ScheduleResult(
                        solver_name=self.name,
                        status=SolverStatus.FEASIBLE,
                        assignments=reanchored_warm_candidate,
                    )
                elif warm_start_rejected_reason is None:
                    warm_start_rejected_reason = "warm_start_reanchored_infeasible"
            elif warm_start_rejected_reason is None:
                warm_start_rejected_reason = "warm_start_infeasible"
        if initial_result is None and frozen_assignments:
            # For RHC inner windows, prefer a frozen-compatible constructive seed
            # instead of a standalone greedy seed that may become infeasible after
            # re-anchoring against committed assignments.
            remaining_budget_s = max(0.0, time_limit_s - (time.monotonic() - t0))
            if _phase1_budget_exhausted():
                if warm_start_rejected_reason is None:
                    warm_start_rejected_reason = "phase1_wall_budget_exhausted"
            elif (
                n_ops <= frozen_initial_repair_max_ops
                and remaining_budget_s >= frozen_initial_repair_min_remaining_time_s
            ):
                frozen_seed_outcome = _repair_greedy_outcome(
                    problem,
                    frozen_assignments,
                    set(problem_op_ids),
                )
                if frozen_seed_outcome.status == RepairStatus.FEASIBLE:
                    frozen_seed_candidate = list(frozen_seed_outcome.assignments)
                    if _is_valid_complete_schedule(frozen_seed_candidate):
                        recompute_assignment_setups(frozen_seed_candidate, dispatch_context)
                        initial_solver_name = "frozen_greedy_repair"
                        initial_result = ScheduleResult(
                            solver_name=self.name,
                            status=SolverStatus.FEASIBLE,
                            assignments=frozen_seed_candidate,
                        )
                    elif warm_start_rejected_reason is None:
                        warm_start_rejected_reason = "frozen_greedy_seed_infeasible"
                elif warm_start_rejected_reason is None:
                    warm_start_rejected_reason = f"frozen_greedy_seed_{frozen_seed_outcome.reason}"
            elif warm_start_rejected_reason is None:
                warm_start_rejected_reason = "frozen_greedy_seed_skipped_budget_or_size"

        # Task 24: Native initial seed — fast path using Rust greedy_repair_batch.
        # Dispatches ALL operations in topological order to earliest-available machines.
        # If valid → use as initial solution, skip Python GreedyDispatch entirely.
        native_initial_seed_attempted = False
        native_initial_seed_used = False
        native_initial_seed_ms = 0
        native_initial_seed_fallback_reason: str | None = None

        if native_initial_seed_enabled and initial_result is None:
            native_initial_seed_attempted = True
            t_native = time.monotonic()

            native_seed_result = _try_native_initial_seed(
                problem,
                frozen_assignments=frozen_assignments,
                ops_by_id=ops_by_id,
                frozen_assignments_by_op=frozen_assignments_by_op,
            )
            native_initial_seed_ms = int((time.monotonic() - t_native) * 1000)

            if native_seed_result is not None:
                # Validate the native seed with a RELAXED check:
                # Only require completeness (all ops assigned) and no internal
                # machine overlap. Skip frozen-precedence and full feasibility
                # checks — the native seed is a heuristic initial solution that
                # ALNS will improve through destroy/repair iterations.
                # This is the standard approach in ALNS literature (Ropke &
                # Pisinger 2006): the initial solution need not be feasible,
                # only complete.
                native_seed_valid = (
                    len(native_seed_result) == n_ops
                    and len({a.operation_id for a in native_seed_result}) == n_ops
                    and not _has_machine_overlap(native_seed_result)
                )
                if native_seed_valid:
                    recompute_assignment_setups(native_seed_result, dispatch_context)
                    initial_solver_name = "native_greedy"
                    native_initial_seed_used = True
                    initial_result = ScheduleResult(
                        solver_name=self.name,
                        status=SolverStatus.FEASIBLE,
                        assignments=native_seed_result,
                    )
                else:
                    native_initial_seed_fallback_reason = "native_seed_infeasible"
            else:
                native_initial_seed_fallback_reason = "native_unavailable_or_failed"

        if initial_result is None:
            if n_ops <= initial_beam_op_limit:
                beam_result = BeamSearchDispatch(beam_width=3).solve(problem)
                greedy_result = GreedyDispatch().solve(
                    problem,
                    time_limit_s=_initial_seed_budget_s(),
                )

                beam_valid = _is_valid_complete_schedule(list(beam_result.assignments))
                greedy_valid = _is_valid_complete_schedule(list(greedy_result.assignments))

                if beam_valid and greedy_valid:
                    beam_cost = _objective_cost(
                        _evaluate_objective(
                            problem,
                            list(beam_result.assignments),
                            sdst,
                            ops_by_id=ops_by_id,
                        ),
                        objective_weights,
                    )
                    greedy_cost = _objective_cost(
                        _evaluate_objective(
                            problem,
                            list(greedy_result.assignments),
                            sdst,
                            ops_by_id=ops_by_id,
                        ),
                        objective_weights,
                    )
                    if greedy_cost < beam_cost:
                        initial_solver_name = "greedy"
                        initial_result = greedy_result
                    else:
                        initial_solver_name = "beam"
                        initial_result = beam_result
                elif beam_valid:
                    initial_solver_name = "beam"
                    initial_result = beam_result
                else:
                    initial_solver_name = "greedy"
                    initial_result = greedy_result
            else:
                initial_solver_name = "greedy"
                initial_result = GreedyDispatch().solve(
                    problem,
                    time_limit_s=_initial_seed_budget_s(),
                )

            if _initial_seed_timed_out(initial_result):
                # Seed timed out but may still have produced enough assignments
                # to serve as a starting point. Proceed to ALNS search rather than
                # bailing out — the completion phase below will repair any gaps,
                # and the ALNS loop will then improve the resulting schedule.
                seed_coverage = len(initial_result.assignments) / max(n_ops, 1)
                if seed_coverage > 0:
                    logger.info(
                        "ALNS seed timed out at %.1f%% coverage (%d/%d), "
                        "proceeding to completion + search",
                        seed_coverage * 100,
                        len(initial_result.assignments),
                        n_ops,
                    )
                else:
                    return _initial_generation_error_result(
                        "initial_seed_greedy_timed_out",
                        reason_key="initial_seed_greedy_timed_out",
                        time_limit_exhausted_before_search=True,
                    )

            if not _is_valid_complete_schedule(list(initial_result.assignments)):
                # Fall back to greedy if beam failed to cover the full instance.
                initial_solver_name = "greedy"
                initial_result = GreedyDispatch().solve(
                    problem,
                    time_limit_s=_initial_seed_budget_s(),
                )
                if _initial_seed_timed_out(initial_result):
                    seed_coverage = len(initial_result.assignments) / max(n_ops, 1)
                    if seed_coverage > 0:
                        logger.info(
                            "ALNS fallback seed timed out at %.1f%% coverage (%d/%d), "
                            "proceeding to completion + search",
                            seed_coverage * 100,
                            len(initial_result.assignments),
                            n_ops,
                        )
                    else:
                        return _initial_generation_error_result(
                            "initial_seed_greedy_timed_out",
                            reason_key="initial_seed_greedy_timed_out",
                            time_limit_exhausted_before_search=True,
                        )
                if not _is_valid_complete_schedule(list(initial_result.assignments)):
                    # Proceed with whatever coverage we have — completion phase
                    # and ALNS will repair missing ops. Only bail if zero coverage.
                    if len(initial_result.assignments) > 0:
                        logger.info(
                            "ALNS seed incomplete (%d/%d ops), proceeding to "
                            "completion + search for repair",
                            len(initial_result.assignments),
                            n_ops,
                        )
                    else:
                        return _initial_generation_error_result(
                            "initial solution generation failed"
                        )

        if initial_result is not None and frozen_assignments:
            reanchored_initial_assignments, _ = _reanchor_against_frozen(
                list(initial_result.assignments)
            )
            if _is_valid_complete_schedule(reanchored_initial_assignments):
                recompute_assignment_setups(
                    reanchored_initial_assignments,
                    dispatch_context,
                )
                initial_result = initial_result.model_copy(
                    update={"assignments": reanchored_initial_assignments}
                )
            else:
                return _initial_generation_error_result("initial solution generation failed")

        # Completion phase: if seed did not cover all operations, repair the
        # missing ones via greedy dispatch so ALNS starts from a full schedule.
        # Hard-stop when Phase-1 wall fraction is exhausted so RHC can fall back
        # instead of burning the full window on uncapped completion.
        if initial_result is not None and len(initial_result.assignments) < n_ops:
            if _phase1_budget_exhausted():
                return _initial_generation_error_result(
                    "phase1_wall_budget_exhausted_before_completion",
                    time_limit_exhausted_before_search=True,
                )
            covered_ids = {a.operation_id for a in initial_result.assignments}
            missing_ids = problem_op_ids - covered_ids
            if missing_ids:
                repair_outcome = _repair_greedy_outcome(
                    problem,
                    list(initial_result.assignments),
                    missing_ids,
                )
                if repair_outcome.status == RepairStatus.FEASIBLE:
                    completed = list(initial_result.assignments) + list(repair_outcome.assignments)
                    completed.sort(
                        key=lambda a: (
                            a.start_time,
                            op_positions.get(a.operation_id, 0),
                        )
                    )
                    initial_result = initial_result.model_copy(update={"assignments": completed})
                    logger.info(
                        "ALNS completion phase repaired %d missing ops (now %d/%d)",
                        len(missing_ids),
                        len(completed),
                        n_ops,
                    )
                elif _phase1_budget_exhausted() or (time.monotonic() - t0) > time_limit_s:
                    return _initial_generation_error_result(
                        "phase1_wall_budget_exhausted_during_completion",
                        time_limit_exhausted_before_search=True,
                    )

        if (
            initial_result is not None
            and _phase1_budget_exhausted()
            and (time.monotonic() - t0) > time_limit_s * 0.85
        ):
            # Seed finished but consumed the Phase-1 ceiling - surface as
            # pre-search timeout so RHC prefers inline greedy coverage path.
            return _initial_generation_error_result(
                "phase1_wall_budget_exhausted_after_seed",
                time_limit_exhausted_before_search=True,
            )

        initial_solution_ms = int((time.monotonic() - initial_solution_t0) * 1000)
        time_limit_exhausted_before_search = (time.monotonic() - t0) > time_limit_s

        # Current best
        current_assignments = list(initial_result.assignments)
        current_obj = _evaluate_objective(problem, current_assignments, sdst, ops_by_id=ops_by_id)
        current_cost = _objective_cost(current_obj, objective_weights)
        initial_cost = current_cost

        # P2.1: Pre-compute order due offsets once (avoids datetime math per iteration)
        horizon_start = problem.planning_horizon_start
        order_due_offsets = {
            order.id: (order.due_date - horizon_start).total_seconds() / 60.0
            for order in problem.orders
        }
        # Build per-machine cache for incremental evaluation
        current_cache = _build_machine_objective_cache(
            problem,
            current_assignments,
            sdst,
            ops_by_id=ops_by_id,
            horizon_start=horizon_start,
            order_due_offsets=order_due_offsets,
        )

        best_assignments = list(current_assignments)
        best_obj = current_obj
        best_cost = current_cost

        # ─── Task 18: Adaptive Iteration Budget + Warm-Start Skip ───────────
        # These features reduce iteration budget for "easy" windows where the
        # warm-start already provides a near-optimal solution.

        # Task 18.2: Warm-start skip when gap < threshold.
        # If the warm-start solution is already within `warm_start_skip_threshold_gap`
        # of the lower bound, skip ALNS entirely and commit the warm-start directly.
        # Default 0.0 = disabled (conservative); set to 0.03 for aggressive skip.
        warm_start_skip_threshold_gap: float = float(
            kwargs.get("warm_start_skip_threshold_gap", 0.0)
        )
        alns_skipped_warm_start_sufficient = False
        alns_skip_gap: float | None = None

        if warm_start_skip_threshold_gap > 0 and warm_start_used:
            ws_makespan = current_obj.makespan_minutes
            ws_gap = (ws_makespan - lower_bound.value) / max(lower_bound.value, 1e-6)
            if ws_gap <= warm_start_skip_threshold_gap:
                # Warm-start is already near-optimal — skip ALNS entirely.
                alns_skipped_warm_start_sufficient = True
                alns_skip_gap = round(ws_gap, 6)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                recompute_assignment_setups(best_assignments, dispatch_context)
                final_obj = _evaluate_objective(
                    problem, best_assignments, sdst, ops_by_id=ops_by_id
                )
                return ScheduleResult(
                    solver_name=self.name,
                    status=SolverStatus.FEASIBLE,
                    assignments=best_assignments,
                    objective=final_obj,
                    duration_ms=elapsed_ms,
                    random_seed=seed,
                    metadata={
                        "alns_skipped_warm_start_sufficient": True,
                        "alns_skip_gap": alns_skip_gap,
                        "iterations_completed": 0,
                        "improvements": 0,
                        "accepted_iterations": 0,
                        "improved_iterations": 0,
                        "stagnation_detected": False,
                        "stagnation_iteration": None,
                        "warm_start_used": warm_start_used,
                        "warm_start_supplied_assignments": warm_start_supplied_assignments,
                        "warm_start_completed_assignments": warm_start_completed_assignments,
                        "warm_start_rejected_reason": warm_start_rejected_reason,
                        "alns_warm_start_used": warm_start_used,
                        "alns_warm_start_coverage": round(
                            warm_start_supplied_assignments / max(n_ops, 1), 6
                        ),
                        "initial_solver": initial_solver_name,
                        "initial_solution_ms": initial_solution_ms,
                        "native_initial_seed_attempted": native_initial_seed_attempted,
                        "native_initial_seed_used": native_initial_seed_used,
                        "native_initial_seed_ms": native_initial_seed_ms,
                        "native_initial_seed_fallback_reason": native_initial_seed_fallback_reason,
                        "time_limit_exhausted_before_search": False,
                        "max_iterations": max_iterations,
                        "max_no_improve_iters": max_no_improve_iters,
                        "lower_bound": round(lower_bound.value, 4),
                        "alns_lower_bound": round(lower_bound.value, 4),
                        "alns_gap_ratio": round(
                            max(final_obj.makespan_minutes - lower_bound.value, 0.0)
                            / max(lower_bound.value, 1e-6),
                            6,
                        ),
                        "lower_bound_components": lower_bound.as_metadata(),
                    },
                )

        # Task 18.1: Reduce max_no_improve_iters for high-coverage warm-starts.
        # When warm-start coverage > 80%, the initial solution is already good;
        # fewer stagnation-patience iterations are needed.
        warm_start_coverage = warm_start_supplied_assignments / max(n_ops, 1)
        if warm_start_used and warm_start_coverage > 0.8 and max_no_improve_iters > 15:
            max_no_improve_iters = 15

        # Task 18.3: Adaptive iteration scaling.
        # Scale max_iterations proportionally to (1 - warm_start_coverage):
        # full coverage → 10% of budget (floor), no coverage → full budget.
        # Default False (conservative); RHC can enable via inner_kwargs.
        adaptive_iteration_scaling: bool = bool(kwargs.get("adaptive_iteration_scaling", False))
        adaptive_iteration_scaling_applied = False
        original_max_iterations = max_iterations

        if adaptive_iteration_scaling and warm_start_used:
            scale_factor = max(0.1, 1.0 - warm_start_coverage)
            max_iterations = max(5, int(max_iterations * scale_factor))
            adaptive_iteration_scaling_applied = True

        if sa_auto_calibration_enabled:
            sa_calibrated_base_temp, sa_calibration_samples = _calibrate_sa_temperature(
                problem,
                current_assignments,
                current_cost=current_cost,
                objective_weights=objective_weights,
                sdst=sdst,
                destroy_size=destroy_size,
                max_destroy=max_destroy,
                ops_by_id=ops_by_id,
                successors_by_op=successors_by_op,
                trials=sa_calibration_trials,
                acceptance_probability=sa_initial_acceptance_probability,
                seed=seed,
                fallback_temperature=sa_initial_temp,
            )
            if sa_calibration_samples > 0:
                # R5: express sa_temp_min as a fraction of calibrated T_0.
                # An absolute floor of 50.0 causes acceptance probability
                # e^(-delta/50) ≈ 0 for large-scale objectives (delta ~ 1000s),
                # effectively reducing SA to a hill-climber after very few iters.
                # Pepels (2014): T_min = 0.01 * T_0 is the recommended lower end.
                sa_temp_min = max(sa_temp_min, 0.01 * sa_calibrated_base_temp)
                # Recompute effective initial temperature with calibrated base
                # via _compute_effective_temperature.
                effective_sa_initial_temp = _compute_effective_temperature(
                    base_temp=sa_calibrated_base_temp,
                    due_pressure=due_pressure,
                    candidate_pressure=candidate_pressure,
                    due_alpha=sa_due_alpha if dynamic_sa_enabled else 0.0,
                    candidate_beta=sa_candidate_beta if dynamic_sa_enabled else 0.0,
                    min_temp=sa_temp_min,
                    max_temp=sa_temp_max,
                )

        # ------- Phase 2: ALNS operator selection (Roulette Wheel) -------
        n_operators = len(DESTROY_OPERATORS)
        operator_names = [name for name, _ in DESTROY_OPERATORS]
        operator_scores = [0.0] * n_operators
        operator_attempts = [0] * n_operators

        # C2 (Task 12.1): Process initial_operator_weights kwarg via helper.
        # Prefer dict keyed by operator name (robust to DESTROY_OPERATORS reordering).
        initial_normalized_weights = _normalize_initial_operator_weights(
            initial_operator_weights_raw, operator_names
        )
        operator_weights = list(initial_normalized_weights)

        # Snapshot initial weights for metadata (after normalization)
        initial_operator_weights_dict = {
            name: round(w, 6) for name, w in zip(operator_names, operator_weights, strict=True)
        }

        # C4 (Task 3b.2-3b.4): Bounded cross-window operator bias.
        # Applied once at initialization (before the main loop). Does NOT modify
        # weights during the loop. When the flag is off or hints are absent,
        # behavior is identical to baseline.
        cross_window_bias_applied = False
        cross_window_bias_operator_deltas: dict[str, float] = dict.fromkeys(operator_names, 0.0)

        if (
            cross_window_operator_bias_enabled
            and cross_window_hints
            and isinstance(cross_window_hints, list)
            and len(cross_window_hints) > 0
        ):
            # Compute setup concentration signal: average max machine setup cost
            # across all hint windows, normalized to [0, 1].
            total_max_setup = 0.0
            valid_hint_count = 0
            for hint in cross_window_hints:
                setup_by_machine = getattr(hint, "setup_cost_by_machine", None)
                if setup_by_machine and isinstance(setup_by_machine, dict):
                    machine_costs = [
                        v for v in setup_by_machine.values() if isinstance(v, int | float) and v > 0
                    ]
                    if machine_costs:
                        total_max_setup += max(machine_costs)
                        valid_hint_count += 1

            if valid_hint_count > 0:
                avg_max_setup = total_max_setup / valid_hint_count
                # Normalize signal to [0, 1] — 100 minutes of setup cost is
                # considered full saturation.
                signal = min(1.0, avg_max_setup / 100.0)
                # Bounded boost: max 15% of the operator's own weight.
                boost_factor = min(0.15, signal * 0.15)

                if boost_factor > 0.0:
                    pre_bias_weights = list(operator_weights)

                    # Primary boost: machine_segment
                    for idx, name in enumerate(operator_names):
                        if name == "machine_segment":
                            operator_weights[idx] += boost_factor * operator_weights[idx]
                        elif name == "worst":
                            # Secondary boost: worst gets half the boost
                            operator_weights[idx] += (boost_factor * 0.5) * operator_weights[idx]

                    # 3b.3: Floor — no operator weight below 1/(n_operators * 10)
                    # i.e., 10% of uniform weight. This prevents any operator from
                    # being zeroed out.
                    weight_floor = 1.0 / (n_operators * 10)
                    for idx in range(n_operators):
                        if operator_weights[idx] < weight_floor:
                            operator_weights[idx] = weight_floor

                    # Re-normalize to sum 1.0
                    weight_sum = sum(operator_weights)
                    if weight_sum > 0.0:
                        operator_weights = [w / weight_sum for w in operator_weights]

                    cross_window_bias_applied = True
                    cross_window_bias_operator_deltas = {
                        name: round(operator_weights[idx] - pre_bias_weights[idx], 6)
                        for idx, name in enumerate(operator_names)
                    }

        # Score rewards (Ropke & Pisinger 2006 §4.2)
        sigma_1 = 33.0  # new global best
        sigma_2 = 9.0  # better than current
        sigma_3 = 3.0  # accepted (SA)

        temperature = effective_sa_initial_temp

        # Tracking
        improvements = 0
        cpsat_repair_attempts = 0
        cpsat_repairs = 0
        cpsat_repair_skips_large_destroy = 0
        cpsat_repair_timeouts = 0
        greedy_repair_attempts = 0
        greedy_repairs = 0
        greedy_repair_timeouts = 0
        cpsat_repair_ms_total = 0
        greedy_repair_ms_total = 0
        # R2 (EMA calibration): track total destroyed-op count per repair lane
        # so RHC can compute an empirical mean repair time per destroyed op.
        cpsat_repair_total_destroy_size = 0
        greedy_repair_total_destroy_size = 0
        feasibility_failures = 0
        sa_worsening_accepted = 0
        sa_worsening_rejected = 0
        repair_rejection_reasons: dict[str, int] = {}
        iterations_completed = 0
        accepted_iterations = 0
        no_improve_streak = 0
        no_improve_early_stop = False
        stagnation_iteration: int | None = None
        # B3 (Task 7.4): Cumulative per-operator tracking (never reset)
        cumulative_operator_attempts = [0] * n_operators
        cumulative_operator_improvements = [0] * n_operators
        # P3.3: EMA repair-time tracker
        ema_repair_ms: float = 0.0
        ema_repair_samples: int = 0
        # P3.1: fixed ops tracking
        fixed_ops_applied = len(fixed_op_ids)

        logger.info(
            "ALNS starting: %d ops, %d machines, destroy_size=%d, max_iter=%d, fixed_ops=%d",
            n_ops,
            len(problem.work_centers),
            destroy_size,
            max_iterations,
            fixed_ops_applied,
        )

        # B3 (Task 7.3): Per-iteration trace — bounded via deque(maxlen=N).
        # Oldest-dropped via deque(maxlen=N). When the trace exceeds
        # max_iteration_records, the oldest records are silently discarded.
        # This keeps memory bounded while preserving the most recent
        # convergence behavior.
        iteration_trace: deque[AlnsIterationRecord] = (
            deque(maxlen=max_iteration_records) if record_iteration_metrics else deque(maxlen=0)
        )

        # ------- Phase 3: Main ALNS loop -------
        if time_limit_exhausted_before_search:
            logger.info(
                "ALNS time limit exhausted during initial solution generation (%d ms)",
                initial_solution_ms,
            )
        else:
            for iteration in range(1, max_iterations + 1):
                elapsed = time.monotonic() - t0
                # D3: time_limit_s is a HARD deadline. It must win over
                # min_iterations — the old `iteration > min_iterations` gate
                # let 5 unbounded repair iterations overshoot an 8s budget 5x.
                if elapsed >= time_limit_s:
                    logger.info("ALNS time limit reached at iteration %d", iteration)
                    break

                iterations_completed = iteration

                # Select destroy operator (roulette wheel)
                total_weight = sum(operator_weights)
                r = rng.random() * total_weight
                cumulative = 0.0
                selected_op_idx = 0
                for idx, w in enumerate(operator_weights):
                    cumulative += w
                    if cumulative >= r:
                        selected_op_idx = idx
                        break

                op_name, destroy_fn = DESTROY_OPERATORS[selected_op_idx]

                # P3.2: use adaptive destroy size
                effective_destroy_size = (
                    adaptive_destroy_current if adaptive_destroy_enabled else destroy_size
                )

                destroyed_ids = destroy_fn(
                    current_assignments,
                    problem,
                    sdst,
                    effective_destroy_size,
                    rng,
                    ops_by_id=ops_by_id,
                )

                # P3.1: exclude fixed ops from destroy set
                if fixed_op_ids:
                    destroyed_ids -= fixed_op_ids

                if not destroyed_ids:
                    continue

                destroyed_ids = _expand_successor_closure(
                    destroyed_ids,
                    successors_by_op,
                )
                destroyed_ids = _cap_destroy_set_preserving_successor_closure(
                    destroyed_ids,
                    ops_by_id,
                    successors_by_op,
                    max_destroy,
                    rng,
                )

                # Frozen assignments (everything not destroyed)
                internal_frozen = [
                    assignment
                    for assignment in current_assignments
                    if assignment.operation_id not in destroyed_ids
                ]
                frozen = frozen_assignments + internal_frozen
                frozen_by_op = dict(frozen_assignments_by_op)
                frozen_by_op.update(
                    {assignment.operation_id: assignment for assignment in internal_frozen}
                )

                # Repair — primary depends on use_cpsat_repair flag
                # CP-SAT repair (Laborie & Godard 2007) when enabled, greedy fallback otherwise
                new_assignments: list[Assignment] | None = None
                repair_used = "none"

                def record_repair_outcome(outcome: RepairOutcome) -> None:
                    if outcome.status == RepairStatus.FEASIBLE:
                        return
                    reason = outcome.reason or outcome.status.value
                    repair_rejection_reasons[reason] = repair_rejection_reasons.get(reason, 0) + 1

                if use_cpsat_repair and len(destroyed_ids) <= cpsat_max_destroy_ops:
                    cpsat_repair_attempts += 1
                    cpsat_repair_t0 = time.monotonic()
                    # D3: clamp the micro-repair budget to the remaining
                    # wall-clock budget so a single repair cannot blow the
                    # solver deadline (floor of 1s keeps CP-SAT usable).
                    remaining_s = time_limit_s - (time.monotonic() - t0)
                    effective_repair_limit_s = max(1, min(repair_time_limit_s, int(remaining_s)))
                    cpsat_outcome = _repair_cpsat_outcome(
                        problem,
                        frozen,
                        destroyed_ids,
                        time_limit_s=effective_repair_limit_s,
                        num_workers=repair_num_workers,
                        ops_by_id=ops_by_id,
                        op_positions=op_positions,
                    )
                    cpsat_repair_ms_total += int((time.monotonic() - cpsat_repair_t0) * 1000)
                    cpsat_repair_total_destroy_size += len(destroyed_ids)
                    if cpsat_outcome.status == RepairStatus.TIMEOUT:
                        cpsat_repair_timeouts += 1
                    if cpsat_outcome.status == RepairStatus.FEASIBLE:
                        cpsat_result = list(cpsat_outcome.assignments)
                        # Quick machine-overlap check against frozen assignments:
                        # CP-SAT sub-problem doesn't see frozen timelines, so verify
                        # no returned assignment overlaps a frozen one on the same machine.
                        test_candidate = frozen + cpsat_result
                        if not _has_machine_overlap(
                            test_candidate
                        ) and not _violates_frozen_precedence(
                            cpsat_result,
                            frozen_by_op,
                            ops_by_id,
                        ):
                            new_assignments = cpsat_result
                            repair_used = "cpsat"
                            cpsat_repairs += 1
                        else:
                            record_repair_outcome(
                                RepairOutcome(
                                    status=RepairStatus.INFEASIBLE,
                                    assignments=(),
                                    reason="cpsat_conflict_with_frozen",
                                )
                            )
                    else:
                        record_repair_outcome(cpsat_outcome)
                elif use_cpsat_repair:
                    cpsat_repair_skips_large_destroy += 1

                if new_assignments is None:
                    greedy_repair_attempts += 1
                    greedy_repair_t0 = time.monotonic()
                    greedy_outcome = _repair_greedy_outcome(problem, frozen, destroyed_ids)
                    greedy_repair_ms_total += int((time.monotonic() - greedy_repair_t0) * 1000)
                    greedy_repair_total_destroy_size += len(destroyed_ids)
                    if greedy_outcome.status == RepairStatus.TIMEOUT:
                        greedy_repair_timeouts += 1
                    if greedy_outcome.status == RepairStatus.FEASIBLE:
                        greedy_repair_assignments = list(greedy_outcome.assignments)
                        test_candidate = frozen + greedy_repair_assignments
                        if not _has_machine_overlap(
                            test_candidate
                        ) and not _violates_frozen_precedence(
                            greedy_repair_assignments, frozen_by_op, ops_by_id
                        ):
                            new_assignments = greedy_repair_assignments
                            repair_used = "greedy"
                            greedy_repairs += 1
                        else:
                            record_repair_outcome(
                                RepairOutcome(
                                    status=RepairStatus.INFEASIBLE,
                                    assignments=(),
                                    reason="greedy_conflict_with_frozen",
                                )
                            )
                    else:
                        record_repair_outcome(greedy_outcome)

                if new_assignments is None:
                    continue  # repair failed, discard this iteration

                # Assemble candidate solution
                candidate = internal_frozen + new_assignments

                # Quick feasibility sanity check (only check completeness)
                candidate_op_ids = {a.operation_id for a in candidate}
                if len(candidate_op_ids) != n_ops:
                    feasibility_failures += 1
                    continue
                if _has_precedence_violation(candidate, ops_by_id):
                    feasibility_failures += 1
                    continue
                if _violates_frozen_precedence(
                    candidate,
                    frozen_assignments_by_op,
                    ops_by_id,
                ):
                    feasibility_failures += 1
                    continue
                if _has_machine_overlap(frozen_assignments + candidate):
                    feasibility_failures += 1
                    continue

                # Evaluate incrementally — only recompute affected machines
                # Affected = machines that had destroyed ops + machines that got repaired ops
                affected_machine_ids: set[Any] = set()
                destroyed_assignment_map = {
                    a.operation_id: a
                    for a in current_assignments
                    if a.operation_id in destroyed_ids
                }
                for a in destroyed_assignment_map.values():
                    affected_machine_ids.add(a.work_center_id)
                for a in new_assignments:
                    affected_machine_ids.add(a.work_center_id)

                candidate_obj, candidate_cache = _evaluate_objective_incremental(
                    problem,
                    candidate,
                    sdst,
                    ops_by_id=ops_by_id,
                    horizon_start=horizon_start,
                    affected_machine_ids=affected_machine_ids,
                    base_cache=current_cache,
                )
                candidate_cost = _objective_cost(candidate_obj, objective_weights)
                delta = candidate_cost - current_cost

                # SA acceptance
                score_reward = 0.0
                if candidate_cost < best_cost:
                    # New global best
                    best_assignments = list(candidate)
                    best_obj = candidate_obj
                    best_cost = candidate_cost
                    current_assignments = candidate
                    current_obj = candidate_obj
                    current_cost = candidate_cost
                    current_cache = candidate_cache
                    score_reward = sigma_1
                    improvements += 1
                    no_improve_streak = 0
                    logger.debug(
                        "ALNS iter %d: new best (cost=%.1f, makespan=%.1f, %s destroy, %s repair)",
                        iteration,
                        best_cost,
                        best_obj.makespan_minutes,
                        op_name,
                        repair_used,
                    )
                elif _sa_accept(delta, temperature, rng):
                    current_assignments = candidate
                    current_obj = candidate_obj
                    current_cost = candidate_cost
                    current_cache = candidate_cache
                    score_reward = sigma_2 if delta < 0 else sigma_3
                    if delta < 0:
                        no_improve_streak = 0
                    else:
                        sa_worsening_accepted += 1
                        no_improve_streak += 1
                # else: reject
                else:
                    if delta > 0:
                        sa_worsening_rejected += 1
                    no_improve_streak += 1

                # Update operator scores
                operator_scores[selected_op_idx] += score_reward
                operator_attempts[selected_op_idx] += 1

                # B3 (Task 7.4): Cumulative per-operator tracking (never reset)
                cumulative_operator_attempts[selected_op_idx] += 1
                if score_reward >= sigma_1:
                    cumulative_operator_improvements[selected_op_idx] += 1
                # Track accepted iterations (improved OR SA-accepted)
                if score_reward > 0.0:
                    accepted_iterations += 1

                # Update operator weights on segment boundaries and reset the segment.
                if iteration % operator_weight_segment_length == 0:
                    operator_weights = _update_operator_weights_for_segment(
                        operator_scores,
                        operator_attempts,
                        reset_mix=operator_weight_reset_mix,
                    )
                    operator_scores = [0.0] * n_operators
                    operator_attempts = [0] * n_operators

                # B3 (Task 7.3): Record per-iteration metrics when enabled.
                # The boolean check is near-zero overhead when disabled.
                if record_iteration_metrics:
                    iteration_trace.append(
                        AlnsIterationRecord(
                            iteration=iteration,
                            operator_name=op_name,
                            destroy_size=len(destroyed_ids),
                            repair_status="feasible",  # only reached when repair succeeded
                            candidate_cost=candidate_cost,
                            best_cost=best_cost,
                            temperature=temperature,
                            accepted=score_reward > 0.0,
                            improved=score_reward >= sigma_1,
                        )
                    )

                # P3.3: Update EMA repair time
                iter_repair_ms = 0
                if repair_used == "cpsat":
                    iter_repair_ms = cpsat_repair_ms_total  # cumulative, approximate
                elif repair_used == "greedy":
                    iter_repair_ms = greedy_repair_ms_total
                if iter_repair_ms > 0:
                    if ema_repair_samples == 0:
                        ema_repair_ms = float(iter_repair_ms)
                    else:
                        ema_repair_ms = (
                            ema_repair_alpha * iter_repair_ms
                            + (1.0 - ema_repair_alpha) * ema_repair_ms
                        )
                    ema_repair_samples += 1

                # P3.2: Adaptive destroy sizing
                if adaptive_destroy_enabled:
                    if score_reward >= sigma_1:
                        # Improvement found — shrink destroy to exploit
                        adaptive_destroy_current = max(
                            min_destroy,
                            int(adaptive_destroy_current * adaptive_destroy_shrink_rate),
                        )
                    elif no_improve_streak > 0 and no_improve_streak % 5 == 0:
                        # No improvement plateau — grow destroy to explore
                        adaptive_destroy_current = min(
                            max_destroy,
                            int(adaptive_destroy_current * adaptive_destroy_grow_rate),
                        )

                # Cool down
                temperature *= effective_sa_cooling_rate

                if max_no_improve_iters > 0 and no_improve_streak >= max_no_improve_iters:
                    no_improve_early_stop = True
                    stagnation_iteration = iteration
                    logger.info(
                        "ALNS early stop: no improvements for %d consecutive iterations",
                        no_improve_streak,
                    )
                    break

        # ------- Phase 4: Final validation -------
        # Recompute setups from final sequence
        recompute_assignment_setups(best_assignments, dispatch_context)
        final_obj = _evaluate_objective(problem, best_assignments, sdst, ops_by_id=ops_by_id)
        final_cost = _objective_cost(final_obj, objective_weights)

        # Full feasibility check
        violations = checker.check(problem, best_assignments)
        final_violations_before_recovery = len(violations)
        final_violation_recovery_attempted = final_violations_before_recovery > 0
        final_violation_recovered = False
        final_violation_recovery_source: str | None = None

        if final_violation_recovery_attempted:
            # Recover to the initial full schedule if the ALNS incumbent is invalid.
            # This keeps downstream RHC windows from failing due to a rare
            # end-of-search violation in an otherwise schedulable window.
            recovered_assignments = list(initial_result.assignments)
            recompute_assignment_setups(recovered_assignments, dispatch_context)
            recovered_violations = checker.check(problem, recovered_assignments)
            if not recovered_violations:
                logger.warning(
                    "ALNS final incumbent had %d violations; recovering to initial solution",
                    final_violations_before_recovery,
                )
                best_assignments = recovered_assignments
                final_obj = _evaluate_objective(
                    problem,
                    best_assignments,
                    sdst,
                    ops_by_id=ops_by_id,
                )
                final_cost = _objective_cost(final_obj, objective_weights)
                violations = recovered_violations
                final_violation_recovered = True
                final_violation_recovery_source = "initial_solution"
            else:
                logger.warning(
                    "ALNS final incumbent had %d violations; "
                    "initial-solution recovery still has %d violations",
                    final_violations_before_recovery,
                    len(recovered_violations),
                )

        status = SolverStatus.FEASIBLE if not violations else SolverStatus.ERROR

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            "ALNS finished: %d iterations, %d improvements, cost=%.1f, "
            "makespan=%.1f min, %d cpsat repairs, %d greedy repairs, "
            "%d feasibility failures, %d violations, %d ms",
            iterations_completed,
            improvements,
            final_cost,
            final_obj.makespan_minutes,
            cpsat_repairs,
            greedy_repairs,
            feasibility_failures,
            len(violations),
            elapsed_ms,
        )

        return ScheduleResult(
            solver_name=self.name,
            status=status,
            assignments=best_assignments,
            objective=final_obj,
            duration_ms=elapsed_ms,
            random_seed=seed,
            metadata={
                "iterations_completed": iterations_completed,
                "improvements": improvements,
                # B3 (Task 7.4): Aggregate convergence metadata — always present
                "accepted_iterations": accepted_iterations,
                "improved_iterations": improvements,
                "operator_attempt_counts": {
                    name: cumulative_operator_attempts[i]
                    for i, (name, _) in enumerate(DESTROY_OPERATORS)
                },
                "operator_improvement_counts": {
                    name: cumulative_operator_improvements[i]
                    for i, (name, _) in enumerate(DESTROY_OPERATORS)
                },
                "alns_final_operator_weights": {
                    name: round(operator_weights[i], 6)
                    for i, (name, _) in enumerate(DESTROY_OPERATORS)
                },
                # C2 (Task 12.1): Operator name list and initial weights for
                # weight-persistence diagnostics across RHC windows.
                "alns_operator_names": operator_names,
                "alns_initial_operator_weights": initial_operator_weights_dict,
                # C4 (Task 3b.4): Cross-window operator bias metadata — always
                # present regardless of whether bias was applied.
                "cross_window_bias_applied": cross_window_bias_applied,
                "cross_window_bias_operator_deltas": cross_window_bias_operator_deltas,
                "stagnation_detected": no_improve_early_stop,
                "stagnation_iteration": stagnation_iteration,
                "cpsat_repair_attempts": cpsat_repair_attempts,
                "cpsat_repairs": cpsat_repairs,
                "cpsat_repair_skips_large_destroy": cpsat_repair_skips_large_destroy,
                "cpsat_repair_timeouts": cpsat_repair_timeouts,
                "cpsat_repair_total_destroy_size": cpsat_repair_total_destroy_size,
                "greedy_repair_attempts": greedy_repair_attempts,
                "greedy_repairs": greedy_repairs,
                "greedy_repair_timeouts": greedy_repair_timeouts,
                "greedy_repair_total_destroy_size": greedy_repair_total_destroy_size,
                # R2 (EMA calibration): empirical mean repair time per destroyed
                # op, weighted across both repair lanes. None when no repair
                # attempt produced a non-zero destroy size (cold start).
                "observed_repair_s_per_destroyed_op": (
                    (cpsat_repair_ms_total + greedy_repair_ms_total)
                    / 1000.0
                    / (cpsat_repair_total_destroy_size + greedy_repair_total_destroy_size)
                    if (cpsat_repair_total_destroy_size + greedy_repair_total_destroy_size) > 0
                    else None
                ),
                "repair_rejection_reasons": repair_rejection_reasons,
                "initial_solver": initial_solver_name,
                "warm_start_used": warm_start_used,
                "warm_start_supplied_assignments": warm_start_supplied_assignments,
                "warm_start_completed_assignments": warm_start_completed_assignments,
                "warm_start_rejected_reason": warm_start_rejected_reason,
                # C1 (Task 9.4): explicit ALNS-scoped warm-start signals for RHC
                # telemetry. `alns_warm_start_used` mirrors `warm_start_used`
                # but is prefixed to avoid ambiguity with RHC-owned keys.
                # `alns_warm_start_coverage` is the fraction of operations in
                # the current (sub-)problem that the caller-supplied warm
                # start covered before any greedy fill or rejection.
                "alns_warm_start_used": warm_start_used,
                "alns_warm_start_coverage": round(
                    warm_start_supplied_assignments / max(n_ops, 1), 6
                ),
                "initial_beam_op_limit": initial_beam_op_limit,
                "frozen_initial_repair_max_ops": frozen_initial_repair_max_ops,
                "phase1_wall_fraction": phase1_wall_fraction,
                "frozen_initial_repair_min_remaining_time_s": (
                    frozen_initial_repair_min_remaining_time_s
                ),
                "cpsat_max_destroy_ops": cpsat_max_destroy_ops,
                "repair_num_workers": repair_num_workers,
                "initial_solution_ms": initial_solution_ms,
                "native_initial_seed_attempted": native_initial_seed_attempted,
                "native_initial_seed_used": native_initial_seed_used,
                "native_initial_seed_ms": native_initial_seed_ms,
                "native_initial_seed_fallback_reason": native_initial_seed_fallback_reason,
                "time_limit_exhausted_before_search": time_limit_exhausted_before_search,
                "max_no_improve_iters": max_no_improve_iters,
                "max_no_improve_base_iters": max_no_improve_base_iters,
                "dynamic_no_improve_enabled": dynamic_no_improve_enabled,
                "dynamic_sa_enabled": dynamic_sa_enabled,
                "sa_auto_calibration_enabled": sa_auto_calibration_enabled,
                "sa_calibration_trials": sa_calibration_trials,
                "sa_calibration_samples": sa_calibration_samples,
                "sa_initial_acceptance_probability": sa_initial_acceptance_probability,
                "due_pressure": round(due_pressure, 4),
                "candidate_pressure": round(candidate_pressure, 4),
                "sa_pressure_factor": round(sa_pressure_factor, 4),
                "sa_calibrated_base_temp": round(sa_calibrated_base_temp, 4),
                "effective_sa_initial_temp": round(effective_sa_initial_temp, 4),
                "effective_sa_cooling_rate": round(effective_sa_cooling_rate, 6),
                "operator_weight_segment_length": operator_weight_segment_length,
                "operator_weight_reset_mix": operator_weight_reset_mix,
                "sa_due_alpha": sa_due_alpha,
                "sa_candidate_beta": sa_candidate_beta,
                "sa_pressure_cooling_gamma": sa_pressure_cooling_gamma,
                "sa_temp_min": sa_temp_min,
                "sa_temp_max": sa_temp_max,
                "no_improve_due_alpha": no_improve_due_alpha,
                "no_improve_candidate_beta": no_improve_candidate_beta,
                "no_improve_min_iters": no_improve_min_iters,
                "no_improve_max_iters": no_improve_max_iters,
                "no_improve_early_stop": no_improve_early_stop,
                "no_improve_streak_final": no_improve_streak,
                "sa_worsening_accepted": sa_worsening_accepted,
                "sa_worsening_rejected": sa_worsening_rejected,
                "effective_sa_acceptance_rate": round(
                    sa_worsening_accepted / max(1, sa_worsening_accepted + sa_worsening_rejected),
                    4,
                ),
                "cpsat_repair_ms_total": cpsat_repair_ms_total,
                "greedy_repair_ms_total": greedy_repair_ms_total,
                "cpsat_repair_ms_mean": round(cpsat_repair_ms_total / cpsat_repair_attempts, 2)
                if cpsat_repair_attempts > 0
                else 0.0,
                "greedy_repair_ms_mean": round(greedy_repair_ms_total / greedy_repair_attempts, 2)
                if greedy_repair_attempts > 0
                else 0.0,
                "feasibility_failures": feasibility_failures,
                "final_violation_recovery_attempted": final_violation_recovery_attempted,
                "final_violation_recovered": final_violation_recovered,
                "final_violation_recovery_source": final_violation_recovery_source,
                "final_violations_before_recovery": final_violations_before_recovery,
                "final_violations": len(violations),
                "destroy_operators": {
                    name: {
                        "final_weight": round(operator_weights[i], 4),
                    }
                    for i, (name, _) in enumerate(DESTROY_OPERATORS)
                },
                "sdst_matrix_bytes": sdst.memory_bytes(),
                "initial_cost": round(initial_cost, 2),
                "final_cost": round(final_cost, 2),
                "lower_bound": round(lower_bound.value, 4),
                "upper_bound": round(final_obj.makespan_minutes, 4),
                "gap": round(
                    max(final_obj.makespan_minutes - lower_bound.value, 0.0)
                    / max(final_obj.makespan_minutes, 1e-9),
                    6,
                ),
                "lower_bound_method": "relaxed_precedence_capacity",
                "lower_bound_components": lower_bound.as_metadata(),
                # Audit task 6.2 / 6.3: ALNS-scoped lower bound + gap ratio
                # using the conventional relative-gap formula (denominator is
                # max(LB, 1e-6)), compared against the makespan (never the
                # weighted ALNS cost) per audit correction.
                "alns_lower_bound": round(lower_bound.value, 4),
                "alns_gap_ratio": round(
                    max(final_obj.makespan_minutes - lower_bound.value, 0.0)
                    / max(lower_bound.value, 1e-6),
                    6,
                ),
                "improvement_pct": round((1 - final_cost / max(initial_cost, 1e-9)) * 100, 2),
                # P3.1: Variable fixing metadata
                "fixed_ops_applied": fixed_ops_applied,
                # P3.2: Adaptive destroy metadata
                "adaptive_destroy_enabled": adaptive_destroy_enabled,
                "adaptive_destroy_final_size": adaptive_destroy_current,
                # P3.3: EMA repair-time metadata
                "ema_repair_ms": round(ema_repair_ms, 2),
                "ema_repair_samples": ema_repair_samples,
                # Task 18: Adaptive iteration budget metadata
                "alns_skipped_warm_start_sufficient": alns_skipped_warm_start_sufficient,
                "adaptive_iteration_scaling": adaptive_iteration_scaling,
                "adaptive_iteration_scaling_applied": adaptive_iteration_scaling_applied,
                "max_iterations": max_iterations,
                "original_max_iterations": original_max_iterations,
                # B3 (Task 7.3): Per-iteration convergence trace (only when enabled)
                **(
                    {"alns_iteration_trace": [record.to_dict() for record in iteration_trace]}
                    if record_iteration_metrics
                    else {}
                ),
            },
        )
