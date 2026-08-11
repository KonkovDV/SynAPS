# Wave 7 Red Team verification — 2026-08-11

## Scope

Close Wave 6 accepted residuals per `WAVE7_EXECUTION_PLAN.md`.

## Checklist

| ID | Claim | Verdict | Evidence |
|---|---|---|---|
| 7.1 | `_destroy_worst` includes energy when weighted; native skipped | PASS | Python path adds `energy_weight * get_energy`; native scores only if weight==0; `test_destroy_worst_prefers_high_energy_when_weighted` |
| 7.2 | Native override skip honest in metadata | PASS (after RT17-H1) | Seed: problem-wide reason. Repair: observe-only via skip list + `native_greedy_repair_override_skips` (not pretensioned). |
| 7.3 | `_solve_core` ratchet shrinks | PASS | 1727 → 1681; repair lanes extracted (`_attempt_alns_pair_repair` 65, `_try_cpsat_repair_lane` 61, `_try_greedy_repair_lane` 41) — all ≤80 |
| 7.4 | dmorill GPL gate documented | PASS | `benchmark/instances/public/sdst/README.md` + `KNOWN_ISSUES.md` KI-F16: **do not vendor GPL-3.0** |

## Residual / accepted follow-ups

- Native ABI still cannot rank true `p_{o,m}` (skip-to-Python remains the contract).
- CP-SAT energy objective term still out of scope.
- Further `_solve_core` decomposition still welcome (1681 ≫ 80).

## Tests run

Focused: `tests/test_wave7_residuals.py`, `tests/test_wave6_residuals.py`, `tests/test_architecture.py`.
