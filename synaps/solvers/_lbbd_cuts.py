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

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from synaps.model import Assignment, Operation, ScheduleProblem


class BendersCutLike(Protocol):
    """Structural type for Benders cuts shared by both LBBD solvers.

    Both `synaps.solvers.lbbd_solver._BendersCut` and
    `synaps.solvers.lbbd_hd_solver._BendersCut` carry these attributes
    via `__slots__`. A Protocol keeps `cut_pool_fingerprint` solver-agnostic
    without inviting a hard cross-import.
    """

    kind: str
    rhs: float
    bottleneck_ops: set[UUID]
    assignment_map: dict[UUID, UUID]


def cut_pool_fingerprint(
    cut: BendersCutLike,
) -> tuple[str, frozenset[UUID], frozenset[tuple[UUID, UUID]], float]:
    """Return a canonical fingerprint for cut-pool deduplication.

    Two cuts collapse to the same fingerprint iff they agree on kind, the
    distinguishing payload, and rhs to three decimals. The rhs rounding
    avoids near-duplicate accumulation when subproblem makespans differ
    only by floating-point drift across iterations or partitions.

    The distinguishing payload depends on the cut family (audit v3, N2):

    * A ``nogood`` forbids an EXACT master assignment, so it is keyed by that
      assignment (`frozenset(assignment_map.items())`). Every no-good carries
      an empty ``bottleneck_ops`` and ``rhs == 0.0``; keying it on those alone
      collapsed all no-goods to one fingerprint, so the master learned only
      the first assignment and span-spun on the second forever.
    * An optimality cut (``setup_cost`` / ``machine_tsp`` / ...) is keyed by
      its bottleneck operations and rhs, which fully determine its HiGHS row.

    Units: rhs is in minutes (consistent with makespan_minutes). The 3-decimal
    precision is noise-free for integer minute values and typical float results
    from setup/transition lookups. ARC-derived bounds that divide by pool_size
    may produce sub-minute precision; rounding prevents near-duplicates.
    """

    if cut.kind == "nogood":
        assignment_key = frozenset(cut.assignment_map.items())
        return (cut.kind, frozenset(), assignment_key, round(float(cut.rhs), 3))
    return (cut.kind, frozenset(cut.bottleneck_ops), frozenset(), round(float(cut.rhs), 3))


def reported_lower_bound(raw_relaxation: float, best_ub: float) -> tuple[float, bool]:
    """Return ``(reported_lb, invariant_violated)`` for an LBBD run (N5).

    The reported lower bound is the RAW cut-free master relaxation, never
    ``min(raw_relaxation, best_ub)``. Clamping to the incumbent would make
    ``lb <= ub`` hold by construction and silence an invalid relaxation (one
    that exceeds a feasible solution) — the same muffle-your-own-sentinel
    anti-pattern as ``_clamp_non_negative`` in ``lower_bounds.py``.

    A finite incumbent that the relaxation exceeds is a bug: the relaxation is
    supposed to be a valid lower bound on the optimum, and the optimum is
    <= any feasible incumbent. We therefore report the raw value and set the
    violation flag so the caller can diagnose (and tests can assert) instead of
    hiding it. ``eps`` absorbs integer-minute float drift.
    """
    eps = 1e-6
    invariant_violated = best_ub < float("inf") and raw_relaxation > best_ub + eps
    return raw_relaxation, invariant_violated


