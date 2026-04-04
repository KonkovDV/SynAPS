from __future__ import annotations

import json
from pathlib import Path

from benchmark.run_benchmark import load_problem, run_benchmark
from tests.conftest import make_simple_problem


def _write_instance(tmp_path: Path, name: str = "instance.json") -> Path:
    problem = make_simple_problem(n_orders=3, ops_per_order=2)
    instance_path = tmp_path / name
    instance_path.write_text(
        json.dumps(problem.model_dump(mode="json"), indent=2), encoding="utf-8"
    )
    return instance_path


def test_load_problem_reads_schedule_problem(tmp_path: Path) -> None:
    instance_path = _write_instance(tmp_path)

    problem = load_problem(instance_path)

    assert len(problem.orders) == 3
    assert len(problem.work_centers) == 2
    assert len(problem.operations) == 6


def test_run_benchmark_emits_single_solver_report(tmp_path: Path) -> None:
    instance_path = _write_instance(tmp_path)

    report = run_benchmark(instance_path=instance_path, solver_names=["GREED"], runs=1)

    assert report["instance"] == instance_path.name
    assert report["problem_profile"]["order_count"] == 3
    assert report["solver_config"] == "GREED"
    assert report["selected_solver_config"] == "GREED"
    assert report["results"]["solver_name"] == "greedy_dispatch"
    assert report["results"]["feasible"] is True
    assert report["statistics"]["runs"] == 1


def test_run_benchmark_compare_mode_returns_all_configs(tmp_path: Path) -> None:
    instance_path = _write_instance(tmp_path)

    report = run_benchmark(
        instance_path=instance_path,
        solver_names=["GREED", "CPSAT-10"],
        runs=1,
        compare=True,
    )

    assert report["instance"] == instance_path.name
    assert len(report["comparisons"]) == 2
    assert {item["solver_config"] for item in report["comparisons"]} == {"GREED", "CPSAT-10"}


def test_run_benchmark_auto_mode_reports_selected_solver(tmp_path: Path) -> None:
    instance_path = _write_instance(tmp_path)

    report = run_benchmark(instance_path=instance_path, solver_names=["AUTO"], runs=1)

    assert report["instance"] == instance_path.name
    assert report["problem_profile"]["size_band"] == "small"
    assert report["solver_config"] == "AUTO"
    assert report["selected_solver_config"] == "CPSAT-10"
    assert report["results"]["solver_name"] == "cpsat"
    assert report["results"]["feasible"] is True


def test_run_benchmark_supports_academic_epsilon_profile(tmp_path: Path) -> None:
    instance_path = _write_instance(tmp_path)

    report = run_benchmark(
        instance_path=instance_path,
        solver_names=["CPSAT-EPS-SETUP-110"],
        runs=1,
    )

    assert report["solver_config"] == "CPSAT-EPS-SETUP-110"
    assert report["selected_solver_config"] == "CPSAT-EPS-SETUP-110"
    assert report["results"]["feasible"] is True


def test_benchmark_tradeoff_instance_exposes_setup_improvement() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    instance_path = repo_root / "benchmark" / "instances" / "pareto_setup_tradeoff_4op.json"

    report = run_benchmark(
        instance_path=instance_path,
        solver_names=["CPSAT-10", "CPSAT-EPS-SETUP-110"],
        runs=1,
        compare=True,
    )

    by_solver = {
        comparison["solver_config"]: comparison["results"]
        for comparison in report["comparisons"]
    }

    assert by_solver["CPSAT-EPS-SETUP-110"]["total_setup_minutes"] < by_solver["CPSAT-10"]["total_setup_minutes"]
    assert by_solver["CPSAT-EPS-SETUP-110"]["makespan_minutes"] <= 121


def test_benchmark_medium_stress_instance_loads_and_solves() -> None:
    """The medium_stress_20x4 instance must load and be solvable by GREED."""
    repo_root = Path(__file__).resolve().parents[1]
    instance_path = repo_root / "benchmark" / "instances" / "medium_stress_20x4.json"

    report = run_benchmark(
        instance_path=instance_path,
        solver_names=["GREED"],
        runs=1,
    )

    assert report["instance"] == "medium_stress_20x4.json"
    assert report["problem_profile"]["operation_count"] == 20
    assert report["problem_profile"]["work_center_count"] == 4
    assert report["results"]["feasible"] is True
    assert report["results"]["assignments"] == 20
