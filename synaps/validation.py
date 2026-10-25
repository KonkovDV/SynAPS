"""Validation surfaces for SynAPS schedule results."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from synaps.model import ScheduleProblem, ScheduleResult, SolverStatus
from synaps.solvers.feasibility_checker import (
    FeasibilityChecker,
    FeasibilityViolation,
    proven_hard_violations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID


@dataclass(frozen=True)
class SetupTriangleViolation:
    """A single SDST triangle-inequality violation on one work center.

    ``setup(from -> to) > setup(from -> via) + setup(via -> to)`` on
    ``work_center_id`` — i.e. going direct costs more than routing through an
    intermediate state, which breaks the metric assumption that TSP-style setup
    bounds and greedy insertion rely on.
    """

    work_center_id: UUID
    from_state_id: UUID
    via_state_id: UUID
    to_state_id: UUID
    direct_minutes: float
    via_minutes: float


def _triangle_violations_by_source(
    problem: ScheduleProblem,
) -> Iterator[list[SetupTriangleViolation]]:
    """Yield, per (work center, source state), its triangle violations.

    Vectorised (NumPy) form of the triple loop ``for a, c, b``: for a fixed
    source ``a`` the matrix ``via[c, b] = D[a, b] + D[b, c]`` is one broadcast,
    and missing cells are NaN (every comparison with NaN is False, which is the
    historical "missing cell = no assertion" rule). Only states that occur in
    the work center's own entries can take part, so each work center costs
    ``O(k^3)`` flops on its ``k`` participating states instead of ``O(|S|^3)``
    interpreted Python iterations (audit 2026-10: this ran on every
    ``solve()``). Output order is identical to the historical loop
    (work centers in set order, then ``a``, ``c``, ``b`` in ``problem.states``
    order).
    """
    import numpy as np

    entries_by_wc: dict[UUID, list[tuple[UUID, UUID, float]]] = {}
    for e in problem.setup_matrix:
        entries_by_wc.setdefault(e.work_center_id, []).append(
            (e.from_state_id, e.to_state_id, float(e.setup_minutes))
        )
    wc_ids = {e.work_center_id for e in problem.setup_matrix}
    state_ids = [s.id for s in problem.states]
    for wc_id in wc_ids:
        rows = entries_by_wc[wc_id]
        present = {state for row in rows for state in row[:2]}
        local = [state for state in state_ids if state in present]
        position = {state: i for i, state in enumerate(local)}
        k = len(local)
        matrix = np.full((k, k), np.nan)
        for from_state, to_state, minutes in rows:
            if from_state in position and to_state in position:
                matrix[position[from_state], position[to_state]] = minutes
        off_diagonal = ~np.eye(k, dtype=bool)
        transposed = matrix.T
        for a in range(k):
            via = matrix[a][None, :] + transposed  # via[c, b] = D[a, b] + D[b, c]
            hits = (matrix[a][:, None] > via + 1e-9) & off_diagonal
            hits[a, :] = False  # c == a
            hits[:, a] = False  # b == a
            found = [
                SetupTriangleViolation(
                    work_center_id=wc_id,
                    from_state_id=local[a],
                    via_state_id=local[b],
                    to_state_id=local[c],
                    direct_minutes=float(matrix[a, c]),
                    via_minutes=float(via[c, b]),
                )
                for c, b in np.argwhere(hits)
            ]
            if found:
                yield found


def validate_setup_matrix_metricity(
    problem: ScheduleProblem,
    *,
    limit: int | None = None,
) -> list[SetupTriangleViolation]:
    """Return every triangle-inequality violation in the SDST matrix (M3).

    The policy is *flag, don't forbid*: non-metric matrices are legal, but this
    surface makes the violations enumerable so metricity-dependent bounds and
    heuristics can warn instead of silently under/over-claiming. A missing
    (from, to) cell is treated as +inf (no assertion possible), so it never
    fabricates a violation.

    Semantics note (audit 2026-10): solvers and the checker read a missing
    cross-state cell as a ZERO setup (sparse SDST). "Metric" here therefore
    means metric over the EXPLICIT cells; the effective matrix used by the
    solvers can be non-metric through implicit zeros even when this returns
    no violation.

    ``limit`` stops the enumeration once at least that many violations were
    found (whole source-state blocks are kept, so the list may be longer).
    """
    violations: list[SetupTriangleViolation] = []
    for found in _triangle_violations_by_source(problem):
        violations.extend(found)
        if limit is not None and len(violations) >= limit:
            break
    return violations


def is_setup_matrix_metric(problem: ScheduleProblem) -> bool:
    """True iff the SDST matrix satisfies the triangle inequality everywhere (M3).

    Short-circuits on the first violation.
    """
    return not validate_setup_matrix_metricity(problem, limit=1)


@dataclass(frozen=True)
class SolutionVerification:
    """Structured feasibility verification result."""

    feasible: bool
    violation_count: int
    violation_kinds: list[str]
    violation_kind_counts: dict[str, int]
    violations: list[FeasibilityViolation]


def verify_schedule_result(
    problem: ScheduleProblem,
    result: ScheduleResult,
) -> SolutionVerification:
    """Verify a solver result against the caller's declared problem contract.

    Always checks against the submitted ``planning_horizon_end``. Solver-side
    placement-horizon extension (RHC coverage mode) must not rewrite the
    customer contract for ``verified_feasible``.

    ``feasible`` uses :func:`proven_hard_violations` so unproven greedy lane
    false-positives do not flip the customer oracle (Wave 8 / RT17-H2). All
    raw violations remain in ``violations`` for diagnostics.

    ``feasible`` is True only when status is ``FEASIBLE`` / ``OPTIMAL`` and
    the notary is empty. ERROR / TIMEOUT / INFEASIBLE stay False even if
    placed work is clean. When those statuses carry assignments, the checker
    still runs so studies do not publish empty ``independent_violation_kinds``
    next to a solver notary (KI-N15 / K2.1). Empty-assignment failures skip
    the checker: a 500k COVER miss would otherwise emit 500k
    ``MISSING_ASSIGNMENT`` rows.
    """

    success = result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
    if not success and not result.assignments:
        return SolutionVerification(
            feasible=False,
            violation_count=0,
            violation_kinds=[],
            violation_kind_counts={},
            violations=[],
        )

    violations = FeasibilityChecker().check(problem, result.assignments, exhaustive=True)
    violation_kind_counts = Counter(violation.kind for violation in violations)
    proven = proven_hard_violations(violations)
    return SolutionVerification(
        feasible=bool(success and not proven),
        violation_count=len(violations),
        violation_kinds=sorted(violation_kind_counts.keys()),
        violation_kind_counts=dict(sorted(violation_kind_counts.items())),
        violations=violations,
    )


__all__ = ["SolutionVerification", "verify_schedule_result"]
