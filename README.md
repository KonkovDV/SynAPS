# SynAPS

Open-source production scheduling engine for MO-FJSP-SDST-ARC workloads: flexible job-shop scheduling with sequence-dependent setup times and auxiliary-resource constraints.

Language: **EN** | [RU](README_RU.md)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## What It Contains

SynAPS is a deterministic scheduling stack for cases where a plan has to be inspectable, reproducible, and independently validated.

The current repository includes:

- exact and decomposition solvers: `CP-SAT`, `LBBD`, `LBBD-HD`, `Pareto Slice`
- constructive and bounded-repair layers: `Greedy ATCS`, `Beam Search`, `Incremental Repair`
- large-instance search paths: `ALNS` and `RHC`
- a named solver registry with 21 public configurations
- an independent `FeasibilityChecker` that runs after every feasible or optimal solve-path
- optional native acceleration seams in [synaps/accelerators.py](synaps/accelerators.py), with Python fallback

As of April 2026, the public portfolio exposes 12 solver families through 21 named configurations.

## Evidence Boundary

SynAPS targets a real and difficult scheduling class, but the evidence boundary matters more than the headline.

| Surface | Current claim |
|---------|---------------|
| Exact layer | Strongest current evidence is still on small and medium instances. `CP-SAT` and `LBBD` are the exact or near-exact layer with explicit lower-bound or gap semantics. |
| Large-instance layer | `ALNS`, `RHC`, and `LBBD-HD` are the current path for synthetic 5K-50K studies. They target feasibility, runtime, and bottleneck discovery, not proof of optimality. |
| Validation | Every feasible or optimal result is checked by an independent `FeasibilityChecker` covering completeness, eligibility, precedence, machine capacity, setup gaps, auxiliary resources, and horizon bounds. |
| Dedicated 50K path | A reproducible 50K study exists under [benchmark/study_rhc_50k.py](benchmark/study_rhc_50k.py). The current materialized artifact is [benchmark/studies/2026-04-12-rhc-50k/rhc_50k_study.json](benchmark/studies/2026-04-12-rhc-50k/rhc_50k_study.json). |
| Factory deployment | No live-factory deployment claim is made in this repository. |

If you need the documentation router, start from [docs/README.md](docs/README.md). If you need the publication draft, use [docs/habr/synaps-open-source-habr-v3.md](docs/habr/synaps-open-source-habr-v3.md).

## Current 50K Result

The repository now has a stable 50K evidence surface, and the useful part is that it shows the current limit plainly.

The artifact at [benchmark/studies/2026-04-12-rhc-50k/rhc_50k_study.json](benchmark/studies/2026-04-12-rhc-50k/rhc_50k_study.json) records one deterministic `industrial-50k` run for `RHC-GREEDY` and `RHC-ALNS`.

- `RHC-GREEDY` stopped after `120.087s` with `887` committed assignments.
- `RHC-ALNS` stopped after `300.184s` with `944` committed assignments.
- both runs exited with `status=error` and `feasible=false`
- both runs saturated the first window, with peak candidate counts of `49,931` and `49,993`
- both runs skipped global fallback repair after the time budget was exhausted, so the artifact now preserves the real bottleneck instead of hiding it behind an unbounded cleanup pass

That means SynAPS already has a dedicated 50K profiling path, but the current `industrial-50k` preset is not yet a solved full-scale benchmark. The next bottleneck is window admission pressure inside `RHC`, not feasibility checking.

## Solver Portfolio

| Layer | Main members | Role |
|-------|--------------|------|
| Exact | `CPSAT-10`, `CPSAT-30`, `CPSAT-120` | exact solves on small and medium instances |
| Decomposition | `LBBD-5`, `LBBD-10`, `LBBD-5-HD`, `LBBD-10-HD`, `LBBD-20-HD` | exact or near-exact decomposition for larger constrained instances |
| Multi-objective slices | `CPSAT-EPS-SETUP-110`, `CPSAT-EPS-TARD-110`, `CPSAT-EPS-MATERIAL-110` | reproducible epsilon-constraint trade-off runs |
| Constructive | `GREED`, `GREED-K1-3`, `BEAM-3`, `BEAM-5` | latency-first feasible schedules |
| Large-instance search | `ALNS-300`, `ALNS-500`, `ALNS-1000`, `RHC-ALNS`, `RHC-CPSAT`, `RHC-GREEDY` | synthetic large-instance exploration and temporal decomposition |

The authoritative registry lives in [synaps/solvers/registry.py](synaps/solvers/registry.py). The routing policy lives in [synaps/solvers/router.py](synaps/solvers/router.py).

## Quick Start

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
pip install -e ".[dev]"
```

Solve a small public instance:

```bash
python -m synaps solve benchmark/instances/tiny_3x3.json
```

Run a benchmark comparison:

```bash
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-10 --compare
```

Run the dedicated 50K study:

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/2026-04-12-rhc-50k
```

Run the Python test suite:

```bash
python -m pytest tests -q
```

## Repository Map

- [docs/README.md](docs/README.md) - documentation router
- [benchmark/README.md](benchmark/README.md) - reproducible benchmark harness
- [control-plane/README.md](control-plane/README.md) - TypeScript BFF and runtime boundary
- [docs/audit/ACADEMIC_AUDIT_L6_RESPONSE_2026_04_12.md](docs/audit/ACADEMIC_AUDIT_L6_RESPONSE_2026_04_12.md) - claim-by-claim academic verification pass
- [docs/habr/synaps-open-source-habr-v3.md](docs/habr/synaps-open-source-habr-v3.md) - current Habr draft

## Current Status

Implemented:

- deterministic solver portfolio with exact, decomposition, constructive, and large-instance layers
- independent feasibility validation after every feasible or optimal solve-path
- public benchmark harness and deterministic synthetic instance generation
- dedicated 50K study command and materialized artifact surface
- optional native acceleration seams for hot-path scoring and capacity checks

Current bottleneck:

- the first `RHC` window on the current `industrial-50k` preset admits almost the full candidate set, so the 50K path is currently a profiling surface for window-admission pressure rather than a closed industrial solve

Not claimed here:

- live-factory validation
- turnkey ERP or MES integration
- a planner-facing production UI
- a proven feasible full `industrial-50k` schedule under the current public time budgets
- a mandatory compiled core beyond optional hot-path seams

## License

MIT.
