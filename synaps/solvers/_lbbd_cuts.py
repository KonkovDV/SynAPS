"""Shared lower-bound helpers for LBBD master cuts.

Both `synaps.solvers.lbbd_solver` and `synaps.solvers.lbbd_hd_solver` rely on
the same three sequence-aware lower-bound primitives:

    * `compute_machine_transition_floor` — sequence-independent per-transition
      floor that is safe for the master because it is positive only when every
      pair of states routable to the machine carries a positive sdst.
    * `compute_sequence_independent_setup_lower_bound` — total floor for a
      machine cluster derived from the realised state mix in the subproblem
      assignments (used as the right-hand side of the legacy `setup_cost` cut).
    * `compute_machine_tsp_lower_bound` — sequence-aware Bellman-Held-Karp
      bound that solves the asymmetric Hamiltonian-path problem on the
      realised distinct state types per machine (Naderi & Roshanaei, 2021).

Centralising these helpers keeps the two solvers in lockstep and prevents the
silent divergence that would otherwise occur as cut formulations evolve.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from uuid import UUID

    from synaps.model import Assignment, Operation, ScheduleProblem


class BendersCutLike(Protocol):
    """Structural type for Benders cuts shared by both LBBD solvers.

    Both `synaps.solvers.lbbd_solver._BendersCut` and
    `synaps.solvers.lbbd_hd_solver._BendersCut` carry these four attributes
    via `__slots__`. A Protocol keeps `cut_pool_fingerprint` solver-agnostic
    without inviting a hard cross-import.
    """

    kind: str
    rhs: float
    bottleneck_ops: set[UUID]


def cut_pool_fingerprint(cut: BendersCutLike) -> tuple[str, frozenset[UUID], float]:
    """Return a canonical fingerprint for cut-pool deduplication.

    Two cuts collapse to the same fingerprint iff they agree on kind,
    bottleneck operations, and rhs to three decimals. The rhs rounding
    avoids near-duplicate accumulation when subproblem makespans differ
    only by floating-point drift across iterations or partitions.

    Units: rhs is in minutes (consistent with makespan_minutes). The 3-decimal
    precision is noise-free for integer minute values and typical float results
    from setup/transition lookups. ARC-derived bounds that divide by pool_size
    may produce sub-minute precision; rounding prevents near-duplicates.
    """

    return (cut.kind, frozenset(cut.bottleneck_ops), round(float(cut.rhs), 3))


def compute_machine_transition_floor(
    problem: ScheduleProblem,
    eligible_by_op: dict[UUID, list[UUID]],
    work_center_id: UUID,
    setup_lookup: Mapping[tuple[UUID, UUID, UUID], float],
) -> float:
    """Return the strongest safe per-transition setup floor for the master.

    The master does not know the realized state sequence, so a positive floor
    is valid only when every possible transition between states that may be
    routed to the machine carries a positive setup cost.
    """

    relevant_state_ids = {
        operation.state_id
        for operation in problem.operations
        if work_center_id in eligible_by_op.get(operation.id, [])
    }
    if not relevant_state_ids:
        return 0.0

    min_transition = float("inf")
    for from_state_id in relevant_state_ids:
        for to_state_id in relevant_state_ids:
            transition = float(
                setup_lookup.get((work_center_id, from_state_id, to_state_id), 0.0)
            )
            if transition <= 0:
                return 0.0
            min_transition = min(min_transition, transition)

    return 0.0 if min_transition == float("inf") else min_transition


def compute_sequence_independent_setup_lower_bound(
    assignments: list[Assignment],
    work_center_id: UUID,
    ops_by_id: dict[UUID, Operation],
    setup_lookup: Mapping[tuple[UUID, UUID, UUID], float],
) -> float:
    """Return a sequence-independent setup lower bound for a machine cluster."""

    state_ids = [
        operation.state_id
        for assignment in assignments
        if (operation := ops_by_id.get(assignment.operation_id)) is not None
    ]
    if len(state_ids) < 2:
        return 0.0

    distinct_state_ids = sorted(set(state_ids), key=str)
    if len(distinct_state_ids) == 1:
        state_id = distinct_state_ids[0]
        self_setup = float(setup_lookup.get((work_center_id, state_id, state_id), 0.0))
        return max(self_setup, 0.0) * float(len(state_ids) - 1)

    min_cross_state_setup = min(
        float(setup_lookup.get((work_center_id, from_state_id, to_state_id), 0.0))
        for from_state_id in distinct_state_ids
        for to_state_id in distinct_state_ids
        if from_state_id != to_state_id
    )
    if min_cross_state_setup <= 0:
        return 0.0

    return min_cross_state_setup * float(len(distinct_state_ids) - 1)


def compute_machine_tsp_lower_bound(
    state_ids: list[UUID],
    work_center_id: UUID,
    setup_lookup: Mapping[tuple[UUID, UUID, UUID], float],
    *,
    max_states: int = 12,
) -> float:
    """Sequence-aware setup lower bound on a single machine.

    Solves the asymmetric Hamiltonian-path problem on the realised distinct
    state types via Bellman-Held-Karp dynamic programming. The result is the
    minimum cumulative setup time for any visit order of those state types
    under the work-center-local sdst matrix and is therefore a valid lower
    bound on the actual sequence-dependent setup contribution to the
    machine's makespan, dominating the sequence-independent floor used by
    `compute_sequence_independent_setup_lower_bound`.

    Falls back to 0.0 when the distinct state count exceeds `max_states`
    (12 by default; BHK cost is O(n^2 * 2^n)) or when fewer than two state
    types are present.

    Reference: Naderi & Roshanaei (2021), "Critical-Path-Search Logic-Based
    Benders Decomposition Approaches for Flexible Job Shop Scheduling",
    INFORMS Journal on Optimization 4(1).
    """

    if len(state_ids) < 2:
        return 0.0

    distinct = list(dict.fromkeys(state_ids))
    n = len(distinct)
    if n < 2 or n > max_states:
        return 0.0

    inf = float("inf")
    cost: list[list[float]] = [[inf] * n for _ in range(n)]
    for i, from_state in enumerate(distinct):
        for j, to_state in enumerate(distinct):
            if i == j:
                continue
            cost[i][j] = float(
                setup_lookup.get((work_center_id, from_state, to_state), 0.0)
            )

    full = 1 << n
    dp: list[list[float]] = [[inf] * n for _ in range(full)]
    for i in range(n):
        dp[1 << i][i] = 0.0

    for mask in range(1, full):
        for i in range(n):
            if not (mask >> i) & 1:
                continue
            base = dp[mask][i]
            if base == inf:
                continue
            remaining = (~mask) & (full - 1)
            j = 0
            while remaining:
                if remaining & 1:
                    next_mask = mask | (1 << j)
                    candidate = base + cost[i][j]
                    if candidate < dp[next_mask][j]:
                        dp[next_mask][j] = candidate
                remaining >>= 1
                j += 1

    best = min(dp[full - 1])
    return 0.0 if best == inf else best


__all__ = [
    "BendersCutLike",
    "compute_machine_transition_floor",
    "compute_machine_tsp_lower_bound",
    "compute_sequence_independent_setup_lower_bound",
    "cut_pool_fingerprint",
]
