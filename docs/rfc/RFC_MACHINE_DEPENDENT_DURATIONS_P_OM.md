# RFC: Machine-dependent durations `p_{o,m}` (T-30)

- **Status:** Implemented (Wave 5) — helpers + model field + fjs overrides; full
  conformance matrix row optional follow-up
- **Date:** 2026-08-11
- **Audit:** Red Team v4 / gap vs PyJobShop & classical FJSP

## Motivation

SynAPS today expresses processing time as rank-1 factorization
`p(o,m) = base_duration_min(o) / speed_factor(m)` (canonicalized in
`synaps.timegrain`). Classical FJSP and the `.fjs` public format carry an
arbitrary table `p_{o,m}`. That is the main expressiveness ceiling versus
PyJobShop / OptalCP backends.

## Proposed model

```python
class Operation(...):
    base_duration_min: float
    # Optional per-machine overrides in INTEGER minutes AFTER all factors.
    # Missing key → fall back to timegrain.duration_minutes(base, speed).
    machine_duration_overrides: dict[UUID, int] = Field(default_factory=dict)
```

Physical floor for a `(op, wc)` pair:

- if override present: `float(override)` (already grain-aligned)
- else: `physical_processing_minutes(base, speed)`

Reservation grain:

- if override present: `max(1, override)`
- else: `duration_minutes(base, speed)`

## Touch matrix (migration without silent regression)

| Surface | Change |
|---|---|
| `synaps/timegrain.py` | `duration_minutes_for(op, wc)` / `physical_processing_minutes_for(op, wc)` |
| `synaps/model.py` | field + cross-ref validation (override keys ⊆ eligible ∪ all WC) |
| `benchmark/fjs_loader.py` | map native `p_{o,m}` into overrides (already the natural source) |
| CP-SAT / LBBD / ALNS / GREED / RHC / checker / lower_bounds | call the new helpers; no raw `base/speed` |
| Architecture Rule 1 | forbid raw division; prefer the `*_for(op, wc)` API |
| Benchmarks | `.fjs` loader fills overrides → true `p_{o,m}`; Brandimarte makespans
  become comparable to literature BKS once OPTIMAL is claimed (KI-F16a). Empty
  overrides still fall back to `base/speed`. |

## Non-goals (this RFC)

- Energy / tool changes (T-35)
- Continuous-time (seconds) grid
- Changing DEFAULT_WEIGHTS / sort key

## Acceptance for the design wave

1. This RFC reviewed.
2. Follow-up implementation PR ships helpers + fjs_loader mapping + conformance tests
   (`tests/test_model_field_conformance.py` gains a `machine_duration_overrides` row).
3. CHANGELOG Impact notes any makespan shift on `.fjs` instances.
