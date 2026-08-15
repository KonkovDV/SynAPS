# K3 wall-clock stamp Red Team — 2026-08-15

Hostile pass on `wall_clock_path_dependent`. Claim level: **honesty**.
Not bitwise identity. Not OPTIMAL. Not a CI error.

External frame: OR-Tools CP-SAT separates `max_deterministic_time` from
wall clock (Google or-tools-discuss; ADR 0001 in this repo). ALNS/RHC have
no deterministic-time analogue: remaining repair budget is `time.monotonic()`
(Wave 15 A15-P2). K2 found the ALNS boolean was **hardcoded True** even when
`search_stop_reason=max_iterations`. K3 makes the boolean match the stop.

## Verdict

**ship with residuals.** ALNS `_alns_wall_clock_honesty_meta` and RHC
metadata now set `wall_clock_path_dependent` iff the stop is a wall cut
(`search_stop_reason` starts with `wall_clock`, including
`wall_clock_before_search`). Early ALNS ERROR returns that exhaust the
budget before search publish the same keys. `determinism_violated` stays
informational (`strict` ∧ wall cut). Pytest does not fail the process
because a run hit the wall.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **K3-P0** | P0 | Boolean always True | Matches `search_stop_reason.startswith("wall_clock")` |
| **K3-P1** | P1 | Pre-search ERROR omitted the stamp | `_initial_generation_error_result` merges the helper |
| **K3-P2** | P1 | No regression that a wall cut sets the flag | `test_alns_zero_budget_stamps_wall_cut` (`time_limit_s=0`) |
| **K3-P3** | P1 | RT15 probe required the constant True | Probe now asserts consistency with the stop reason |

## Attacks that had to land

| Attack | Result |
|--------|--------|
| Stamp True ⇒ bitwise ALNS is forbidden even on max_iterations | **blocked** — K2 greedy fixture is now `wall_clock_path_dependent=False` |
| Stamp False ⇒ remaining repair clamp is wall-free | **lands as residual** — `remaining_s` still clamps in-flight repair |
| Wall cut ⇒ CI error / solver crash | **blocked** — ERROR+stamp, no pytest failure on status |
| RHC still hardcoded True | **blocked** — `bool(time_limit_reached)` |
| Change ALNS-300 default / UCB1 / C5a | **blocked** |
| CP-SAT `determinism_violated` now a CI error | **blocked** — ADR 0001 unchanged |

## Live residuals

| ID | Sev | Finding |
|----|-----|---------|
| **K3-R1** | P2 | Max-iteration ALNS still clamps repair to leftover wall. Not this boolean |
| **S4** | P1 | Delta notary still not shipped |
| **C6-R1-R2** | P1 | Freeze-wave Hamming path-dependence is a different kernel |

## Forbidden claims

Do not add: bitwise-identical ALNS/RHC under a wall timeout, OPTIMAL, SOTA,
“stamp False means deterministic”, INFIMUM, C5a, UCB1 default.

## Next honest step

C-R2 docs. S4 is opt-in, not default. Do not open C5a.
Do not put weights into COVER. Do not flip ALNS to UCB1.
