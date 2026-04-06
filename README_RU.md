# SynAPS

Открытый движок планирования и оркестрации ресурсов для задач класса MO-FJSP-SDST-ML-ARC.

Language: [EN](README.md) | **RU**

## Статус

SynAPS сейчас является публичным исследовательским и инженерным репозиторием.

В кодовой базе уже есть Python-ядро расписаний, каноническая схема данных, система бенчмарков и инструменты проверки. При этом репозиторий **не** заявляет, что вся целевая архитектура "Алеф", киберфизическая интеграция или промышленное развёртывание уже реализованы как готовое ПО.

### Что реализовано сегодня

- Точные сценарии CP-SAT с учётом переналадок, зависящих от последовательности, дополнительных ресурсов и точной обработки `max_parallel` через cumulative-ограничения или виртуальные disjunctive lanes там, где это требуется для SDST.
- Жадкий диспетчер с устойчивой логарифмической оценкой приоритета, явным штрафом за потери материала и ограниченным режимом локального ремонта с корректным учётом tardiness и material loss.
- Профили CP-SAT с ограничением по допуску для режимов `setup-vs-makespan` (`CPSAT-EPS-SETUP-110`), `tardiness-vs-makespan` (`CPSAT-EPS-TARD-110`) и `material-loss-vs-makespan` (`CPSAT-EPS-MATERIAL-110`).
- Solver LBBD на базе HiGHS и CP-SAT с отсечениями по узким местам, setup-cost cuts, балансировке нагрузки, master warm-start и межкластерным ограничениям.
- Проверки на случайных данных через Hypothesis.
- Проверки согласованности между solver-режимами.
- Регрессионные benchmark-проверки с фиксированными границами качества.
- Horizon-bound validation в feasibility checker.
- Pydantic-модель текущего канонического формата данных.
- Воспроизводимый набор benchmark-сценариев с тремя уровнями входных данных (`tiny`, `medium`, `medium-stress`) в [benchmark/README.md](benchmark/README.md).
- Репозиторная проверка через `pytest`, `ruff` и сборку пакета.

### Что относится к target blueprint

Длинные архитектурные документы описывают целевое развитие системы, включая:

- событийную оркестрацию и более строгие границы между слоями;
- аппаратно-ориентированные быстрые участки, например мосты на Rust или PyO3;
- decomposition и LBBD для более крупных инстансов;
- вспомогательные ML- или LLM-слои с явными ограничителями.

Если эти элементы не подтверждены текущим кодом и данными из бенчмарков, их нужно читать как план развития, а не как уже поставленную функциональность.

## Границы заявлений

На SynAPS лучше смотреть как на инженерный репозиторий, а не как на маркетинговый манифест.

- Репозиторий не утверждает, что здесь уже реализованы pinning железа, zero-copy IPC, event sourcing, GNN-отсечения или LLM-пояснения.
- Публичная публикация репозитория не означает промышленную готовность, регуляторную готовность или сертифицированную интеграцию с заводским контуром.
- Инвесторские материалы являются вспомогательным контекстом, а не единственным техническим источником правды.

## Быстрый старт

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"

# Запуск расчёта через portfolio API с JSON-ответом
python -m synaps solve benchmark/instances/tiny_3x3.json

# Сгенерировать схемы контрактов для внешнего TypeScript-слоя
python -m synaps write-contract-schemas --output-dir schema/contracts

# Запустить минимальный TypeScript-шлюз
cd control-plane
npm install
npm run dev

pytest tests/ -v
ruff check synaps tests benchmark --select F,E9

python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare
```

Чтобы собрать пакет локально:

```bash
python -m build
twine check dist/*
```

## Карта репозитория

- [docs/README.md](docs/README.md): англоязычный путеводитель по архитектурным, доменным, эволюционным и исследовательским документам.
- [docs/README_RU.md](docs/README_RU.md): русскоязычный путеводитель по технической документации.
- [docs/PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md](docs/PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md): ручной список действий после первого публичного push в GitHub.
- [benchmark/README.md](benchmark/README.md): англоязычное описание системы бенчмарков.
- [benchmark/README_RU.md](benchmark/README_RU.md): русскоязычное описание системы бенчмарков.
- `python -m synaps solve <instance.json>`: запуск расчёта с JSON-ответом.
- [`schema/contracts/`](schema/contracts/README.md): стабильный JSON-контракт для будущего TypeScript-слоя.
- [`control-plane/`](control-plane/README.md): англоязычное описание минимального TypeScript-шлюза.
- [`control-plane/README_RU.md`](control-plane/README_RU.md): русскоязычное описание сетевой границы TypeScript-слоя.
- [CONTRIBUTING.md](CONTRIBUTING.md): правила участия и проверки изменений.
- [SUPPORT.md](SUPPORT.md): поддерживаемые публичные каналы поддержки.
- [SECURITY.md](SECURITY.md): маршрут для сообщений об уязвимостях.

## Архитектурные и исследовательские материалы

В репозитории есть более широкие документы по целевой системе и доменной модели:

- [docs/architecture/01_OVERVIEW.md](docs/architecture/01_OVERVIEW.md)
- [docs/architecture/02_CANONICAL_FORM.md](docs/architecture/02_CANONICAL_FORM.md)
- [docs/architecture/03_SOLVER_PORTFOLIO.md](docs/architecture/03_SOLVER_PORTFOLIO.md)
- [research/SYNAPS_OSS_STACK_2026.md](research/SYNAPS_OSS_STACK_2026.md)
- [research/SYNAPS_UNIVERSAL_ARCHITECTURE.md](research/SYNAPS_UNIVERSAL_ARCHITECTURE.md)
- [research/SYNAPS_AIR_GAPPED_OFFLINE.md](research/SYNAPS_AIR_GAPPED_OFFLINE.md)

Эти материалы полезны для понимания направления развития, но текущую границу реализации всё равно определяют код, тесты, бенчмарки и поверхности сборки в самом репозитории.

## Темы roadmap

- Усилить декомпозицию и масштабирование поверх текущей LBBD-базы, включая более сильные отсечения и подсказки для поиска.
- Вынести границы оркестрации отдельно от математического ядра, чтобы состояние расписания не оставалось целиком внутри solver-слоя.
- Расширить набор epsilon-профилей до сценариев потерь материала и более явного многокритериального перебора.
- Добавить более зрелые процессы релизов, обновления зависимостей и проверки цепочки поставки.
- Жёстко привязывать сильные исследовательские утверждения к измеримым доказательствам.

## Инвесторские и верификационные материалы

Опциональный пакет для проверки может жить в `docs/investor/`.

Этот слой намеренно вторичен. Открытый код, тесты, система бенчмарков и сборка пакета от этой подпапки не зависят. Если задача в том, чтобы понять, что репозиторий умеет сегодня, начинать стоит с инженерных точек входа выше.

Если инвесторский слой всё же нужен, начинайте с [docs/investor/README_RU.md](docs/investor/README_RU.md). Этот путеводитель теперь ведёт только к сокращённому активному набору и к границе архива.
