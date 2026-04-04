# SynAPS Benchmark Harness

Reproducible solver evaluation for the SynAPS scheduling platform.

## Quick Start

```bash
# Single solver, single instance
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED

# Routed portfolio mode (router chooses the concrete solver)
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers AUTO

# Compare two solvers
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

# Compare the default exact profile against an epsilon-constrained Pareto slice
python -m benchmark.run_benchmark benchmark/instances/pareto_setup_tradeoff_4op.json \
  --solvers CPSAT-10 CPSAT-EPS-SETUP-110 --compare

# Multiple runs for statistical confidence
python -m benchmark.run_benchmark benchmark/instances/medium_20x10.json \
  --solvers GREED CPSAT-10 --runs 5 --compare

# All instances in a directory
python -m benchmark.run_benchmark benchmark/instances/ --solvers GREED CPSAT-30
```

## Solver Configurations

| Name | Solver | Parameters |
|------|--------|------------|
| `GREED` | GreedyDispatch | K1=2.0, K2=0.5 |
| `GREED-K1-3` | GreedyDispatch | K1=3.0, K2=0.5 |
| `CPSAT-10` | CpSatSolver | time_limit=10s |
| `CPSAT-30` | CpSatSolver | time_limit=30s |
| `CPSAT-120` | CpSatSolver | time_limit=120s |
| `CPSAT-EPS-SETUP-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise setup under a `1.10x` makespan cap |
| `CPSAT-EPS-TARD-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise tardiness under a `1.10x` makespan cap |
| `LBBD-5` | LbbdSolver | HiGHS master + CP-SAT sub, 5 iterations, capacity + load-balance cuts |
| `LBBD-10` | LbbdSolver | HiGHS master + CP-SAT sub, 10 iterations |
| `AUTO` | Portfolio router | Chooses a concrete solver configuration per instance |

## Academic Portfolio Note

`CPSAT-EPS-SETUP-110` and `CPSAT-EPS-TARD-110` are the public academic epsilon-constraint profiles in the SynAPS portfolio.

They are intentionally not marketed as full Pareto-front explorers. Instead, each exposes one reproducible and benchmarkable Pareto slice:

1. stage 1 finds a strong exact incumbent with the default makespan-first CP-SAT model;
2. stage 2 constrains makespan to within `10%` of that incumbent and minimises the chosen secondary objective (setup or tardiness);
3. inside the slice, the solver tie-breaks on makespan to avoid arbitrary slack.

`LBBD-5` and `LBBD-10` demonstrate Logic-Based Benders Decomposition with HiGHS MIP master and CP-SAT subproblems. The master emits two cut types per iteration:

- **Capacity cuts** (Hooker & Ottosson 2003): tighten the lower bound based on bottleneck machine processing.
- **Load-balance cuts**: enforce `C_max >= total_load / num_machines` as a relaxation-free bound.

This gives a current-proof surface for both multi-objective and decomposition research without overstating capabilities.

## Output Format

### Single Solver

```json
{
  "instance": "tiny_3x3.json",
  "solver_config": "GREED",
  "selected_solver_config": "GREED",
  "results": {
    "status": "feasible",
    "feasible": true,
    "solver_name": "greedy_dispatch",
    "makespan_minutes": 95.0,
    "total_setup_minutes": 18.0,
    "assignments": 6
  },
  "statistics": {
    "runs": 1,
    "wall_time_s_mean": 0.0012
  }
}
```

### Comparison Mode

```json
{
  "instance": "tiny_3x3.json",
  "comparisons": [
    {"solver_config": "GREED", "results": {...}, "statistics": {...}},
    {"solver_config": "CPSAT-30", "results": {...}, "statistics": {...}}
  ]
}
```

## Programmatic API

```python
from pathlib import Path
from benchmark.run_benchmark import load_problem, run_benchmark

problem = load_problem(Path("benchmark/instances/tiny_3x3.json"))
report = run_benchmark(Path("benchmark/instances/tiny_3x3.json"), solver_names=["GREED"], runs=3)
```

## Adding Solvers

Register new configurations in `synaps/solvers/registry.py`:

```python
_SOLVER_REGISTRY["MY-SOLVER"] = SolverRegistration(
  factory=build_my_solver,
  solve_kwargs={"param": value},
  description="short human-readable description",
)
```

The special `AUTO` mode is benchmark-only and routes through `synaps.solve_schedule()`.

## Instances

See [`instances/README.md`](instances/README.md) for the instance format and included files.
