# Wave 5 Red Team verification (2026-08-11)

Independent hostile audit of the Wave 5 working tree before commit.

## Verdict

**pass-with-residuals** after fixing critical C1 and high H1/H3/H4/H5.

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| C1 | CRITICAL | `_attach_canonical_objective` dropped `total_energy_kwh` | **Fixed** + solver-boundary test |
| H1 | HIGH | PyJobShop oracle used `base/speed` | **Fixed** → `duration_minutes_for` |
| H3 | HIGH | BKS test docstring still said RELAXATION | **Fixed** |
| H4 | HIGH | CP-SAT symmetry ignored override fingerprint | **Fixed** (sig in class key) |
| H5 | HIGH | Missing CHANGELOG Impact for T-30 | **Fixed** |
| H2 | HIGH | ALNS native ranks on `base/speed` then snaps `*_for` | **Documented** in KI-F16 residual |
| M1–M8 | MED/LOW | ALNS search ignores energy; MAB destroy-only arms; SDST toy only; etc. | Accepted residuals |

## Evidence

- Focused suites green after fixes (`test_energy_and_pom` includes
  `test_solver_boundary_publishes_setup_energy`).
- Brandimarte fast BKS invariants previously green under T-30 equality path.
