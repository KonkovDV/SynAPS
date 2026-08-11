# Red Team audit — Waves 1–8 (2026-08-11)

Independent hostile re-verification after Wave 8 closes RT17 residuals.

## Verdict

**pass-with-residuals**

Waves 1–7 algebra/claims reconfirmed. Wave 8 closes RT17-H2 (portfolio F7
oracle), RT17-M2 (full objective attach), and RT17-M5 (non-vacuous energy
ranking test). No CRITICAL reopeners.

## Wave scorecard

| Wave | Theme | Verdict |
|---|---|---|
| 1–4 | Algebra | **PASS** |
| 5 | T-30 / T-35 / T-34 / KI | **PASS** |
| 6 | Native skip / energy search / MAB / SDST | **PASS** |
| 7 | Destroy energy / meta / extract / GPL | **PASS** |
| 8 | F7 proven oracle / attach / energy test | **PASS** |

## Wave 8 checklist

| ID | Claim | Verdict | Evidence |
|---|---|---|---|
| 8.1 | `verified_feasible` uses proven oracle | PASS | `proven_hard_violations`; `test_verify_schedule_result_feasible_when_lane_unproven` |
| 8.2 | Full canonical objective attach | PASS | `model_copy` replace; `test_attach_canonical_objective_replaces_full_vector` |
| 8.3 | Energy weight changes ranking | PASS | `test_objective_cost_prefers_lower_energy_when_weighted` |
| KI-F7 | Registry closed | PASS | `KNOWN_ISSUES.md` |

## Findings this pass

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| — | — | No new CRITICAL/HIGH | — |

## Accepted residuals (carry forward)

- `hard_violations` remains conservative (keeps greedy triggers) by design.
- Native ABI cannot rank true `p_{o,m}`; CP-SAT energy term deferred.
- dmorill GPL-3.0 — do not vendor.
- `_solve_core` still ≫ 80; M0 `machine_duration_overrides` row optional.
- `compute_min_out_assignment_setup_lb` still latent in solvers.
- KI-S3 BHK subset-monotone xfail remains accepted sentinel.
- `test_guard_d3_timebox_within_tolerance` is wall-clock flaky under load (ALNS/CPSAT
  overshoot); not a Wave 8 regression — keep monitoring.

## Evidence

Focused suites green: exact-lane (incl. verify oracle), wave6–8 residuals, energy/pom,
architecture, known-issues registry, weighted_sum boundary. Guards: KI-S3 xfail;
D3 timebox excluded as environment flake this run.
