# Wave 9 execution plan — honesty / conformance / CI residual pack

- **Date:** 2026-08-11
- **Inputs:** `WAVES_1_8_REDTEAM_AUDIT_2026_08_11.md` accepted residuals

## Priority order

| Step | Residual | Goal | Exit criteria |
|---|---|---|---|
| 9.1 | M0 `machine_duration_overrides` | Conformance matrix row | Builder + assert; SOLVER_FIELD_CONFORMANCE sync |
| 9.2 | GUARD-D3 flake | Harden timebox | Budget accounting + soft cushion ≤1.5×; ALNS skip repair when remaining too low |
| 9.3 | Latent min-out LB | LBBD metadata only | `assignment_setup_lb` in metadata; **no** KI-S3 cuts |
| 9.4 | `_solve_core` size | Extract nested `_reanchor_against_frozen` | Ratchet shrinks |
| 9.5 | RHC energy hygiene | Internal `_evaluate_final` includes energy | `get_energy` summed |
| 9.6 | Verify + audit + ship | Focused green + Red Team 1–9 | Commit + push |

## Non-goals

- Native ABI for `p_{o,m}`
- CP-SAT energy objective term
- Vendoring dmorill (GPL-3.0)
- Revival of KI-S3 discountable cuts
- Large `_solve_core` seed orchestration rewrite
