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
_SKIP_EVIDENCE = ("50K", "SEARCH_COVER")
_DIR_LINE = re.compile(r"Directory `benchmark/evidence/([^/`]+)/`")
_EVIDENCE_DIR = re.compile(r"benchmark/evidence/([A-Za-z0-9._-]+)/")
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


def _cited_evidence_mds() -> list[Path]:
    """K3.2: every BENCHMARK_EVIDENCE_*.md except retired 50K / SEARCH_COVER."""

    out: list[Path] = []
    for md in sorted(_BENCH.glob("BENCHMARK_EVIDENCE_*.md")):
        if any(token in md.name for token in _SKIP_EVIDENCE):
            continue
        out.append(md)
    return out


def _study_dir_from_md(text: str) -> str:
    """Map an evidence MD to its SHA256SUMS folder.

    Prefer the Artifact ``Directory `benchmark/evidence/<dir>/` `` line so a
    session path mentioned earlier in the narrative cannot steal the mapping
    (BEAM/ALNS cites deadzone sessions before its own folder).
    """

    match = _DIR_LINE.search(text)
    if match:
        return match.group(1)
    names = _EVIDENCE_DIR.findall(text)
    assert names, "markdown has no benchmark/evidence/<dir>/ path"
    for name in reversed(names):
        if (_BENCH / "evidence" / name / "SHA256SUMS.txt").is_file():
            return name
    return names[0]


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
    """F0.5 / K3.2: MD Artifact/SHA-256 table matches SHA256SUMS.txt line for line."""
    mds = _cited_evidence_mds()
    assert mds, "no cited BENCHMARK_EVIDENCE_*.md files"
    for md in mds:
        text = md.read_text(encoding="utf-8")
        study = _study_dir_from_md(text)
        sums_path = _BENCH / "evidence" / study / "SHA256SUMS.txt"
        assert sums_path.is_file(), f"{md.name}: missing {sums_path}"
        sums = _parse_sha256sums(sums_path)
        listed = _parse_hashes(text)
        _assert_md_table_matches_sums(md.name, sums, listed)


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
    mds = _cited_evidence_mds()
    names = {md.name for md in mds}
    assert "BENCHMARK_EVIDENCE_CALENDAR_3000_8M_2026_08_27.md" in names
    assert "BENCHMARK_EVIDENCE_ALNS_PROFILE_2026_08_27.md" in names
    assert "BENCHMARK_EVIDENCE_BEAM_ALNS_2026_08_26.md" in names
    assert "BENCHMARK_EVIDENCE_ALNS_500_5K8_APPEND_2026_08_27.md" in names
    assert "BENCHMARK_EVIDENCE_ALNS_500_5K_LIST_SCHEDULE_2026_08_27.md" in names
    assert "BENCHMARK_EVIDENCE_COVER_100K_SEED42_2026_08_27.md" in names
    assert "BENCHMARK_EVIDENCE_50K_2026_05_18.md" not in names
    assert "BENCHMARK_EVIDENCE_SEARCH_COVER_2026_07_29.md" not in names
    for md in mds:
        text = md.read_text(encoding="utf-8")
        assert "SHA-256" in text or "SHA256" in text, f"{md.name}: no hash section"
        listed = _parse_hashes(text)
        assert listed, f"{md.name}: no hash rows"
        study = _study_dir_from_md(text)
        folder = _BENCH / "evidence" / study
        for rel, digest in listed.items():
            path = folder / rel
            assert path.is_file(), f"{md.name}: missing {rel}"
            assert _sha256(path) == digest, f"{md.name}: mismatch {rel}"


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


def test_night_list_schedule_5k_session_is_not_a_yes() -> None:
    """Windowed 5k list-schedule is complete-and-fast, not a P2.3 Yes."""

    session = json.loads(
        (
            _BENCH
            / "evidence"
            / "deadzone-5k-2026-08-25"
            / "sessions"
            / "night-window-scan-2026-08-28"
            / "run_5000ops_8m_RHC_GREEDY_seed1.json"
        ).read_text(encoding="utf-8")
    )
    assert session["global_greedy_cover"] is True
    assert session["scheduled_ratio"] == 0.7446
    assert session["ops_scheduled"] == 3723
    assert session["verified_feasible"] is False
    assert session["wall_time_s"] == 1.165
    hashed = json.loads(
        (
            _BENCH / "evidence" / "deadzone-5k-2026-08-25" / "run_5000ops_8m_RHC_GREEDY_seed1.json"
        ).read_text(encoding="utf-8")
    )
    assert hashed["scheduled_ratio"] == 0.7702


