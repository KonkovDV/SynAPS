# ADR-0002: CP-SAT proof logging / VeriPB (T-33)

- **Status:** Proposed (no-go for immediate implementation)
- **Date:** 2026-08-11
- **Audit:** Red Team v4

## Context

SynAPS reports honest lower bounds and `OPTIMAL` statuses from OR-Tools CP-SAT,
but those certificates are not machine-checkable by an external verifier.
Frontier scheduling research (VeriPB / CakePB line; Gocht–Nordström) treats
proof logging as the path to auditable optimality.

## Decision drivers (2026)

| Factor | Assessment |
|---|---|
| OR-Tools proof-log export maturity | Experimental / incomplete for full CP scheduling models with `AddCircuit` + optional intervals; not a stable public API SynAPS can depend on in 9.10–9.15 |
| VeriPB coverage of SynAPS constraint mix | Circuit / cumulative / optional interval proofs are the hard part; research prototypes ≠ production gate |
| Engineering cost | Large (export, normalize, CI verifier job) with limited user demand today |
| Differentiator value | High long-term for regulated APS; low near-term vs correctness Waves 1–2 |

## Decision

**No-go for implementation in the current release train.** Keep:

1. Honest status semantics (F12 / T-24).
2. Bound-validity property tests (S1–S3 lineage).
3. Optional PyJobShop cross-check (T-31) as an independent oracle.

Revisit when OR-Tools ships a documented, version-stable proof artifact for
models using optional intervals + circuit/SDST, or when a regulated customer
requires an external certificate.

## Consequences

- No `proof_path` metadata field yet.
- ADR remains the pointer for future work; do not half-wire a stub exporter.
