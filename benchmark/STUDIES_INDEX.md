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
