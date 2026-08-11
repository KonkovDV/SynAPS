# Wave 5 execution plan — close open KI + implement Wave 3 RFCs

- **Date:** 2026-08-11
- **Mode:** Red Team continuation after Waves 1–4 (`0568a12`)
- **Authority:** `KNOWN_ISSUES.md`, `docs/rfc/RFC_MACHINE_DEPENDENT_DURATIONS_P_OM.md`,
  `docs/rfc/RFC_E_FJSP_ENERGY_OBJECTIVE.md`, `docs/rfc/DESIGN_ALNS_MAB_OPERATOR_SELECTION.md`,
  `docs/audit/SDST_BENCHMARKS_T31_2026_08_11.md`

## Priority order (correctness → expressiveness → research)

| Step | ID | Goal | Exit criteria |
|---|---|---|---|
| 5.1 | **KI-F7** | Flag greedy lane fallback when it drives an infeasibility claim | Emit `LANE_INFERENCE_UNPROVEN` on size/budget greedy path **iff** that path also records a hard lane/setup/capacity violation; unit test; close KI-F7 | **DONE** |
| 5.2 | **T-30 / p_{o,m}** | First-class machine-dependent durations | `machine_duration_overrides` on `Operation`; `duration_minutes_for` / `physical_processing_minutes_for`; `fjs_loader` fills UUID overrides; solvers/checker use `*_for`; Brandimarte with uniform alts stay bit-identical; conformance row | **DONE** (conformance row optional follow-up) |
| 5.3 | **KI-F16a** | Two-sided OPT on exact `.fjs` | After 5.2, when CP-SAT claims `OPTIMAL` on `BRANDIMARTE_PROVEN_OPTIMAL` stems, assert `makespan == BKS`; update `public_bks` docstring | **DONE** |
| 5.4 | **T-35 / energy** | Stop dead `SetupEntry.energy_kwh` | `ObjectiveValues.total_energy_kwh`; aggregate in `evaluate`; `DEFAULT_WEIGHTS["energy"]=0`; unit test | **DONE** (CP-SAT energy term still deferred) |
| 5.5 | **KI-S3** | Honest residual | Status → `accepted (sentinel)`; fixed-set validity companion for min-out; keep GUARD-S3 xfail on BHK | **DONE** |
| 5.6 | **KI-F16b/c** | SDST pack slice | Tiny vendored SDST fixture + loader; smoke parse test; full Shen pack still deferred | **DONE** (partial; full pack deferred) |
| 5.7 | **T-34 / MAB** | ALNS pair bandit (opt-in) | `mab_pair_selection=False` default; UCB1 over destroy operators; smoke tests | **DONE** (destroy×repair cartesian deferred) |

## Non-goals this wave

- VeriPB / OptalCP production (ADR-0002 / spike notes only)
- Peak-power / TOU energy
- Cross-instance MAB transfer learning
- Closing GUARD-S3 by rewriting BHK (cuts already removed)

## Risk notes

- **p_{o,m}** changes makespan on heterogeneous `.fjs` alternatives — CHANGELOG Impact required.
- Energy field default `0` keeps sort-key / scalarize backward compatible.
- Advisory `LANE_INFERENCE_UNPROVEN` must not false-fail feasible schedules.
