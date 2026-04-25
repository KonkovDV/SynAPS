# Система бенчмарков SynAPS

Language: [EN](README.md) | **RU**

Эта директория содержит воспроизводимую систему бенчмарков для solver-ов SynAPS.

## Быстрый старт

```bash
# Один solver, один пример
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED

# Сгенерировать воспроизводимый large boundary instance для LBBD-исследований
python -m benchmark.generate_instances benchmark/instances/generated_large.json \
  --preset large --seed 7

# Агрегировать поведение router по семействам preset/seed
python -m benchmark.study_routing_boundary --presets medium large --seeds 1 2 3

# Сравнить реальное поведение solver-ов на generated preset families
python -m benchmark.study_solver_scaling --presets medium large --seeds 1 2 3 \
  --solvers GREED CPSAT-30 LBBD-10 AUTO

# Запустить отдельное 50K-исследование для large-instance пути RHC
python -m benchmark.study_rhc_50k --preset industrial-50k --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/2026-04-12-rhc-50k

# Прогнать staged 500K-исследование в безопасном plan-режиме (без solve)
python -m benchmark.study_rhc_500k --execution-mode plan --lane both --seeds 1 2 3

# Прогнать gate-защищённую лестницу 50k->500k
python -m benchmark.study_rhc_500k --execution-mode gated --lane both --seeds 1 \
  --scales 50000 100000 200000 300000 500000 \
  --write-dir benchmark/studies/2026-04-19-rhc-500k

# Автоматический выбор solver-а
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers AUTO

# Сравнение двух solver-ов
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

# Сравнение обычного точного профиля и профиля с допуском
python -m benchmark.run_benchmark benchmark/instances/pareto_setup_tradeoff_4op.json \
  --solvers CPSAT-10 CPSAT-EPS-SETUP-110 --compare

# Несколько прогонов для статистической устойчивости
python -m benchmark.run_benchmark benchmark/instances/medium_20x10.json \
  --solvers GREED CPSAT-10 --runs 5 --compare

# Все примеры в директории
python -m benchmark.run_benchmark benchmark/instances/ --solvers GREED CPSAT-30
```

## Конфигурации solver-ов

| Имя | Solver | Параметры |
|------|--------|------------|
| `GREED` | GreedyDispatch | K1=2.0, K2=0.5 |
| `GREED-K1-3` | GreedyDispatch | K1=3.0, K2=0.5 |
| `CPSAT-10` | CpSatSolver | time_limit=10s |
| `CPSAT-30` | CpSatSolver | time_limit=30s |
| `CPSAT-120` | CpSatSolver | time_limit=120s |
| `CPSAT-EPS-SETUP-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise setup under a `1.10x` makespan cap |
| `CPSAT-EPS-TARD-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise tardiness under a `1.10x` makespan cap |
| `CPSAT-EPS-MATERIAL-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, минимизация потерь материала при ограничении makespan `1.10x` |
| `LBBD-5` | LbbdSolver | HiGHS master + CP-SAT sub, 5 iterations, capacity + load-balance cuts |
| `LBBD-10` | LbbdSolver | HiGHS master + CP-SAT sub, 10 iterations |
| `AUTO` | Portfolio router | выбирает конкретную конфигурацию под задачу |

## Что важно понимать

`CPSAT-EPS-SETUP-110`, `CPSAT-EPS-TARD-110` и `CPSAT-EPS-MATERIAL-110` — это публичные профили с допуском, а не полный перебор фронта Парето.

Каждый профиль делает три шага:

1. на первом шаге находится сильное базовое решение через обычный CP-SAT;
2. на втором шаге makespan ограничивается в пределах `10%` от базы, после чего минимизируется вторичная цель: setup, tardiness или material loss;
3. внутри этого режима solver дополнительно выбирает более компактное решение по makespan, чтобы не оставлять лишний запас.

`LBBD-5` и `LBBD-10` показывают декомпозицию Logic-Based Benders: HiGHS решает мастер-задачу, а CP-SAT — подзадачи. Поэтому система бенчмарков покрывает не только одиночные solver-режимы, но и путь через декомпозицию.

## Формат вывода

### Один solver

```json
{
  "instance": "tiny_3x3.json",
  "solver_config": "GREED",
  "selected_solver_config": "GREED",
  "results": {
    "status": "feasible",
    "feasible": true,
    "proved_optimal": false,
    "solver_name": "greedy_dispatch",
    "makespan_minutes": 95.0,
    "total_setup_minutes": 18.0,
    "total_material_loss": 0.0,
    "assignments": 6
  },
  "statistics": {
    "runs": 1,
    "wall_time_s_mean": 0.0012,
    "wall_time_s_min": 0.0012,
    "wall_time_s_max": 0.0012,
    "peak_rss_mb": 85.0
  }
}
```

### Режим сравнения

```json
{
  "instance": "tiny_3x3.json",
  "comparisons": [
    {"solver_config": "GREED", "results": {...}, "statistics": {...}},
    {"solver_config": "CPSAT-30", "results": {...}, "statistics": {...}}
  ]
}
```

## Использование из кода

```python
from pathlib import Path
from benchmark.run_benchmark import load_problem, run_benchmark

