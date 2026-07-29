# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `filter_commit_candidates_by_precedence` (`synaps/solvers/rhc/_window.py`) + opt-in `commit_precedence_gate_enabled` (default off; enabled in `SEARCH_COVER`): commit-time temporal precedence gate that defers candidates which would bake cross-window precedence violations into the frozen schedule; deferred ops are re-placed by later windows or residual greedy fill. Eliminates all PRECEDENCE_VIOLATIONs on `industrial` (20→0) and `industrial-2k` (107→0) at full coverage with slightly better makespan. Telemetry (emitted regardless of the flag): `commit_precedence_gate_enabled`, `commit_precedence_deferred_ops_total` (unique ops), per-window `commit_precedence_deferred_ops` (per-event, gate-on only). Tests: `tests/test_commit_precedence_gate.py`.
- `CoveragePaceController` (`synaps/solvers/rhc/_budget.py`): deterministic outer/inner objective alignment for RHC — projects final coverage from the observed per-window commit rate and, when the projection falls below threshold, reroutes the next window to the greedy commit path. Opt-in via `coverage_pace_guard_enabled` (default off; historical behavior unchanged). Telemetry: `coverage_pace_interventions`, `coverage_pace_final_ratio`.
- `RhcPolicy.SEARCH_COVER` preset and `RHC-ALNS-SEARCH-COVER` portfolio config: search-active DOE geometry (360/90, presearch cap 2000) combined with the coverage-pace guard and a 15% residual-fill time reserve, targeting 50K+ search-entry without scheduled_ratio regression.
- `benchmark/fjs_loader.py`: strict parser for the standard `.fjs` public FJSP benchmark format (Brandimarte / Hurink / DAFJS) with documented mapping caveats; `run_benchmark` now accepts `.fjs` files and directories.
- `JsonKnnRuntimeModel` + `RuntimePredictor.load_json()` (`synaps/ml_advisory.py`): torch-free deterministic k-NN solver advisor; `benchmark/train_runtime_advisor.py` trains the JSON artifact from `--compare` benchmark reports with a verified-feasible-only labeling gate (ADR-006).
- Tests: `test_coverage_pace_guard.py`, `test_fjs_loader.py`, `test_ml_advisory_json_model.py` (55 tests incl. reruns of touched suites).
- `benchmark/BENCHMARK_EVIDENCE_SEARCH_COVER_2026_07_29.md`: bounded A/B/C evidence — `SEARCH_COVER` lifts `industrial-2k` coverage 0.386→1.0 and cuts independent violations 11× vs the `BALANCED` baseline; documents a localized pre-existing RHC cross-window precedence boundary and pre-existing native-seed test brittleness (both confirmed on the parent commit).

### Fixed

