from __future__ import annotations

from typing import TYPE_CHECKING

from benchmark.study_routing_boundary import study_routing_boundary

if TYPE_CHECKING:
    from pathlib import Path


def test_study_routing_boundary_reports_stable_lbbd_selection_for_large_preset() -> None:
    report = study_routing_boundary(presets=["large"], seeds=[3, 4])

    summary = report["summary_by_preset"]["large"]

    assert report["study_kind"] == "routing-boundary"
    assert summary["instance_count"] == 2
    assert summary["routing_counts"]["LBBD-10"] == 2
    assert summary["size_band_counts"]["large"] == 2
    assert summary["operation_count"]["min"] > 120
    assert summary["routing_stable"] is True


def test_study_routing_boundary_can_materialize_generated_instances(tmp_path: Path) -> None:
    report = study_routing_boundary(presets=["tiny"], seeds=[5], write_dir=tmp_path)

    record = report["records"][0]
    instance_path = tmp_path / "tiny_seed5.json"

    assert instance_path.exists()
    assert record["instance_path"] == str(instance_path)
    assert report["summary_by_preset"]["tiny"]["instance_count"] == 1
