"""E2: empty coverage cannot be FEASIBLE/OPTIMAL."""

from __future__ import annotations

from synaps.model import ScheduleResult, SolverStatus
from synaps.solvers.coverage_outcome import (
    CoverageClass,
    classify_coverage,
    honest_status,
    process_exit_code,
    stamp_honest_coverage,
)
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
    assert process_exit_code(result.status, CoverageClass.FULL) == 0


def test_stamp_demotes_empty_feasible_on_every_family_label() -> None:
    problem = make_simple_problem()
    for name in (
        "greedy",
        "alns",
        "cpsat",
        "rhc",
        "lbbd",
        "lbbd_hd",
        "incremental_repair",
        "beam_search",
    ):
        result = ScheduleResult(solver_name=name, status=SolverStatus.FEASIBLE, assignments=[])
        stamped = stamp_honest_coverage(problem, result)
        assert stamped.status is SolverStatus.ERROR, name
        assert process_exit_code(stamped.status, CoverageClass.EMPTY) == 3


def test_process_exit_codes_match_adr_0005() -> None:
    assert process_exit_code(SolverStatus.FEASIBLE, CoverageClass.FULL) == 0
    assert process_exit_code(SolverStatus.FEASIBLE, CoverageClass.INCOMPLETE) == 2
    assert process_exit_code(SolverStatus.ERROR, CoverageClass.EMPTY) == 3
    assert process_exit_code(SolverStatus.ERROR, CoverageClass.INCOMPLETE) == 1
