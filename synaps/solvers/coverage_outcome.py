"""Coverage class vs solver status (E2). Empty + success is forbidden."""

from __future__ import annotations

from enum import StrEnum

from synaps.model import SolverStatus


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
    proposed CLI / harness codes are 0=full, 2=incomplete, 3=empty, 1=error.
    """

    if coverage is CoverageClass.EMPTY and status in {
        SolverStatus.FEASIBLE,
        SolverStatus.OPTIMAL,
    }:
        return SolverStatus.ERROR
    if coverage is CoverageClass.INCOMPLETE and status is SolverStatus.OPTIMAL:
        return SolverStatus.FEASIBLE
    return status
