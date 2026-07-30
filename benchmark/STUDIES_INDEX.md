# SynAPS Benchmark Studies

Local study outputs live under `benchmark/studies/` (gitignored).

Published protocol and claim boundary:

- [`BENCHMARK_EVIDENCE_50K_2026_05_18.md`](BENCHMARK_EVIDENCE_50K_2026_05_18.md)

Run harnesses:

```bash
python -m benchmark.study_rhc_50k --help
python -m benchmark.study_rhc_500k --help
python -m benchmark.run_benchmark --help
```

Keep scratch/diagnostic run directories local (`test-*`, `_*`). Do not commit raw study dumps to the public repository.

## Statistical protocol (D5)

Quality studies aggregate repeated measurements via `benchmark/_stats.py`
(`summarize_runs`: best / mean / std / CV / 95% CI + deviation-from-BKS). Run
quality DOE studies with multiple seeds **and** `--repeats > 1` and cite the
confidence interval, never a single point estimate:

```bash
python -m benchmark.study_rhc_alns_doe --seeds 1 2 3 --repeats 5 --bks-makespan <BKS>
python -m benchmark.study_rhc_alns_geometry_doe --seeds 1 2 3 --repeats 5
python -m benchmark.study_solver_scaling --seeds 1 2 3 --runs 5
```

> **Superseded conclusions.** All single-shot DOE conclusions produced by
> `study_rhc_alns_doe.py` and `study_rhc_alns_geometry_doe.py` before the D5
> statistics wiring are point estimates and must be re-verified with
> `--repeats > 1` and the reported confidence interval before being cited.
