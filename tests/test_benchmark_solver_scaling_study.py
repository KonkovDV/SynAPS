from __future__ import annotations

from pathlib import Path

from benchmark.study_solver_scaling import study_solver_scaling


def test_study_solver_scaling_compares_requested_solvers_for_large_preset() -> None:
    report = study_solver_scaling(
        presets=["large"],
        seeds=[1],
        solver_names=["GREED", "LBBD-10", "AUTO"],
    )

    assert report["study_kind"] == "solver-scaling"
    assert len(report["records"]) == 1

    record = report["records"][0]
    by_solver = {entry["solver_config"]: entry for entry in record["comparisons"]}

    assert set(by_solver) == {"GREED", "LBBD-10", "AUTO"}
    assert by_solver["LBBD-10"]["results"]["feasible"] is True
    assert by_solver["AUTO"]["selected_solver_config"] == "LBBD-10"
    assert report["summary_by_preset"]["large"]["solver_counts"]["LBBD-10"] >= 2


def test_study_solver_scaling_can_materialize_generated_instances(tmp_path: Path) -> None:
    report = study_solver_scaling(
        presets=["medium"],
        seeds=[2],
        solver_names=["GREED"],
        write_dir=tmp_path,
    )

    instance_path = tmp_path / "medium_seed2.json"
    record = report["records"][0]

    assert instance_path.exists()
    assert record["instance_path"] == str(instance_path)
    assert record["comparisons"][0]["solver_config"] == "GREED"
    assert report["summary_by_preset"]["medium"]["instance_count"] == 1
