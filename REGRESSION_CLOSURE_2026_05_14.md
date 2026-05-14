# SynAPS Regression Closure Report — 2026-05-14

## Executive Summary

Focused regression verification on current HEAD (`e4f1298`).
Previous report (2026-05-12) documented 6 pre-existing failures in
`test_alns_rhc_scaling.py`; these **no longer reproduce** on current HEAD.
The main blockers have shifted from functional regressions to
engineering-quality gates (`mypy --strict`, `ruff check/format`).

| Category | Result |
|----------|--------|
| Fast focused unit/property tests | Green |
| RHC/ALNS scaling (`test_alns_rhc_scaling.py`) | **96 passed**, 0 failed |
| Stage C cross-window verification | 3 passed |
| RHC-ALNS E2E (500-op) | 10 passed |
| Native seam parity | 22 passed |
| Control-plane (TS build + tests) | Green |
| **Type checking (`mypy --strict`)** | **Blocked** — see below |
| **Lint (`ruff check`)** | **Blocked** — see below |
| **Format (`ruff format --check`)** | **Blocked** — see below |

## Baseline

| Parameter | Value |
|-----------|-------|
| Working tree | Clean (`git status --short` silent) |
| HEAD | `e4f1298` |
| Commit message | `docs: update tasks.md with Task 24 completion status` |
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

The 6 failures from 2026-05-12 were behavioural assertions tied to RHC
inner-solver semantics that were stabilized between `f985c03` and `e4f1298`.

## Quality-Gate Status — 2026-05-14 (Updated)

| Gate | Status | Evidence |
|------|--------|----------|
| `ruff check synaps tests benchmark` | **GREEN** | `All checks passed!` |
| `ruff format --check synaps tests benchmark` | **GREEN** | `122 files already formatted` |
| `mypy synaps --strict --no-error-summary` | **GREEN** | Exit code 0, no errors |

### Fixes Applied (Mechanical)

- **RHC mypy attr-defined:** Added `__all__` to `_admission.py` and `_state.py`.
- **RHC mypy no-any-return:** Added explicit `set[UUID]` and `int` annotations in
  `_solver.py` plus `UUID` import.
- **E402 (import not at top):** Moved `hypothesis` imports from inline blocks to
  top-level in `test_alns_metadata.py`, `test_benchmark_rhc_50k_study.py`,
  `test_cross_window_telemetry.py`, `test_lower_bounds.py`,
  `test_operator_weight_persistence.py`.
- **E501 (line too long):** Split docstrings / f-strings in
  `test_rhc_warm_start_filter.py`, `test_stage_c_verification.py`,
  `benchmark/study_rhc_alns_geometry_doe.py`.
- **C420/C416 (unnecessary dict comprehension):** Replaced uniform-value
  comprehensions with `dict.fromkeys()` or `dict()` in `alns_solver.py`,
  `lbbd_solver.py`, `rhc/_window.py`, and tests; added `# noqa: C420` for
  mutable-list initializations.
- **I001 (unsorted imports):** Auto-fixed via `ruff --fix`.
- **pyproject.toml:** Added `exclude` for `benchmark/studies/` and
  `benchmark/results/` to `tool.ruff`; aligned `tool.ruff.lint.select`.
- **highspy untyped imports:** Added `# type: ignore[import-untyped]` in
  `lbbd_solver.py` and `lbbd_hd_solver.py`.

### 4. Native Greedy Repair Symbol Gap

`greedy_repair_batch` exists in Rust source (`native/synaps_native/src/lib.rs`)
but is **not exported** by installed wheel `synaps_native 0.3.0`.

Runtime check:
```json
"greedy_repair_batch_backend": "python"
"greedy_repair_batch": false
```

**Action required:** Rebuild and reinstall `synaps_native` from current
`native/synaps_native` source to enable native greedy-repair path.

## Verified Green Rails (Commands for Reproduction)

### ALNS focused
```powershell
python -m pytest tests/test_alns_destroy_operators.py tests/test_alns_metadata.py tests/test_alns_sa_temperature.py tests/test_alns_warm_start.py -q
```
Result: `46 passed` (baseline from prior session).

### RHC budget / policy / admission / warm-start
```powershell
python -m pytest tests/test_rhc_budget_module.py tests/test_rhc_budget_property.py tests/test_rhc_admission_module.py tests/test_rhc_policy.py tests/test_rhc_warm_start_filter.py -q
```
Result: `67 passed` (baseline).

### Lower bounds / LBBD
```powershell
python -m pytest tests/test_lower_bounds.py tests/test_lower_bounds_arc.py tests/test_lbbd_phase2_features.py -q
```
Result: `39 passed` (baseline).

### Stage C cross-window
```powershell
python -m pytest tests/test_stage_c_verification.py -q
```
Result: `3 passed`.

### Full RHC scaling
```powershell
python -m pytest tests/test_alns_rhc_scaling.py -q
```
Result: `96 passed`, 41 deprecation warnings.

### Native parity
```powershell
python -m pytest tests/test_sdst_native_batch.py tests/test_native_destroy_scoring.py tests/test_native_objective_parity.py tests/test_native_stabilize_parity.py -q
```
Result: `22 passed`.

### RHC-ALNS E2E
```powershell
python -m pytest tests/test_e2e_rhc_alns_integration.py -q
```
Result: `10 passed`.

### Control-plane
```powershell
cd control-plane
npm test
npm run build
```
Result: Green.

## Deprecation Warning Noise

`test_alns_rhc_scaling.py` emits 41 warnings:
```
Passing raw kwargs to RhcSolver is deprecated; use RhcPolicy + overrides instead
```

These are **not failures** but technical debt. Migration of test fixtures to
`RhcPolicy + overrides` recommended to reduce noise in regression output.

## Next Steps

| Priority | Action | Owner |
|----------|--------|-------|
| **P0** | Verify `mypy synaps --strict` after RHC mechanical fixes | This session |
| **P0** | Close `ruff check` / `ruff format --check` for `tests/` + `benchmark/` | Next mechanical wave |
| **P1** | Rebuild + reinstall `synaps_native` wheel; verify `greedy_repair_batch` | Build/env |
| **P1** | Fresh 50K multi-seed benchmark evidence | Benchmark lane |
| **P1** | Fresh 100K bounded benchmark evidence | Benchmark lane |
| **P2** | Migrate RHC test fixtures from raw kwargs to `RhcPolicy` | Test hygiene |
| **P2** | Update README claims to match current evidence boundary | Docs |

## Conclusion

The codebase has **crossed from functional-regression red to quality-gate yellow**.
The previously reported 6 RHC failures are closed. The critical path now is
engineering closure: strict type checking, lint/format compliance, native wheel
alignment, and fresh benchmark evidence before any production claims are
strengthened.
