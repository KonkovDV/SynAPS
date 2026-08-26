# BENCHMARK_EVIDENCE_CALENDAR_3000_8M_2026_08_27

K2.1. Machine: Windows 11, CPython 3.12, native accelerator **off**.
Kernel `9fe0e481` (master after PR #12). Solver `RHC-GREEDY` (`time_limit_s=120`
plus documented 30 s fallback). Generator: `generate_large_instance` 3000 ops /
8 machines / 720 h, **no per-op windows**, then `WorkCenter.calendar` night
shifts 22:00–06:00 on every machine.

This is **not** the dead-zone 5k@8 figure 0.7702. That study stamps per-op
`[earliest_start, latest_finish]` on a 24/7 work center. Do not reuse 0.7702
as night coverage for signs.

## Ratios (three seeds)

| seed | ops_scheduled | scheduled_ratio | wall_time_s | status | search_stop_reason | notary_hard_violation_kinds |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 2761 | 0.9203 | 150.138 | error | wall_clock | `CALENDAR_VIOLATION`, `MISSING_ASSIGNMENT` |
| 42 | 2702 | 0.9007 | 150.108 | error | wall_clock | `CALENDAR_VIOLATION`, `MISSING_ASSIGNMENT` |
| 999 | 2625 | 0.8750 | 150.116 | error | wall_clock | `CALENDAR_VIOLATION`, `MISSING_ASSIGNMENT` |

`verified_feasible=false` on all three. Independent `verify_schedule_result`
reported empty `violation_kinds`; the solver notary is the occupancy source.

## Unplaced reason codes (every leftover op)

Classifier: `benchmark/study_calendar_3000.py` (`WINDOW_CLOSED` /
`NO_CREW_CAPACITY` / `IMPOSSIBLE_BY_CONSTRUCTION` / `GOST_PRIORITY_PREEMPTED`).
Tests: `tests/test_calendar_unplaced_reasons.py`. GOST is a domain code; this
kernel instance cannot emit it.

| seed | unplaced | WINDOW_CLOSED | NO_CREW_CAPACITY | IMPOSSIBLE_BY_CONSTRUCTION | GOST_PRIORITY_PREEMPTED |
| --- | --- | --- | --- | --- | --- |
| 1 | 239 | 0 | 239 | 0 | 0 |
| 42 | 298 | 0 | 298 | 0 | 0 |
| 999 | 375 | 0 | 375 | 0 | 0 |

Every leftover op **fits some published night shift on an empty eligible
machine**. None is impossible by shift length. None is window-closed (ops have
no `earliest_start` / `latest_finish`). The remainder is crew/machine occupancy
under an 8 h/24 h calendar, measured with the 120 s RHC box exhausted
(`wall_clock` + fallback stop).

Notary `CALENDAR_VIOLATION` count is **above** leftover count (seed 1: 289 vs
239). Some placed assignments still fail occupancy `[start − setup, end]`.
That is a notary fact on this run, not a Yes.

## Non-claims

1. Not a sign-city pitch number beyond this generator and this box.
2. Not Linux. Native COVER was not loaded.
3. Not a retune of `global_greedy_cover_min_ops`.
4. Hash-gate `_CURRENT` / `_STUDY` still allowlists three COVER/cable/deadzone
   MD files; this file is outside that list until K3.2.

## Artifact SHA-256

Directory `benchmark/evidence/calendar-3000-8m-2026-08-27/`. Rows from
`SHA256SUMS.txt` (working-tree bytes). `benchmark/evidence/**` is `-text`;
git-blob LF digest is the citable one after commit.

| File | SHA-256 |
|------|---------|
| `environment.json` | `ad66604e32b75bb9245b657742862c79b973d65f58d044b10d56fa7d4758035e` |
| `run_3000ops_8m_RHC_GREEDY_calendar_seed1.json` | `606a5b0c9872f89f99740a5df21f1b9812b6e9637f42efa5ffb358a610a4db30` |
| `run_3000ops_8m_RHC_GREEDY_calendar_seed42.json` | `7739faa9198aca0c7585e0ddfb03d38b1f15ae041dcc9a18bba0bbf711f1cb1d` |
| `run_3000ops_8m_RHC_GREEDY_calendar_seed999.json` | `c897b168d2cc9963b4288149428a146991df1fea82b450b8a0706fb7e4822cd6` |
| `summary.json` | `33ce8c217165b192707051cd6ad2a1041565a0e7d2d9aaff3382884cab22ef27` |
