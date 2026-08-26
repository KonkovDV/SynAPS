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
4. Words forbidden: optimally, proven (except empty-notary on a full schedule), <!-- claims-ok -->
   guarantees, industrially deployed. <!-- claims-ok -->
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

- `summary_p2_3_5000x8.json` = `8c1fd12dc128a244eb6216f5a617c85503300bf5d08d3a438eee29b34c618b25`
- `SHA256SUMS_p2_3.txt` = `93f55815ceab4400a6108d0ade584e574e8dce7ecc965b460fa536a706852595`

Live directory after remainder + summary rebuild (`SHA256SUMS.txt`
`f3d1615d2e524bdae7f6bce6f13f1dc60c454c0c60695f920f3934ed49bd0c20`).
`environment.json` is remainder-session, not the P2.3 capture.
P2.3 freeze sums now list only the 15 `run_5000ops_8m_*.json` files plus
`summary_p2_3_5000x8.json` (the old freeze `summary.json` bytes). The freeze
copy no longer lists overwritten `environment.json` / live `summary.json` /
`run_3000ops_4m_GREED_seed1.json`.

Recapture (not P2.3): `sessions/recapture-2026-08-26/environment.json`
SHA-256 `c8bc8363a3b0849fd33639b589283f7dda326712bbe1ea3b590af9a18834e1bc`.

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
| `environment.json` | `ef3d4ae969749474d324c29c41897382611bddad0d436f39efc331977832b1cf` |
| `sessions/recapture-2026-08-26/environment.json` | `c8bc8363a3b0849fd33639b589283f7dda326712bbe1ea3b590af9a18834e1bc` |
| `sessions/worker-error-2026-08-26/run_8000ops_4m_RHC_GREEDY_seed1.json` | `b09fc80fe11dfeea44174c63aa849e3b5120da0c2aeacdd746ec74f5b7f62a5c` |
| `sessions/worker-error-2026-08-26/SHA256SUMS.txt` | `e1cc6e2566cb3b811cb698fafb3b8d7751049800c6e3c76bcec115e9926cf29d` |
| `sessions/worker-error-2026-08-26-py313/run_8000ops_4m_RHC_GREEDY_seed1.json` | `d51f8ea42e5cc911c6851916f4dcd783d25e9542ed8d0760525d63f11f35178f` |
| `sessions/worker-error-2026-08-26-py313/SHA256SUMS.txt` | `33ca8da76c2bed1ab8c5f2a8c81846ea32383b7f6a38aa510af7559b24511ed9` |
| `summary.json` | `29ab576d0023c9aff16f674c6f94d257c4d4b94a9c15a3086249a890643b45c4` |
| `SHA256SUMS.txt` | `f3d1615d2e524bdae7f6bce6f13f1dc60c454c0c60695f920f3934ed49bd0c20` |
| `run_5000ops_8m_GREED_seed1.json` | `358062e9b2d3c0a1848d3eedbca1deb8aee6819cac82baf68facf2bb431df2a6` |
| `run_5000ops_8m_GREED_seed42.json` | `f254f11e1bb7f9dea5a5d58cf94a18f569bfceac9b634b6fea7e4b8266ab0508` |
| `run_5000ops_8m_GREED_seed999.json` | `d05ce024f7d5adab25e9c32c8ba06355c456d0231c331a5a7a34f4516fabfddc` |
| `run_5000ops_8m_ALNS_500_seed1.json` | `397a172e6e82acc726c781c82b059269ffb05c7cd147c17845fd5e6071250734` |
| `run_5000ops_8m_ALNS_500_seed42.json` | `f761ff8173a085a42d03a5eb8cc6cbcb0f1c9e29573ec13a69a8504240eeac63` |
| `run_5000ops_8m_ALNS_500_seed999.json` | `e5a004f6b2edf6e973c45abd87b0f79c4232abec5ec6fd8c7484421244666c78` |
| `run_5000ops_8m_RHC_GREEDY_seed1.json` | `7b163f7c545460bb53108d5537d9e1b7d44215395b8eac0da68b2236357caac9` |
| `run_5000ops_8m_RHC_GREEDY_seed42.json` | `cc7df457f4fbf0291e7cabc869de38cfd928e2ed4b9befab7d6be9572ae5a96c` |
| `run_5000ops_8m_RHC_GREEDY_seed999.json` | `67c051ed87a3b78732fa1490beeff240bdc826eabd54add824fad0e58285b8c8` |
| `run_5000ops_8m_RHC_GREEDY_COVER_seed1.json` | `2a8d5c4ab17c593c886f93676f331b5540df59f055091a8520e10b97facf3980` |
| `run_5000ops_8m_RHC_GREEDY_COVER_seed42.json` | `ff3460981f09883cf2ba031013098f82f4f78d2f329fb60a9b6e470add6e449f` |
| `run_5000ops_8m_RHC_GREEDY_COVER_seed999.json` | `5c744685a4e0e31e6eae7ca16000699b46e38658c157cb0bdc5905152f2b4c54` |
| `run_5000ops_8m_RHC_ALNS_SEARCH_COVER_seed1.json` | `00d8c9aec9f3432fa587daa5495d0c8797c87b1c422c5049ced8c18498b1bd1c` |
| `run_5000ops_8m_RHC_ALNS_SEARCH_COVER_seed42.json` | `f6d5a86a713ec65e34df0f3f839032f03689251236241a7e7adf2febc6982968` |
| `run_5000ops_8m_RHC_ALNS_SEARCH_COVER_seed999.json` | `6e3f535589be54971401fc1d81f6c2ecaacdf251b3d1ac7464af7547f0373ed1` |
| `run_3000ops_12m_RHC_GREEDY_seed1.json` | `bfd5a53155b1ea73b297991e58acb78e1ab86fb6221692b0bd993f71942f57f9` |
| `run_3000ops_12m_RHC_GREEDY_seed42.json` | `61bf9db501fa712adb1d962f8dc1af8f6c283599ca490326d52b5da2127b419f` |
| `run_3000ops_12m_RHC_GREEDY_seed999.json` | `34a0f141849dfca61e4943dbeedc5c0d32cd14ba26f01636040d1553a01e8b97` |
| `run_3000ops_4m_GREED_seed1.json` | `4978269481fd0388b97122c45a4eabc41917c254e34f75659ea1817f46265f41` |
| `run_3000ops_4m_RHC_GREEDY_seed1.json` | `f78b669033e3ec8005e5619921b579bfda15652e59f06d2324b30867dbfc062e` |
| `run_3000ops_4m_RHC_GREEDY_seed42.json` | `01d17739fdc29bb0f0c6bae3abf383908c8e6289c4a6400abb54a3586efe9b7a` |
| `run_3000ops_4m_RHC_GREEDY_seed999.json` | `c930c09681036ed407aa883da9fd162739d8d5405c95d978c45dd93496b78b6f` |
| `run_3000ops_8m_RHC_GREEDY_seed1.json` | `3e80173b3c2b234cc249034ad4cb88922d3bf74a6f45e74d2c035e52e33a3bdb` |
| `run_3000ops_8m_RHC_GREEDY_seed42.json` | `3c293464ed6bef3598b179c6dc81197c187daf24868badc70dcfd66c56d91f01` |
| `run_3000ops_8m_RHC_GREEDY_seed999.json` | `4ede6956b7e536534abdc760bdb2109f67af3782dfd63092933f0ab2de52fb12` |
| `run_5000ops_12m_RHC_GREEDY_seed1.json` | `bbc1cbf1573350bbb53c8068ba5d2668458f71134158cf4dc0d34ef5267882ae` |
| `run_5000ops_12m_RHC_GREEDY_seed42.json` | `87f8a6391c123f0d8fe26946953aff1faa7f58115335992303fa58553d23ac7d` |
| `run_5000ops_12m_RHC_GREEDY_seed999.json` | `7b1f0aca4a4bc9da729fe72e908cc04343c1fb301dc5c862ec8a365df262a666` |
| `run_5000ops_4m_RHC_GREEDY_seed1.json` | `335d4359c70531c2b1e93ce208f6a8fca10a13b28ee537be192199948d165f18` |
| `run_5000ops_4m_RHC_GREEDY_seed42.json` | `50f1c5b752f1360cb47a36ccd550d9cec3135b67845f45d6e87766aa4d11318c` |
| `run_5000ops_4m_RHC_GREEDY_seed999.json` | `1b73fb7781451db04bb7cc0c5fc645b9c05826e1e07a6b83a9f861478e8e6c7d` |
| `run_8000ops_12m_RHC_GREEDY_seed1.json` | `9c9418a4789fc41ae58252871478f5a0659e91d52d2d7248431bf976037ffa60` |
| `run_8000ops_12m_RHC_GREEDY_seed42.json` | `96536806925e3ae48980440f861a62eda4d995ee80a921a21344b56f05fcb15f` |
| `run_8000ops_12m_RHC_GREEDY_seed999.json` | `9fd5e828e3b98a6eb3a50c6a24715c221fd7b842c18ea7316817dc5b80340008` |
| `run_8000ops_4m_RHC_GREEDY_seed1.json` | `357aa5c7a4eeaecef171492bca7dd7f27d733c60b97d4a948f8dff0168936b9b` |
| `run_8000ops_4m_RHC_GREEDY_seed42.json` | `142c92b82bcb509a60d015c15a099e9997ee583241c4cea795e950069db83e77` |
| `run_8000ops_4m_RHC_GREEDY_seed999.json` | `6be3ead841554ba8ab00c4f197b415863646a5131b82a381fcfb1164ffb98a1c` |
| `run_8000ops_8m_RHC_GREEDY_seed1.json` | `29b965d86bcc16a57e95f54dd3f8e28a83a95dfa251e242c61bc43eccbf64828` |
| `run_8000ops_8m_RHC_GREEDY_seed42.json` | `3e6e30b7a1719f6e22bbdba7381a120a6b1fb7a250ac4642a6320a37303c3be4` |
| `run_8000ops_8m_RHC_GREEDY_seed999.json` | `e9b80ce63816f6e6f7c50b64311550f160f082ef696f2d724c4f51682144f342` |

**Remainder (explicit):** the `run_3000*`, `run_5000ops_4m_*`, `run_5000ops_12m_*`,
and `run_8000*` rows above are remainder cells (not P2.3).
`run_3000ops_4m_GREED_seed1.json` is the in-process 14.5 min stall.
`sessions/**` is a later capture, not P2.3, and is not in live `SHA256SUMS.txt`.