- Eight native/ortools-9.15-brittle tests in `tests/test_alns_rhc_scaling.py` hardened without masking intent: explicit `native_initial_seed_enabled=False` on Python-seed-lane tests, state-based fake clock instead of a fixed `time.monotonic` mark sequence, deterministic checker-call sequence via `max_iterations=0`, budget-scaling expectations derived from the ALNS window cap, and full-horizon inner-solve contract pinned via `window_bound_inner_horizon=False`. Suite green with native built (96/96) and on the native-disabled CI lane.
- `tests/test_e2e_rhc_alns_integration.py` zero-violation contract (pre-existing failure: 19 cross-window PRECEDENCE_VIOLATIONs on the 500-op fixture, reproduced on HEAD before this change) now holds by enabling the commit-time precedence gate in the E2E solve configuration.
- **P0-1 (correctness):** CP-SAT setup interval no longer welds `end_i` to `start_j`. The setup was modelled as an `IntervalVar` with `start=ends[i]`, `end=starts[j]` — and since a CP-SAT interval enforces `start + size == end`, this forced `start_j == end_i + setup` exactly, forbidding machine idle and right-shifting predecessors along precedence chains. It is now a right-justified window `[start_j - setup, start_j]` with its own start var (`su_start >= end_i` under the arc literal), which still feeds the aux-resource cumulative and matches the FeasibilityChecker setup-window semantics. Verified: a constructed idle-requiring instance returned makespan 150 (`OPTIMAL`) before and 110 after. Impact: CP-SAT (and LBBD subproblems using it) previously overstated makespan on any instance with non-zero setup plus machine idle; affected CP-SAT/LBBD numbers in prior `BENCHMARK_EVIDENCE_*` are superseded. Test: `tests/test_cpsat_setup_interval_regression.py`.
- **P0-2 (correctness):** CP-SAT symmetry breaking no longer cuts the optimum, and its default is now `False`. The old cut grouped machines by `(capability_group, speed_factor)` and imposed `sum(presences_a) >= sum(presences_b)` over operations for which the whole group was eligible — invalid whenever an operation was eligible on A but not B, since the machines are then not interchangeable. Symmetry classes are now strict: identical `capability_group`, `speed_factor`, `max_parallel`, setup-matrix signature, AND identical eligible-operation sets; the capacity ordering applies only within such a class. Verified: a construction with an M1-only operation returned makespan 110 with SB on vs 100 off before, and 100 in both after; a 200-instance property test asserts SB on/off agree. Impact: any prior CP-SAT result run with the default `enable_symmetry_breaking=True` may have been a cut optimum reported as `OPTIMAL`. Test: `tests/test_cpsat_symmetry_regression.py`.

### Changed

- Public GitHub surface hygiene: removed session audits/plans, Habr drafts, study JSON dumps, and debug scripts from the tracked tree; README trimmed to install / quick start / portfolio / claim boundary.
- `.gitignore` no longer blanket-ignores `docs/` or `benchmark/instances/`; local studies/audits stay on disk but unpublished.

### Added

- `RHC-GREEDY-COVER` portfolio config and `RhcPolicy.GREEDY_COVER` preset for coverage-complete constructive solves (time reserve, soft overrun; horizon extension is opt-in, default factor 1.0).
- RHC coverage knobs: `coverage_time_reserve_*`, `fallback_repair_on_timeout`, `fallback_repair_soft_budget_s`, `coverage_horizon_extension_factor`.
- `scripts/probe_coverage_10k.py` for quick industrial-10k coverage probes.
- Python lock files (`requirements-lock.txt`, `requirements-dev-lock.txt`) generated via `uv pip compile`.
- CycloneDX SBOM (`sbom.json`) generation and attestation in release workflow.
- Lock file freshness check in CI `build-distributions` job.
- `BENCHMARK_EVIDENCE_50K_2026_05_18.md` with reproducible protocol, non-claims, and failure taxonomy.
- 50K 3-seed matrix attempt documented (RHC-GREEDY `solver_error`; confirms 50K as stress boundary).
- Tenant ID abstraction in control-plane (`x-tenant-id` header, per-tenant rate limits, cross-tenant job ACL).
- `SYNAPS_CONTROL_PLANE_API_KEY_MAP` (JSON `{apiKey: tenantId}`) so multi-tenant identity is derived from credentials, not spoofable headers.
- Control-plane strips `assignments` on non-`feasible`/`optimal` solve responses and annotates `metadata.coverage_complete`.
- Control-plane admission gate: max ops/WCs/states/setup-cube, solver-class op caps, concurrent sync solve limit (default 2).
- `/metrics` and `/openapi.json` are private without auth unless `SYNAPS_CONTROL_PLANE_PUBLIC_METRICS` / `PUBLIC_OPENAPI` are set.
- `SYNAPS_REQUEST_ID` env var propagation to Python bridge for subprocess traceability.
- CI `benchmark-smoke` job for end-to-end solver validation on tiny instances.
- `installed-wheel-smoke` CI job that builds the wheel, installs it into a fresh venv, and runs `tests/smoke`.
- Smoke tests for installed wheel (`tests/smoke/test_installed_wheel.py`).
- Artifact provenance attestations in release workflow via `actions/attest-build-provenance`.
- Dependabot grouped updates for Python dev/runtime and GitHub Actions ecosystems.
- Dependabot coverage for npm (`control-plane`) and Cargo (`native/synaps_native`).

