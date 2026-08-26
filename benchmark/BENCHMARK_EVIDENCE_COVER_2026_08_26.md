# SynAPS COVER ladder evidence — 2026-08-26

> **Status:** Artifact-bound. Not a performance guarantee. Not SOTA.
> **Supersedes:** [`BENCHMARK_EVIDENCE_50K_2026_05_18.md`](BENCHMARK_EVIDENCE_50K_2026_05_18.md)
>   as the *scale evidence protocol* linked from README. The May file is kept
>   as history (`solver_error`, 98,067 unscheduled, hashes TBD).
> **Claim level:** multi-seed point cloud (n=3). Not a DOE with repeats>1
>   beyond these three generator seeds. CHANGELOG `[Unreleased]` seed=1 rows
>   are **point estimates**, not results.

---

## Protocol

### Hardware / environment

Recorded in `benchmark/evidence/cover-ladder-2026-08-25/environment.json`.

| Item | This run |
| --- | --- |
| OS | Windows 11 (10.0.26200) |
| CPU | Intel Family 6 Model 183, 20 logical processors |
| Interpreter | CPython 3.13.7 (`C:\Users\Пользователь\AppData\Local\Programs\Python\Python313\python.exe`) |
| Kernel tree | `bd09d13561b3bd690845d07546def59b4521b16c` |
| `synaps_native` wheel | present (`list_schedule_cover` kernel loaded) |
| RSS probe | **failed** in the ladder process (`peak_rss_mb=null`). Do not cite CHANGELOG 2.3 GB RSS as this run's measurement. |

### Canonical command

```bash
python -m benchmark.study_cover_ladder --resume
```

Solver: named config `RHC-GREEDY-COVER` (registry kwargs, `time_limit_s=1800`,
`random_seed` = generator seed). Independent notary:
`synaps.validation.verify_schedule_result` (exhaustive `FeasibilityChecker`,
`proven_hard_violations`).

### Generator (keyword-only; CHANGELOG positional form is invalid)

| scale_id | kwargs |
| --- | --- |
| 60k@100 | `n_operations=60000, n_machines=100, horizon_hours=720` |
| 100k@200 | `n_operations=100000, n_machines=200, horizon_hours=720` |
| 200k@400 | `n_operations=200000, n_machines=400, n_aux_resources=40, horizon_hours=720` |
| 500k@1000 | `n_operations=500000, n_machines=1000, n_aux_resources=100, machine_flexibility=0.05, horizon_hours=720` |

Seeds: **1, 42, 999**. Statistics: min / median / max, sample CV, Student-t
95% interval with df=2 (wide; a dispersion bound, not a quality claim).

### What we record

`scheduled_ratio`, `verified_feasible`, notary emptiness, makespan vs horizon,
wall time, RSS (when the probe works), `native_backend`, `determinism`,
`determinism_violated`, `global_greedy_cover`, `commit_precedence_gate_enabled`.

---

## Results

[АРТЕФАКТ: `benchmark/evidence/cover-ladder-2026-08-25/`, 2026-08-26, seeds 1/42/999]

Solver `RHC-GREEDY-COVER`. Horizon 43 200 min on every cell. `global_greedy_cover=true`.
`commit_precedence_gate_enabled=false`. `determinism=strict`. Native list-schedule on.

### Per-seed

