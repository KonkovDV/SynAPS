# RFC: E-FJSP energy objective (T-35)

- **Status:** Implemented (Wave 5 evaluate + Wave 10 CP-SAT search term)
- **Date:** 2026-08-11
- **Audit:** Red Team v4 / Wave 10

## Current state (Wave 10)

`SetupEntry.energy_kwh` is aggregated by `objective.evaluate` into
`ObjectiveValues.total_energy_kwh` and published through
`BaseSolver._attach_canonical_objective`. Default scalar weight is `energy: 0`.

CP-SAT now includes scaled arc `energy_kwh` terms in the hierarchical objective
(default weight 0 → bit-compatible with pre-Wave-10 makespan hierarchy). Pass
`objective_weights={"energy": N}` (N>0) to optimize energy as a secondary term.

ALNS search already honors energy via `get_energy` / `_objective_cost` (Waves 6–7).
Native ABI still cannot rank true `p_{o,m}` (permanent deferral — Wave 10).

## Literature sketch (2024–2026)

Typical E-FJSP objectives:

| Form | Meaning | SynAPS fit |
|---|---|---|
| Sum energy | `Σ_ops e(o,m) + Σ_setups energy_kwh` | Natural 5th `ObjectiveValues` component |
| Peak power | max instantaneous kW under tariff windows | Needs time-indexed power profile (larger) |
| Cost under TOU tariffs | energy × price(t) | Needs tariff calendar on the problem |

## Acceptance

- [x] `total_energy_kwh` in evaluate + BaseSolver publish
- [x] CP-SAT scaled integer energy term behind F5 overflow guard
- [x] Unit test: non-zero energy weight prefers low-energy transition order
- Peak-power / TOU remain out of scope until a tariff model lands