def test_night_rhc_rolling_5k_session_is_not_a_yes() -> None:
    """Rolling 5k@8 after window leftover scan is still wall_clock, not a Yes."""

    folder = (
        _BENCH / "evidence" / "deadzone-5k-2026-08-25" / "sessions" / "night-rhc-rolling-2026-08-28"
    )
    expected = {
        1: (3844, 0.7688, 128.074),
        42: (3918, 0.7836, 128.046),
        999: (3857, 0.7714, 127.661),
    }
    for seed, (ops, ratio, wall) in expected.items():
        payload = json.loads(
            (folder / f"run_5000ops_8m_RHC_GREEDY_seed{seed}.json").read_text(encoding="utf-8")
        )
        assert payload["global_greedy_cover"] is False
        assert payload["ops_scheduled"] == ops
        assert payload["scheduled_ratio"] == ratio
        assert payload["wall_time_s"] == wall
        assert payload["search_stop_reason"] == "wall_clock"
        assert payload["verified_feasible"] is False


def test_remainder_window_scan_session_is_wall_clock_not_yes() -> None:
    """Remainder 5k/8k seed 1 after window leftover scan is still not a Yes."""

    folder = (
        _BENCH
        / "evidence"
        / "deadzone-5k-2026-08-25"
        / "sessions"
        / "remainder-window-scan-2026-08-28"
    )
    expected = {
        "run_5000ops_4m_RHC_GREEDY_seed1.json": (2005, 0.401),
        "run_5000ops_8m_RHC_GREEDY_seed1.json": (3857, 0.7714),
        "run_5000ops_12m_RHC_GREEDY_seed1.json": (4257, 0.8514),
        "run_8000ops_4m_RHC_GREEDY_seed1.json": (2078, 0.25975),
        "run_8000ops_8m_RHC_GREEDY_seed1.json": (4379, 0.547375),
        "run_8000ops_12m_RHC_GREEDY_seed1.json": (6131, 0.766375),
    }
    for name, (ops, ratio) in expected.items():
        payload = json.loads((folder / name).read_text(encoding="utf-8"))
        assert payload["search_stop_reason"] == "wall_clock"
        assert payload["ops_scheduled"] == ops
        assert payload["scheduled_ratio"] == ratio
        assert payload["verified_feasible"] is False
        assert payload["notary_hard_violation_kinds"] == ["MISSING_ASSIGNMENT"]


def test_night_window_edd_session_is_not_a_yes() -> None:
    """Window-aware 5k@8 list-schedule is faster and denser, not a P2.3 Yes."""

    folder = (
        _BENCH / "evidence" / "deadzone-5k-2026-08-25" / "sessions" / "night-window-edd-2026-08-28"
    )
    expected = {
        1: (4176, 0.8352, 4.978),
        42: (4129, 0.8258, 5.636),
        999: (4099, 0.8198, 5.879),
    }
    for seed, (ops, ratio, wall) in expected.items():
        payload = json.loads(
            (folder / f"run_5000ops_8m_RHC_GREEDY_seed{seed}.json").read_text(encoding="utf-8")
        )
        assert payload["global_greedy_cover"] is True
        assert payload["ops_scheduled"] == ops
        assert payload["scheduled_ratio"] == ratio
        assert payload["wall_time_s"] == wall
        assert payload["search_stop_reason"] == "completed"
        assert payload["verified_feasible"] is False
        assert payload["notary_hard_violation_kinds"] == ["MISSING_ASSIGNMENT"]
    hashed = json.loads(
        (
            _BENCH / "evidence" / "deadzone-5k-2026-08-25" / "run_5000ops_8m_RHC_GREEDY_seed1.json"
        ).read_text(encoding="utf-8")
    )
    assert hashed["scheduled_ratio"] == 0.7702


def test_remainder_window_fix_session_is_not_a_yes() -> None:
    """Remainder 5k/8k seed 1 after window-aware list-schedule is still not a Yes."""

    folder = (
        _BENCH
        / "evidence"
        / "deadzone-5k-2026-08-25"
        / "sessions"
        / "remainder-window-fix-2026-08-28"
    )
    expected = {
        "run_5000ops_4m_RHC_GREEDY_seed1.json": (2029, 0.4058, 5.319),
        "run_5000ops_8m_RHC_GREEDY_seed1.json": (4188, 0.8376, 5.756),
        "run_5000ops_12m_RHC_GREEDY_seed1.json": (4997, 0.9994, 0.69),
        "run_8000ops_4m_RHC_GREEDY_seed1.json": (2156, 0.2695, 8.507),
        "run_8000ops_8m_RHC_GREEDY_seed1.json": (4519, 0.564875, 10.824),
        "run_8000ops_12m_RHC_GREEDY_seed1.json": (6689, 0.836125, 10.367),
    }
    for name, (ops, ratio, wall) in expected.items():
        payload = json.loads((folder / name).read_text(encoding="utf-8"))
        assert payload["global_greedy_cover"] is True
        assert payload["search_stop_reason"] == "completed"
        assert payload["ops_scheduled"] == ops
        assert payload["scheduled_ratio"] == ratio
        assert payload["wall_time_s"] == wall
        assert payload["verified_feasible"] is False
        assert payload["notary_hard_violation_kinds"] == ["MISSING_ASSIGNMENT"]


