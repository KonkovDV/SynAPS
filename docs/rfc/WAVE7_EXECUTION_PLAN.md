# Wave 7 execution plan — Wave 6 accepted residuals

- **Date:** 2026-08-11
- **Inputs:** `WAVE6_REDTEAM_VERIFICATION_2026_08_11.md` accepted residuals

## Priority order

| Step | Residual | Goal | Exit criteria |
|---|---|---|---|
| 7.1 | `_destroy_worst` ignores energy | Score removals with setup+material+`energy_weight*energy` | Python path honors weight; native skipped when `energy_weight>0`; unit test |
| 7.2 | Native override skip undocumented | Metadata honesty (Wave 6.1 exit gap) | `native_*_fallback_reason=machine_duration_overrides` when skipped |
| 7.3 | `_solve_core` size debt | Extract repair attempt helper | `_solve_core` ratchet shrinks vs Wave 6 ceiling |
| 7.4 | SDST full pack | License gate only | Document dmorill is **GPL-3.0** — do not vendor into SynAPS; keep hand fixtures |
| 7.5 | Verify + commit | Focused green + changelog | Commit to master |

## Non-goals

- Native ABI for `p_{o,m}` duration matrix
- CP-SAT energy objective term
- Vendoring GPL dmorill instances
