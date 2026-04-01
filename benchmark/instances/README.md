# Benchmark Instances

Standard problem instances for reproducible Syn-APS solver evaluation.

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

## Adding New Instances

1. Create a valid `ScheduleProblem` JSON (use `model_dump(mode="json")`)
2. Place in this directory with a descriptive name
3. Update the table above
4. Run `python -m benchmark.run_benchmark <file> --solvers GREED` to verify loading
