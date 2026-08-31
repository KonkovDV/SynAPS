# Red Team triage — RHC stabilize precedence close (2026-08-31)

Claim level: **honesty**. Not a hashed P2.3 Yes. Not a 5k recapture.
Not a retune of `global_greedy_cover_min_ops` or
`_NATIVE_LIST_SCHEDULE_MIN_OPS` (both stay 10_000). Not a packing Yes.
Not a domain pin. KI-N12 stays closed.

Linux `test-slow` on origin `main` after PR #32 failed:
`tests/test_commit_precedence_gate.py::TestGateEliminatesPrecedenceViolations::test_industrial_seed42_zero_precedence_violations`
with three `PRECEDENCE_VIOLATION` after SEARCH_COVER + gate-on
(run [33300807877](https://github.com/KonkovDV/SynAPS/actions/runs/33300807877)).
PR CI skips `test-slow`, so the pin bump PR #33 did not see it.

## Verdict

**ship.** Each temporal-stabilize pass now re-closes order precedence
after machine/aux later-shifts. A resource push of the predecessor
cannot be the last mutation leaving `start < pred_end` on a movable
successor. The industrial seed42 node is green locally (Windows, 21 s).
`FEASIBLE` still requires empty proven hard notary **and** stabilize
`converged`. Residual HORIZON/SETUP/AUX on a short-budget fallback
remains ERROR, not a silent FEASIBLE.

## Closed this pass

| ID | Sev | Finding | Close |
| --- | --- | --- | --- |
| Industrial seed42 gate | P1 | 3 `PRECEDENCE_VIOLATION` on Linux `test-slow` | `_stabilize_one_pass` ends with a second `_shift_later_for_precedence` after machine/aux |
| Last-pass machine push | P2 | Pass cap is order-chain depth; machine ping-pong re-broke precedence after the last pred sweep | closing sweep in the same pass; unit `test_precedence_closed_after_same_pass_machine_push` |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_commit_precedence_gate.py::TestGateEliminatesPrecedenceViolations::test_industrial_seed42_zero_precedence_violations` | Linux: 3 `PRECEDENCE_VIOLATION` (succ start before pred end, different machines, ~Apr 4 afternoon) |
| `tests/test_rhc_window_module.py::TestStabilizeTemporalConsistency::test_precedence_closed_after_same_pass_machine_push` | `max_passes=1`: machine push of pred on M1 left succ on M2 overlapping |

## Attacks

| Attack | Result |
| --- | --- |
| Cite this as a hashed P2.3 / night analog Yes | **blocked** |
| Lower `global_greedy_cover_min_ops` or `_NATIVE_LIST_SCHEDULE_MIN_OPS` | **blocked** — still 10_000 |
| Claim SEARCH_COVER industrial is `FEASIBLE` whenever coverage is 791/791 | **blocked** — notary + `converged`; short-budget fallback still ERROR with other hard kinds |
| Loosen the industrial test to allow 3 violations | **blocked** |
| Skip / xfail the slow node | **blocked** |
| Reopen KI-N12 | **blocked** |
| Rewrite hashed epoch JSON | **blocked** |
| C5a / COVER weights / N-1 / SAIDI / live plant | **blocked** |
| Move sealed window commits | **blocked** — immutable set unchanged; this close is for movable ops (fallback / last window) |

## Residuals (not this commit)

| Residual | Why it stays |
| --- | --- |
| Stabilize `converged=0` under a tight wall | Pass cap is still chain depth; honesty is ERROR |
| Other hard kinds on fallback (HORIZON / SETUP / AUX) | Independent notary; not this test's contract |
| `test-slow` skipped on PRs | GitHub workflow; the node runs on `main` push |
| Sealed window 1–2 commits | Gate must still defer at commit; not unsealed here |

## Non-claims

- Not a Yes on hashed 5k@8, COVER 100k, remainder, or calendar-3000.
- Not a three-seed night analog Yes.
- Not a proof that ALNS inner SEARCH_COVER is OPTIMAL.
- Not a live plant calendar.
