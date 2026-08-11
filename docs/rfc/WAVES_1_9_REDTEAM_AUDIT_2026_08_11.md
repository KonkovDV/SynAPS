# Red Team audit — Waves 1–9 (2026-08-11)

Independent hostile verification after Wave 9 residual pack.

## Verdict

**pass-with-residuals**

Wave 9 closes the actionable honesty/conformance/CI residuals from the
Waves 1–8 audit without touching deferred megaprojects (native ABI, CP-SAT
energy term, GPL dmorill).

## Wave scorecard

| Wave | Theme | Verdict |
|---|---|---|
| 1–4 | Algebra | **PASS** |
| 5–8 | T-30/35/34, native/energy/MAB, F7 oracle | **PASS** |
| 9 | M0 p_om, D3, min-out meta, reanchor extract, RHC energy | **PASS** |

## Wave 9 checklist

| ID | Claim | Verdict | Evidence |
|---|---|---|---|
| 9.1 | M0 `machine_duration_overrides` | PASS | `test_model_field_conformance` + SOLVER_FIELD_CONFORMANCE |
| 9.2 | GUARD-D3 harden | PASS | cushion 1.5×; ALNS skips repair when `remaining_s < 1` |
| 9.3 | Min-out LB metadata only | PASS | `assignment_setup_lb` in LBBD/HD; no cuts revived |
| 9.4 | `_solve_core` shrink | PASS | 1681 → 1549 via `_reanchor_against_frozen` extract |
| 9.5 | RHC internal energy | PASS | `_evaluate_final` sums `get_energy` |

## Findings this pass

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| — | — | No new CRITICAL/HIGH | — |

## Accepted residuals (still deferred)

- Native ABI for true `p_{o,m}` ranking
- CP-SAT energy **optimization** term
- dmorill GPL-3.0 — do not vendor
- KI-S3 BHK subset-monotone xfail (accepted sentinel)
- Further `_solve_core` decomposition (1549 ≫ 80)
- `hard_violations` remains conservative vs `proven_hard_violations` by design

## Evidence

Focused: wave6–9 residuals, architecture, exact-lane, energy/pom, weighted_sum,
tsp LB contract, known-issues registry, M0 `machine_duration_overrides` row (5 reps).
