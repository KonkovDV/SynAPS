# SynAPS Regression Closure Report — 2026-05-15 (post-Wave 3b/4)

## Executive Summary

Focused regression verification on current HEAD (post-Wave 3b/4 commit).
All functional regressions from the 2026-05-12 report remain resolved.
Wave 3b (LBBD cut strengthening) and Wave 4 (RHC policy + variable fixing)
changes are verified: **all 350+ tests pass**, type checking and lint remain green.

| Category | Result |
|----------|--------|
| Fast focused unit/property tests | Green |
| RHC/ALNS scaling (`test_alns_rhc_scaling.py`) | **96 passed**, 0 failed |
| Stage C cross-window verification | 3 passed |
| LBBD solver (standard + HD) | **47 passed** (18 + 29) |
| RHC subsystem (admission/budget/policy/window/variable-fix) | **84 passed** |
| RHC-ALNS E2E (500-op) | 10 passed |
| Native seam parity | 22 passed |
| **Type checking (`mypy --strict`)** | **GREEN** |
| **Lint (`ruff check`)** | **GREEN** |
| **Format (`ruff format --check`)** | **GREEN** |

## Baseline

| Parameter | Value |
|-----------|-------|
| Working tree | Clean (`git status --short` silent) |
| HEAD | post-Wave 3b/4 commit |
| Commit message | `feat: comprehensive audit ...` + Wave 3b/4 updates |
| Python | `3.13.7` |
| Native package | `synaps_native 0.3.0` (installed from site-packages) |
| Solver registry | `python -m synaps list-solver-configs` succeeds |

## Resolved Since 2026-05-12

| Previous Failure | Current Status |
|------------------|----------------|
| 6 RHC scaling failures | **No longer reproduce** (`96 passed`) |
| Stage C verification | **Now passing** (operator weight persistence, cross-window bias, telemetry) |
| E2E 500-op integration | **Now passing** (`10 passed`) |
| Native seam parity (SDST/destroy/objective/stabilize) | **Now passing** (`22 passed`) |
| Type checking (`mypy --strict`) | **GREEN** (no errors) |
| Lint (`ruff check`) | **GREEN** (all checks passed) |
| Format (`ruff format --check`) | **GREEN** (formatted) |

The 6 failures from 2026-05-12 were behavioural assertions tied to RHC
inner-solver semantics that were stabilized between `f985c03` and the current HEAD.

## Changes Since 2026-05-14

### Wave 3b — LBBD Cut Strengthening

- `machine_tsp` cut (Bellman-Held-Karp) ported from HD into standard LBBD (`enable_machine_tsp_cuts=True`)
- Cut-pool deduplication via `cut_pool_fingerprint()` (kind + bottleneck_ops + rhs@3dp)
- `ub_evolution` tracking in both `LBBD` and `LBBD-HD`
- `cut_kind_lb_contribution` attribution per iteration
- `_register_cut()` returns `bool` for duplicate detection
- HiGHS warm-start via `setSolution()` using previous master assignment

### Wave 4 — RHC Parameter Surface Reduction

- Named policy presets: `coverage-first`, `balanced`, `search-entry`, `bounded-100k`, `fast-50k`
- Structured spec dataclasses: `AdmissionSpec`, `BudgetSpec`, `GuardSpec`, `InnerSpec`
- `build_solve_kwargs_from_spec()` with dotted-path override support
- `resolve_policy()` with deprecation path for raw kwargs
- Cross-window variable fixing via `detect_cross_window_stable_ops()` (L-RHO pattern)
- Fixed-op IDs passed to ALNS inner solver with per-op stability frequency tracking

## Quality-Gate Status — 2026-05-15 (all GREEN)

| Gate | Status |
|------|--------|
| `ruff check synaps tests benchmark` | ✅ All checks passed |
| `ruff format --check synaps tests benchmark` | ✅ All formatted |
| `mypy synaps --strict --no-error-summary` | ✅ Exit code 0 |
| `pytest tests/ -x -q --tb=line` | ✅ 374 passed (all test suites) |

## Verified Green Rails

```powershell
# Full suite — 374 passed, 0 failed
python -m pytest tests/ -x -q --tb=line

# Sub-test confirmations
python -m pytest tests/test_alns_rhc_scaling.py -q    # 96 passed
python -m pytest tests/test_lbbd_solver.py tests/test_lbbd_hd_solver.py -q  # 47 passed
python -m pytest tests/test_rhc_*.py -q                 # 84+ passed
python -m pytest tests/test_greedy_dispatch_time_limit.py -q  # 2 passed
python -m pytest tests/test_critical_path_extension.py -q     # 5 passed
python -m pytest tests/test_e2e_rhc_alns_integration.py -q    # 10 passed
python -m pytest tests/test_stage_c_verification.py -q         # 25 passed
```

## Open Items

| Priority | Action | Owner |
|----------|--------|-------|
| **P1** | Full 50K benchmark evidence (in progress, ~20 min wall-time) | Benchmark lane |
| **P1** | Rebuild `synaps_native` wheel to enable native `greedy_repair_batch` | Build/env |
| **P1** | Fresh 100K bounded benchmark evidence | Benchmark lane |
| **P2** | Migrate RHC test fixtures from raw kwargs to `RhcPolicy` | Test hygiene |
| **P2** | Update README claims to match current evidence boundary | Docs |
| **P3** | Wave 5: Multi-objective positioning documentation | Docs |

## Conclusion

The codebase has **crossed from functional-regression red to quality-gate green**.
All previously reported failures are closed. All engineering-quality gates
(type checking, lint, format) are green. The remaining work is benchmark
evidence collection and native wheel rebuild — no blocking issues remain.