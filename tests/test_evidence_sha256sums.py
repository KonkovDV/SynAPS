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


def test_all_sha256sums_txt_files_match_listed_bytes() -> None:
    """K3.2 / RT27-R2: every SHA256SUMS.txt under evidence/, including sessions.

    Does not require every ``run_*.json`` on disk to be listed (untracked BEAM
    leftovers must not fail CI).
    """

    paths = sorted(_EVIDENCE.rglob("SHA256SUMS.txt"))
    assert paths, "no SHA256SUMS.txt under benchmark/evidence"
    for path in paths:
        _check_sums(path)


def test_beam_night_boxed_leftovers_live_outside_hashed_sums() -> None:
    """K3-R5: seed42/999 BEAM night leftovers are not in the hashed box sums."""

    hashed = _EVIDENCE / "beam-alns-box-2026-08-26" / "SHA256SUMS.txt"
    text = hashed.read_text(encoding="utf-8")
    leftover_42 = "run_3000ops_4m_BEAM_3_night_boxed_seed42.json"
    leftover_999 = "run_3000ops_4m_BEAM_3_night_boxed_seed999.json"
    assert leftover_42 not in text
    assert leftover_999 not in text
    session = (
        _EVIDENCE
        / "beam-alns-box-2026-08-26"
        / "sessions"
        / "beam-3-night-boxed-leftover-2026-08-26"
    )
    assert (session / leftover_42).is_file()
    assert (session / leftover_999).is_file()
    _check_sums(session / "SHA256SUMS.txt")


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