| scale | seed | ops | ratio | verified | notary | makespan | wall s | RSS MB | det_violated |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 60k@100 | 1 | 60000 | 1.0 | true | 0 | 41195 | 7.022 | — | false |
| 60k@100 | 42 | 60000 | 1.0 | true | 0 | 42065 | 6.957 | — | false |
| 60k@100 | 999 | 60000 | 1.0 | true | 0 | 41641 | 4.477 | — | false |
| 100k@200 | 1 | 100000 | 1.0 | true | 0 | 33442.01 | 13.719 | — | false |
| 100k@200 | 42 | 100000 | — | **STALL** | — | — | >480 (killed) | — | — |
| 100k@200 | 999 | 100000 | 1.0 | true | 0 | 33090 | 12.569 | 843.0 | false |
| 200k@400 | 1 | 200000 | 1.0 | true | 0 | 32321 | 24.286 | 1624.2 | false |
| 200k@400 | 42 | 200000 | 1.0 | true | 0 | 31946.03 | 24.046 | 1626.4 | false |
| 200k@400 | 999 | 200000 | 1.0 | true | 0 | 32166.03 | 23.79 | 1628.0 | false |
| 500k@1000 | 1 | 500000 | 1.0 | true | 0 | 31620 | 73.001 | 3956.3 | false |
| 500k@1000 | 42 | 500000 | 1.0 | true | 0 | 31649.02 | 74.172 | 3958.4 | false |
| 500k@1000 | 999 | 500000 | 1.0 | true | 0 | 32115.02 | 71.446 | 3959.1 | false |

60k RSS is empty: those three cells ran before the Windows RSS probe was fixed.
100k seed 1 same. Do not back-fill from CHANGELOG 2.3 GB.

100k seed 42: process killed after >8 min in fallback greedy repair (136 leftovers).
Sibling seeds finished in ~13 s. This is the CHANGELOG residual-hang limitation,
not a retune.

500k packed **500000** ops on all three seeds. CHANGELOG seed=1 said 499 770 —
order-packing undershoot did not reproduce here. Keep both figures as
point estimates of different generator draws.

### Dispersion (completed seeds only)

| scale | n | ratio min/med/max | makespan min/med/max | CV makespan | wall min/med/max | CV wall | t 95% makespan half-width |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 60k@100 | 3 | 1/1/1 | 41195 / 41641 / 42065 | 0.0104 | 4.477 / 6.957 / 7.022 | 0.236 | 1081 |
| 100k@200 | 2 | 1/1/1 | 33090 / 33266 / 33442 | 0.0075 | 12.569 / 13.144 / 13.719 | 0.062 | n=2: hashed `summary.json` has no half-width (helper was n=3-only). Code now emits df=1; interval is wide. JSON not rewritten. |
| 200k@400 | 3 | 1/1/1 | 31946 / 32166 / 32321 | 0.0059 | 23.79 / 24.05 / 24.29 | 0.010 | 468 |
| 500k@1000 | 3 | 1/1/1 | 31620 / 31649 / 32115 | 0.0087 | 71.45 / 73.00 / 74.17 | 0.019 | 690 |

`all_verified_feasible` is **false** at 100k@200 because one seed stalled.
Do not cite “100k COVER is feasible on three seeds”.

---

## Non-claims

1. Not a world record. Not cross-instance portable. Not live-factory.
2. Not algorithm-only: native list-schedule is on.
3. n=3 is not `--repeats>1` in the CHANGELOG DOE sense; CV/CI are descriptive.
4. `FEASIBLE` here means independent `proven_hard_violations = ∅` on this
   generator family, not industrial deployment.
5. Words forbidden unless a solver returned checked `OPTIMAL`: optimally, <!-- claims-ok -->
   proven (except the empty-notary tautology), guarantees, industrially deployed. <!-- claims-ok -->
6. 400@8 native-dead zone, gap-insert cap 64 / 80k remain limitations.
   Unconstrained 5k@400s still routes to ALNS-500. Instances with per-op
   windows or a machine calendar do not (`RHC-GREEDY`). Do not retune
   `global_greedy_cover_min_ops` to chase a Yes on the night analog.
7. Cable seeds 1..10 and C6-R1 re-probe:
   [`BENCHMARK_EVIDENCE_CABLE_C6_2026_08_26.md`](BENCHMARK_EVIDENCE_CABLE_C6_2026_08_26.md).
   Generator tardiness span is 3.87×; solver-seed CV is 0. C6-R1 INFEASIBLE
   was **not** reproduced (freeze remains unconfirmed).

---

## Failure taxonomy (this protocol)

