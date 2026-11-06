# SynAPS

Детерминированный движок планирования для **MO-FJSP-SDST-ARC**.

Язык: [EN](README.md) | **RU**

| | |
| --- | --- |
| Ветка GitHub | `main` |

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

Нужен **Python ≥ 3.12**. Опциональное Rust-ускорение лежит в [`native/synaps_native`](native/synaps_native/) и импортируется как `synaps_native`. Релизный workflow вкладывает его в платформенное колесо проекта `synaps`; отдельного проекта на PyPI нет. Linux-колёса собираются в образе manylinux_2_28 на базе `x86-64-v2` (`scripts/check_wheel_isa.py` отвергает VEX/EVEX). Локальная сборка следует `.cargo/config.toml` (`target-cpu=native`). HTTP BFF: [`control-plane/`](control-plane/).

CP-SAT по умолчанию работает в `determinism="strict"`: один поток и останов по детерминированному времени. Контракт: [ADR-0001](docs/adr/0001-strict-determinism-single-thread.md).

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
| Horizon | `RHC-GREEDY`, `RHC-ALNS`, `RHC-ALNS-SEARCH-COVER`, `RHC-GREEDY-COVER` | Крупные инстансы (10K–100K+) |

Для **полного покрытия** на крупных инстансах — `RHC-GREEDY-COVER`. `RHC-ALNS` — refine/качество, не обеспечивает completeness в коротком timebox. `RHC-ALNS-SEARCH-COVER` совмещает поисковую геометрию DOE со сторожем темпа покрытия.

`critical_path` в ALNS снимает плотное множество на реализованном дизъюнктивном графе ([каноническая форма](docs/architecture/02_CANONICAL_FORM.md)): цепь нулевого зазора, затем остальные критические активности, затем сосед по тому же ручью. Этот граф не является цепью минимальных длительностей внутри нижней оценки makespan, и его выбор не измерен как улучшение поиска. `sound_cuts` у LBBD добавляет допустимые строки мастера и выключен, пока флаг не задан. `FEASIBLE` означает `proven_hard_violations = ∅`.

## Что заявлено и что нет

**Есть:** deterministic-first портфель, стабильные solve/repair контракты, feasibility checker, CI, lockfiles + SBOM, опциональное native-расширение внутри колеса `synaps`.

**Не заявлено:** валидация на живом заводе; SOTA; N-1 / SAIDI; отдельный пакет `synaps_native`; `sound_cuts` по умолчанию; более короткий makespan от `critical_path`. `RHC-ALNS` не гарантия completeness в коротком timebox. Покрытие крупных инстансов — путь `RHC-GREEDY-COVER`, не ALNS. Цифры 50K–500K и статус `FEASIBLE` из README не цитировать: только хешированная лестница [`benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md`](benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md). **60k/200k/500k — три сида; хешированный 100k@200 — два из трёх** (seed 42 STALL). Recapture seed 42 на Python COVER (ratio 1.0, 40.137 s): [`benchmark/BENCHMARK_EVIDENCE_COVER_100K_SEED42_2026_08_27.md`](benchmark/BENCHMARK_EVIDENCE_COVER_100K_SEED42_2026_08_27.md). Эта лестница — широкий горизонт без календаря смен; ночной аналог — другая геометрия ([`benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md`](benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md)). Майский протокол — история: [`benchmark/BENCHMARK_EVIDENCE_50K_2026_05_18.md`](benchmark/BENCHMARK_EVIDENCE_50K_2026_05_18.md) (`SUPERSEDED`).

Протокол evidence: [`benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md`](benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md). История: [`CHANGELOG.md`](CHANGELOG.md).

## Разработка

```bash
ruff check synaps tests benchmark
ruff format --check synaps tests benchmark
python -m mypy synaps --strict --no-error-summary
pytest tests/ -q -m "not slow"
```

См. [`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md), [`RELEASE_POLICY.md`](RELEASE_POLICY.md).

## Ссылка

[`CITATION.cff`](CITATION.cff).

## Документация

| Путь | Содержание |
| --- | --- |
| [`docs/`](docs/) | Архитектура, домены, research |
| [`benchmark/`](benchmark/) | Инстансы, харнесс, evidence |
| [`control-plane/`](control-plane/) | Fastify BFF |

## Лицензия

[MIT](LICENSE)
