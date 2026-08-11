"""KI-F16c: tiny SDST public fixture parses into a non-empty setup matrix."""

from __future__ import annotations

from pathlib import Path

from benchmark.sdst_fjs_loader import load_sdst_fjs_problem

_TOY = (
    Path(__file__).resolve().parent.parent
    / "benchmark"
    / "instances"
    / "public"
    / "sdst"
    / "toy_2x2.sdstfjs"
)


def test_toy_sdst_fixture_loads() -> None:
    problem = load_sdst_fjs_problem(_TOY)
    assert len(problem.orders) == 2
    assert len(problem.work_centers) == 2
    assert len(problem.operations) == 4
    assert problem.setup_matrix, "SDST fixture must produce SetupEntry cells"
    assert all(entry.setup_minutes > 0 for entry in problem.setup_matrix)
