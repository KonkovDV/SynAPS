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

## Public FJSP benchmarks (.fjs)

The runner accepts the standard `.fjs` text format used by the public FJSP
suites (Brandimarte `mk01`–`mk10`, Hurink `edata`/`rdata`/`vdata`, DAFJS):

```bash
# Vendored Brandimarte slice (mk01–mk10) lives under
# benchmark/instances/public/brandimarte/. Other suites may still be downloaded
# from https://people.idsia.ch/~monaldo/fjsp.html or OR-Library mirrors:
python -m benchmark.run_benchmark benchmark/instances/public/brandimarte/mk01.fjs \
  --solvers GREED CPSAT-30 --compare
```

Mapping caveats (see `benchmark/fjs_loader.py`, `describe_fjs_mapping()`):

1. The format has no SDST and no due dates → instances load as the pure-FJSP
   subset (empty setup matrix, due = horizon end, makespan-only scoring).
2. SynAPS stores per-machine durations in `machine_duration_overrides` (and a
   code-keyed map in `domain_attributes['fjs_machine_durations']`);
   `base_duration_min` is the min alternative as a fallback when overrides are
   empty.
3. With overrides populated, OPTIMAL makespans **are** comparable to published
   per-pair-exact BKS (T-30). Empty overrides retain the historical
   min-alternative relaxation — always report the mapping note alongside numbers.

## Evidence and claims

Published protocol and non-claims: [`BENCHMARK_EVIDENCE_COVER_2026_08_26.md`](BENCHMARK_EVIDENCE_COVER_2026_08_26.md). May 2026 file is historical (`SUPERSEDED`): [`BENCHMARK_EVIDENCE_50K_2026_05_18.md`](BENCHMARK_EVIDENCE_50K_2026_05_18.md).

Cable C6a / C6-R1 (2026-08-26): [`BENCHMARK_EVIDENCE_CABLE_C6_2026_08_26.md`](BENCHMARK_EVIDENCE_CABLE_C6_2026_08_26.md).

5k night-window dead-zone (P2.3 = **no**): [`BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md`](BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md).

SEARCH_COVER + coverage-pace guard + `.fjs` loader evidence (2026-07): [`BENCHMARK_EVIDENCE_SEARCH_COVER_2026_07_29.md`](BENCHMARK_EVIDENCE_SEARCH_COVER_2026_07_29.md).

Study index (how to keep local runs): [`STUDIES_INDEX.md`](STUDIES_INDEX.md).

For coverage-complete large solves use portfolio config `RHC-GREEDY-COVER`. Historical ALNS/GREEDY 50K timeboxes remain stress/profiling slices, not a “factory plan at 100%” guarantee.

## Related

- Solver registry: `synaps/solvers/registry.py`
- Root overview: [`../README.md`](../README.md)
