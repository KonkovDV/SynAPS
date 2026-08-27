# BENCHMARK_EVIDENCE_ALNS_500_5K8_APPEND_2026_08_27

K3.6 recapture. Unconstrained `ALNS-500` 5000 ops / 8 machines, named
`time_limit_s=300`, seeds 1 / 42 / 999. Generator:
`generate_large_instance` (no night analog, no machine calendar).
`--store-assignments` for the new folder only.

Parent kernel `5ef0708` (PR #13 merge) plus uncommitted K3.6:
append gap-scan at n>=2000, skip native initial seed and Phase-1 completion
repair at that n, skip SA calibration at that n. Machine: Windows 11,
CPython 3.13.7, `synaps_native` present. Hashed epoch JSON in
`benchmark/evidence/beam-alns-box-2026-08-26/` is not rewritten.

## Ratios (three seeds)

| seed | ops_scheduled | scheduled_ratio | status | search_stop_reason | wall_time_s | wall_clock_before_search | verified_feasible |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1299 | 0.2598 | error | completed | 299.979 | false | false |
| 42 | 522 | 0.1044 | error | completed | 299.172 | false | false |
| 999 | 554 | 0.1108 | error | completed | 299.63 | false | false |

ALNS search **starts** (`wall_clock_before_search=false`). Coverage is
partial. Status is `error`. This is not a Yes on 5k@8.

Epoch И5.2 (same named box, same generator): 0.0 /
`wall_clock_before_search` / ~253 s. Do not mix the two folders.

## Non-claims

1. Not a Yes on 5k@8. `verified_feasible=false` on all three seeds.
2. Not a rewrite of hashed COVER / deadzone / cable / И5.2 ALNS JSON.
3. Not a retune of `global_greedy_cover_min_ops`.
4. Not Linux. Native COVER path was not used (ALNS Python/native repair).
5. `search_stop_reason=completed` is the honesty stamp **in this hashed JSON**
   (D3 `remaining_s < 1` used to fall through to `completed`). Code after the
   K3 RT pass stamps that cut as `wall_clock`. JSON bytes were not rewritten.
   Wall is the 300 s box. Do not quote it as a complete 5000-op schedule.

## Artifact SHA-256

Directory `benchmark/evidence/alns-500-5k8-append-2026-08-27/`. Rows from
`SHA256SUMS.txt` (working-tree bytes). `benchmark/evidence/**` is `-text`;
git-blob LF digest is the citable one after commit.

| File | SHA-256 |
|------|---------|
| `environment.json` | `20c45658c27a9abbe0d2e6b7fbec4f51307d6259383df899651b44cc22abd668` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed1.json` | `df4a7bfcbb858c6b5d776893c73c0546d00e283ed6f9a69237142a6dd3cbceb6` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed42.json` | `d587f5f2574e431fd3bca12a31be7a0b4fb9c93248ab73e46b6bcf3d3c0b1794` |
| `run_5000ops_8m_ALNS_500_free_boxed_seed999.json` | `90589f3ac7c479080add069cd307fbb7745ca2c4d7022e579b4d91a4a4cba1f1` |