problem = load_problem(Path("benchmark/instances/tiny_3x3.json"))
report = run_benchmark(Path("benchmark/instances/tiny_3x3.json"), solver_names=["GREED"], runs=3)
```

## Добавление новых solver-ов

Регистрируйте новые конфигурации в `synaps/solvers/registry.py`:

```python
_SOLVER_REGISTRY["MY-SOLVER"] = SolverRegistration(
  factory=build_my_solver,
  solve_kwargs={"param": value},
  description="short human-readable description",
)
```

Специальный режим `AUTO` используется только для маршрута с автоматическим выбором и идёт через `synaps.solve_schedule()`.

## Параметрическая генерация инстансов

`benchmark.generate_instances` активирует planned synthetic-generator surface из benchmark protocol и даёт воспроизводимые JSON-инстансы в текущем формате `ScheduleProblem`.

### Пресеты

| Пресет | Целевой band | Назначение |
|--------|--------------|------------|
| `tiny` | small | smoke/CI и проверка схемы |
| `small` | small | регрессии и сравнение эвристик |
| `medium` | medium | exact-профили и epsilon-slice сравнения |
| `large` | large | routing boundary для LBBD и decomposition studies |
| `industrial` | large | офлайн stress generation для research runs |

### Примеры CLI

```bash
# Использовать preset как есть
python -m benchmark.generate_instances benchmark/instances/generated_medium.json \
  --preset medium --seed 11

# Переопределить параметры для boundary-сценария
python -m benchmark.generate_instances benchmark/instances/generated_boundary.json \
  --preset large --seed 17 --jobs 48 --machines 14 --operations-min 4 --operations-max 6
```

Генератор пишет JSON-файл в текущем schema-compatible формате и печатает summary с deterministic seed и вычисленным `problem_profile`. Поэтому получившийся инстанс можно сразу использовать в `python -m synaps solve ...` и `python -m benchmark.run_benchmark ...` без промежуточной конвертации.

## Routing Boundary Study

`benchmark.study_routing_boundary` превращает generated preset families в воспроизводимый академический отчёт.

Утилита делает три вещи:

1. генерирует каждый указанный preset для набора deterministic seed-ов;
2. вычисляет `problem_profile` для каждого инстанса;
3. фиксирует решение deterministic router-а, чтобы гипотезы Phase 1 про LBBD-boundary были подтверждены фактами, а не только narrative-ом.

Пример:

```bash
python -m benchmark.study_routing_boundary \
  --presets medium large \
  --seeds 1 2 3 4 \
  --write-dir benchmark/instances/studies
```

В JSON-отчёт входят записи по каждому инстансу и агрегат `summary_by_preset`: counts по routed solver-ам, size band-ам, статистика по числу операций и флаг `routing_stable`, который сразу показывает drift границы, если preset перестал маппиться в ожидаемый portfolio member.

## Solver Scaling Study

`benchmark.study_solver_scaling` использует те же preset families, но переводит их в исполнимое comparative evidence по solver-ам.

Для каждой комбинации `preset × seed` утилита:

1. материализует инстанс в текущем schema-compatible формате;
2. прогоняет указанные solver-конфигурации через публичный benchmark harness;
3. агрегирует mean runtime, mean makespan и feasibility rate по фактически выбранному solver-у.

Пример:

```bash
python -m benchmark.study_solver_scaling \
  --presets medium large \
  --seeds 1 2 3 \
  --solvers GREED CPSAT-30 LBBD-10 AUTO \
  --write-dir benchmark/instances/scaling-studies
```

В отчёте сохраняются per-instance comparison records и агрегат `summary_by_preset`, который позволяет без ручного разбора ответить на вопросы вида: «схлопывается ли `AUTO` в `LBBD-10` на large generated instances?» и «какой runtime/quality trade-off получается между `GREED` и exact/decomposition profiles на одном и том же семействе preset-ов?`.

