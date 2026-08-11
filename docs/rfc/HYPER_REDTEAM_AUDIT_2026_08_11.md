# Hyper-deep Red Team audit — full codebase (2026-08-11)

Hostile pass after Wave 10 (`825739c`). Live defects remain despite Waves 1–10 green.

## Verdict

**fail-open → Wave 11 fix pack required**

2 CRITICAL + several HIGH defects in IncrementalRepair, F7 oracle demotion scope,
ALNS↔scalarize weight divergence, LBBD KI-S3 applicator landmine, and public-API honesty.

## CRITICAL

| ID | Finding | Fix in Wave 11 |
|---|---|---|
| **C1** | `IncrementalRepair._cpsat_fallback` ignores `frozen_assignments` | Pass frozen + predecessor end offsets into CP-SAT |
| **C2** | IncrementalRepair always returns `FEASIBLE` with partial repair | `INFEASIBLE` when neighbourhood unrepaired |

## HIGH

| ID | Finding | Fix in Wave 11 |
|---|---|---|
| **H1** | `proven_hard_violations` demotes trigger kinds globally | Scope demotion by `work_center_id` |
| **H2** | IncrementalRepair serializes `max_parallel>1` | Explicit refuse or virtualize (refuse first) |
| **H3** | ALNS `_objective_cost` ≠ `scalarize` keys/defaults | Unify on `DEFAULT_WEIGHTS` + `material`/`material_loss` alias |
| **H4** | Advisory `except KeyError` misses `ValueError` from `create_solver` | Catch `ValueError` too |
| **H5** | `SolveOptions` silently clamps `time_limit_s` to 600 | Reject OOB values |

## MEDIUM (Wave 11 if time; else residual)

| ID | Finding |
|---|---|
| M1 | LBBD still *applies* `setup_cost`/`machine_tsp` if injected — remove branch |
| M2 | Benchmark README contradicts T-30 / Brandimarte vendoring |
| M3 | Native exception fallthrough silent |
| M4 | SDST loader drops negative setups silently |

## Non-goals this wave

- Native `p_{o,m}` ABI (permanent deferral)
- dmorill GPL vendoring (forbidden)
- Full RHC `_solver.py` decomposition
- Peak-power / TOU energy
