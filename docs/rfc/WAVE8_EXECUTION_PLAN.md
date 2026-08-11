# Wave 8 execution plan — RT17 residuals

- **Date:** 2026-08-11
- **Inputs:** `WAVES_1_7_REDTEAM_AUDIT_2026_08_11.md` residual backlog

## Priority order

| Step | Residual | Goal | Exit criteria |
|---|---|---|---|
| 8.1 | RT17-H2 F7 portfolio | Customer `verified_feasible` must not false-fail on unproven greedy lane faults | `proven_hard_violations` + `verify_schedule_result` uses it; KI-F7 → closed |
| 8.2 | RT17-M2 attach footgun | Replace field-wise copy with full canonical objective | `_attach_canonical_objective` assigns whole vector |
| 8.3 | RT17-M5 weak energy test | Non-vacuous energy cost preference | Unit test: equal makespan, lower energy wins under weight |
| 8.4 | Verify + Red Team 1–8 + commit | Focused green + audit doc | Push to master |

## Non-goals

- Demoting trigger kinds inside legacy `hard_violations` (kept conservative for BKS/sentinel)
- Native ABI for `p_{o,m}`; CP-SAT energy term; dmorill vendoring
- Full `_solve_core` decomposition
