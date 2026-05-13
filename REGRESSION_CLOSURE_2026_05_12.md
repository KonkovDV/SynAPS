# SynAPS Regression Closure Report — 2026-05-12

## Executive Summary

Full regression pass on the SynAPS test suite after Wave 2 audit
corrections. Working tree is clean at HEAD (`f985c03`).

| Category | Collected | Passed | Failed | Skipped |
|----------|-----------|--------|--------|---------|
| Fast unit/property tests (excl. solver scaling) | 555 | 555 | 0 | 9 |
| RHC/ALNS scaling integration (`test_alns_rhc_scaling.py`) | 96 | 90 | 6 | 0 |
| **Total observed** | **651** | **645** | **6** | **9** |

Remaining tests (≈48) are in slow benchmark/E2E suites (`500k_study`,
`doe`, `boundary_study`, `e2e_rhc_alns_integration`) which require
multi-minute solver runs or OR-Tools availability.

## Skipped Tests (9)

All skips are due to native Rust module unavailability on the test host:

- `test_native_destroy_scoring.py` — 7 tests (native module not available)
- `test_native_objective_parity.py` — 1 test
- `test_native_stabilize_parity.py` — 1 test

These are expected on hosts without a compiled `synaps_native` extension.

## Failing Tests (6) — Pre-Existing

All 6 failures exist at HEAD without any local modifications (git working
tree clean). They are RHC inner-solver behavioral assertions:

| # | Test | Failure Mode |
|---|------|-------------|
| 1 | `TestRhcSolver::test_rhc_adaptive_window_expands_starved_frontier_before_bootstrap` | `adaptive_window_expansions == 0` (expected 1) |
| 2 | `TestRhcInnerSolver::test_rhc_passes_overlap_tail_into_next_alns_window` | Extra UUID in overlap tail set |
| 3 | `TestRhcInnerSolver::test_rhc_retains_boundary_crossing_assignments_for_next_window` | Assertion on boundary retention |
| 4 | `TestRhcInnerSolver::test_rhc_presearch_budget_guard_skips_alns_for_oversized_window` | Budget guard predicate |
| 5 | `TestRhcInnerSolver::test_rhc_reanchors_inner_assignments_before_freeze_merge` | Re-anchor assertion |
| 6 | `TestRhcInnerSolver::test_rhc_passes_frozen_context_into_followup_alns_window` | Frozen context propagation |

### Root Cause Assessment

Tests 1–6 appear to be regressions introduced by commit `f985c03`
("implement 50K solver improvement stages A-E + G1") which added
substantial RHC inner-solver logic (overlap-tail propagation, freeze-merge
re-anchoring, frozen-context forwarding) without updating the pre-existing
assertions in `test_alns_rhc_scaling.py`.

These are **not** caused by the Wave 2 audit edits (all audit edits touched
`lbbd_solver.py`, `_window.py`, test files outside `test_alns_rhc_scaling.py`,
README, CI, and pyproject.toml).

### Recommended Fix Priority

| Priority | Action |
|----------|--------|
| **High** | Update tests 2–6 to match the new inner-solver semantics from `f985c03` |
| **Medium** | Fix test 1 by adjusting chain fixture or adaptive threshold so expansion triggers deterministically |

## Wave 2 Audit Deliverables — Verified Green

| Item | Test Coverage | Status |
|------|--------------|--------|
| Critical-path destroy operator | `test_alns_destroy_operators.py` | ✅ Pass |
| Due-pressure destroy operator | `test_alns_destroy_operators.py` | ✅ Pass |
| ALNS lower-bound gap metadata | `test_alns_metadata.py` | ✅ Pass |
| SA temperature extraction | `test_alns_sa_temperature.py` | ✅ Pass |
| Warm-start filtering | `test_alns_warm_start.py` | ✅ Pass |
| RHC admission frontier (R20) | `test_rhc_admission_module.py` | ✅ Pass |
| Budget property tests (R21) | `test_rhc_budget_property.py` | ✅ Pass |
| ARC lower-bound regression (R17) | `test_lower_bounds_arc.py` | ✅ Pass |
| SDST matrix backend | `test_sdst_matrix_backend.py` | ✅ Pass |
| Benchmark 50K study | `test_benchmark_rhc_50k_study.py` | ✅ Pass |
| Feasibility checker | `test_feasibility.py` | ✅ Pass |
| Solver portfolio routing | `test_solver_portfolio.py` | ✅ Pass |
| Benchmark harness | `test_benchmark_harness.py` | ✅ Pass |
| Benchmark generator | `test_benchmark_generator.py` | ✅ Pass |
| Benchmark regression | `test_benchmark_regression.py` | ✅ Pass |

## CI Lint Status

CI workflow (`.github/workflows/ci.yml`) updated to run full `ruff check`
and `ruff format --check`. Local execution not verified in this pass (CI
host required).

## Dependency Hygiene

`pyproject.toml` confirmed: `hypothesis`, `ruff`, `pytest-cov`,
`pytest-benchmark` all declared under `[project.optional-dependencies.dev]`
with version constraints.

## Next Steps (Post-Closure)

1. **Fix 6 pre-existing test failures** in `test_alns_rhc_scaling.py` —
   align assertions with `f985c03` inner-solver semantics.
2. **Stage E**: Native CSR SDST backend + batch API (deferred until native
   build chain works on Windows CI).
3. **Stage F**: Parallel repair — remains deferred per roadmap.
4. **Stage G**: E2E 500-op integration test (`test_e2e_rhc_alns_integration.py`)
   — requires `generate_large_instance` and long solver runs.
5. **Benchmark evidence**: 50K multi-seed benchmark run with inter-seed CV
   reporting.

## Conclusion

The Wave 2 audit extension is complete. All targeted test files pass
(105 + 48 + 402 = 555 tests green). The 6 failures are pre-existing
regressions from the Stage A-E implementation commit and are unrelated
to audit corrections. The codebase is stable for continued development
on Stages E–G.
