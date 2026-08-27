"""E2: empty coverage cannot be FEASIBLE/OPTIMAL."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from synaps.model import ScheduleResult, SolverStatus
from synaps.solvers.coverage_outcome import (
    CoverageClass,
    classify_coverage,
    honest_status,
    process_exit_code,
    stamp_honest_coverage,
)
from synaps.solvers.registry import available_solver_configs, create_solver
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


@pytest.mark.parametrize("name", available_solver_configs())
def test_named_config_empty_assignments_are_error(name: str) -> None:
    """И8.1: zero assignments cannot stay FEASIBLE on any of the 25 configs."""

    problem = make_simple_problem()
    result = ScheduleResult(solver_name=name, status=SolverStatus.FEASIBLE, assignments=[])
    stamped = stamp_honest_coverage(problem, result)
    assert stamped.status is SolverStatus.ERROR, name
    assert stamped.metadata.get("coverage_class") == CoverageClass.EMPTY.value, name
    assert process_exit_code(stamped.status, CoverageClass.EMPTY) == 3, name


def test_alns_500_zero_scheduled_ops_is_not_feasible() -> None:
    """И8.3 / KI-N1: ALNS-500 with 0 placed operations is not FEASIBLE."""

    problem = make_simple_problem()
    result = ScheduleResult(solver_name="alns", status=SolverStatus.FEASIBLE, assignments=[])
    stamped = stamp_honest_coverage(problem, result)
    assert stamped.status is SolverStatus.ERROR
    assert stamped.metadata.get("coverage_class") == CoverageClass.EMPTY.value


def _call_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def test_stamp_honest_coverage_is_wired_on_solver_and_harness_paths() -> None:
    """K3.5: every BaseSolver.solve stamps coverage; harness paths too."""

    root = Path(__file__).resolve().parents[1]
    solvers_root = root / "synaps" / "solvers"
    missing: list[str] = []
    seen = 0
    for path in sorted(solvers_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                isinstance(base, ast.Name) and base.id == "BaseSolver" for base in node.bases
            ):
                continue
            solve = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, ast.FunctionDef) and child.name == "solve"
                ),
                None,
            )
            assert solve is not None, f"{path.name}::{node.name} has no solve()"
            seen += 1
            if "stamp_honest_coverage" not in _call_names(solve):
                missing.append(f"{path.relative_to(root).as_posix()}::{node.name}.solve")
    assert seen >= 8, f"expected BaseSolver subclasses, found {seen}"
    assert not missing, "solve() missing stamp_honest_coverage: " + ", ".join(missing)

    for rel in ("synaps/portfolio.py", "benchmark/run_benchmark.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        assert "stamp_honest_coverage" in _call_names(tree), rel


def test_pareto_slice_demotes_empty_feasible_inner(monkeypatch: pytest.MonkeyPatch) -> None:
    """И8.2: CPSAT-EPS-* must not re-emit an unstamped empty FEASIBLE inner result."""

    from synaps.solvers.cpsat_solver import CpSatSolver

    problem = make_simple_problem()

    def fake_solve(self: CpSatSolver, problem_arg: object, **kwargs: object) -> ScheduleResult:
        del problem_arg, kwargs
        return ScheduleResult(solver_name="cpsat", status=SolverStatus.FEASIBLE, assignments=[])

    monkeypatch.setattr(CpSatSolver, "solve", fake_solve)
    solver, kwargs = create_solver("CPSAT-EPS-SETUP-110")
    result = solver.solve(problem, **kwargs)
    assert result.status is SolverStatus.ERROR
    assert result.metadata.get("coverage_class") == CoverageClass.EMPTY.value
    assert process_exit_code(result.status, CoverageClass.EMPTY) == 3
