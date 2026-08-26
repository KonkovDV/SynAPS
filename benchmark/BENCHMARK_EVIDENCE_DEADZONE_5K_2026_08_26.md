# 5k dead-zone (night-window analog) — 2026-08-26

> Not a calendar model. Not a retune. Not COVER at ≥10k.

[АРТЕФАКТ: `benchmark/evidence/deadzone-5k-2026-08-25/`, 2026-08-26]

Command:

```bash
python -m benchmark.study_deadzone_5k --resume --ops 5000 --machines 8
```

Kernel `bd09d13561b3bd690845d07546def59b4521b16c`. Native `list_schedule_cover` present.
Windows 11, CPython 3.13.7, 20 logical CPUs.

## Geometry (limitation of the analog)

Kernel `WorkCenter` has **no shift calendar**. Each operation gets a single
8-hour `[earliest_start, latest_finish]` starting 22:00, consecutive nights by
`seq_in_order`, orders spread by enumeration index. Daytime between nights is
not a machine off-shift; it is simply outside that op's window. A single op
cannot straddle days.

Generator: `generate_large_instance` with `n_states=8`, `ops_per_order=4`,
`machine_flexibility=0.5`, `setup_density=0.85`, `horizon_hours=720`,
`duration_range=(8, 24)`, `n_aux_resources=4`. Then the night stamp above.

Named configs, registry kwargs unchanged. `RHC-GREEDY-COVER` at 5000 ops does
**not** take the global list-schedule (`global_greedy_cover_min_ops=10000`).
`global_greedy_cover=false` on every COVER / SEARCH-COVER cell below.

Study watchdog (isolation only, not a solver retune): GREED 600s because the
registry has no `time_limit_s`; other configs = named `time_limit_s` + 90s.

## P2.3 — 5000 ops / 8 machines / seeds 1, 42, 999

**Question:** exists a named config with `scheduled_ratio=1.0` and
`verified_feasible=true` on all three seeds?

**Answer: no.** `winning_configs=[]`. All five configs were run.

| config | seed 1 | seed 42 | seed 999 | notes |
| --- | --- | --- | --- | --- |
| GREED | stall 600s | stall 600s | stall 600s | no `time_limit_s` |
| ALNS-500 | 0.0 / error / 253s | 0.0 / 253s | 0.0 / 253s | `wall_clock_before_search` |
| RHC-GREEDY | 0.7702 | 0.7812 | 0.7708 | `MISSING_ASSIGNMENT`; wall ~130s |
| RHC-GREEDY-COVER | 0.7530 | 0.7674 | 0.7624 | `global_greedy_cover=false`; ~515–846s |
| RHC-ALNS-SEARCH-COVER | 0.7580 | 0.7712 | 0.7668 | ALNS incumbents still dirty; ~385–438s |

Notary kinds on the RHC paths that returned: **`MISSING_ASSIGNMENT` only**
(independent `verify_schedule_result` violation_count 0 on the *assigned*
subset; `verified_feasible=false` because coverage is incomplete).

ALNS-500 scheduled **0** operations on all three seeds. Stop reason
`wall_clock_before_search`. Do not quote 253s as “search quality”.

Do **not** retune `global_greedy_cover_min_ops`, ALNS `time_limit_s`, or night
width to chase a Yes.

Post-evidence kernel (not these hashes): `GREED`/`GREED-K1-3` registry
`time_limit_s=120`; windowed/calendar 5k@400s routes to `RHC-GREEDY`. The
table above is the unbounded-GREED / ALNS-500 routing epoch.

## Remainder of 3k/5k/8k × 4/8/12 (RHC-GREEDY only)

Does not change the P2.3 **No**. Other four named configs were not re-run
off 5k@8. Extra cell: 3000@4 GREED seed=1 killed after ~14.5 min in-process.

| cell | seed 1 | seed 42 | seed 999 |
| --- | --- | --- | --- |
| 3000@4 | 0.5967 | 0.6217 | 0.6223 |
| 3000@8 | 0.8440 | 0.8650 | 0.8753 |
| 3000@12 | 0.8383 | 0.8480 | worker_error exit 1 |
| 5000@4 | worker_error exit 1 | same | same |
| 5000@8 | 0.7702 | 0.7812 | 0.7708 |
| 5000@12 | worker_error exit 1 | same | same |
| 8000@4/8/12 | worker_error exit 1 | same | same |

