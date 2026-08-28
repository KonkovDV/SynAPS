"""Coverage class vs solver status (E2). Empty + success is forbidden."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from synaps.model import (
    ScheduleResult,
    SolverStatus,
)

if TYPE_CHECKING:
    from synaps.model import ScheduleProblem


class CoverageClass(StrEnum):
    """How many operations were placed. Independent of ``SolverStatus``."""

    EMPTY = "empty"
    INCOMPLETE = "incomplete"
    FULL = "full"


def classify_coverage(*, n_operations: int, n_assigned: int) -> CoverageClass:
    """Map assignment count to empty / incomplete / full."""

    if n_assigned <= 0 or n_operations <= 0:
        return CoverageClass.EMPTY
    if n_assigned >= n_operations:
        return CoverageClass.FULL
    return CoverageClass.INCOMPLETE


def honest_status(status: SolverStatus, coverage: CoverageClass) -> SolverStatus:
    """``FEASIBLE`` / ``OPTIMAL`` are dishonest when nothing was placed.

    Incomplete coverage stays ``FEASIBLE`` at the solver object (historical
    greedy/RHC contract) but must not be treated as a process success:
    CLI / harness codes are 0=full, 2=incomplete, 3=empty, 1=error.
    """

    if coverage is CoverageClass.EMPTY and status in {
        SolverStatus.FEASIBLE,
        SolverStatus.OPTIMAL,
    }:
        return SolverStatus.ERROR
    if coverage is CoverageClass.INCOMPLETE and status is SolverStatus.OPTIMAL:
        return SolverStatus.FEASIBLE
    return status


def process_exit_code(status: SolverStatus, coverage: CoverageClass) -> int:
    """ADR-0005 process codes: 0 full success, 2 incomplete, 3 empty, 1 error."""

    if coverage is CoverageClass.EMPTY:
        return 3
    if status is SolverStatus.ERROR:
        return 1
    if coverage is CoverageClass.INCOMPLETE:
        return 2
    if status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}:
        return 0
    return 1


def stamp_honest_coverage(problem: ScheduleProblem, result: ScheduleResult) -> ScheduleResult:
    """Apply empty-success demotion and record ``coverage_class`` on *result*."""

    coverage = classify_coverage(
        n_operations=len(problem.operations),
        n_assigned=len(result.assignments),
    )
    result.metadata["coverage_class"] = coverage.value
    result.status = honest_status(result.status, coverage)
    return result
