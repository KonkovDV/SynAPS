# SynAPS

Deterministic-first scheduling engine for MO-FJSP-SDST-ARC production planning.

Language: **EN** | [RU](README_RU.md)

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

SynAPS is for teams that need not just a schedule, but an explainable and reproducible schedule.

- Explicit solver portfolio with named configurations
- Machine-readable solver portfolio manifest via CLI (`python -m synaps list-solver-configs`)
- Deterministic routing and auditable metadata
- Independent feasibility validation surface
- Reproducible benchmark harness (including a dedicated 50K study)

## Why This Exists

In many planning stacks, the hardest production question is not "what did we schedule?" but "why this exact decision?".

SynAPS takes a white-box approach:

- known solver config
- known parameters (including seed where applicable)
- known constraints and validation path
- known artifact saved to disk

## Current Reality (April 2026)

What is implemented and verified in this repository:

- 22 public solver configurations in the registry (`available_solver_configs()`)
- Python requirement: `>=3.12` (`pyproject.toml`)
- Core runtime dependencies: `ortools`, `highspy`, `pydantic`, `numpy`
- Stable solve/repair JSON contracts (`synaps/contracts.py`)
- End-to-end contract examples (`schema/contracts/examples/`)
- Dedicated reproducible 50K compare rail plus a staged 500K study harness (`benchmark/study_rhc_50k.py`, `benchmark/study_rhc_500k.py`)
- The staged 500K harness now includes scale-aware ALNS pre-search guard scaling and an optional bounded `max_windows_override` for 100K+ academic runs
- Separate feasibility checker (`synaps/solvers/feasibility_checker.py`)
- ALNS can accept partial warm starts, complete missing assignments, and recompute setups before local search
- ALNS now rejects infeasible full seeds and reanchored warm starts before local search, so final recovery cannot silently fall back to an invalid initial baseline
- RHC can carry unfinished overlap tails into the next ALNS window and exposes warm-start metadata in solver output
- Post-audit RHC hardening adds full-frontier fallback for underfilled admission windows (`admission_full_scan_*` metadata)
- Post-audit RHC hardening also auto-scales ALNS repair budget per window (`alns_effective_repair_time_limit_s` telemetry)
- RHC now treats `time_limit_exhausted_before_search && iterations_completed == 0` on the ALNS lane as an explicit fallback condition (`inner_time_limit_exhausted_before_search`) instead of accepting a zero-search inner result
- RHC now records `budget_guard_skipped_initial_search` when oversized ALNS windows are short-circuited into explicit fallback rather than burning the whole window budget in phase-1 seed generation
- RHC candidate scoring is wired through the NumPy/native batch seam when acceleration is available
- The TypeScript control-plane validates JSON contracts, executes the real Python kernel for solve/repair, and CI bootstraps the Python runtime before `control-plane` integration tests
- Pinned GitHub Actions security workflows cover Python, TypeScript, and Rust surfaces via CodeQL, and publish OSSF Scorecards SARIF results

What is not claimed:

- full industrial validation on a live factory
- guaranteed full feasible 50K solve within the current study timeboxes

## 50K Snapshot (industrial-50k)

Canonical artifacts:

- `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`
- Pre-fix live stress artifact: `benchmark/studies/test-50k-academic-matrix-v1/rhc_50k_study.json`
- Latest post-fix guarded artifact: `benchmark/studies/2026-04-26-rhc-alns-postfix-canonical-v4/rhc_50k_study.json`

Summary from the latest post-fix guarded artifact:

| Solver | Wall time (s) | Feasibility rate | Mean scheduled ratio | Mean makespan (min) | Mean inner fallback ratio |
|---|---:|---:|---:|---:|---:|
| `RHC-ALNS` | 1201.146 | 0.0 | 0.3028 | 9675.18 | 1.0 |

Interpretation:

- This is still a profiling/evidence slice, not a "50K solved" claim.
- The pre-fix stress matrix remains the honest evidence surface for ALNS objective improvement under weak throughput.
- The latest post-fix artifact shows a different regime: oversized ALNS windows are now explicitly short-circuited before expensive phase-1 seed generation can burn the whole window budget.
- On `industrial-50k`, that guard materially improves throughput versus the failing post-fix reruns (`mean_scheduled_ratio` recovered to `0.3028`), but it does so by admitting that the ALNS lane is not entering destroy-repair search on these windows.
- So the current `RHC-ALNS` throughput lane should be read as a guarded fallback controller, not as evidence that large-window ALNS search is already effective at 50K.

