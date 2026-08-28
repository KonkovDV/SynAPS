# Red Team triage — residuals KI-N1 / N4 / N10 / N12 / BEAM leftovers (2026-08-27)

Claim level: **honesty**. Not a COVER rewrite. Not a hashed 5k@8 Yes.
Not a native-wheel Yes on the 100k seed 42 session. Required CI Linux COVER
cell ran on [33119219605](https://github.com/KonkovDV/SynAPS/actions/runs/33119219605)
(`native-accelerator`): 60k@100 seed 1, ratio 1.0, native, wall 8.919 s.

## Verdict

**ship with domain-pin follow-up.** Customer FEASIBLE oracle is intact
(`FEASIBLE` ⇒ `proven_hard_violations = ∅`). Unconstrained ALNS-500 at
n>=2000 now seeds from list-schedule COVER. COVER residual fill at large n
uses append scan. Hashed epoch JSON is **not** rewritten.

## Closed this pass

| ID | Sev | Finding | Close |
| --- | --- | --- | --- |
| KI-N1 unconstrained | CRITICAL | ALNS 5k+ never closed all ops | list-schedule seed; session ratio 1.0 on three seeds (`benchmark/BENCHMARK_EVIDENCE_ALNS_500_5K_LIST_SCHEDULE_2026_08_27.md`) |
| KI-N4 hang | HIGH | 100k seed 42 never recaptured | residual append-scan; session 100000/100000 in 40.137 s Python (`benchmark/BENCHMARK_EVIDENCE_COVER_100K_SEED42_2026_08_27.md`); hashed STALL kept |
| KI-N10 job | MEDIUM | COVER ladder absent from PR CI | `native-accelerator` runs 60k@100 seed 1 `--ci-gate` |
| K3-R5 | P2 | BEAM seed42/999 in hashed folder | moved to `sessions/beam-3-night-boxed-leftover-2026-08-26/`; gitignore on hashed names |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_rhc_cover.py::test_residual_greedy_uses_append_scan_when_timeline_is_large` | leftover fill called `find_earliest_feasible_slot` with default `gap_scan=all` against a packed timeline |
| `tests/test_alns_append_seed.py::test_alns_list_schedule_seed_covers_unconstrained_at_append_threshold` | `initial_solver` was greedy; n>=2000 seed incomplete; hashed 5k@8 stayed 0.0 |
| `tests/test_cover_ladder_ci.py::test_ci_gate_rejects_python_backend_and_stall` | no PR job asserted native COVER at a ladder cell |
| `tests/test_evidence_sha256sums.py::test_beam_night_boxed_leftovers_live_outside_hashed_sums` | `run_3000ops_4m_BEAM_3_night_boxed_seed42.json` / `seed999.json` sat in the hashed box directory |

## Attacks

| Attack | Result |
| --- | --- |
| Cite hashed 5k@8 ALNS as ratio 1.0 | **blocked** — epoch JSON untouched; session is a different folder |
| Cite hashed 100k seed 42 as native 13 s Yes | **blocked** — STALL row kept; session is Python 40.137 s |
| Retune `global_greedy_cover_min_ops` | **blocked** — still 10_000 |
| Rewrite hashed COVER / deadzone / И5.2 JSON | **blocked** |
| Add BEAM leftovers to hashed `SHA256SUMS.txt` | **blocked** — moved + gitignore |
| Night analog ALNS completeness | **blocked** — calendar/windows skip list-schedule seed; router stays `CALENDAR_AWARE` |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** |

## Live residuals

| ID | Sev | Finding |
| --- | --- | --- |
| KI-N1 night | CRITICAL | Night analog still not an ALNS Yes |
| Hashed 5k@8 ALNS | CRITICAL | Epoch remains 0.0 / `wall_clock_before_search` |

KI-N12 closed 2026-08-28: GridPlan #7 and MobiRoute #4 merged; origin pins `54ebf9f`.

## CI Linux run id

| Surface | Run | Note |
| --- | --- | --- |
| This drop `native-accelerator` COVER 60k | [33119219605](https://github.com/KonkovDV/SynAPS/actions/runs/33119219605) | 60k@100 seed 1, ratio 1.0, native, wall 8.919 s, RSS 438.7 MB |
| Prior `main` required including `test-slow` | [33103963622](https://github.com/KonkovDV/SynAPS/actions/runs/33103963622) | unchanged this drop |

## Non-claims

- Not a rewrite of hashed COVER / deadzone / cable / ALNS-500 epoch JSON.
- Not a retune of `global_greedy_cover_min_ops`.
- Not a Yes on hashed 5k@8 or hashed COVER 100k seed 42.
- Not native COVER on the 100k seed 42 session.
- Not a hashed 500k re-run. The Linux cell is 60k@100 seed 1 only.