All returned cells: `verified_feasible=false`, `MISSING_ASSIGNMENT`. No cell
hit ratio 1.0. `worker_error` means the isolate process exited 1 before writing
a result (not a registry timebox). Do not quote those cells as coverage.

A subset `--resume` previously rewrote `summary.json` to `answer=incomplete`
and clobbered `environment.json`. Harness now globs every `run_*.json` and
does not overwrite `environment.json` on `--resume`. P2.3 freeze copies
(`summary_p2_3_5000x8.json`, `SHA256SUMS_p2_3.txt`) keep the original 5k@8
payload. `environment.json` on disk is the remainder-session capture; the
P2.3-era bytes are gone.

## Non-claims

1. Not a factory night-shift. No machine calendar.
2. Not COVER-at-scale: 5k is below the 10k global list-schedule gate.
3. n=3 seeds, one draw each. Not `--repeats>1`.
4. Words forbidden: optimally, proven (except empty-notary on a full schedule),
   guarantees, industrially deployed.
5. Watchdog 600s is not GREED's registry time box.

## Failure taxonomy (this protocol)

| Category | Symptom | Typical cause |
| --- | --- | --- |
| `greed-unbounded-stall` | no return inside study watchdog | this protocol: GREED had no registry `time_limit_s` (KI-N2 now boxes 120s) |
| `alns-wall-before-search` | ratio 0, `wall_clock_before_search` | constructive / admission burned the 300s box |
| `night-window-coverage-gap` | ratio ~0.75–0.78, `MISSING_ASSIGNMENT` | 8h op windows vs RHC 8h/6h windows + residual fill |
| `cover-below-10k` | `global_greedy_cover=false` | router / COVER min-ops gate, not a ladder result |
| `worker-exit-nonzero` | isolate exit 1, no result JSON from solver | remainder 5k@4/12 and 8k RHC-GREEDY cells |

## SHA-256

P2.3 freeze (5k@8 payload; `environment.json` in this file is **orphaned** —
later remainder overwrote the bytes):

- `summary_p2_3_5000x8.json` = `25a4cf8bf27052eb106f06724e2af678f9d0e0500e171d5131d0368e87e1c62d`
- `SHA256SUMS_p2_3.txt` = `22f71aaa49a93a8a08b8b2529ea7953d5a1c4f7d34e4f75f9f7faebd437789fa`

Live directory after remainder + summary rebuild (`SHA256SUMS.txt`
`3ef7e7b138f8645c930f048b0e20007c6ea4bcc8e2b436705414512f654a0d63`).
`environment.json` is remainder-session, not the P2.3 capture.
P2.3 freeze sums now list only the 15 `run_5000ops_8m_*.json` files plus
`summary_p2_3_5000x8.json` (the old freeze `summary.json` bytes). The freeze
copy no longer lists overwritten `environment.json` / live `summary.json` /
`run_3000ops_4m_GREED_seed1.json`.

Recapture (not P2.3): `sessions/recapture-2026-08-26/environment.json`
SHA-256 `8fa793e793479e128289329c059fea193083f5e4593d39335f95b43c00dc14c1`.

B1 recapture 8k@4 RHC-GREEDY seed 1 (hashed remainder JSON **not** rewritten).
Epoch file stays `worker_error` at 210 s. This tree: isolate finished inside
the watchdog. Not a Yes. `sessions/worker-error-2026-08-26-py313/` is the
matching interpreter (CPython 3.13.7, native on): ratio 0.264375, 2115/8000,
`MISSING_ASSIGNMENT`, wall 145.212 s, `status=error`, `time_limit_reached`.
`sessions/worker-error-2026-08-26/` is CPython 3.12.10, no native: ratio
0.2585, wall 146.555 s. Exit 1 did not reproduce. Cause of the hashed kill
is unknown (old isolate may have dropped stderr).