### Changed

- `industrial-*` instance generator planning horizon is now SDST-aware (`P/m×3 + 2×setup_LB`, floor `P/m×4.5`) so dense changeovers do not clip late ops.
- `benchmark/study_rhc_50k.py` GREEDY lane enables coverage-complete residual-fill knobs.
- Non-loopback control-plane binds refuse `ALLOW_ANONYMOUS`; require `API_KEY` or `API_KEY_MAP`.
- Shared API key ignores spoofable `x-tenant-id` unless `SYNAPS_CONTROL_PLANE_TRUST_TENANT_HEADER=1` or the key is mapped via `API_KEY_MAP`.
- `SYNAPS_PYTHON_EXEC_TIMEOUT_MS=0` is ignored unless `SYNAPS_PYTHON_EXEC_ALLOW_UNLIMITED_TIMEOUT=1` (defaults back to 300s).
- BFF defaults `SYNAPS_RESOURCE_GUARDS_FAIL_OPEN=0`; portfolio fail-closed when `SYNAPS_ENABLE_RESOURCE_GUARDS=1`.
- BFF defaults `SYNAPS_SOLVE_MEMORY_LIMIT_MB=4096` and samples RSS during guarded solves.
- ACL setup interpolation budget lowered to 50k with full `|W|×|S|²` pre-check.
- `SYNAPS_INSTANCE_DIR` refuses repository-root (or parent) mounts.
- All GitHub Actions in `.github/workflows/` pinned to full commit SHAs for supply-chain security.
- README updated with OpenSSF Scorecard badge and supply-chain hardening notes.
- `pyproject.toml` excludes `synaps/scripts` and `tests/fixtures` from ruff/mypy to avoid diagnostic noise on debug scripts.

### Fixed

- RHC no longer abandons residual greedy coverage solely because rolling windows exhausted the global timebox; soft overrun + reserved budget keep leftover ops fillable.
- Coverage reserve is capped at 50% of `time_limit_s` so short budgets cannot starve the window loop.
- RHC inner ALNS/CPSAT subproblems are window-horizon-bounded by default (`window_bound_inner_horizon`) to raise commit yield.
- ALNS Phase-1 seed/completion is hard-capped via `phase1_wall_fraction` (default 0.5); `frozen_initial_repair_max_ops` default raised to 2000 for RHC window sizes.
- Soft overrun is disabled when `SYNAPS_ENABLE_RESOURCE_GUARDS` is active so wall time cannot exceed the advertised solve timeout.
- `verified_feasible` always checks the caller's declared `planning_horizon_end` (solver placement-horizon extension no longer rewrites the contract).
- Async solve job GET requires exact tenant match (`null` only readable without a resolved tenant).
- `Makefile` `native-test` target indentation (was nested inside `native-build` recipe).
- `tests/smoke/__init__.py` invalid syntax.
- Removed accidentally tracked native wheel (`native-dist/synaps_native-0.3.0-cp313-cp313-win_amd64.whl`) from git index.

## [0.1.0] - 2026-05-14

### Added

- Initial public release with 23 solver configurations.
- Deterministic-first solver portfolio: Greedy ATCS, Beam, CP-SAT, LBBD, LBBD-HD, ALNS, RHC variants.
- Reproducible benchmark harness including 50K and 500K study runners.
- Optional Rust/PyO3 native acceleration (`synaps_native` v0.3.0) for ATCS/RHC hot paths.
- TypeScript Fastify control-plane with AJV validation, OpenAPI, and Python subprocess bridge.
- Stable JSON solve/repair contracts with schema examples.
- Feasibility checker independent of solver output.
- Property-based and metamorphic test coverage (Hypothesis).
