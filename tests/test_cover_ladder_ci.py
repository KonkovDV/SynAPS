"""Linux PR COVER gate helpers (KI-N10)."""

from __future__ import annotations

from benchmark.study_cover_ladder import _ci_gate_failures


def test_ci_gate_accepts_native_full_coverage() -> None:
    runs = [
        {
            "scale_id": "60k@100",
            "seed": 1,
            "stalled": False,
            "scheduled_ratio": 1.0,
            "verified_feasible": True,
            "native_backend": "native",
            "wall_time_s": 7.0,
        }
    ]
    assert _ci_gate_failures(runs, max_wall_s=180.0) == []


def test_ci_gate_rejects_python_backend_and_stall() -> None:
    python_backend = {
        "scale_id": "60k@100",
        "seed": 1,
        "stalled": False,
        "scheduled_ratio": 1.0,
        "verified_feasible": True,
        "native_backend": "python",
        "wall_time_s": 7.0,
    }
    stall = {"scale_id": "100k@200", "seed": 42, "stalled": True}
    assert any(
        "native_backend" in item for item in _ci_gate_failures([python_backend], max_wall_s=180)
    )
    assert any("stalled" in item for item in _ci_gate_failures([stall], max_wall_s=180))
