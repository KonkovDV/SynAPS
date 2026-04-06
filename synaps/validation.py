"""Validation surfaces for SynAPS schedule results."""

from __future__ import annotations

from dataclasses import dataclass

from synaps.model import ScheduleProblem, ScheduleResult, SolverStatus
from synaps.solvers.feasibility_checker import FeasibilityChecker, FeasibilityViolation


@dataclass(frozen=True)
class SolutionVerification:
    """Structured feasibility verification result."""

    feasible: bool
    violation_count: int
    violation_kinds: list[str]
    violations: list[FeasibilityViolation]


def verify_schedule_result(
    problem: ScheduleProblem,
    result: ScheduleResult,
) -> SolutionVerification:
    """Verify a solver result against the canonical feasibility checker."""

    if result.status not in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}:
        return SolutionVerification(
            feasible=False,
            violation_count=0,
            violation_kinds=[],
            violations=[],
        )

    violations = FeasibilityChecker().check(problem, result.assignments)
    return SolutionVerification(
        feasible=not violations,
        violation_count=len(violations),
        violation_kinds=sorted({violation.kind for violation in violations}),
        violations=violations,
    )


__all__ = ["SolutionVerification", "verify_schedule_result"]
