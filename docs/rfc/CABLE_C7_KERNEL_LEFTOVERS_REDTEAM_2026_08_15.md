# C7 kernel leftovers Red Team — 2026-08-15

Hostile pass on the 11.08 algebra ledger items still labelled Open in
`AI_EXECUTOR_WORK_PLAN_2026_08_15.md`. Claim level: **kernel honesty**.
Not a cable feature. Not SOTA. Not OPTIMAL.

Baptiste / Le Pape / Nuijten *Constraint-Based Scheduling* (discrete
time): EST ceils onto the grain, LFT floors. OR-Tools `SatParameters`
are not a second identity channel for `random_seed` under `strict`
(ADR-0001). Scalarization is one function (`scalarize`); a leftover
CP-SAT big-M `weighted_sum` must not beat an ALNS 0.0 on a tie.

## Verdict

**ship with residuals.** Two ledger rows were already closed in-tree
and must not be re-implemented: F5 `epsilon_primary` overflow
(`tests/test_bigm_overflow_guard.py`) and F9 worker-count deny
(`tests/test_determinism_override_rejected.py`). C7 closes the
remaining holes: ingest EST snap, `random_seed` deny under `strict`,
and `objective_sort_key` / Pareto pick via `scalarize()`.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **C7-P0** | P2 | Ledger said `epsilon_primary` lacked `2^62` | **already F5** — `_objective_product_overflows`; no new code |
| **C7-P1** | P2 | Ledger said `num_workers` via `sat_parameters` under `strict` | **already F9** — workers denied; C7 adds `random_seed` to the same set |
| **C7-P2** | P2 | `sat_parameters={"random_seed": 99}` swapped the solve() seed while metadata claimed `strict` | Denied in `strict`; `fast` still publishes the override |
| **C7-P3** | P3 | Sub-minute `release_date` / `earliest_start` vs checker datetime | Ingest ceils via `snap_schedule_windows_to_minute_grain`; greedy offset ceils; due_date untouched |
| **C7-P4** | P2 | `objective_sort_key` / Pareto used leftover `weighted_sum` | Both call `scalarize()`; inversion test (ALNS 0.0 vs CP-SAT 1e7) |

## Attacks that had to land

| Attack | Result |
|--------|--------|
| Re-ship F5 overflow “to close the ledger” | **blocked** — existing `test_epsilon_primary_overflow_degrades_instead_of_corrupting` |
| `sat_parameters={"random_seed": 42}` matching kwargs is allowed in `strict` | **lands as deny** — seed lives only on `solve(random_seed=)` |
| 90s start stays CLEAN after ingest | **blocked** — checker now sees 2-minute EST |
| Caller `Order.release_date` mutated in place | **blocked** — ingest copies; `problem.orders[0]` is snapped |
| `due_date` at +90s is ceiled (tardiness shift) | **blocked** — EST fields only |
| Sort key with DEFAULT_WEIGHTS changes greedy metric-matrix path | **blocked** — sweep is non-metric only; default scalarize is makespan |
| Flip notary default / open C5a / weights in COVER / UCB1 default | **blocked** |

## Live residuals

| ID | Sev | Finding |
|----|-----|---------|
| **C7-R1** | P3 | `latest_finish` is still not floored at ingest (CP-SAT already floors the offset) |
| **C7-R2** | P3 | `fast` may still override `random_seed` via `sat_parameters` (explicit opt-out) |
| **S4-R1** | P1 | Notary default still exhaustive |
| **C5a** | — | Still gated (C6b occupancy 21 ≪ pool 48) |

## Forbidden claims

Do not add: OPTIMAL, SOTA, INFIMUM, “we replaced the 11.08 audit”,
minute grain implies bitwise CP-SAT/greedy identity, ingest ceil is a
feasibility relaxation, C5a, delta-notary default.

## Next honest step

Standing forbids only. Optional: floor `latest_finish` at ingest
(C7-R1). Do not open C5a. Do not put weights into COVER. Do not flip
the notary default. Do not flip ALNS to UCB1.
