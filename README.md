# SynAPS

Deterministic-first scheduling and resource-orchestration engine for planning problems modeled in the MO-FJSP-SDST-ML-ARC family.

Language: **EN** | [RU](README_RU.md)

## Status

SynAPS is a public research and engineering repository.

The repository currently contains a Python scheduling core, canonical schema surfaces, a benchmark harness, and validation tooling. It does **not** yet claim full production deployment, cyber-physical plant integration, or the entire "Aleph" target architecture as implemented software.

### Solver Portfolio (8 components, 4 315 LOC)

| Component | Source | LOC | Algorithm | Quality Guarantee |
|-----------|--------|-----|-----------|-------------------|
| **CP-SAT Exact** | `cpsat_solver.py` | 772 | Circuit + NoOverlap + Cumulative (SDST, ARC) | Proven optimal on small-medium instances |
| **LBBD** | `lbbd_solver.py` | 969 | HiGHS MIP master + CP-SAT subproblems + 4 Benders cut families | Gap-bounded convergence |
| **LBBD-HD** | `lbbd_hd_solver.py` | 1 324 | Parallel subproblems + ARC-aware partitioning + topological post-assembly | Industrial scale (50K+ operations) |
| **Greedy ATCS** | `greedy_dispatch.py` | 296 | Log-space ATCS index (Lee, Bhaskaran & Pinedo 1997) | Feasible schedule in < 1 s |
| **Pareto Slice** | `pareto_slice_solver.py` | 104 | Two-stage ε-constraint (Haimes 1971, Mavrotas 2009) | Pareto-efficient near baseline |
| **Incremental Repair** | `incremental_repair.py` | 318 | Neighbourhood radius + greedy fallback + micro-CP-SAT | < 5% nervousness |
| **Portfolio Router** | `router.py` | 252 | Deterministic regime×size decision tree | Same input → same solver |
| **FeasibilityChecker** | `feasibility_checker.py` | 280 | 7-class independent event-sweep validator | No solver bypasses verification |

Additional surfaces: Graph Partitioning (271 LOC), Solver Registry with 13 profiles (210 LOC), Pydantic data model (333 LOC), TypeScript control-plane BFF (674 LOC). Test suite: 175 tests across 26 modules (5 553 LOC).

### Implemented today

- Exact CP-SAT scheduling paths with sequence-dependent setup handling, auxiliary resources across setup and processing windows, and exact `max_parallel` handling through cumulative constraints or virtual disjunctive lanes when any sequence-dependent transition cost (setup, material loss, or energy) requires lane-level ordering.
- Greedy dispatch with queue-local log-space ATCS scoring, explicit material-loss penalties, and bounded incremental repair heuristics with accurate tardiness and material-loss accounting.
- First-class epsilon-constrained CP-SAT profiles for setup-vs-makespan (`CPSAT-EPS-SETUP-110`), tardiness-vs-makespan (`CPSAT-EPS-TARD-110`), and material-loss-vs-makespan (`CPSAT-EPS-MATERIAL-110`) trade-off studies.
- Logic-Based Benders Decomposition (LBBD) solver with HiGHS master, CP-SAT subproblems, bottleneck capacity cuts, setup-cost cuts, load-balance cuts (Hooker 2007, §7.3), master warm-start support, and post-assembly cross-cluster precedence/setup enforcement.
- Property-based test suite (Hypothesis) validating structural invariants across random problem instances.
- Cross-solver consistency tests ensuring all solvers satisfy the same feasibility, precedence, and objective-sign contracts.
- Benchmark regression tests with pinned quality bounds as CI guardrails.
- Horizon-bound validation in the feasibility checker.
- Pydantic-based canonical data model for the current solver surfaces.
- Reproducible benchmark harness with three instance tiers (tiny, medium, medium-stress) under [benchmark/README.md](benchmark/README.md).
- Repository validation via `pytest`, targeted `ruff` checks, and package build metadata.

### Target blueprint

The longer-form architecture material describes the intended next layers of the system, including:

- event-sourced orchestration and anti-corruption boundaries;
- hardware-aware hot paths such as Rust or PyO3 bridges;
- larger-instance decomposition strategies such as LBBD;
- advisory ML or LLM layers with explicit verification guardrails.

