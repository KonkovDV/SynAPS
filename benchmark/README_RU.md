# Бенчмарк-харнесс SynAPS

Language: [EN](README.md) | **RU**

Воспроизводимая оценка солверов SynAPS.

## Быстрый старт

```bash
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

python -m benchmark.study_rhc_50k --preset industrial-50k --seeds 1 \
  --solvers RHC-GREEDY RHC-GREEDY-COVER \
  --write-dir benchmark/studies/_local-rhc-50k
```

Результаты в `benchmark/studies/` — **локальные** (в git не коммитить).

## Evidence

Протокол и границы claims: [`BENCHMARK_EVIDENCE_50K_2026_05_18.md`](BENCHMARK_EVIDENCE_50K_2026_05_18.md).

Индекс локальных прогонов: [`STUDIES_INDEX.md`](STUDIES_INDEX.md).
