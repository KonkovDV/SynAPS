# SynAPS

Deterministic-first scheduling engine for MO-FJSP-SDST-ARC production planning.

Language: **EN** | [RU](README_RU.md)

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

SynAPS is for teams that need not just a schedule, but an explainable and reproducible schedule.

- Explicit solver portfolio with named configurations
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
- Separate feasibility checker (`synaps/solvers/feasibility_checker.py`)

What is not claimed:

- full industrial validation on a live factory
- guaranteed full feasible 50K solve within the current study timeboxes

## 50K Snapshot (industrial-50k)

Canonical artifact:

- `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`

Summary from that artifact:

| Solver | Wall time (s) | Feasibility rate | Assignments |
|---|---:|---:|---:|
| `RHC-GREEDY` | 120.115 | 0.0 | 6,959 / 50,000 |
| `RHC-ALNS` | 366.23 | 0.0 | 1,078 / 50,000 |

Interpretation:

- This is a profiling/evidence slice, not a "50K solved" claim.
- The artifact captures an honest boundary: partial progress with explicit stop reasons.
- Candidate-pool pressure remains the main bottleneck at this stage.

## Solver Portfolio

Main families:

- Exact / near-exact: CP-SAT, LBBD, LBBD-HD
- Constructive: Greedy ATCS, Beam
- Trade-off slices: epsilon/Pareto CP-SAT profiles
- Large-scale paths: ALNS, RHC
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

Run the dedicated 50K study:

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/_local-rhc-50k
```

Run tests:

```bash
python -m pytest tests -q
```

## Repository Map

- `synaps/solvers/` - solver implementations and registry
- `synaps/model.py` - core Pydantic models
- `synaps/contracts.py` - stable JSON contracts
- `synaps/problem_profile.py` - instance profiling
- `synaps/validation.py` - solve-result verification path
- `benchmark/` - benchmark harness and studies
- `tests/` - test suite
- `docs/` - architecture, audits, publication drafts

## Read Next

- Habr draft (RU): `docs/habr/synaps-open-source-habr-v3.md`
- Publication pack: `docs/habr/synaps-open-source-habr-v3-pack.md`
- Benchmark guide: `benchmark/README.md`
- Reproducibility and robustness protocol: `docs/architecture/06_BENCHMARK_REPRODUCIBILITY_AND_ROBUSTNESS.md`
- Contributing: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`

## License

MIT. See [LICENSE](LICENSE).
