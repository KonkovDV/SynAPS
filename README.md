# SynAPS

Deterministic-first scheduling engine for **MO-FJSP-SDST-ARC** production planning.

Language: **EN** | [RU](README_RU.md)

[![CI](https://github.com/KonkovDV/SynAPS/actions/workflows/ci.yml/badge.svg)](https://github.com/KonkovDV/SynAPS/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Type checked: mypy](https://img.shields.io/badge/type%20checked-mypy-%231D9BF0)](https://mypy-lang.org/)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/KonkovDV/SynAPS/badge)](https://scorecard.dev/viewer/?uri=github.com/KonkovDV/SynAPS)
[![CITATION.cff](https://img.shields.io/badge/cite-CITATION.cff-orange.svg)](CITATION.cff)

SynAPS builds **explainable, reproducible** schedules: named solver configs, auditable metadata, independent feasibility checks, and a benchmark harness.

## Install

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"
```

Requires **Python ≥ 3.12**. Optional Rust acceleration: see [`native/`](native/). HTTP BFF: see [`control-plane/`](control-plane/).

## Quick start

```bash
# Solve a tiny instance
python -m synaps solve benchmark/instances/tiny_3x3.json

# Compare solvers
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

# List the public portfolio
python -m synaps list-solver-configs
```

JSON contracts live under [`schema/contracts/`](schema/contracts/). Examples: [`schema/contracts/examples/`](schema/contracts/examples/).

## Solver portfolio

23 named configs in [`synaps/solvers/registry.py`](synaps/solvers/registry.py), routed by [`synaps/solvers/router.py`](synaps/solvers/router.py):

| Family | Examples | Role |
| --- | --- | --- |
| Constructive | `GREED`, `BEAM-3` | Fast feasible baselines |
| Exact / MIP | `CPSAT-*`, `LBBD-*` | Small–medium exact / decomposed |
| Metaheuristic | `ALNS-*` | Local search quality |
| Horizon | `RHC-GREEDY`, `RHC-ALNS`, `RHC-GREEDY-COVER` | Large instances (10K–100K+ ops) |

For **full coverage** on large instances, prefer `RHC-GREEDY-COVER` (reserved residual fill). `RHC-ALNS` is a refine/quality lane, not a completeness guarantee under short timeboxes.

## What is (and is not) claimed

**Shipped:** deterministic-first portfolio, stable solve/repair contracts, feasibility checker, CI (Python / TypeScript / Rust), lockfiles + SBOM, Scorecard workflows.

**Not claimed:** live-factory validation; full feasible 50K under historical ALNS/GREEDY study timeboxes without the coverage-complete path and adequate wall time.

Scale evidence protocol: [`benchmark/BENCHMARK_EVIDENCE_50K_2026_05_18.md`](benchmark/BENCHMARK_EVIDENCE_50K_2026_05_18.md). History: [`CHANGELOG.md`](CHANGELOG.md).

## Development

```bash
ruff check synaps tests benchmark
python -m mypy synaps --strict --no-error-summary
pytest tests/ -q -m "not slow"

cd control-plane && npm install && npm test
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md), [`RELEASE_POLICY.md`](RELEASE_POLICY.md).

## Documentation

| Path | Contents |
| --- | --- |
| [`docs/`](docs/) | Architecture, domains, research notes |
| [`benchmark/`](benchmark/) | Instances, study harness, evidence |
| [`control-plane/`](control-plane/) | Fastify BFF |
| [`technical/monitoring/`](technical/monitoring/) | Grafana / Prometheus examples |

## Citation

Use [`CITATION.cff`](CITATION.cff).

## License

[MIT](LICENSE)
