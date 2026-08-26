"""CI: BENCHMARK_EVIDENCE_*.md hash tables match files on disk (A4)."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BENCH = _ROOT / "benchmark"
_HASH_ROW = re.compile(r"\| `([^`]+)` \| `([0-9a-f]{64})` \|", re.I)
_HASH_BULLET = re.compile(r"`([^`]+)` = `([0-9a-f]{64})`", re.I)
_CURRENT = (
    "BENCHMARK_EVIDENCE_COVER_2026_08_26.md",
    "BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md",
    "BENCHMARK_EVIDENCE_CABLE_C6_2026_08_26.md",
)
_STUDY = {
    "BENCHMARK_EVIDENCE_COVER_2026_08_26.md": "cover-ladder-2026-08-25",
    "BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md": "deadzone-5k-2026-08-25",
    "BENCHMARK_EVIDENCE_CABLE_C6_2026_08_26.md": "cable-c6-2026-08-25",
}
_SCALE_FILE = {
    "60k@100": "60k_at_100",
    "100k@200": "100k_at_200",
    "200k@400": "200k_at_400",
    "500k@1000": "500k_at_1000",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_hashes(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _HASH_ROW.finditer(text):
        found[match.group(1)] = match.group(2).lower()
    for match in _HASH_BULLET.finditer(text):
        found[match.group(1)] = match.group(2).lower()
    return found


def _parse_sha256sums(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, fname = line.split(None, 1)
        rows[fname] = digest.lower()
    return rows


def _assert_md_table_matches_sums(
    md_name: str, sums: dict[str, str], listed: dict[str, str]
) -> None:
    root_listed = {key: digest for key, digest in listed.items() if "/" not in key}
    missing = [fname for fname in sums if fname not in root_listed]
    mismatch = [
        fname
        for fname, digest in sums.items()
        if fname in root_listed and root_listed[fname] != digest
    ]
    assert not missing, f"{md_name}: SHA256SUMS rows missing from MD table: {missing}"
    assert not mismatch, f"{md_name}: MD digest != SHA256SUMS for {mismatch}"


def test_artifact_sha256_table_matches_sha256sums_txt() -> None:
    """F0.5: MD Artifact/SHA-256 table matches SHA256SUMS.txt line for line."""
    for name, study in _STUDY.items():
        sums = _parse_sha256sums(_BENCH / "evidence" / study / "SHA256SUMS.txt")
        listed = _parse_hashes((_BENCH / name).read_text(encoding="utf-8"))
        _assert_md_table_matches_sums(name, sums, listed)


def test_artifact_sha256_table_fails_on_planted_mismatch() -> None:
    try:
        _assert_md_table_matches_sums(
            "PLANTED.md",
            {"environment.json": "a" * 64},
            {"environment.json": "b" * 64},
        )
    except AssertionError as exc:
        assert "PLANTED.md" in str(exc)
        assert "MD digest" in str(exc)
    else:
        raise AssertionError("hash table gate accepted a planted MD/SHA256SUMS mismatch")


def test_current_evidence_markdown_files_have_matching_hashes() -> None:
    for name in _CURRENT:
        md = _BENCH / name
        text = md.read_text(encoding="utf-8")
        assert "SHA-256" in text or "SHA256" in text, f"{name}: no hash section"
        listed = _parse_hashes(text)
        assert listed, f"{name}: no hash rows"
        study = _STUDY[name]
        for rel, digest in listed.items():
            path = _BENCH / "evidence" / study / rel
            assert path.is_file(), f"{name}: missing {rel}"
            assert _sha256(path) == digest, f"{name}: mismatch {rel}"


def test_cover_md_cells_match_run_json() -> None:
    folder = _BENCH / "evidence" / "cover-ladder-2026-08-25"
    seed1_60k = json.loads((folder / "run_60k_at_100_seed1.json").read_text(encoding="utf-8"))
    assert seed1_60k["ops_scheduled"] == 60000
    assert seed1_60k["scheduled_ratio"] == 1.0
    assert seed1_60k["verified_feasible"] is True
    assert seed1_60k["makespan_minutes"] == 41195.0
    assert seed1_60k["wall_time_s"] == 7.022
    seed1_500k = json.loads((folder / "run_500k_at_1000_seed1.json").read_text(encoding="utf-8"))
    assert seed1_500k["ops_scheduled"] == 500000
    assert seed1_500k["peak_rss_mb"] == 3956.3
    stall = json.loads((folder / "run_100k_at_200_seed42.json").read_text(encoding="utf-8"))
    assert stall["stalled"] is True
    assert stall["ops_scheduled"] is None


def test_cover_catalog_is_exactly_the_hash_table() -> None:
    folder = _BENCH / "evidence" / "cover-ladder-2026-08-25"
    md = (_BENCH / "BENCHMARK_EVIDENCE_COVER_2026_08_26.md").read_text(encoding="utf-8")
    listed = set(_parse_hashes(md))
    on_disk = {p.name for p in folder.iterdir() if p.is_file()}
    assert on_disk == listed


def test_cover_md_table_matches_each_run_json() -> None:
    folder = _BENCH / "evidence" / "cover-ladder-2026-08-25"
    md = (_BENCH / "BENCHMARK_EVIDENCE_COVER_2026_08_26.md").read_text(encoding="utf-8")
    row = re.compile(
        r"\| (60k@100|100k@200|200k@400|500k@1000) \| (\d+) \| (\d+) \| "
        r"([0-9.]+|—) \| (true|\*\*STALL\*\*) \|"
    )
    seen = 0
    for match in row.finditer(md):
        scale, seed_s, ops_s, ratio_s, verified = match.groups()
        seed = int(seed_s)
        path = folder / f"run_{_SCALE_FILE[scale]}_seed{seed}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        seen += 1
        if verified == "**STALL**":
            assert payload.get("stalled") is True
            continue
        assert payload["ops_scheduled"] == int(ops_s)
        assert payload["scheduled_ratio"] == float(ratio_s)
        assert payload["verified_feasible"] is True
    assert seen == 12


def test_deadzone_unlisted_files_are_remainder_or_sessions() -> None:
    folder = _BENCH / "evidence" / "deadzone-5k-2026-08-25"
    md = (_BENCH / "BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md").read_text(encoding="utf-8")
    assert "Remainder (explicit)" in md
    listed = set(_parse_hashes(md))
    top = {p.name for p in folder.iterdir() if p.is_file()}
    remainder_ok = {
        name
        for name in top
        if name.startswith("run_3000")
        or name.startswith("run_5000ops_4m_")
        or name.startswith("run_5000ops_12m_")
        or name.startswith("run_8000")
        or name in {"SHA256SUMS.txt", "SHA256SUMS_p2_3.txt", "summary_p2_3_5000x8.json"}
    }
    unknown = top - listed - remainder_ok
    assert not unknown, f"unlabeled deadzone files: {sorted(unknown)}"


def test_deadzone_p2_3_table_matches_run_json() -> None:
    folder = _BENCH / "evidence" / "deadzone-5k-2026-08-25"
    alns = json.loads((folder / "run_5000ops_8m_ALNS_500_seed1.json").read_text(encoding="utf-8"))
    assert alns["scheduled_ratio"] == 0.0
    assert alns["ops_scheduled"] == 0
    assert alns["status"] == "error"
    assert alns["search_stop_reason"] == "wall_clock_before_search"
    rhc = json.loads((folder / "run_5000ops_8m_RHC_GREEDY_seed1.json").read_text(encoding="utf-8"))
    assert rhc["scheduled_ratio"] == 0.7702
    assert rhc["verified_feasible"] is False
    assert rhc["notary_hard_violation_kinds"] == ["MISSING_ASSIGNMENT"]
    worker = json.loads(
        (folder / "run_8000ops_4m_RHC_GREEDY_seed1.json").read_text(encoding="utf-8")
    )
    assert worker["status"] == "worker_error"
    assert worker["stalled"] is True


def test_hashed_8k4_remainder_stays_worker_error() -> None:
    folder = _BENCH / "evidence" / "deadzone-5k-2026-08-25"
    hashed = json.loads(
        (folder / "run_8000ops_4m_RHC_GREEDY_seed1.json").read_text(encoding="utf-8")
    )
    assert hashed["status"] == "worker_error"
    assert hashed["ops_scheduled"] is None
    recap = json.loads(
        (
            folder
            / "sessions"
            / "worker-error-2026-08-26-py313"
            / "run_8000ops_4m_RHC_GREEDY_seed1.json"
        ).read_text(encoding="utf-8")
    )
    assert recap["status"] == "error"
    assert recap["scheduled_ratio"] == 0.264375
    assert recap["ops_scheduled"] == 2115
    assert recap["verified_feasible"] is False


def test_hashed_verified_feasible_cells_have_no_machine_calendar() -> None:
    """И3.4: COVER/deadzone hashed Yes-cells cannot flip under occupancy notary.

    Those protocols have empty WorkCenter.calendar (COVER is wide-horizon;
    deadzone is per-op night windows). Re-notary of stored assignments is
    impossible: run JSON has no assignment list. Geometry implies ноль flips.
    """

    cover = _BENCH / "evidence" / "cover-ladder-2026-08-25"
    for path in cover.glob("run_*_seed*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("verified_feasible") is not True:
            continue
        dumped = json.dumps(payload.get("generator_kwargs") or {})
        assert "calendar" not in dumped, path.name
    dead = _BENCH / "evidence" / "deadzone-5k-2026-08-25"
    for path in dead.glob("run_5000ops_8m_*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("verified_feasible") is True:
            raise AssertionError(f"P2.3 freeze unexpectedly verified_feasible: {path.name}")
        assert payload.get("night_window_hours") == 8 or "night" in json.dumps(payload).lower()


def test_deadzone_worker_job_records_exception(tmp_path: Path) -> None:
    from benchmark.study_deadzone_5k import _run_worker_job

    out = tmp_path / "run.json"
    job = tmp_path / "job.json"
    job.write_text(
        json.dumps(
            {
                "n_operations": 8,
                "n_machines": 2,
                "solver_config": "NOT-A-NAMED-CONFIG",
                "seed": 1,
                "out_path": str(out),
            }
        ),
        encoding="utf-8",
    )
    assert _run_worker_job(job) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["status"] == "worker_error"
    assert payload["search_stop_reason"] == "worker_exception"
    assert payload["worker_traceback"]
    assert "NOT-A-NAMED-CONFIG" in (payload.get("stall_note") or "")
