# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `RHC-GREEDY-COVER` portfolio config and `RhcPolicy.GREEDY_COVER` preset for coverage-complete constructive solves (time reserve, soft overrun, horizon extension).
- RHC coverage knobs: `coverage_time_reserve_*`, `fallback_repair_on_timeout`, `fallback_repair_soft_budget_s`, `coverage_horizon_extension_factor`.
- `scripts/probe_coverage_10k.py` for quick industrial-10k coverage probes.
- Python lock files (`requirements-lock.txt`, `requirements-dev-lock.txt`) generated via `uv pip compile`.
- CycloneDX SBOM (`sbom.json`) generation and attestation in release workflow.
- Lock file freshness check in CI `build-distributions` job.
- `BENCHMARK_EVIDENCE_50K_2026_05_18.md` with reproducible protocol, non-claims, and failure taxonomy.
- 50K 3-seed matrix attempt documented (RHC-GREEDY `solver_error`; confirms 50K as stress boundary).
- Tenant ID abstraction in control-plane (`x-tenant-id` header, per-tenant rate limits, cross-tenant job ACL).
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
- Feasibility verification honors `effective_planning_horizon_end` when RHC extends placement horizon.
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
- Async solve job GET requires exact tenant match (`null` only readable without `x-tenant-id`).
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
