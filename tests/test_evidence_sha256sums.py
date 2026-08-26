"""CI ratchet: hashed evidence files still match SHA256SUMS; P2.3 answer stays no."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_EVIDENCE = _ROOT / "benchmark" / "evidence"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_sums(sums_path: Path, *, skip: frozenset[str] = frozenset()) -> None:
    base = sums_path.parent
    lines = [line for line in sums_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert lines, f"{sums_path} is empty"
    for line in lines:
        digest, fname = line.split(None, 1)
        if fname in skip:
            continue
        path = base / fname
        assert path.is_file(), f"{sums_path}: missing {fname}"
        assert _sha256(path) == digest, f"{sums_path}: mismatch {fname}"


def test_cover_ladder_sha256sums_match_files() -> None:
    _check_sums(_EVIDENCE / "cover-ladder-2026-08-25" / "SHA256SUMS.txt")


def test_cable_c6_sha256sums_match_files() -> None:
    _check_sums(_EVIDENCE / "cable-c6-2026-08-25" / "SHA256SUMS.txt")


def test_deadzone_p2_3_freeze_run_files_still_match() -> None:
    """Freeze sums are the 15 5k@8 runs + summary_p2_3 copy. Env bytes are lost."""
    _check_sums(_EVIDENCE / "deadzone-5k-2026-08-25" / "SHA256SUMS_p2_3.txt")


def test_deadzone_live_sha256sums_match_files() -> None:
    _check_sums(_EVIDENCE / "deadzone-5k-2026-08-25" / "SHA256SUMS.txt")


def test_deadzone_p2_3_answer_is_no() -> None:
    freeze = json.loads(
        (_EVIDENCE / "deadzone-5k-2026-08-25" / "summary_p2_3_5000x8.json").read_text(
            encoding="utf-8"
        )
    )
    p2 = freeze["p2_3"]
    assert p2["answer"] == "no"
    assert p2["winning_configs"] == []
    assert p2["five_named_configs_complete"] is True
    live = json.loads(
        (_EVIDENCE / "deadzone-5k-2026-08-25" / "summary.json").read_text(encoding="utf-8")
    )
    assert live["p2_3"]["answer"] == "no"
