# RFC: E-FJSP energy objective (T-35)

- **Status:** Draft (research)
- **Date:** 2026-08-11
- **Audit:** Red Team v4

## Current state

`SetupEntry.energy_kwh` already exists on the model but is **never aggregated**
by `objective.evaluate`, CP-SAT, ALNS, or LBBD — a dead field from the goals'
point of view.

## Literature sketch (2024–2026)

Typical E-FJSP objectives:

| Form | Meaning | SynAPS fit |
|---|---|---|
| Sum energy | `Σ_ops e(o,m) + Σ_setups energy_kwh` | Natural 5th `ObjectiveValues` component |
| Peak power | max instantaneous kW under tariff windows | Needs time-indexed power profile (larger) |
| Cost under TOU tariffs | energy × price(t) | Needs tariff calendar on the problem |

## Proposal

1. Add `total_energy_kwh: float = 0.0` to `ObjectiveValues` (default 0 keeps
   sort-key backward compatible: extend `scalarize` / `DEFAULT_WEIGHTS` with
   `energy: 0`).
2. Aggregate in `evaluate`: sum `SetupEntry.energy_kwh` along the same
   lane-aware transitions used for setup minutes (F3 path) + optional
   per-op consumption if/when `Operation.energy_kwh` is introduced.
3. CP-SAT: scaled integer term behind the same overflow guard as F5.
4. Document that peak-power / TOU are out of scope until a tariff model lands.

## Acceptance

RFC + a follow-up that wires `energy_kwh` through `evaluate` with a unit test
proving a non-zero setup energy appears in `ObjectiveValues.total_energy_kwh`.
