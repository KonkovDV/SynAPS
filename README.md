# SynAPS

Deterministic production scheduling engine for MO-FJSP-SDST-ARC workloads.

Language: [EN](#synaps-in-english) | **RU**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Зачем проект появился

Я делал этот проект с тем же вопросом, который обычно возникает у технолога на реальном производстве:

"Почему система поставила заказ именно сюда и именно сейчас?"

В коммерческих APS это часто скрыто внутри закрытой логики. В SynAPS целевой принцип другой:
1. ядро остается детерминированным,
2. решение проходит независимую валидацию,
3. причины маршрутизации и деградации можно проверить по артефактам.

## Честная рамка заявлений

Что подтверждается в этом репозитории:
1. код, тесты и benchmark-контур воспроизводимы локально,
2. solver-портфель и routing реально работают,
3. ограничения проверяются отдельным post-solve валидатором.

Что не заявляется как уже закрытое:
1. validated live-factory deployment,
2. стабильное fully feasible решение публичного industrial-50k в текущих открытых лимитах,
3. готовый production UI плановика,
4. turnkey ERP/MES интеграция.

## Фактчек-срез на 2026-04-16

Проверено напрямую по состоянию репозитория:
1. public solver configurations: **22**,
2. Python test collection: **293 tests collected**,
3. `requires-python`: **>=3.12**,
4. core deps в `pyproject.toml`: `ortools`, `highspy`, `pydantic`, `numpy`.

## Портфель решателей (текущее ядро)

### Exact and decomposition
1. `CPSAT-10`, `CPSAT-30`, `CPSAT-120`
2. `LBBD-5`, `LBBD-10`
3. `LBBD-5-HD`, `LBBD-10-HD`, `LBBD-20-HD`

### Multi-objective slices
1. `CPSAT-PARETO-SKETCH-SETUP`
2. `CPSAT-EPS-SETUP-110`
3. `CPSAT-EPS-TARD-110`
4. `CPSAT-EPS-MATERIAL-110`

### Constructive and large-scale heuristics
1. `GREED`, `GREED-K1-3`, `BEAM-3`, `BEAM-5`
2. `ALNS-300`, `ALNS-500`, `ALNS-1000`
3. `RHC-ALNS`, `RHC-CPSAT`, `RHC-GREEDY`

Независимая проверка ограничений выполняется через `FeasibilityChecker`.

## Что реально обновлено в апреле 2026

Реализовано в ядре и покрыто тестами:
1. pressure-adaptive early stop для ALNS,
2. динамический `max_no_improve_iters` от `due_pressure` и `candidate_pressure`,
3. передача pressure-контекста из RHC в inner ALNS,
4. frontier-health метрики в RHC metadata:
   1. `candidate_pressure_mean|max`,
   2. `due_pressure_mean`,
   3. `due_drift_minutes_mean|max`,
   4. `spillover_count`.

Ключевые поверхности:
1. [synaps/solvers/alns_solver.py](synaps/solvers/alns_solver.py)
2. [synaps/solvers/rhc_solver.py](synaps/solvers/rhc_solver.py)
3. [tests/test_alns_rhc_scaling.py](tests/test_alns_rhc_scaling.py)
4. [docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md](docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md)

## 50K benchmark surface (публичный артефакт)

Канонический артефакт:
[benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json](benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json)

Сводка по `summary_by_solver`:

| Solver | mean_wall_time_s | feasibility_rate | mean_makespan_minutes | mean_total_setup_minutes | mean_peak_window_candidate_count |
|---|---:|---:|---:|---:|---:|
| `RHC-GREEDY` | 120.115 | 0.0 | 5077.55 | 18671.0 | 49931.0 |
| `RHC-ALNS` | 366.23 | 0.0 | 1515.04 | 10852.0 | 49993.0 |

Это рабочий profiling-контур масштаба 50K, но не финальная quality-граница.

## Дорожная карта

### Now (0-6 weeks)
1. укрепление pressure-adaptive контура (latency/quality KPI),
2. epsilon-grid governance для устойчивого multi-objective поведения,
3. расширение benchmark-корпуса на stress-варианты для RHC-границ.

### Next (6-16 weeks)
1. RL-driven operator policy в shadow-rollout режиме,
2. bounded MOALNS archive,
3. bounded LLM planner/explainer над deterministic kernel.

### Later (16+ weeks)
1. graph-native RHO accelerator path,
2. расширенная multi-agent orchestration с state provenance,
3. hardware-aware optimization lane после подтверждённого bottleneck profiling.

## Быстрый старт

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"
```

Базовый solve:

```bash
python -m synaps solve benchmark/instances/tiny_3x3.json
```

Сравнение решателей:

```bash
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-10 --compare
```

Тесты:

```bash
python -m pytest tests -q
```

## Как проверить ключевые claims локально

Количество solver-конфигов:

```bash
python -c "from synaps.solvers.registry import available_solver_configs as f; print(len(f()))"
```

Количество тестов:

```bash
pytest --collect-only -q tests
```

50K summary values:

```bash
python -c "import json, pathlib; obj=json.loads(pathlib.Path('benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json').read_text(encoding='utf-8')); print(obj['summary_by_solver'])"
```

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

## What is implemented now

1. deterministic solver portfolio and deterministic router,
2. ALNS/RHC pressure-adaptive early-stop baseline,
3. frontier-health telemetry in RHC metadata,
4. independent feasibility checks after solve.

## What is not claimed as completed

1. live-factory validated deployment,
2. stable fully feasible industrial-50k under current public limits,
3. production planner UI,
4. turnkey ERP/MES integration.

## Roadmap highlights

1. Next: RL policy shadow rollout, bounded MOALNS archive, bounded LLM planner/explainer.
2. Later: graph-native RHO acceleration and hardware-aware optimization lane.

## Quick links

1. [Architecture router](docs/README.md)
2. [Benchmark harness](benchmark/README.md)
3. [Control-plane boundary](control-plane/README.md)
4. [Strategic update](docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md)

## License

MIT.
