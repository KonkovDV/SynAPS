# Benchmark Instances

Standard problem instances for reproducible SynAPS solver evaluation.

## Format

Each `.json` file is a serialised `ScheduleProblem` (Pydantic v2):

| Field | Type | Description |
|-------|------|-------------|
| `states` | `State[]` | Product / process states for SDST transitions |
| `orders` | `Order[]` | Production orders with due dates and priorities |
| `work_centers` | `WorkCenter[]` | Machines / processing units |
| `operations` | `Operation[]` | Steps within orders, with eligible work centers |
| `setup_matrix` | `SetupEntry[]` | Sequence-dependent setup times |
| `planning_horizon_start` | `datetime` | Scheduling window start (ISO 8601) |
| `planning_horizon_end` | `datetime` | Scheduling window end (ISO 8601) |

## Included Instances

| File | Orders | Work Centres | Operations | Setup Entries | Complexity |
|------|--------|-------------|------------|---------------|------------|
| `tiny_3x3.json` | 3 | 3 | 6 | 5 | Smoke test |
| `medium_20x10.json` | 20 | 10 | ~60 | 200 | Integration benchmark |
| `pareto_setup_tradeoff_4op.json` | 1 | 2 | 4 | 4 | Objective-tradeoff benchmark |
| `medium_stress_20x4.json` | 8 | 4 | 20 | 15 | Medium stress with aux constraints |

## Adding New Instances

1. Create a valid `ScheduleProblem` JSON (use `model_dump(mode="json")`)
2. Place in this directory with a descriptive name
3. Update the table above
4. Run `python -m benchmark.run_benchmark <file> --solvers GREED` to verify loading

## Recommended Research Comparisons

The `pareto_setup_tradeoff_4op.json` instance exists specifically to compare:

1. `CPSAT-10` — default makespan-first exact profile
2. `CPSAT-EPS-SETUP-110` — near-optimal epsilon-constrained setup-minimising profile

Expected qualitative behavior:

1. the default exact profile should win on makespan;
2. the epsilon profile should reduce setup while keeping makespan within the declared bound;
3. both schedules should remain fully feasible under the deterministic checker.

### Tardiness trade-off comparison

Use the `CPSAT-EPS-TARD-110` profile against `CPSAT-10` on any instance with tight due dates:

```bash
python -m benchmark.run_benchmark benchmark/instances/medium_stress_20x4.json \
  --solvers CPSAT-10 CPSAT-EPS-TARD-110 --compare
```

### LBBD decomposition comparison

The `medium_stress_20x4.json` instance is sized to exercise LBBD convergence:

```bash
python -m benchmark.run_benchmark benchmark/instances/medium_stress_20x4.json \
  --solvers GREED CPSAT-10 LBBD-5 --compare
```

Expected: LBBD should close the gap between GREED and CP-SAT while keeping wall time under the budget.
