# SynAPS

Deterministic-first движок планирования и оркестрации ресурсов для задач класса MO-FJSP-SDST-ML-ARC.

Language: [EN](README.md) | **RU**

## Статус

SynAPS сейчас является публичным исследовательским и инженерным репозиторием.

В кодовой базе уже есть Python-ядро расписаний, каноническая схема данных, benchmark harness и surfaces для валидации. При этом репозиторий **не** заявляет, что вся целевая архитектура "Алеф", киберфизическая интеграция или production-развёртывание уже реализованы как готовое ПО.

### Что реализовано сегодня

- Точные CP-SAT сценарии с учётом sequence-dependent setups и auxiliary resources.
- Жадный диспетчер и bounded incremental repair.
- Pydantic-модель текущего канонического формата данных.
- Воспроизводимый benchmark harness в [benchmark/README.md](benchmark/README.md).
- Репозиторная валидация через `pytest`, targeted `ruff` checks и packaging metadata.

### Что относится к target blueprint

Длинные архитектурные документы описывают целевое развитие системы, включая:

- event-sourced orchestration и более строгие boundary между слоями;
- hardware-aware hot paths, например Rust или PyO3 мосты;
- decomposition и LBBD для более крупных инстансов;
- advisory ML или LLM-слои с явными guardrails.

Эти части следует считать roadmap и research direction, если для них нет прямого подтверждения текущим кодом, тестами и бенчмарками в этом репозитории.

## Границы заявлений

Читать SynAPS лучше как engineering surface, а не как маркетинговый манифест.

- Репозиторий не утверждает, что hardware pinning, zero-copy IPC, event sourcing, GNN cuts или LLM explanation уже реализованы здесь сегодня.
- Публичная публикация репозитория не означает production readiness, regulator-ready состояние или сертифицированную интеграцию с заводским контуром.
- Investor и diligence материалы являются вспомогательным контекстом, а не единственным техническим SSOT.

## Быстрый старт

```bash
git clone https://github.com/synaps/synaps.git
cd synaps
python -m pip install -e ".[dev]"

# Routed solve через portfolio API с JSON output
python -m synaps solve benchmark/instances/tiny_3x3.json

# Сгенерировать runtime contract schemas для TS outer shell
python -m synaps write-contract-schemas --output-dir schema/contracts

# Запустить минимальный TypeScript control-plane BFF
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

- [docs/README.md](docs/README.md): навигация по архитектурным, доменным, эволюционным и research документам.
- [docs/PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md](docs/PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md): ручной GitHub checklist после первого публичного push.
- [benchmark/README.md](benchmark/README.md): воспроизводимое сравнение solver-ов.
- `python -m synaps solve <instance.json>`: high-level routed solve с JSON output.
- [`schema/contracts/`](schema/contracts/README.md): стабильный JSON contract для будущего TS control-plane.
- [`control-plane/`](control-plane/README.md): минимальный TypeScript BFF как proof network-facing control-plane boundary.
- [CONTRIBUTING.md](CONTRIBUTING.md): правила contribution flow и проверки.
- [SUPPORT.md](SUPPORT.md): поддерживаемые публичные каналы поддержки.
- [SECURITY.md](SECURITY.md): маршрут для сообщений об уязвимостях.

## Архитектурные и research-материалы

В репозитории есть более широкие документы по целевой системе и доменной модели:

- [docs/architecture/01_OVERVIEW.md](docs/architecture/01_OVERVIEW.md)
- [docs/architecture/02_CANONICAL_FORM.md](docs/architecture/02_CANONICAL_FORM.md)
- [docs/architecture/03_SOLVER_PORTFOLIO.md](docs/architecture/03_SOLVER_PORTFOLIO.md)
- [research/SYNAPS_MASTER_BLUEPRINT.md](research/SYNAPS_MASTER_BLUEPRINT.md)
- [research/SYNAPS_OSS_STACK_2026.md](research/SYNAPS_OSS_STACK_2026.md)

Эти материалы полезны для понимания направления развития, но текущую границу реализации всё равно определяют код, тесты, benchmark harness и packaging surfaces в самом репозитории.

## Темы roadmap

- Усилить decomposition и масштабирование поверх текущего solver-centric baseline.
- Вынести orchestration boundaries отдельно от математического ядра.
- Добавить более зрелые public release и supply-chain surfaces.
- Жёстко привязывать сильные claims к измеримым evidence.

## Investor и diligence материалы

Опциональный diligence packet может жить в `docs/investor/`.

Этот слой намеренно вторичен. Open-source код, тесты, benchmark harness и packaging от этой подпапки не зависят. Если задача в том, чтобы понять, что репозиторий умеет сегодня, начинать стоит с инженерных entrypoint-ов выше.
