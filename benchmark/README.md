# Syn-APS Benchmark Harness

Reproducible solver evaluation for the Syn-APS scheduling platform.

## Quick Start

```bash
# Single solver, single instance
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED

# Compare two solvers
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

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

## Output Format

### Single Solver

```json
{
  "instance": "tiny_3x3.json",
  "solver_config": "GREED",
  "results": {
    "status": "feasible",
    "feasible": true,
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

Register new configurations in `benchmark/run_benchmark.py`:

```python
_SOLVER_REGISTRY["MY-SOLVER"] = (MySolverClass, {"param": value})
```

## Instances

See [`instances/README.md`](instances/README.md) for the instance format and included files.