def test_calendar_list_schedule_session_is_three_seed_yes() -> None:
    """Machine-calendar 3000@8 list-schedule is a session Yes. Not hashed. Not P2.3."""

    folder = (
        _BENCH
        / "evidence"
        / "calendar-3000-8m-2026-08-27"
        / "sessions"
        / "calendar-list-schedule-2026-08-28"
    )
    expected = {1: 0.282, 42: 0.303, 999: 0.286}
    for seed, wall in expected.items():
        payload = json.loads(
            (folder / f"run_3000ops_8m_RHC_GREEDY_calendar_seed{seed}.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["scheduled_ratio"] == 1.0
        assert payload["ops_scheduled"] == 3000
        assert payload["verified_feasible"] is True
        assert payload["notary_hard_violation_kinds"] == []
        assert payload["has_machine_calendar"] is True
        assert payload["has_per_op_windows"] is False
        assert payload["wall_time_s"] == wall
    hashed = json.loads(
        (
            _BENCH
            / "evidence"
            / "calendar-3000-8m-2026-08-27"
            / "run_3000ops_8m_RHC_GREEDY_calendar_seed1.json"
        ).read_text(encoding="utf-8")
    )
    assert hashed["verified_feasible"] is False
    assert "CALENDAR_VIOLATION" in hashed["notary_hard_violation_kinds"]


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


def test_alns_500_5k8_append_enters_search() -> None:
    """K3.6: recapture must start ALNS search; epoch 0.0 JSON is not rewritten."""

    folder = _BENCH / "evidence" / "alns-500-5k8-append-2026-08-27"
    expected = {
        1: (1299, 0.2598, 299.979),
        42: (522, 0.1044, 299.172),
        999: (554, 0.1108, 299.63),
    }
    for seed, (ops, ratio, wall) in expected.items():
        payload = json.loads(
            (folder / f"run_5000ops_8m_ALNS_500_free_boxed_seed{seed}.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["ops_scheduled"] == ops
        assert payload["scheduled_ratio"] == ratio
        assert payload["wall_time_s"] == wall
        assert payload["status"] == "error"
        assert payload["verified_feasible"] is False
        assert payload["wall_clock_before_search"] is False
        assert payload["search_stop_reason"] != "wall_clock_before_search"
        assert payload["assignments"]
        assert payload.get("iterations_completed") is None
    epoch = json.loads(
        (
            _BENCH
            / "evidence"
            / "beam-alns-box-2026-08-26"
            / "run_5000ops_8m_ALNS_500_free_boxed_seed1.json"
        ).read_text(encoding="utf-8")
    )
    assert epoch["ops_scheduled"] == 0
    assert epoch["search_stop_reason"] == "wall_clock_before_search"


def test_alns_5k_list_schedule_seed_is_full_feasible() -> None:
    """KI-N1 session: unconstrained 5k ALNS-500 completes via list-schedule seed."""

    folder = _BENCH / "evidence" / "alns-5k-list-schedule-2026-08-27"
    expected = {
        1: (5000, 1.0, 92.162, 22),
        42: (5000, 1.0, 89.706, 33),
        999: (5000, 1.0, 89.207, 24),
    }
    for seed, (ops, ratio, wall, iters) in expected.items():
        payload = json.loads(
            (folder / f"run_5000ops_8m_ALNS_500_free_boxed_seed{seed}.json").read_text(
                encoding="utf-8"
            )
        )
        assert payload["ops_scheduled"] == ops
        assert payload["scheduled_ratio"] == ratio
        assert payload["wall_time_s"] == wall
        assert payload["status"] == "feasible"
        assert payload["verified_feasible"] is True
        assert payload["initial_solver"] == "list_schedule_cover"
        assert payload["wall_clock_before_search"] is False
        assert payload["iterations_completed"] == iters
    epoch = json.loads(
        (
            _BENCH
            / "evidence"
            / "beam-alns-box-2026-08-26"
            / "run_5000ops_8m_ALNS_500_free_boxed_seed1.json"
        ).read_text(encoding="utf-8")
    )
    assert epoch["ops_scheduled"] == 0


def test_cover_100k_seed42_session_is_full_python_cover() -> None:
    """KI-N4: hashed stall row stays; session recapture is complete on Python COVER."""

    hashed = json.loads(
        (_BENCH / "evidence" / "cover-ladder-2026-08-25" / "run_100k_at_200_seed42.json").read_text(
            encoding="utf-8"
        )
    )
    assert hashed["stalled"] is True
    session = json.loads(
        (
            _BENCH / "evidence" / "cover-100k-seed42-2026-08-27" / "run_100k_at_200_seed42.json"
        ).read_text(encoding="utf-8")
    )
    assert session.get("stalled") is not True
    assert session["ops_scheduled"] == 100000
    assert session["scheduled_ratio"] == 1.0
    assert session["verified_feasible"] is True
    assert session["native_backend"] == "python"
    assert session["wall_time_s"] == 40.137


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
