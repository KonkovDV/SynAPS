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
| `earliest_start` / `latest_finish` | ✅ | ✅ | ✅ | ✅ | ✅ | Wave 15 / G11: per-op hard window; `RELEASE_DATE_VIOLATION` / `HORIZON_BOUND_VIOLATION` |
| `WorkCenter.calendar` | ✅ greedy/COVER clip | ❌ silent | ❌ silent | ❌ silent | ❌ silent | KI-N7: empty = 24/7; checker `CALENDAR_VIOLATION`. Exact/ALNS/BEAM do not encode shifts — a family-`FEASIBLE` result can still fail the notary. Native COVER skips. |
| `setup_minutes` | ✅ | ✅ | ✅ | ✅ | ✅ | SDST separation on shared machine |
| `priority` | ✅ | ✅ | ✅ | ✅ | ✅ | ATCS weight / tardiness objective (not in the fast matrix) |
| `material_loss` | ✅ | ✅ | ✅ | ✅ | ✅ | secondary objective term (not in the fast matrix) |
| `energy_kwh` | ✅ | ✅ | ✅ | ✅ | ✅ | evaluate + CP-SAT search term (Wave 10; default weight 0) |
| `planning_horizon_*` | ✅ | ✅ | ✅ | ✅ | ✅ | `HORIZON_BOUND_VIOLATION` in checker |
| `pool_size` / `quantity_needed` | ✅ | ✅ | ✅ | ✅ | ✅ | auxiliary-resource capacity (aux cumulative) |

The fast matrix in the test asserts release/parallel/speed/predecessor/setup/
aux/horizon/material_loss/`machine_duration_overrides`/`earliest_start` across all five
representatives; remaining soft fields (priority, energy optimization) are
exercised by dedicated suites. A solver that cannot honor a field must reject the
instance explicitly rather than silently mis-schedule it (audit M0).
