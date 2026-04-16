# SynAPS

Deterministic production scheduling engine for MO-FJSP-SDST-ARC workloads.

Language: [EN](#synaps-in-english) | **RU**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Зачем это

Когда в производстве начинается ручной "пожарный" режим, главный вопрос всегда один:

"Почему система поставила заказ именно сюда и именно сейчас?"

SynAPS сделан вокруг этого вопроса. Здесь план строится не как черный ящик, а как проверяемый процесс:
1. выбор решателя детерминированный,
2. ограничения проверяются независимым валидатором,
3. поведение можно разобрать по артефактам, а не по догадкам.

## Статус

Текущее состояние проекта:
1. код, тесты и benchmark-контур воспроизводимы,
2. solver-портфель работает и покрыт тестами,
3. live-factory валидация в этом репозитории не заявляется.

## Что сейчас в коде (фактчек 2026-04-16)

Проверено по репозиторию:
1. `available_solver_configs()` -> **22** публичных конфигурации,
2. `pytest --collect-only -q tests` -> **293 tests collected**,
3. `requires-python` -> **>=3.12**,
4. core зависимости ядра -> `ortools`, `highspy`, `pydantic`, `numpy`.

## Портфель решателей

В `synaps/solvers` сейчас 9 классов решателей (по `class ... (BaseSolver)`):

| Компонент | Что делает | Где применяется |
|---|---|---|
| `CpSatSolver` | Exact CP-SAT решение | малые и средние постановки |
| `LbbdSolver` | Logic-Based Benders | средние/крупные постановки |
| `LbbdHdSolver` | Иерархическая/параллельная декомпозиция | крупные инстансы |
| `GreedyDispatch` | Быстрый конструктив | low-latency режим |
| `BeamSearchDispatch` | Улучшенный конструктив (beam) | SDST-чувствительные случаи |
| `AlnsSolver` | Большие инстансы через LNS | 10k+ сценарии |
| `RhcSolver` | Рецедирующий горизонт | long-horizon и very-large |
| `ParetoSliceCpSatSolver` | Epsilon-constraint срезы | multi-objective сравнение |
| `IncrementalRepair` | Локальный ремонт расписания | change/breakdown/rush сценарии |

Плюс отдельный контур проверки выполнимости: `FeasibilityChecker`.

## 50K benchmark surface

Публичный артефакт:
[benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json](benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json)

Сводка `summary_by_solver`:

| Solver | mean_wall_time_s | feasibility_rate | mean_makespan_minutes | mean_total_setup_minutes | mean_peak_window_candidate_count |
|---|---:|---:|---:|---:|---:|
| `RHC-GREEDY` | 120.115 | 0.0 | 5077.55 | 18671.0 | 49931.0 |
| `RHC-ALNS` | 366.23 | 0.0 | 1515.04 | 10852.0 | 49993.0 |

Это рабочий контур профилирования масштаба 50K, но не финальная quality-граница.

## Что изменилось весной 2026

Реализовано и покрыто тестами:
1. pressure-adaptive early stop для ALNS,
2. динамический `max_no_improve_iters` от `due_pressure` и `candidate_pressure`,
3. передача pressure-контекста из RHC в inner ALNS,
4. frontier-health метрики в RHC metadata (`candidate_pressure`, `due_drift`, `spillover`).

Основные файлы:
1. [synaps/solvers/alns_solver.py](synaps/solvers/alns_solver.py)
2. [synaps/solvers/rhc_solver.py](synaps/solvers/rhc_solver.py)
3. [tests/test_alns_rhc_scaling.py](tests/test_alns_rhc_scaling.py)
4. [docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md](docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md)

## Планы

### Now (0-6 weeks)
1. стабилизация pressure-adaptive KPI (latency/quality),
2. epsilon-grid governance для multi-objective профилей,
3. расширение stress benchmark-корпуса для RHC.

### Next (6-16 weeks)
1. RL-driven operator policy в shadow mode,
2. bounded MOALNS archive,
3. bounded LLM planner/explainer над deterministic kernel.

### Later (16+ weeks)
1. graph-native RHO acceleration,
2. multi-agent orchestration со строгим state provenance,
3. hardware-aware optimization lane после подтвержденного bottleneck profiling.

## Быстрый старт

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"

# Базовый solve
python -m synaps solve benchmark/instances/tiny_3x3.json

# Сравнение решателей
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-10 --compare

# Тесты
python -m pytest tests -q
```

## Как проверить claims локально

```bash
# 22 solver configs
python -c "from synaps.solvers.registry import available_solver_configs as f; print(len(f()))"

# 293 tests
pytest --collect-only -q tests

# 50K summary
python -c "import json, pathlib; obj=json.loads(pathlib.Path('benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json').read_text(encoding='utf-8')); print(obj['summary_by_solver'])"
```

## Границы заявлений

Проект не заявляет в текущей версии:
1. подтвержденное внедрение на живом заводе,
2. полностью feasible industrial-50k в текущих публичных лимитах,
3. production UI плановика,
4. turnkey ERP/MES интеграцию.

## Карта репозитория

1. [docs/README.md](docs/README.md) - documentation router
2. [benchmark/README.md](benchmark/README.md) - benchmark harness
3. [control-plane/README.md](control-plane/README.md) - TypeScript BFF boundary
4. [docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md](docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md) - strategic update

## License

MIT.

---

<a id="synaps-in-english"></a>

# SynAPS in English

Deterministic scheduling engine for MO-FJSP-SDST-ARC with independent feasibility validation.

## Status snapshot (2026-04-16)

Verified from repo state:
1. 22 public solver configurations,
2. 293 collected Python tests,
3. Python requirement is 3.12+,
4. 50K benchmark surface is reproducible through a public JSON artifact.

## Why this project exists

SynAPS focuses on one practical requirement: planning decisions must be explainable.
The design is deterministic-first, with independent post-solve feasibility checks and reproducible benchmark artifacts.

## Current implementation

1. solver portfolio is live and routed deterministically,
2. ALNS/RHC pressure-adaptive baseline is implemented,
3. frontier-health telemetry is exposed in RHC metadata,
4. independent feasibility checks run after solve paths.

## Roadmap highlights

1. Next: RL operator policy in shadow mode, bounded MOALNS archive, bounded LLM planner/explainer.
2. Later: graph-native RHO acceleration and hardware-aware optimization lane.

## Current non-claims

1. no validated live-factory deployment claim,
2. no claim of stable fully feasible industrial-50k under current public limits,
3. no claim of production planner UI,
4. no claim of turnkey ERP/MES integration.

## Quick links

1. [Architecture router](docs/README.md)
2. [Benchmark harness](benchmark/README.md)
3. [Control-plane boundary](control-plane/README.md)
4. [Strategic update](docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md)

## License

MIT.
