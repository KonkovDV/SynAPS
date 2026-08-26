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

Hashed boxed cell (this folder): `BEAM-3` 3000 ops / 4 machines / night analog,
seed 1. `status=timeout`, `time_limit_s_kwarg=120`, `wall_time_s=12632.756`,
`scheduled_ratio=0.224` (672/3000), `verified_feasible=false`. That is the
measurement that the declared box does not stop BEAM. Full 12-cell boxed
matrix and the unboxed matrix are not complete in this file. Completing them
would measure unbounded BEAM cost, not whether the declared box works.

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
5. BEAM boxed matrix is incomplete except the hashed 3000@4 seed-1 cell
   (`ratio=0.224`, `timeout`, `verified_feasible=false`). Do not cite that
   ratio as a Yes or as a working 120 s box.

## Hash provenance

Canonical digest is the git blob (LF). Reproduce:

```bash
git show HEAD:benchmark/evidence/beam-alns-box-2026-08-26/run_5000ops_8m_ALNS_500_free_boxed_seed1.json | python -c "import hashlib,sys; print(hashlib.sha256(sys.stdin.buffer.read()).hexdigest())"
```

## Artifact SHA-256

Directory `benchmark/evidence/beam-alns-box-2026-08-26/`. Rows from
`SHA256SUMS.txt`. Working-tree bytes in this folder are CRLF; `-text` keeps
the git blob identical. Digests below are those bytes.

| File | SHA-256 |
|------|---------|
| `environment.json` | `b517a30f297e7c9e271f7c948103a9476e4eed488592d052342affa9aeb4ad0c` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed1.json` | `26c34febf0e74f030d59aa9c9c9b1589e2ad70dd9f643eae7cfbb535068c8b42` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed42.json` | `f3b5552a4e5f8b898337411ab732571939e1781a8c008894da2b5456449c3793` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed999.json` | `c701cf53be87b7184e52ec4e71afe760b54da2285594e53b8adddc8c0268d7df` |
| `run_3000ops_4m_BEAM_3_night_boxed_seed1.json` | `9c4687b17d055e114a642eafc79648b096152aba4b53777d1b71d4f14a082c47` |
