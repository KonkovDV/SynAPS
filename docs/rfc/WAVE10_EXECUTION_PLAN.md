# Wave 10 execution plan — CP-SAT energy + permanent deferral decisions

- **Date:** 2026-08-11
- **Context:** After Wave 9, four items remained deferred. Decisions:

| Item | Decision | Rationale |
|---|---|---|
| **CP-SAT energy term** | **Implement now** | Evaluate/ALNS already honor energy; CP-SAT was the last search hole. Default weight `0` keeps bit-identical makespan hierarchy. |
| **Native ABI `p_{o,m}`** | **Permanent deferral** | Requires Rust duration-matrix ABI; skip-to-Python remains the contract (KI-F16). |
| **dmorill pack** | **Permanent forbid** | GPL-3.0 — never vendor into SynAPS; keep hand fixtures only. |
| **KI-S3 BHK sentinel** | **Keep accepted** | No sound monotone discountable setup LB yet; do not revive cuts. |

## Exit criteria

1. CP-SAT arc terms include scaled `energy_kwh`; weight default 0; non-zero weight breaks makespan ties toward lower energy.
2. KNOWN_ISSUES / RFC updated with permanent decisions.
3. Focused tests green; Red Team 1–10; commit + push.

## Non-goals

- Peak-power / TOU tariffs
- Native duration matrix
- Vendoring GPL instances
- KI-S3 cut revival
