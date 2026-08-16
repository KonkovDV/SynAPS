"""KI-F16c: SDST public fixtures parse into non-empty setup matrices."""

from __future__ import annotations

from pathlib import Path

from benchmark.sdst_fjs_loader import load_sdst_fjs_problem

_SDST_DIR = Path(__file__).resolve().parent.parent / "benchmark" / "instances" / "public" / "sdst"


def test_sdst_pack_fixtures_parse() -> None:
    paths = sorted(_SDST_DIR.glob("*.sdstfjs"))
    assert len(paths) >= 3
    for path in paths:
        problem = load_sdst_fjs_problem(path)
        assert problem.setup_matrix, path.name
        assert len(problem.orders) >= 2
