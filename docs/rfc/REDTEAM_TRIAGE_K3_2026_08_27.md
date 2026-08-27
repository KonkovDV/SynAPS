# Red Team triage — K3 honesty close (2026-08-27)

Claim level: **honesty**. Not Linux-green. Not a COVER rewrite.
Kernel tree: `k3/honesty-close` on top of `5ef0708`.

## Verdict

**ship with residuals.** Customer FEASIBLE oracle is intact
(`FEASIBLE` ⇒ `proven_hard_violations = ∅`; empty success demoted; incomplete
ALNS is `ERROR` via `MISSING_ASSIGNMENT`). Two P1 honesty holes found on this
pass are closed in code: near-wall `remaining_s < 1` stamped `completed`, and
`synaps recheck` skipping the notary when client `status ≠ FEASIBLE/OPTIMAL`.
Hashed K3.6 recapture JSON is **not** rewritten (it still records the
pre-fix stamp `completed`).

## Closed this pass

| ID | Sev | Finding | Close |
| --- | --- | --- | --- |
| K3-P0 | P0 | customer FEASIBLE + nonempty proven_hard | no hit; ALNS final violations → `ERROR` |
| K3.1 | P2 | README_RU sourced PERF_NUM floor | `verify_claims.py --stats`; test ≥90% (vacuous 1.0 if M=0) |
| K3.2 | P1 | hash-gate allowlist of 3 MD | glob cited `BENCHMARK_EVIDENCE_*.md` except 50K / SEARCH_COVER; rglob `SHA256SUMS.txt` |
| K3.3 | P1 | BEAM `_solve_core` ignored `time_limit_s` | shared deadline across widths 1..B; inner slot + completion-to-go abort |
| K3.4 | P1 | `verified_feasible` self-report | `synaps recheck`; hashed COVER stays `recheckable=false` |
| K3.4b | P1 | recheck coerced missing status to `FEASIBLE` and skipped notary on `error` | probe `status=FEASIBLE` for the checker; missing/invalid client status → `ERROR`; `client_status` in report |
| K3.5 | P1 | stamp line-list | AST: every `BaseSolver.solve` calls `stamp_honest_coverage` |
| K3.6 | P1 | ALNS seed `evaluate_gap` O(n²·m); native completion unbounded | append gap-scan at n≥2000; skip native initial seed and Phase-1 completion at that n; skip SA calibration; IncrementalRepair append scan. Recapture: `benchmark/BENCHMARK_EVIDENCE_ALNS_500_5K8_APPEND_2026_08_27.md` |
| K3-R1 | P1 | D3 `remaining_s < 1` stop stamped `completed` | `_alns_wall_clock_honesty_meta` treats `elapsed + 1s >= time_limit` as `wall_clock` when iters < max. Hashed recapture JSON kept as measured |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_timebox_enforcement.py::test_beam_stops_when_slot_search_is_slow` | BEAM wall 16.4s exceeds 2.2s cap (deadline only at step start; completion-to-go unbounded) |
| `tests/test_alns_append_seed.py::test_alns_enters_search_without_completion_repair_at_append_threshold` | ALNS-500 5k@8 native completion of missing ops; `search_stop_reason=wall_clock_before_search`; hung recapture ~47 min |
| `tests/test_alns_wall_stamp.py::test_alns_wall_stamp_matches_stop_reason` | elapsed 299.2 / limit 300 / iters 317 → `completed` (loop already stopped at `remaining_s < 1`) |
| `tests/test_cli.py::test_cli_recheck_notary_ignores_client_error_status` | client `status=error` skipped `FeasibilityChecker`; `verified_feasible=false` with empty `violation_kinds` |
| `tests/test_architecture.py::test_function_length_ratchet` | `greedy_dispatch.py::_solve_core` 383 > 372; `alns_solver.py::_solve_core` 1569 > 1568 |
| `tests/test_cli.py` TC004 | `Path` used at runtime while imported under `TYPE_CHECKING` |

## Attacks

| Attack | Result |
| --- | --- |
| Incomplete ALNS 5k → FEASIBLE | **blocked** — `MISSING_ASSIGNMENT` → `ERROR`; recapture `verified_feasible=false` |
| Empty FEASIBLE | **blocked** — `stamp_honest_coverage` |
| Native completion of thousands of holes hangs 300s box | **blocked** — skip completion at n≥2000; search starts |
| Cite 0.2598 as COVER / sign coverage | **blocked** — non-claim; different slot rule; not 0.7702 |
| Retune `global_greedy_cover_min_ops` | **blocked** — default 10_000; COVER still list-schedule |
| Rewrite epoch COVER / deadzone / И5.2 ALNS JSON | **blocked** |
| Near-wall `remaining_s < 1` → quote `completed` as full search finish | **blocked in code**; hashed recapture still says `completed` (measured) |
| Forge recheck `status=error` to skip notary | **blocked** — checker runs on assignments |
| Missing/garbage status coerced to FEASIBLE | **blocked** — fail-closed `ERROR` |
| Commit untracked BEAM seed42/999 into hashed `beam-alns-box-2026-08-26/` | **blocked by process** — not added |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** — no new claims |
| In-search native/Python greedy repair with destroy < 2000 | **lands as residual** |
| Stagnation early-stop labeled `completed` | **lands as residual** |
| Warm-start skip `FEASIBLE` with `iterations_completed=0` and no stop reason | **lands as residual** (off unless `warm_start_skip_threshold_gap>0`) |
| One-line `_solve_core` growth | **lands as residual** — at exact slack 1568 |

## Live residuals

| ID | Sev | Finding |
| --- | --- | --- |
| K3-R2 | P2 | In-search greedy/native repair has no deadline; native skip is `len(destroyed) >= 2000`, not `n_ops` |
| K3-R3 | P2 | `no_improve` early-stop still stamps `completed` (no `stagnation` reason) |
| K3-R4 | P2 | Hashed K3.6 JSON omits `iterations_completed`; study `_record` now stores it for **new** runs only |
| K3-R5 | P2 | Untracked `run_3000ops_4m_BEAM_3_night_boxed_seed42.json` / `seed999.json` in a hashed folder; do not add |
| K3-R6 | P3 | `synaps recheck` reads caller paths (local CLI; no jail) |
| K3-R7 | P3 | `_solve_core` / `find_earliest_feasible_slot` / `cli.main` sit at ratchet slack |

## CI Linux run id

**не проверено на Linux.**

## Non-claims

- Not a rewrite of hashed COVER / deadzone / cable / ALNS-500 epoch JSON.
- Not a retune of `global_greedy_cover_min_ops`.
- Not a Yes on 5k@8 (K3.6 recapture is partial `error`; search starts).
- Not Linux-green. KI-N14 Windows local pass is not a Linux `test-slow` close.
