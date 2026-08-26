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


def test_sha256sums_gate_fails_on_planted_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "environment.json"
    target.write_text("{}\n", encoding="utf-8")
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text("0" * 64 + " environment.json\n", encoding="utf-8")
    try:
        _check_sums(sums)
    except AssertionError as exc:
        assert "mismatch" in str(exc)
    else:
        raise AssertionError("hash gate accepted a planted mismatch")


def test_beam_alns_box_run_json_files_are_listed_in_sha256sums() -> None:
    """RT 2026-08-27: cited BEAM/ALNS cells cannot sit outside SHA256SUMS."""

    folder = _EVIDENCE / "beam-alns-box-2026-08-26"
    listed = {
        line.split(None, 1)[1]
        for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    on_disk = {path.name for path in folder.glob("run_*.json")}
    missing = sorted(on_disk - listed)
    assert not missing, f"unhashed run JSON in beam-alns-box: {missing}"
    _check_sums(folder / "SHA256SUMS.txt")
