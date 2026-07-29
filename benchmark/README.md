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
# Download instances from the original distributions (not vendored here), e.g.
# https://people.idsia.ch/~monaldo/fjsp.html or the OR-Library mirrors,
# then run them directly:
python -m benchmark.run_benchmark path/to/mk01.fjs --solvers GREED CPSAT-30 --compare
```

Mapping caveats (see `benchmark/fjs_loader.py`, `describe_fjs_mapping()`):

1. The format has no SDST and no due dates → instances load as the pure-FJSP
   subset (empty setup matrix, due = horizon end, makespan-only scoring).
2. SynAPS models one duration per operation; heterogeneous per-machine
   durations are mapped to `min` over alternatives with eligibility limited to
   the listed machines. Exact per-pair durations are preserved in
   `operation.domain_attributes["fjs_machine_durations"]`.
3. Because of (2), makespans on instances with heterogeneous alternative
   durations are **not directly comparable** to published per-pair-exact
   results — always report the mapping note alongside numbers.

## Evidence and claims

Published protocol and non-claims: [`BENCHMARK_EVIDENCE_50K_2026_05_18.md`](BENCHMARK_EVIDENCE_50K_2026_05_18.md).

Study index (how to keep local runs): [`STUDIES_INDEX.md`](STUDIES_INDEX.md).

For coverage-complete large solves use portfolio config `RHC-GREEDY-COVER`. Historical ALNS/GREEDY 50K timeboxes remain stress/profiling slices, not a “factory plan at 100%” guarantee.

## Related

- Solver registry: `synaps/solvers/registry.py`
- Root overview: [`../README.md`](../README.md)