Key comparison points:

- Pre-fix `RHC-ALNS|throughput` in `test-50k-academic-matrix-v1` reported `mean_scheduled_ratio = 0.0946`, `mean_makespan_minutes = 4985.85`, and `mean_inner_fallback_ratio = 0.1`.
- Post-fix guarded `RHC-ALNS|throughput` in `2026-04-26-rhc-alns-postfix-canonical-v4` reports `mean_scheduled_ratio = 0.3028`, `mean_makespan_minutes = 9675.18`, and `mean_inner_fallback_ratio = 1.0`.
- Post-fix `RHC-GREEDY|throughput` in `test-50k-after-fix` remains the stronger pure-coverage baseline at `mean_scheduled_ratio = 0.37` with `mean_inner_fallback_ratio = 0.0`.
- The unresolved research problem is now narrower: create a window geometry and routing policy where ALNS can actually enter search within budget, instead of spending the whole budget on phase-1 seed generation or being guarded into fallback.

## 100K+ Snapshot (staged harness)

Current 100K+ status is a staged research surface, not a production-readiness claim.

What is now implemented and verified:

- `benchmark.study_rhc_500k` has a scale ladder (`50k -> 100k -> 200k -> 300k -> 500k`)
- resource projection and gated execution are active
- ALNS pre-search guard parameters are now scaled with problem size in the harness instead of staying frozen at 50K thresholds
- a bounded academic run can be forced with `--max-windows-override` for reproducible 100K+ evidence slices

What the latest audit established:

- `200k` is still within the current public model operation limit
- `300k` and `500k` are presently blocked by `operations_exceed_model_limit`, not by projected RAM pressure
- so the next hard engineering boundary is model/schema capacity, not workstation memory

## Solver Portfolio

Main families:

- Exact / near-exact: CP-SAT, LBBD, LBBD-HD
- Constructive: Greedy ATCS, Beam
- Trade-off slices: epsilon/Pareto CP-SAT profiles
- Large-scale paths: ALNS, RHC with overlap-tail propagation and optional native batch scoring
- Repair: IncrementalRepair
- Validation: FeasibilityChecker

Authoritative registry:

- `synaps/solvers/registry.py`

Routing policy:

- `synaps/solvers/router.py`

## Determinism Notes

Parts of the portfolio are stochastic by design and accept seeds.

For CP-SAT (OR-Tools), be explicit:

- `num_workers > 1` can reduce bit-for-bit repeatability across runs/machines
- for stricter reproducibility, pin `random_seed` and use single-thread mode (`num_workers = 1`)

## Quick Start

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"
```

Run a tiny example:

```bash
python -m synaps solve benchmark/instances/tiny_3x3.json
```

Compare solvers on a benchmark instance:

```bash
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare
```

Export the public solver portfolio for external control-plane/UI integration:

```bash
python -m synaps list-solver-configs
```

Run the dedicated 50K study:

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/_local-rhc-50k
```

Run a bounded 100K ALNS audit slice:

```bash
python -m benchmark.study_rhc_500k \
  --execution-mode gated \
  --scales 100000 \
  --solvers RHC-ALNS \
  --lane throughput \
  --seeds 1 \
  --time-limit-cap-s 90 \
  --max-windows-override 2 \
  --write-dir benchmark/studies/_local-rhc-100k
```

Run tests:

```bash
python -m pytest tests -q
```

Run the strict type check used in CI:

```bash
python -m mypy synaps --strict --no-error-summary
```

Run the TypeScript control-plane boundary tests:

```bash
cd control-plane
npm install
npm test
```

The control-plane package shells out to `python -m synaps`, so keep the repository
Python package installed in the active interpreter first (`python -m pip install -e ".[dev]"`).

## Native Acceleration

SynAPS includes an optional Rust-based acceleration kernel (`synaps_native` v0.3.0) for hot-path scheduling computations via PyO3.

