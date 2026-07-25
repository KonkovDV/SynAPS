# SynAPS Benchmark Harness

Language: **EN** | [RU](README_RU.md)

Reproducible solver evaluation for SynAPS.

## Quick start

```bash
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED

python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

python -m benchmark.generate_instances benchmark/instances/generated_large.json \
  --preset large --seed 7

python -m benchmark.study_rhc_50k --preset industrial-50k --seeds 1 \
  --solvers RHC-GREEDY RHC-GREEDY-COVER \
  --write-dir benchmark/studies/_local-rhc-50k

python -m benchmark.study_rhc_500k --execution-mode gated --scales 100000 \
  --solvers RHC-ALNS --lane throughput --seeds 1 \
  --time-limit-cap-s 90 --max-windows-override 2 \
  --write-dir benchmark/studies/_local-rhc-100k
```

Study outputs under `benchmark/studies/` are **local** (gitignored). Do not commit raw dumps.

## Fixtures

Tracked instances: [`instances/`](instances/) (`tiny_3x3.json`, medium presets, Pareto sample).

## Evidence and claims

Published protocol and non-claims: [`BENCHMARK_EVIDENCE_50K_2026_05_18.md`](BENCHMARK_EVIDENCE_50K_2026_05_18.md).

Study index (how to keep local runs): [`STUDIES_INDEX.md`](STUDIES_INDEX.md).

For coverage-complete large solves use portfolio config `RHC-GREEDY-COVER`. Historical ALNS/GREEDY 50K timeboxes remain stress/profiling slices, not a “factory plan at 100%” guarantee.

## Related

- Solver registry: `synaps/solvers/registry.py`
- Root overview: [`../README.md`](../README.md)
