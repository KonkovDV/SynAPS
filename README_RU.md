# SynAPS

Детерминированный движок планирования для **MO-FJSP-SDST-ARC**.

Язык: [EN](README.md) | **RU**

[![CI](https://github.com/KonkovDV/SynAPS/actions/workflows/ci.yml/badge.svg)](https://github.com/KonkovDV/SynAPS/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/KonkovDV/SynAPS/badge)](https://scorecard.dev/viewer/?uri=github.com/KonkovDV/SynAPS)

SynAPS строит **объяснимые и воспроизводимые** расписания: именованные конфигурации солверов, аудируемые метаданные, независимая проверка feasibility и бенчмарк-харнесс.

## Установка

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"
```

Нужен **Python ≥ 3.12**. Опционально: Rust-ускорение [`native/`](native/), HTTP BFF [`control-plane/`](control-plane/).

## Быстрый старт

```bash
python -m synaps solve benchmark/instances/tiny_3x3.json

python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

python -m synaps list-solver-configs
```

Контракты: [`schema/contracts/`](schema/contracts/).

## Портфель солверов

25 конфигураций в [`synaps/solvers/registry.py`](synaps/solvers/registry.py):

| Семейство | Примеры | Назначение |
| --- | --- | --- |
| Constructive | `GREED`, `BEAM-3` | Быстрый feasible baseline |
| Exact / MIP | `CPSAT-*`, `LBBD-*` | Малые/средние задачи |
| Metaheuristic | `ALNS-*` | Качество локальным поиском |
| Horizon | `RHC-GREEDY`, `RHC-ALNS`, `RHC-GREEDY-COVER` | Крупные инстансы (10K–100K+) |

Для **полного покрытия** на крупных инстансах — `RHC-GREEDY-COVER`. `RHC-ALNS` — refine/качество, не гарантия completeness в коротком timebox.

## Что заявлено и что нет

**Есть:** deterministic-first портфель, стабильные solve/repair контракты, feasibility checker, CI, lockfiles + SBOM.

**Не заявлено:** валидация на живом заводе; SOTA; N-1 / SAIDI. `RHC-ALNS` не гарантия completeness в коротком timebox. Покрытие крупных инстансов — путь `RHC-GREEDY-COVER`, не ALNS. Цифры 50K–500K и статус `FEASIBLE` из README не цитировать: только хешированная лестница [`benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md`](benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md). **60k/200k/500k — три сида; 100k@200 — два из трёх** (seed 42 stalled). Эта лестница — широкий горизонт без календаря смен; ночной аналог — другая геометрия ([`benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md`](benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md)). Майский протокол — история: [`benchmark/BENCHMARK_EVIDENCE_50K_2026_05_18.md`](benchmark/BENCHMARK_EVIDENCE_50K_2026_05_18.md) (`SUPERSEDED`).

Протокол evidence: [`benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md`](benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md). История: [`CHANGELOG.md`](CHANGELOG.md).

## Разработка

```bash
ruff check synaps tests benchmark
python -m mypy synaps --strict --no-error-summary
pytest tests/ -q -m "not slow"
```

См. [`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md).

## Документация

| Путь | Содержание |
| --- | --- |
| [`docs/`](docs/) | Архитектура, домены, research |
| [`benchmark/`](benchmark/) | Инстансы, харнесс, evidence |
| [`control-plane/`](control-plane/) | Fastify BFF |

## Лицензия

[MIT](LICENSE)
