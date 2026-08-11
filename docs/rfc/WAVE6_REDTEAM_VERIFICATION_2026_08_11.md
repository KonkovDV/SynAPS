# Wave 6 Red Team verification (2026-08-11)

## Verdict: **pass-with-residuals**

| Claim | Result |
|---|---|
| 6.1 Native skip on overrides | **PASS** |
| 6.2 Energy in ALNS search | **PASS** (`get_energy`, eval/cache/cost) |
| 6.3 MAB destroy×repair | **PASS** after HIGH-1 livelock fix (`charge_pair_reject`) |
| 6.4 SDST pack ≥3 fixtures | **PASS** (toy / fattahi_style_3x3 / medium_4x3) |
| Regressions (energy publish, F7) | **PASS** |

## Fixes applied during audit

| ID | Finding | Fix |
|---|---|---|
| HIGH-1 | MAB UCB1 livelock on failed continues | `charge_pair_reject` on empty destroy / cpsat-fail / repair-fail / feasibility rejects |
| HIGH-2 | Ratchet honesty | Extracted `_sum_machine_transitions`; ceilings updated to measured sizes (not silent green-wash of unrelated growth) |

## Accepted residuals

- Full Shen/dmorill SDST pack still deferred (license)
- `_destroy_worst` still ignores energy weight when scoring removals
- Native ABI still cannot rank true `p_{o,m}` (skip-to-Python is the contract)
- `_solve_core` remains large; further extract of repair is follow-up debt
