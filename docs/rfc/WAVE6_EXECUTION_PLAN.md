# Wave 6 execution plan — close Wave 5 Red Team residuals

- **Date:** 2026-08-11
- **Inputs:** KI-F16 residual, `WAVE5_REDTEAM_VERIFICATION_2026_08_11.md` H2/M1–M8

## Priority order

| Step | Residual | Goal | Exit criteria |
|---|---|---|---|
| 6.1 | ALNS native `base/speed` ranking (H2) | Override-aware dispatch | If any disrupted op has `machine_duration_overrides`, skip native greedy and use Python `*_for` path; metadata flag; unit test |
| 6.2 | Energy not in ALNS search (M1) | Search cost sees energy when weight > 0 | `SdstMatrix.get_energy`; `_evaluate_objective` / incremental / `_objective_cost` include energy; test with `energy` weight |
| 6.3 | MAB destroy-only arms (T-34) | Destroy × repair cartesian | `mab_pair_selection` selects `(destroy_i, repair_j)` over `{cpsat,greedy}` (or greedy-only); smoke + ALNS metadata |
| 6.4 | Full SDST pack (F16c) | Expand public slice without license risk | Add 2 hand-authored larger `*.sdstfjs` fixtures + parse smoke; document full Shen/dmorill still deferred pending license |
| 6.5 | Red Team + commit | Hostile re-verify | Verification note; green focused tests; commit |

## Non-goals

- Changing the native extension ABI for a duration matrix (6.1 uses skip-to-Python)
- CP-SAT energy optimization term (still weight/search only in ALNS)
- Vendoring 342 dmorill instances without an explicit license grant
