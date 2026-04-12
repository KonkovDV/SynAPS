"""Tests for benchmark harness reporting and public solver configurations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from benchmark.run_benchmark import available_solvers, run_benchmark
from synaps.solvers.registry import available_solver_configs, create_solver

if TYPE_CHECKING:
    from pathlib import Path

    from synaps.model import ScheduleProblem


def test_registry_exposes_material_loss_epsilon_profile() -> None:
    configs = available_solver_configs()

    assert "CPSAT-EPS-MATERIAL-110" in configs

    solver, solve_kwargs = create_solver("CPSAT-EPS-MATERIAL-110")
    assert solver.name == "cpsat_pareto_slice"
    assert solve_kwargs["primary_objective"] == "material_loss"
    assert solve_kwargs["max_makespan_ratio"] == 1.10


def test_available_solvers_includes_auto_and_material_profile() -> None:
    solvers = available_solvers()

    assert solvers[0] == "AUTO"
    assert "CPSAT-EPS-MATERIAL-110" in solvers


def test_run_benchmark_reports_extended_result_fields(
    simple_problem: ScheduleProblem,
    tmp_path: Path,
) -> None:
    instance_path = tmp_path / "instance.json"
    instance_path.write_text(simple_problem.model_dump_json(indent=2), encoding="utf-8")

    report = run_benchmark(instance_path, solver_names=["CPSAT-10"], runs=1)
    results = report["results"]
    stats = report["statistics"]

    assert report["instance"] == instance_path.name
    assert "problem_profile" in report
    assert results["solver_name"] == "cpsat"
    assert "proved_optimal" in results
    assert "total_material_loss" in results
    assert "best_objective_bound" in results
    assert report["verification"]["feasible"] is True
    assert report["verification"]["violation_count"] == 0
    assert "wall_time_s_mean" in stats
    assert "wall_time_s_min" in stats
    assert "wall_time_s_max" in stats
    assert "verification_time_ms" in stats
    assert "solver_metadata" in report


def test_run_benchmark_compare_mode_returns_multiple_solver_reports(
    simple_problem: ScheduleProblem,
    tmp_path: Path,
) -> None:
    instance_path = tmp_path / "instance.json"
    instance_path.write_text(simple_problem.model_dump_json(indent=2), encoding="utf-8")

    report = run_benchmark(
        instance_path,
        solver_names=["GREED", "CPSAT-EPS-MATERIAL-110"],
        runs=1,
        compare=True,
    )

    assert report["instance"] == instance_path.name
    assert len(report["comparisons"]) == 2
    assert {entry["solver_config"] for entry in report["comparisons"]} == {
        "GREED",
        "CPSAT-EPS-MATERIAL-110",
    }


def test_rhc_50k_study_writes_report(
    tmp_path: Path,
) -> None:
    from benchmark.study_rhc_50k import study_rhc_50k

    artifact_dir = tmp_path / "artifact"
    report = study_rhc_50k(
        preset_name="tiny",
        seeds=[1],
        solver_names=["GREED"],
        runs=1,
        write_dir=artifact_dir,
    )

    report_path = artifact_dir / "rhc_50k_study.json"
    assert report["study_kind"] == "rhc-50k"
    assert report["preset_name"] == "tiny"
    assert report["requested_solver_names"] == ["GREED"]
    assert report_path.exists()
    assert report["summary_by_solver"]["GREED"]["instance_count"] == 1