| Category | Symptom | Typical cause |
| --- | --- | --- |
| `horizon-clip` | `horizon_clipped_assignments>0` then residual fill | latest_finish / horizon vs list-schedule tail |
| `residual-fill` | leftover ops after global cover | aux / latest_finish blocking append |
| `notary-hard` | `verified_feasible=false` | independent checker kinds in the JSON |
| `rss-probe-failed` | `peak_rss_mb=null` | Windows psapi probe (this run) |
| `seed-residual-stall` | wall ≫ sibling seeds at same scale | residual gap-fill (known 100k fragmentation note in CHANGELOG) |

---

## Reproducibility checklist

- [x] Command is `python -m benchmark.study_cover_ladder`
- [x] Named config `RHC-GREEDY-COVER` (no ad-hoc kwargs except `random_seed`)
- [x] Seeds 1, 42, 999
- [x] Independent `FeasibilityChecker` exhaustive
- [x] `SHA256SUMS.txt` present (`benchmark/evidence/cover-ladder-2026-08-25/SHA256SUMS.txt`)
- [x] Native wheel present (`list_schedule_cover`)
- [x] RSS probe failure recorded on the first process (60k + 100k seed 1); later cells measured

---

## Artifact SHA-256

Directory `benchmark/evidence/cover-ladder-2026-08-25/`. Hashes from
`SHA256SUMS.txt` (SHA-256 of that file itself is listed last).
On `fe1c6a8` the published checksum for `run_100k_at_200_seed42.json` was
`e5caad9a…` while the committed JSON hashed `da100734…` (A1). JSON bytes
were not rewritten; the sums table was stale. This table follows the files.

| File | SHA-256 |
|------|---------|
| `environment.json` | `977126179a8a31c25067c57ce43eca31153f890c01d432135ac354967b3db3c7` |
| `run_60k_at_100_seed1.json` | `e39aa48c9a38d236aa3c1b4104ac5396ddf262cefb5cdb5b435e4411700326e1` |
| `run_60k_at_100_seed42.json` | `1636be3360840ef813d0877a46ee4146a2a3112ddb65d5e6cf4b4636d5adbc3f` |
| `run_60k_at_100_seed999.json` | `3f49e808e2fd61359fbecf973a6ac59018043ee7f2c940d71f9c2eaedd73a43c` |
| `run_100k_at_200_seed1.json` | `cacb51584a6dbaf335fc929e7434c2a424bde51f748912b91ba9193aa81dfbde` |
| `run_100k_at_200_seed42.json` | `e5caad9af58b2eeb9a6d876b93adbd0e48d86816e9d17abc8676696ec5bc77b8` |
| `run_100k_at_200_seed999.json` | `46663e743f9b4ca4299488f1a5899aef07ae9a772b76bb5e2aed8ac8d795e156` |
| `run_200k_at_400_seed1.json` | `4f9dd708c0eaacf65bff86652500d34e94f6cea35d1d0dc6d88d1a5d4d87938c` |
| `run_200k_at_400_seed42.json` | `b1d5b34bdbad704916cc84b39ee085c3001bf4ef75e6c1fbf3113d8ff696d625` |
| `run_200k_at_400_seed999.json` | `37b45252c21ce3fe8ab29d0c0e9b0efc663b1c3b0177092caaf6e0968ba3da83` |
| `run_500k_at_1000_seed1.json` | `c8241745863116137824175685b18d90871a0211ca7530937d9f68133a3f012a` |
| `run_500k_at_1000_seed42.json` | `e5c65810eae5c95da0d2ccef7bd51caf7bf60446e2aacc7f419b69549061cc69` |
| `run_500k_at_1000_seed999.json` | `a535085983a715e9cbafb0eaaa6ae1e092fc145f92d1fdad82a632b3d06e612b` |
| `summary.json` | `51b7144d906c14331a001dbbc6b165bb61b9c4483e9161d4a80c5b4d80b2d5b6` |
| `SHA256SUMS.txt` | `79082fc9f5a3160ff71c119eac8d1bf8d69e2a359d6efea5598ac3a1fae45ee2` |
