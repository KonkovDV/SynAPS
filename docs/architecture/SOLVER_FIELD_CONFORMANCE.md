# Solver × Model-Field Conformance Matrix (M0)

Every registry solver must **honor** each model field or **explicitly reject**
an instance that uses it (with a `SolverErrorCategory`) — it must never silently
ignore a field and return a wrong schedule. This document is the human-readable
form of the executable matrix in
[`tests/test_model_field_conformance.py`](../../tests/test_model_field_conformance.py);
keep the two in sync.

Representatives (one per family; RHC/HD/large registry variants reuse these
cores): `GREED`, `BEAM-3`, `CPSAT-10`, `LBBD-5`, `ALNS-300`.

| Model field | GREED | BEAM | CP-SAT | LBBD | ALNS | Guard / notes |
|---|---|---|---|---|---|---|
| `release_date` | ✅ | ✅ | ✅ | ✅ | ✅ | M1: `start >= release_offset`; `RELEASE_DATE_VIOLATION` in checker |
| `max_parallel` | ✅ | ✅ | ✅ | ✅ | ✅ | M2: dispatch lane virtualization; CP-SAT native; LBBD via CP-SAT |
| `speed_factor` | ✅ | ✅ | ✅ | ✅ | ✅ | duration = `base / speed` (when no override) |
| `machine_duration_overrides` | ✅ | ✅ | ✅ | ✅ | ✅ | Wave 9 / T-30: `duration_minutes_for` per WC |
| `predecessor_op_id` | ✅ | ✅ | ✅ | ✅ | ✅ | successor start ≥ predecessor end |
| `setup_minutes` | ✅ | ✅ | ✅ | ✅ | ✅ | SDST separation on shared machine |
| `priority` | ✅ | ✅ | ✅ | ✅ | ✅ | ATCS weight / tardiness objective (not in the fast matrix) |
| `material_loss` | ✅ | ✅ | ✅ | ✅ | ✅ | secondary objective term (not in the fast matrix) |
| `energy_kwh` | ✅ | ✅ | ✅ | ✅ | ✅ | secondary objective term (not in the fast matrix) |
| `planning_horizon_*` | ✅ | ✅ | ✅ | ✅ | ✅ | `HORIZON_BOUND_VIOLATION` in checker |
| `pool_size` / `quantity_needed` | ✅ | ✅ | ✅ | ✅ | ✅ | auxiliary-resource capacity (aux cumulative) |

The fast matrix in the test asserts release/parallel/speed/predecessor/setup/
aux/horizon/material_loss/`machine_duration_overrides` across all five
representatives; remaining soft fields (priority, energy optimization) are
exercised by dedicated suites. A solver that cannot honor a field must reject the
instance explicitly rather than silently mis-schedule it (audit M0).