Those items are roadmap and research direction unless they are explicitly backed by current code and benchmarks in this repository.

## Claim Boundaries

Read this repository as an engineering surface first.

- The root repository does not claim that hardware pinning, zero-copy IPC, event sourcing, GNN cuts, or LLM explanation layers are implemented here today.
- Public publication of this repository does not imply production readiness, regulated deployment readiness, or plant-integration certification.
- Partner or diligence materials are supporting context, not the sole technical source of truth.

## Quick Start

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"

# Routed portfolio solve with JSON output
python -m synaps solve benchmark/instances/tiny_3x3.json

# Export the TypeScript ↔ Python runtime contract schemas
python -m synaps write-contract-schemas --output-dir schema/contracts

# Start the minimal TypeScript control-plane BFF
cd control-plane
npm install
npm run dev

pytest tests/ -v
ruff check synaps tests benchmark --select F,E9

python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare
```

To build a distributable package locally:

```bash
python -m build
twine check dist/*
```

## Repository Map

- [docs/README.md](docs/README.md): architecture, domain, evolution, and research navigation.
- [docs/README_RU.md](docs/README_RU.md): Russian router for the technical documentation surfaces.
- [docs/PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md](docs/PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md): manual GitHub setup after the first public push.
- [benchmark/README.md](benchmark/README.md): reproducible solver benchmarking.
- [benchmark/README_RU.md](benchmark/README_RU.md): Russian benchmark guide.
- `python -m synaps solve <instance.json>`: high-level routed solver execution with JSON output.
- [`schema/contracts/`](schema/contracts/README.md): stable JSON request/response contract for future TypeScript control-plane integration.
- [`control-plane/`](control-plane/README.md): minimal TypeScript BFF proving the network-facing control-plane boundary.
- [`control-plane/README_RU.md`](control-plane/README_RU.md): Russian guide for the TypeScript control-plane boundary.
- [CONTRIBUTING.md](CONTRIBUTING.md): contribution workflow and validation expectations.
- [SUPPORT.md](SUPPORT.md): supported public support channels.
- [SECURITY.md](SECURITY.md): vulnerability reporting path.

## Architecture and Research Notes

The repository includes a broader architecture thesis and domain exploration material for readers who want the long-horizon system design:

- [docs/architecture/01_OVERVIEW.md](docs/architecture/01_OVERVIEW.md)
- [docs/architecture/02_CANONICAL_FORM.md](docs/architecture/02_CANONICAL_FORM.md)
- [docs/architecture/03_SOLVER_PORTFOLIO.md](docs/architecture/03_SOLVER_PORTFOLIO.md)
- [research/SYNAPS_OSS_STACK_2026.md](research/SYNAPS_OSS_STACK_2026.md)
- [research/SYNAPS_UNIVERSAL_ARCHITECTURE.md](research/SYNAPS_UNIVERSAL_ARCHITECTURE.md)
- [research/SYNAPS_AIR_GAPPED_OFFLINE.md](research/SYNAPS_AIR_GAPPED_OFFLINE.md)

These documents are useful for understanding direction, but the current implementation boundary is defined by the code, tests, benchmark harness, and packaging surfaces in this repository.

## Roadmap Themes

- Strengthen decomposition and scaling paths beyond the current LBBD baseline (dual-based cut generation, GNN-guided cuts).
- Introduce explicit orchestration boundaries instead of keeping all scheduling state in a single solver-centric layer.
- Extend the epsilon-constrained portfolio with material-loss and multi-objective Pareto front enumeration.
- Add safer publication and supply-chain surfaces for releases, dependency updates, and security scanning.
- Keep research-grade claims bounded by measurable evidence.

## Partner and Diligence Material

An optional diligence packet can live under `docs/partners/`.

That surface is intentionally secondary. The open-source code, tests, benchmark harness, and packaging do not depend on that subtree. Start with the engineering entrypoints above if your primary goal is to understand what the repository implements today.

If you do need the diligence layer, start with [docs/partners/README.md](docs/partners/README.md). That router now points only to the reduced active set and the archive boundary.