| File | SHA-256 |
| --- | --- |
| `environment.json` | `52cbc8d517bc465907d4161d63dd9782ba08747f88ac4a342c3d80cae4282ca7` |
| `sessions/recapture-2026-08-26/environment.json` | `8fa793e793479e128289329c059fea193083f5e4593d39335f95b43c00dc14c1` |
| `sessions/worker-error-2026-08-26/run_8000ops_4m_RHC_GREEDY_seed1.json` | `bd5c2d7d0187d6eb0f2119c6bdad9b2c65b8f2626e0a875e7003fdfc63eb847e` |
| `sessions/worker-error-2026-08-26/SHA256SUMS.txt` | `905f85fd2250bf0d2e8d280080d5d5fc6cd878b56f2c2d9c066f904175890a5f` |
| `sessions/worker-error-2026-08-26-py313/run_8000ops_4m_RHC_GREEDY_seed1.json` | `fc5623f68c16ef9b46b205e3f8c95dcbf4567fe1d8a8a1b6294b324a6057bd31` |
| `sessions/worker-error-2026-08-26-py313/SHA256SUMS.txt` | `94ed1c9e13a33b96bdabb165d5280a6bb9c1e1c28c352b9e96113fb5e395f040` |
| `summary.json` | `0a24dc92546dc90cc9455102c0ff973e9f4045bf76d7361436ad2c117163407f` |
| `SHA256SUMS.txt` | `3ef7e7b138f8645c930f048b0e20007c6ea4bcc8e2b436705414512f654a0d63` |
| `run_5000ops_8m_GREED_seed1.json` | `dacb5fee40714db95da68cce9937860460e6472f1818a26a093828f19d6accb5` |
| `run_5000ops_8m_GREED_seed42.json` | `30c7345a05755a45bcb5b87ae780fbf7b82d362f2403b3ac08f05775d49acb64` |
| `run_5000ops_8m_GREED_seed999.json` | `5817b5f015911d7b93cd5151367a7b051adcaa7d5dfa0ce6ddebe8a8701131b1` |
| `run_5000ops_8m_ALNS_500_seed1.json` | `f7ce9c52a9d111fedc768cc54488c3c364019ab545cf250756ec296b2e40b4b7` |
| `run_5000ops_8m_ALNS_500_seed42.json` | `7a1f7cabdebaffce3156170b5294604a05534c4b2e9892b6224b278614c4513d` |
| `run_5000ops_8m_ALNS_500_seed999.json` | `2f9b00e38c798fc86ab1083940945e67a9c66e580cdbdadb413dc03b5a24d4b1` |
| `run_5000ops_8m_RHC_GREEDY_seed1.json` | `d6b2483eeb7ae3988d6eda434f9804d3d22670d53536dc9fa570f609b615e90f` |
| `run_5000ops_8m_RHC_GREEDY_seed42.json` | `76556864ecf835141930ff7dfcd8124b1ca1510ef08983b03c5a4da354a28c56` |
| `run_5000ops_8m_RHC_GREEDY_seed999.json` | `20b27f7599dc6928bf9e6919eb17530f00bfb44f14c913d4d1ba735cb1931c07` |
| `run_5000ops_8m_RHC_GREEDY_COVER_seed1.json` | `0d99f075e6caf76f94e6d71e2163550688211410e1236d59334a418918e5c1a9` |
| `run_5000ops_8m_RHC_GREEDY_COVER_seed42.json` | `a48c877e917135c0d7d9dfa646650acc3d776f87110bcb5ce8c786f08297d4d3` |
| `run_5000ops_8m_RHC_GREEDY_COVER_seed999.json` | `454635159ad97ed4ad2040fc8e246f8c274caa3ec8b95e6ac047ff1cd89863f3` |
| `run_5000ops_8m_RHC_ALNS_SEARCH_COVER_seed1.json` | `bdd10160ede03a0bb8081f82ca7e1c70b5952e66731c7ada5e8770cb8a11229d` |
| `run_5000ops_8m_RHC_ALNS_SEARCH_COVER_seed42.json` | `9b623d20ff16714311b974e1da98d6ce8536d954117acd58795354df2a955098` |
| `run_5000ops_8m_RHC_ALNS_SEARCH_COVER_seed999.json` | `9c7f040f7e9b14410f867e1dc11ebcb2295324ee5234a9cfff2e89123387ae19` |

**Remainder (explicit):** `run_3000*`, `run_5000ops_4m_*`, `run_5000ops_12m_*`,
`run_8000*`, `run_3000ops_4m_GREED_seed1.json` (in-process 14.5 min stall;
live SHA-256 `f71ff7892443c7d97e60d314ae3445737e8bda6237c67b7befee06e5fb834937`),
and `sessions/**`. Live `SHA256SUMS.txt` covers top-level JSON including
remainder cells. `sessions/` is a later capture, not P2.3.
