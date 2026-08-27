# Red Team triage — unify `main` / KI-N15 / K3-R (2026-08-27)

Claim level: **honesty**. Not a COVER rewrite. Not ALNS completeness.
Not a Yes on 5k@8. Not Linux-green until a `main` `test-slow` run id exists.

Kernel tree: `unify/main` on top of `e3768a6` (PR #15 merge).

## Verdict

**ship with residuals.** Customer FEASIBLE oracle is intact
(`FEASIBLE` ⇒ `proven_hard_violations = ∅`). ERROR/TIMEOUT with a nonempty
assignment list no longer skips the independent checker (KI-N15), and that
path still cannot become `feasible=True`. GitHub default is a single branch
named `main`. Hashed epoch COVER / deadzone / И5.2 JSON is **not** rewritten.
Untracked BEAM seed42/999 in a hashed folder is **not** added.

## Closed this pass

| ID | Sev | Finding | Close |
| --- | --- | --- | --- |
| KI-N15 | P1 | `verify_schedule_result` skipped the checker unless status was FEASIBLE/OPTIMAL | checker runs when `assignments` nonempty; `feasible=bool(success and not proven_hard_violations)` |
| K3-R3 | P2 | `no_improve` early-stop stamped `completed` | `_alns_wall_clock_honesty_meta(..., no_improve=True)` → `no_improve` |
| K3-R2 (native n_ops) | P2 | in-search native skip was destroy-size only | `max(n_ops, n_destroyed) >= APPEND_GAP_SCAN_MIN_OPS` |
| KI-N3 Linux session | P2 | Linux recapture lived only on conflicted PR #14 | session files + SHA256SUMS under `sessions/n3-linux-2026-08-27/`; epoch JSON untouched; status **algorithmic** |
| Dual default | P1 | Kernel GitHub default `master`; CI listened to `master` | CI/CodeQL/Scorecards/docs → `main` in this commit; GitHub default switch + delete leftover `master` after push |
| UM-RHC | P2 | RHC coverage pace `final_ratio` None on 0 ms Windows finish | `pace_ratio` reports realized coverage when elapsed≤0 after ≥1 window |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_calendar.py::test_verify_error_with_assignments_still_runs_notary` | ERROR + calendar-violating assignment: `independent_violation_kinds=[]` (checker skipped) |
| `tests/test_calendar.py::test_verify_error_with_clean_assignments_is_not_verified_feasible` | ERROR + clean assignment would have been `feasible=True` if skip-on-error were inverted carelessly |
| `tests/test_alns_wall_stamp.py::test_alns_wall_stamp_matches_stop_reason` | iters 40 / max 500 / elapsed 12s / `no_improve=True` stamped `completed` |
| `tests/test_alns_append_seed.py::test_try_native_greedy_repair_skips_when_n_ops_at_append_threshold` | n_ops at threshold, destroy size 1: native `greedy_repair_batch` still callable |
| `tests/test_architecture.py::test_function_length_ratchet` | `_try_native_greedy_repair` 263 with a wrapped `or` (compacted to one `max(...)` line) |
| `tests/test_coverage_pace_guard.py::TestRhcCoveragePaceMetadata::test_enabled_reports_final_ratio` | guard enabled, 4/4 ops, `duration_ms=0` → `coverage_pace_final_ratio is None` (`pace_ratio` treated elapsed≤0 as undefined after windows) |

## Attacks

| Attack | Result |
| --- | --- |
| ERROR + partial assignments → `feasible=True` | **blocked** — `success` still requires FEASIBLE/OPTIMAL |
| ERROR + empty assignments → 500k `MISSING_ASSIGNMENT` rows | **blocked** — empty-assignment skip kept |
| Cite Linux N3 recapture as a rewrite of hashed `worker_error` cells | **blocked** — epoch JSON untouched; KI-N3 taxonomy split |
| Cite N3 ratios as COVER / sign / 0.7702 | **blocked** — remainder recapture, not COVER |
| Retune `global_greedy_cover_min_ops` | **blocked** |
| Rewrite hashed COVER / deadzone / И5.2 / cable JSON | **blocked** |
| Commit untracked BEAM seed42/999 into hashed `beam-alns-box-2026-08-26/` | **blocked by process** |
| Native in-search repair at n≥2000 with small destroy | **blocked** — skip on `n_ops` |
| Stagnation labeled `completed` | **blocked in code** for ALNS stamp helper |
| Zero-duration RHC → `coverage_pace_final_ratio is None` with guard on | **blocked** — realized coverage after ≥1 window |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** — no new claims |
| Python IncrementalRepair in-search at n≥2000 | **lands as residual** |
| Warm-start skip `FEASIBLE` with `iterations_completed=0` and no stop reason | **lands as residual** (off unless `warm_start_skip_threshold_gap>0`) |
| KI-N14 Linux `test-slow` | **lands as residual** until a `main` push run id exists |
| KI-N1 ALNS completeness / KI-N4 seed 42 / KI-N10 Linux COVER / KI-N12 pin bump | **lands as residual** |

## Live residuals

| ID | Sev | Finding |
| --- | --- | --- |
| KI-N1 | CRITICAL | ALNS is not a complete ≥5k solver. K3.6 recapture is partial `error`. |
| KI-N4 | HIGH | COVER 100k@200 seed 42 not recaptured |
| KI-N10 | MEDIUM | Linux COVER ladder not in PR CI |
| KI-N12 | MEDIUM | Domain pins stay until **2026-09-09** |
| KI-N14 | HIGH | Linux `test-slow` on `main` not yet a run id at commit time |
| K3-R2b | P2 | In-search **Python** IncrementalRepair still has no wall deadline at n≥2000 |
| K3-R4 | P2 | Hashed K3.6 JSON omits `iterations_completed` (new runs only) |
| K3-R5 | P2 | Untracked BEAM seed42/999 leftovers; do not add |
| K3-R6 | P3 | `synaps recheck` reads caller paths |
| K3-R7 | P3 | `_solve_core` / slot search / `cli.main` sit at ratchet slack |
| UM-R1 | P2 | First `main` push runs `test-slow`; a red node is a new close, not a silent skip |

## CI Linux run id

| Surface | Run | Note |
| --- | --- | --- |
| PR #15 (K3) required jobs | [33063733144](https://github.com/KonkovDV/SynAPS/actions/runs/33063733144) | lint, typecheck, test-fast 3.12/3.13, benchmark-smoke, control-plane, native-accelerator, CodeQL, wheels. `test-slow` skipped on that PR (`if: push && master` at the time). |
| KI-N3 Linux recapture | [33021109132](https://github.com/KonkovDV/SynAPS/actions/runs/33021109132) | six RHC-GREEDY cells; not `worker_error` |
| This drop `test-slow` on `main` | **не проверено на Linux** | first push to `main` is the evidence; do not pre-claim green |

MobiRoute PR #3 (driver rest) required jobs after merge-commit `017be9d`:
[33099405273](https://github.com/KonkovDV/SynAPS-MobiRoute/actions/runs/33099405273)
(lint, typecheck, test 3.12/3.13, native-accelerator). Merged as
`109de3c` (2026-08-27T17:47:49Z). Default-branch rename in that repo is
a sibling commit, not this kernel tree.

GridPlan GitHub default is already `main`. AeroBIM is already `main`.

## Non-claims

- Not a rewrite of hashed COVER / deadzone / cable / ALNS-500 epoch JSON.
- Not a retune of `global_greedy_cover_min_ops`.
- Not a Yes on 5k@8 or COVER 100k seed 42.
- Not Linux-green for kernel `test-slow` in this commit.
- Not ГОСТ 70314 / 580-FZ (MobiRoute driver rest is policy data).
- Not an AeroBIM change (already `main`).
- Do not claim «всё исправлено».