def compute_machine_transition_floor(
    problem: ScheduleProblem,
    eligible_by_op: dict[UUID, list[UUID]],
    work_center_id: UUID,
    setup_lookup: Mapping[tuple[UUID, UUID, UUID], float],
) -> float:
    """Return the strongest safe per-transition setup floor for the master.

    The master's capacity row applies this floor as ``ms * (n_k - 1)`` for a
    machine carrying ``n_k`` operations (``C_max >= sum p_i + ms*(n_k-1)``). That
    is valid ONLY if EVERY one of the ``n_k - 1`` consecutive transitions costs
    at least ``ms`` — including a transition between two operations of the SAME
    state. The master does not know the realized sequence, so it cannot preclude
    repeated same-state operations (whose changeover is typically 0). Therefore
    the min is taken over ALL ordered state pairs routable to the machine,
    ``from == to`` INCLUDED: if any such transition (same-state included) is not
    strictly positive, no positive per-transition floor is safe and 0 is
    returned.

    This is why the floor is 0 on the usual matrices (same-state setup = 0) —
    that is a conservatively VALID bound, not dead code (Q2). A stronger,
    sequence-aware setup bound requires the realized state MULTIPLICITIES and so
    lives in the per-cluster ``compute_sequence_independent_setup_lower_bound`` /
    ``compute_machine_tsp_lower_bound``; naively dropping ``from == to`` here
    (``ms * (n_k-1)`` with ``ms = min_{s != t}``) would OVER-claim whenever a
    state repeats and reintroduce the S1/S2/S3 invalid-bound defect.
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
            # from == to is intentionally included: see the docstring. A free
            # same-state changeover makes any positive floor unsafe under the
            # master's ms*(n_k-1) application.
            transition = float(setup_lookup.get((work_center_id, from_state_id, to_state_id), 0.0))
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
    """Sequence-aware setup lower bound on a FIXED set of distinct states (F6).

    Solves the asymmetric Hamiltonian-path problem on the realised distinct
    state types via Bellman-Held-Karp dynamic programming. For a FIXED op set
    the BHK optimum is a valid lower bound on the sequence-dependent setup
    contribution of any visit order of those distinct types — dominating the
    sequence-independent floor and the cheap assignment relaxation
    (:func:`compute_min_out_assignment_setup_lb`).

    Falls back to 0.0 when the distinct state count exceeds ``max_states``
    (12 by default; BHK cost is O(n^2 * 2^n)) or when fewer than two state
    types are present.

    Contract (F6 / GUARD-S3, audit v4):

    * Valid as a lower bound on the setup cost of a FIXED set on ANY sdst
      matrix (metric or not): the Hamiltonian-path optimum cannot exceed the
      cost of any particular path.
    * NOT safe to *discount* per removed op. ``L(S) - L(S\\\\{j})`` can be
      strictly positive even when the cut only subtracts ``p_j`` (GUARD-S3
      counterexample). That is why the ``machine_tsp`` optimality cut was
      removed from both LBBD solvers; do not reintroduce discounting without
      a covering residual.
    * For a bound that stays valid under set shrinkage on non-metric matrices
      without recomputing BHK, prefer
      :func:`compute_min_out_assignment_setup_lb`.

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
            cost[i][j] = float(setup_lookup.get((work_center_id, from_state, to_state), 0.0))

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


def compute_min_out_assignment_setup_lb(
    state_ids: list[UUID],
    work_center_id: UUID,
    setup_lookup: Mapping[tuple[UUID, UUID, UUID], float],
) -> float:
    """Cheap assignment-relaxation setup LB, valid on ANY sdst matrix (F6).

    For each distinct state take the cheapest outgoing setup to a different
    state; a Hamiltonian path on ``n`` nodes uses ``n - 1`` arcs, so summing
    the ``n - 1`` smallest min-outs is a valid lower bound (one node may be
    the path end and contribute no outgoing arc). Dominated by BHK
    (:func:`compute_machine_tsp_lower_bound`) but O(n^2) and never
    over-claims on non-metric matrices. **Not** subset-monotone as an
    absolute value (removing a state can raise min-outs by deleting cheap
    edges) — do not discount ``L(S) - L(S\\{j})``; recompute on the fixed
    assigned set instead (same discipline as GUARD-S3 / KI-S3).
    """
    distinct = list(dict.fromkeys(state_ids))
    n = len(distinct)
    if n < 2:
        return 0.0

    min_outs: list[float] = []
    for i, from_state in enumerate(distinct):
        best = min(
            float(setup_lookup.get((work_center_id, from_state, to_state), 0.0))
            for j, to_state in enumerate(distinct)
            if i != j
        )
        min_outs.append(best)
    min_outs.sort()
    return float(sum(min_outs[: n - 1]))


__all__ = [
    "BendersCutLike",
    "compute_machine_transition_floor",
    "compute_machine_tsp_lower_bound",
    "compute_min_out_assignment_setup_lb",
    "compute_sequence_independent_setup_lower_bound",
    "cut_pool_fingerprint",
]