## Отдельное 50K-исследование для RHC

`benchmark.study_rhc_50k` - это воспроизводимый benchmark-path для текущей large-instance пары `RHC-GREEDY` и `RHC-ALNS`.

Одна команда делает четыре вещи:

1. материализует детерминированный `industrial-50k` инстанс для каждого seed;
2. прогоняет публичный benchmark harness с `RHC-GREEDY` и `RHC-ALNS`;
3. сохраняет per-instance records, solver metadata и время верификации;
4. пишет JSON-артефакт в выбранную директорию под `benchmark/`, чтобы README и audit-утверждения ссылались на устойчивую evidence surface.

Пример:

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/2026-04-13-rhc-50k-machine-index
```

Study пишет materialized instances в `instances/` и верхнеуровневый артефакт `rhc_50k_study.json` с агрегатами по wall-clock, verification time, makespan, total setup и RHC-specific metadata вроде `preprocessing_ms` и давления candidate-pool.

### Текущие артефакты

Базовый артефакт лежит в [studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json](studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json).

Последний live stress-matrix артефакт лежит в [studies/test-50k-academic-matrix-v1/rhc_50k_study.json](studies/test-50k-academic-matrix-v1/rhc_50k_study.json).

Его ценность в том, что он сохраняет реальную текущую границу, а не прячет её:

- `RHC-GREEDY` останавливается через `120.115s` и успевает зафиксировать `6959` назначений за `11` окон.
- `RHC-ALNS` останавливается через `366.23s` и успевает зафиксировать `1078` назначений за `3` окна.
- оба прогона заканчиваются с `status=error` и `feasible=false`
- давление candidate-pool всё ещё доходит до `49 931` и `49 993`

Live stress-matrix делает текущее расхождение явным:

- у `RHC-GREEDY` лучше профиль покрытия (`mean_scheduled_ratio = 0.3547`);
- у `RHC-ALNS` лучше профиль частичного objective (`mean_makespan_minutes = 4652.77`), но покрытие заметно хуже (`0.1134`);
- обе solver-линии в этом артефакте всё ещё не проходят feasibility gate на 50K.

Поэтому публичный 50K path реален и воспроизводим, но это всё ещё profiling surface, а не закрытый промышленный benchmark. Последний live-артефакт полезен прежде всего как evidence surface для узких мест, включая pre-fix примеры zero-iteration ALNS окон, которые и привели к явному fallback guard `inner_time_limit_exhausted_before_search` в текущем коде.

Post-audit (2026-04-25) усиление solver-логики теперь включает:

- full-frontier escalation для недозаполненных admission-окон (`admission_full_scan_*` в metadata);
- dynamic ALNS repair-budget scaling, привязанный к effective destroy envelope (`alns_effective_repair_time_limit_s`).

Для обновления этого раздела post-audit метриками нужно повторно запустить `benchmark.study_rhc_50k`.

## Staged 500K-исследование

`benchmark.study_rhc_500k` - это stress-study harness для сценариев до 500K+ операций.

Скрипт расширяет 50K-подход за счёт:

1. лестницы масштабов (`50k -> 100k -> 200k -> 300k -> 500k` по умолчанию);
2. явной проекции ресурсов (setup entries, eligible links, плотная SDST память, оценка working set);
3. admission gate перед дорогими solve-фазами (`execution-mode gated`);
4. робастных метрик (mean/median/IQR/CVaR по makespan и wall-time, scheduled-ratio и tail unscheduled risk);
5. quality gate относительно baseline solver в том же lane и масштабе.

### Режимы выполнения

- `plan`: только topology/resource projection + решения gate, без solve.
- `gated`: выполняет только те масштабы, которые проходят resource gate.
- `full`: выполняет все requested scales, игнорируя gate.

### Типовые команды

```bash
# Быстрый научный pass без тяжёлых solve
python -m benchmark.study_rhc_500k --execution-mode plan --lane both --seeds 1 2 3

# Контролируемый stress-run с gate-защитой
python -m benchmark.study_rhc_500k --execution-mode gated --lane both --seeds 1 \
  --scales 50000 100000 200000 300000 500000 \
  --write-dir benchmark/studies/2026-04-19-rhc-500k
```

Артефакт исследования: `rhc_500k_study.json` в выбранной study-директории.

## Примеры входных данных

Формат instance-файлов и список включённых примеров описаны в [instances/README.md](instances/README.md).