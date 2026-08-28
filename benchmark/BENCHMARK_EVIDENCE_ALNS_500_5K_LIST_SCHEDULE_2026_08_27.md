# ALNS-500 unconstrained 5k list-schedule seed — 2026-08-27

> **Status:** Artifact-bound session. Not a rewrite of hashed И5.2
> `beam-alns-box-2026-08-26/` (those cells stay 0.0 /
> `wall_clock_before_search`). Not a Yes on the night analog.
> **Claim level:** three-seed unconstrained completeness after list-schedule
> COVER seed. Named box was `--time-limit-s 90` (not the registry 300 s).

```bash
python -m benchmark.study_beam_alns_box --mode alns-unconstrained \
  --seeds 1,42,999 --session-id alns-5k-list-schedule-2026-08-27 \
  --time-limit-s 90
```

Generator: unconstrained `generate_large_instance` 5000 ops / 8 machines,
horizon 720 h, no night analog, no machine calendar. Machine: Windows 11,
CPython 3.13.

## Ratios (three seeds)

| seed | ops_scheduled | scheduled_ratio | status | initial_solver | search_stop_reason | wall_time_s | iterations_completed | verified_feasible |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 5000 | 1.0 | feasible | list_schedule_cover | wall_clock | 92.162 | 22 | true |
| 42 | 5000 | 1.0 | feasible | list_schedule_cover | wall_clock | 89.706 | 33 | true |
| 999 | 5000 | 1.0 | feasible | list_schedule_cover | wall_clock | 89.207 | 24 | true |

`wall_clock_before_search=false`. Search runs after a complete seed.
Stop reason `wall_clock` is the 90 s box, not a seed hang.

K3.6 append recapture (same generator, 300 s box, incomplete greedy seed)
stays 0.2598 / 0.1044 / 0.1108 `error`
(`benchmark/BENCHMARK_EVIDENCE_ALNS_500_5K8_APPEND_2026_08_27.md`).
Do not mix folders.

## Non-claims

1. Not a rewrite of hashed 5k@8 ALNS JSON (0.0 / `wall_clock_before_search`).
2. Not a Yes on the night analog. Per-op windows / calendar still route to
   `RHC-GREEDY` (`CALENDAR_AWARE`).
3. Not a retune of `global_greedy_cover_min_ops` (still 10_000).
4. Not Linux. **не проверено на Linux.**
5. Not a quality claim on ALNS search; the 90 s wall is completeness plus
   whatever iterations fit.

## Artifact SHA-256

Directory `benchmark/evidence/alns-5k-list-schedule-2026-08-27/`. Rows from
`SHA256SUMS.txt` (working-tree bytes). `benchmark/evidence/**` is `-text`;
git-blob LF digest is the citable one after commit.

| File | SHA-256 |
|------|---------|
| `environment.json` | `d9cc572c3303bdcb51788a3c30cc2f112ba974902b83ff0a197ea7722e71fcc2` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed1.json` | `5143623a93be687cc64d0fffdcca9fef3ed9d2ece51c1f0d1056bf6304a84c4a` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed42.json` | `4737f239d791285973449b2d91ac61e5217bb20dd00016b9540a729d9b772646` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed999.json` | `d64bda9140aaaa7b2f9e40927f20236d6f7ab06d7df8f2d57c74f814e7c5842a` |
| `SHA256SUMS.txt` | `a3d5ef76a8aeed9cbdbf7b7043d03074a8095b9d35fb0432b4417bb19670299b` |
