# BENCHMARK_EVIDENCE_BEAM_ALNS_2026_08_26

И5. Machine: same Windows 11 / CPython as COVER ladder. Kernel tree at
measurement: `docs/f0-unlock-2026-08-26` (uncommitted И3–И8 on top of `bf8687d`).
Hashed COVER / cable / deadzone JSON not rewritten.

`benchmark/evidence/**` is `-text` in `.gitattributes`. Digests are git-blob LF.

## И5.2 ALNS-500 unconstrained 5000 ops / 8 machines

Generator: `generate_large_instance` (no night analog, no machine calendar).
Named config `ALNS-500` (`time_limit_s=300`). Seeds 1 / 42 / 999.

| seed | ops_scheduled | scheduled_ratio | status | search_stop_reason | wall_time_s | wall_clock_before_search |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0 | 0.0 | error | wall_clock_before_search | 252.927 | true |
| 42 | 0 | 0.0 | error | wall_clock_before_search | 252.725 | true |
| 999 | 0 | 0.0 | error | wall_clock_before_search | 252.857 | true |

ALNS-500 does **not** enter search on unconstrained 5k@8 on this tree. Same
stop reason as the night analog.

## И5.1 BEAM-3 / BEAM-5 box

Registry declares `time_limit_s=120` for `BEAM-3` and `BEAM-5`.
`GreedyDispatch._solve_core` reads that kwarg. `BeamSearchDispatch._solve_core`
does not. The 120 s piggyback is **cosmetic**.

A boxed `BEAM-3` 3000@4 night cell was started after ALNS; it was still running
after 120 s wall (no JSON yet). Full 12-cell boxed matrix and the unboxed
matrix are not complete in this file. Completing them would measure unbounded
BEAM cost, not whether the declared box works.

## И6.1 KI-N3 recapture (session, not a rewrite)

`benchmark/evidence/deadzone-5k-2026-08-25/sessions/n3-recapture-2026-08-26/`
RHC-GREEDY seed 1, isolate watchdog 210 s. All six cells `status=error`,
`search_stop_reason=wall_clock`, `MISSING_ASSIGNMENT`. Not `worker_error`.
`worker_peak_rss_raw=null` (Windows). No signal. Hashed epoch JSON unchanged.

| cell | scheduled_ratio | wall_time_s | status |
| --- | --- | --- | --- |
| 5k@4 | 0.4034 | 133.59 | error |
| 5k@8 | 0.7648 | 137.653 | error |
| 5k@12 | 0.8514 | 135.781 | error |
| 8k@4 | 0.262625 | 130.406 | error |
| 8k@8 | 0.543875 | 150.129 | error |
| 8k@12 | 0.721125 | 150.382 | error |

## Non-claims

1. Not a Yes on 5k@8. `winning_configs` remain empty on the hashed P2.3 freeze.
2. Not a Linux measurement. И6.2 ubuntu-latest 8k@4 was not run.
3. Not a retune of `global_greedy_cover_min_ops` or ALNS `time_limit_s`.
4. Not industrial deployment. Not ЦОДД / Мосгортранс / Россети as customers.
5. BEAM boxed matrix is incomplete; do not cite a BEAM scheduled_ratio from this round.
6. K3.6 recapture (search starts, still not a Yes) is a different folder:
   `benchmark/BENCHMARK_EVIDENCE_ALNS_500_5K8_APPEND_2026_08_27.md`.
7. Unconstrained 5k completeness after list-schedule seed is
   `benchmark/BENCHMARK_EVIDENCE_ALNS_500_5K_LIST_SCHEDULE_2026_08_27.md`
   (hashed И5.2 JSON still 0.0). BEAM night boxed seed42/999 leftovers live in
   `sessions/beam-3-night-boxed-leftover-2026-08-26/` and are **not** in this
   hashed `SHA256SUMS.txt`.

## Hash provenance

Canonical digest is the git blob (LF). Reproduce:

```bash
git show HEAD:benchmark/evidence/beam-alns-box-2026-08-26/run_5000ops_8m_ALNS_500_free_boxed_seed1.json | python -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())"
```

## Artifact SHA-256

Directory `benchmark/evidence/beam-alns-box-2026-08-26/`. Rows from
`SHA256SUMS.txt` after the ALNS-only write (BEAM files, if any, appear later).

| File | SHA-256 |
|------|---------|
| `environment.json` | `b517a30f297e7c9e271f7c948103a9476e4eed488592d052342affa9aeb4ad0c` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed1.json` | `26c34febf0e74f030d59aa9c9c9b1589e2ad70dd9f643eae7cfbb535068c8b42` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed42.json` | `f3b5552a4e5f8b898337411ab732571939e1781a8c008894da2b5456449c3793` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed999.json` | `c701cf53be87b7184e52ec4e71afe760b54da2285594e53b8adddc8c0268d7df` |
