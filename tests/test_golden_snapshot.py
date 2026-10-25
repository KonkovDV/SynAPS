"""Smoke test for scripts/golden_snapshot.py (audit 2026-10 refactor safety net)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "golden_snapshot.py"


def _load_script():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("golden_snapshot", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["golden_snapshot"] = module
    spec.loader.exec_module(module)
    return module


def test_capture_is_reproducible_and_compare_detects_changes(tmp_path: Path) -> None:
    golden = _load_script()
    cases = ["cpsat10_tiny", "greed_lanes", "rhc_greedy_lanes"]
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    for out in (first, second):
        assert golden.main(["capture", str(out), "--cases", *cases]) == 0
    assert set(json.loads(first.read_text(encoding="utf-8"))) == set(cases)
    assert golden.main(["compare", str(first), str(second)]) == 0

    tampered = json.loads(second.read_text(encoding="utf-8"))
    tampered["greed_lanes"]["schedule"] = "0" * 16
    second.write_text(json.dumps(tampered), encoding="utf-8")
    assert golden.main(["compare", str(first), str(second)]) == 1


def test_scrub_drops_volatile_timing_keys() -> None:
    golden = _load_script()
    scrubbed = golden.scrub({"solve_ms": 3, "wall_time_s": 1.0, "nested": {"x": 0.12345678}})
    assert scrubbed == {"nested": {"x": 0.123457}}