**Profiled target hardware**: Intel 12th–14th Gen (Raptor Lake) hybrid P/E architectures with AVX2+FMA3. AVX-512 is **not** used on this profiled path because it is hardware-disabled on hybrid CPUs.

Implemented optimizations (v0.3.0):

| Optimization | Mechanism | Expected Impact |
|---|---|---|
| **Branchless scoring** | `cmov`/blend instead of branch for overdue boost | 5–15% (eliminates ~50% misprediction rate) |
| **Hybrid-aware parallelism** | Rayon `with_min_len(256)` for P/E core work-stealing | 10–25% (prevents E-core straggler effect) |
| **Zero-copy NumPy + CSR** | Direct buffer writes, no intermediate allocations | 2–3× over Vec path |
| **target-cpu=native** | LLVM AVX2/FMA3 auto-vectorization | 10–40% (depends on loop structure) |
| **fast_exp (Schraudolph)** | IEEE-754 bit trick with residual correction, clamp, and endian guard | Free vs `libm::exp()` while preserving close-score ordering |

The kernel is optional — SynAPS falls back to pure Python when not available.

These optimization notes describe the profiled Raptor Lake workstation, not a universal ISA ceiling for every future SynAPS deployment. On AVX-512-capable non-hybrid servers, a separate runtime-dispatch or wheel-split strategy remains possible in principle; the current repository ships and benchmarks the AVX2/FMA3 path only.

Recent native hardening also covers finite behavior on extreme slack inputs and a regression test for very close positive slack values, so the installed native path keeps candidate pressures strictly ordered where the earlier bucketed approximation could collapse ties.

Build the native extension:

```bash
cd native/synaps_native
maturin develop --release
```

See: [HPC Silicon-Level Optimization Roadmap](docs/architecture/08_HPC_SILICON_OPTIMIZATION_ROADMAP.md)

## Repository Map

- `synaps/solvers/` - solver implementations and registry
- `synaps/model.py` - core Pydantic models
- `synaps/contracts.py` - stable JSON contracts
- `schema/contracts/examples/` - solve/repair example payloads for integration smoke tests
- `synaps/problem_profile.py` - instance profiling
- `synaps/validation.py` - solve-result verification path
- `benchmark/` - benchmark harness and studies
- `control-plane/` - minimal TypeScript BFF over the checked-in solve/repair contracts
- `tests/` - test suite
- `docs/` - architecture, audits, publication drafts

## Read Next

- Habr draft (RU): `docs/habr/synaps-open-source-habr-v3.md`
- Publication pack: `docs/habr/synaps-open-source-habr-v3-pack.md`
- Benchmark guide: `benchmark/README.md`
- Post-audit implementation note: `docs/audit/SYNAPS_UPDATE_AUDIT_2026_04_25.md`
- HPC optimization roadmap: `docs/architecture/08_HPC_SILICON_OPTIMIZATION_ROADMAP.md`
- Reproducibility and robustness protocol: `docs/architecture/06_BENCHMARK_REPRODUCIBILITY_AND_ROBUSTNESS.md`
- Contributing: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`

## Scientific Reporting Standard

### Claim Boundary

This README distinguishes verified repository evidence from future intent.

- Verified claims are tied to executable artifacts, checked-in contracts, benchmark outputs, or CI-visible checks.
- Planned items are explicitly labeled as roadmap work and are not presented as delivered capabilities.
- Performance numbers are context-bound to the referenced artifact and hardware profile, not universal guarantees.

### Reproducibility Baseline

Use this minimal protocol when validating or citing results:

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q
python -m mypy synaps --strict --no-error-summary
python -m synaps list-solver-configs
```

For benchmark claims, publish the exact command line, seed list, solver profile, and resulting JSON artifact path under `benchmark/studies/`.

### Citation and Research Reuse

- Preferred citation metadata: `CITATION.cff`
- If citing benchmark outcomes, include repository URL, commit SHA, artifact path, and execution date.
- When comparing against external methods, report both feasibility and wall-time boundaries to avoid selective reporting.

## Governance

- `SUPPORT.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `MAINTAINERS.md`
- `RELEASE_POLICY.md`
- `CITATION.cff`

## License

MIT. See [LICENSE](LICENSE).
