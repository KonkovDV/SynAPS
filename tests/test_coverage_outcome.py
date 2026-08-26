"""E2: empty coverage cannot be FEASIBLE/OPTIMAL."""

from __future__ import annotations

from synaps.model import SolverStatus
from synaps.solvers.coverage_outcome import CoverageClass, classify_coverage, honest_status
from synaps.solvers.registry import create_solver
from tests.conftest import make_simple_problem


def test_classify_coverage_three_classes() -> None:
    assert classify_coverage(n_operations=10, n_assigned=0) is CoverageClass.EMPTY
    assert classify_coverage(n_operations=10, n_assigned=4) is CoverageClass.INCOMPLETE
    assert classify_coverage(n_operations=10, n_assigned=10) is CoverageClass.FULL


def test_honest_status_rejects_empty_feasible() -> None:
    assert honest_status(SolverStatus.FEASIBLE, CoverageClass.EMPTY) is SolverStatus.ERROR
    assert honest_status(SolverStatus.OPTIMAL, CoverageClass.INCOMPLETE) is SolverStatus.FEASIBLE
    assert honest_status(SolverStatus.FEASIBLE, CoverageClass.FULL) is SolverStatus.FEASIBLE


def test_greed_on_tiny_instance_is_full_feasible() -> None:
    problem = make_simple_problem()
    solver, kwargs = create_solver("GREED")
    result = solver.solve(problem, **kwargs)
    assert result.metadata.get("coverage_class") == CoverageClass.FULL.value
    assert len(result.assignments) == len(problem.operations)
    assert result.status is SolverStatus.FEASIBLE
