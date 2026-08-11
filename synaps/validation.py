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


def validate_setup_matrix_metricity(
    problem: ScheduleProblem,
) -> list[SetupTriangleViolation]:
    """Return every triangle-inequality violation in the SDST matrix (M3).

    The policy is *flag, don't forbid*: non-metric matrices are legal, but this
    surface makes the violations enumerable so metricity-dependent bounds and
    heuristics can warn instead of silently under/over-claiming. A missing
    (from, to) cell is treated as +inf (no assertion possible), so it never
    fabricates a violation.
    """
    setup: dict[tuple[UUID, UUID, UUID], float] = {
        (e.work_center_id, e.from_state_id, e.to_state_id): float(e.setup_minutes)
        for e in problem.setup_matrix
    }
    wc_ids = {e.work_center_id for e in problem.setup_matrix}
    state_ids = [s.id for s in problem.states]
    violations: list[SetupTriangleViolation] = []
    for wc_id in wc_ids:
        for a in state_ids:
            for c in state_ids:
                if a == c:
                    continue
                direct = setup.get((wc_id, a, c))
                if direct is None:
                    continue
                for b in state_ids:
                    if b in (a, c):
                        continue
                    ab = setup.get((wc_id, a, b))
                    bc = setup.get((wc_id, b, c))
                    if ab is None or bc is None:
                        continue
                    if direct > ab + bc + 1e-9:
                        violations.append(
                            SetupTriangleViolation(
                                work_center_id=wc_id,
                                from_state_id=a,
                                via_state_id=b,
                                to_state_id=c,
                                direct_minutes=direct,
                                via_minutes=ab + bc,
                            )
                        )
    return violations


def is_setup_matrix_metric(problem: ScheduleProblem) -> bool:
    """True iff the SDST matrix satisfies the triangle inequality everywhere (M3)."""
    return not validate_setup_matrix_metricity(problem)


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
    """

    if result.status not in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}:
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
        feasible=not proven,
        violation_count=len(violations),
        violation_kinds=sorted(violation_kind_counts.keys()),
        violation_kind_counts=dict(sorted(violation_kind_counts.items())),
        violations=violations,
    )


__all__ = ["SolutionVerification", "verify_schedule_result"]
