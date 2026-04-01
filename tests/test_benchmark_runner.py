from __future__ import annotations

import json
from pathlib import Path

from tests.conftest import make_simple_problem

from benchmark.run_benchmark import load_problem, run_benchmark


def _write_instance(tmp_path: Path, name: str = "instance.json") -> Path:
    problem = make_simple_problem(n_orders=3, ops_per_order=2)
    instance_path = tmp_path / name
    instance_path.write_text(json.dumps(problem.model_dump(mode="json"), indent=2), encoding="utf-8")
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
    assert report["solver_config"] == "GREED"
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
