# Система бенчмарков SynAPS

Language: [EN](README.md) | **RU**

Эта директория содержит воспроизводимую систему бенчмарков для решателей SynAPS.

## Быстрый старт

```bash
# Один решатель, один пример
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED

# Сгенерировать воспроизводимый large boundary instance для LBBD-исследований
python -m benchmark.generate_instances benchmark/instances/generated_large.json \
  --preset large --seed 7

# Агрегировать поведение router по семействам preset/seed
python -m benchmark.study_routing_boundary --presets medium large --seeds 1 2 3

# Сравнить реальное поведение решателей на сгенерированных семействах пресетов
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

# Автоматический выбор решателя
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers AUTO

# Сравнение двух решателей
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

## Конфигурации решателей

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
3. внутри этого режима решатель дополнительно выбирает более компактное решение по makespan, чтобы не оставлять лишний запас.

`LBBD-5` и `LBBD-10` показывают декомпозицию Logic-Based Benders: HiGHS решает мастер-задачу, а CP-SAT — подзадачи. Поэтому система бенчмарков покрывает не только одиночные режимы решателей, но и путь через декомпозицию.

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

## Исследование границ маршрутизации

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

## Исследование масштабирования решателей

`benchmark.study_solver_scaling` использует те же preset families, но переводит их в исполнимое comparative evidence по solver-ам.

Для каждой комбинации `preset × seed` утилита:

1. материализует инстанс в текущем schema-compatible формате;
2. прогоняет указанные конфигурации решателей через публичный benchmark harness;
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
4. пишет JSON-артефакт в выбранную директорию под `benchmark/`, чтобы README и audit-утверждения ссылались на устойчивую поверхность подтверждений.

Примечание по temporal-модели `industrial-50k` (2026-04-26):

- заказы теперь несут явный `release_offset_min` в `domain_attributes`;
- release offsets семплируются ранне-смещенным long-tail законом на диапазоне `0..0.55*horizon`;
- это сохраняет admission-сигнал в первом окне для короткого geometry-smoke DOE и одновременно оставляет реалистичное распределение поздних релизов для staged-run сценариев.

Короткий smoke-checkpoint:

- артефакт [studies/2026-04-26-rhc-alns-geometry-doe-postfix-smoke-v4/rhc_alns_geometry_doe.json](studies/2026-04-26-rhc-alns-geometry-doe-postfix-smoke-v4/rhc_alns_geometry_doe.json)
  восстановил ненулевое admission-давление (`peak_raw_window_candidate_count=2670` против zero-frontier collapse в smoke-v2);
- покрытие в этом жестко ограниченном срезе 10s/1-window все еще ниже исторического baseline, поэтому это следует трактовать как admission-recovery hardening, а не как полное закрытие throughput-задачи.

ALNS tuning checkpoint (geometry DOE v6, 2026-04-26):

- в каноническом DOE-профиле зафиксирован `due_admission_horizon_factor=2.0`, чтобы сохранить ненулевое admission-давление до ALNS budget guard;
- артефакт [studies/2026-04-26-rhc-alns-geometry-doe-v6-alns-tuning/rhc_alns_geometry_doe.json](studies/2026-04-26-rhc-alns-geometry-doe-v6-alns-tuning/rhc_alns_geometry_doe.json) является текущей tuning-surface;
- в жестком срезе 10s/1-window только `480/120` сохранил ненулевое покрытие (`scheduled_ratio=0.0147`) и ненулевой frontier (`peak_raw_window_candidate_count=6637`), тогда как `240/60`, `300/90` и `360/90` в этом бюджете ушли в `no assignments produced`.

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

Последний до исправлений live stress-matrix артефакт лежит в [studies/test-50k-academic-matrix-v1/rhc_50k_study.json](studies/test-50k-academic-matrix-v1/rhc_50k_study.json).

Артефакт с защитными ограничителями для уже снятого с публикации профиля лежит в [studies/2026-04-26-rhc-alns-postfix-canonical-v4/rhc_50k_study.json](studies/2026-04-26-rhc-alns-postfix-canonical-v4/rhc_50k_study.json).

Свежий аудит current-head до обновления профиля лежит в [studies/2026-04-27-rhc-50k-audit-v1/rhc_50k_study.json](studies/2026-04-27-rhc-50k-audit-v1/rhc_50k_study.json).

Их нужно читать вместе, а не схлопывать в одну историю:

- до исправлений stress-matrix сохраняет старый профиль деградации ALNS, где покрытие было слабым, но часть окон всё же входила в search;
- артефакт с защитными ограничителями фиксирует второй режим, где oversized ALNS-окна пропускаются до дорогой seed generation, чтобы не сжигать весь бюджет окна;
- свежий аудит current-head фиксирует смешанный режим, где ранние окна действительно входят в ALNS, но окна 2-3 сжигают бюджет на нулевой по результату CP-SAT repair, а поздние окна уходят в fallback или timeout из-за hybrid CP-SAT routing;
- оба прогона всё ещё заканчиваются с `status=error` и `feasible=false`, поэтому ни один нельзя читать как solved industrial benchmark.
- в этом partial-режиме сначала сравнивайте coverage и fallback metrics; не интерпретируйте качество bound-gap, пока `lower_bound_upper_bound_comparable != true`.

Текущее расхождение теперь описывается точнее:

- до исправлений `RHC-ALNS|throughput` давал `mean_scheduled_ratio = 0.0946`, `mean_makespan_minutes = 4985.85` и `mean_inner_fallback_ratio = 0.1`;
- guarded-profile `RHC-ALNS|throughput` даёт `mean_scheduled_ratio = 0.3028`, `mean_makespan_minutes = 9675.18` и `mean_inner_fallback_ratio = 1.0`;
- fresh current-head `RHC-ALNS|throughput` даёт `mean_scheduled_ratio = 0.1243`, `mean_makespan_minutes = 4134.84` и `mean_inner_fallback_ratio = 0.625`;
- после исправлений `RHC-GREEDY|throughput` остаётся более сильным базовым режимом максимального покрытия с `mean_scheduled_ratio = 0.37` и нулевым inner fallback.

Следовательно, публичный 50K path по-прежнему реален и воспроизводим, но последнее evidence теперь строже, чем и старая stress-matrix-история, и история про guarded fallback по отдельности: ALNS действительно может входить в search, однако старый публичный профиль терял слишком много бюджета на CP-SAT side-paths. Поэтому публичный default `RHC-ALNS` теперь отключает hybrid CP-SAT routing и CP-SAT micro-repair, а DOE harness по-прежнему оставляет эти knobs для контролируемых экспериментов.

Post-audit (2026-04-26) усиление solver-логики теперь включает:

- full-frontier escalation для недозаполненных admission-окон (`admission_full_scan_*` в metadata);
- dynamic ALNS repair-budget scaling, привязанный к effective destroy envelope (`alns_effective_repair_time_limit_s`);
- явный pre-search short-circuit для oversized ALNS-окон (`budget_guard_skipped_initial_search`).

RHC-ALNS profile обновление (Апрель 2026):

- `due_admission_horizon_factor=2.0` (было 1.0): настроено через geometry DOE v6 для сохранения non-zero admission pressure в коротких ALNS окнах;
- `alns_presearch_max_window_ops=5000`: синхронизировано с effective window cap для выравнивания presearch guard с candidate-pool семантикой;
- `admission_full_scan_enabled=False`: capped full-scan семантика (добавляет candidates только до `candidate_pool_limit`, не все uncommitted ops) предотвращает runaway candidate sets в недозаполненных окнах;
- `hybrid_inner_routing_enabled=False`: публичный benchmark default больше не маршрутизирует окна с высоким due-pressure напрямую в CP-SAT после того, как аудит 2026-04-27 показал timeout-heavy hybrid behavior у старого профиля;
- `inner_kwargs.use_cpsat_repair=False`: публичный benchmark default теперь использует только greedy ALNS repair, потому что 50K-аудит 2026-04-27 показал ноль принятых CP-SAT repairs у старого профиля;
- новые telemetry поля добавлены в metadata:
  - `precedence_ready_blocked_by_precedence_count`: count операций, отклонённых из-за unresolved predecessor constraints;
  - `precedence_ready_ratio`: ratio precedence-ready ops среди оценённых (0–1);
  - `admission_full_scan_triggered_windows`: count окон, где был активирован full-scan path;
  - `admission_full_scan_added_ops`: count ops добавленных во время full-scan path;
  - `admission_full_scan_final_pool_peak`: peak candidate-pool size после full-scan phase.

Ограниченный 100K evidence для снятого с публикации профиля лежит в [studies/2026-04-27-rhc-100k-audit-v1/rhc_500k_study.json](studies/2026-04-27-rhc-100k-audit-v1/rhc_500k_study.json). Он показывает, что `RHC-GREEDY` успевает расписать `8144/100000` операций за `90.226s`, тогда как `RHC-ALNS` расписывает `0/100000` и тратит `400518 ms` на initial solution generation до первой ALNS-итерации. Этот артефакт нужно читать как evidence отказа старого профиля, а не как заявление, что обновлённый default уже верифицирован на 100K.

Ограниченный 100K evidence для staged geometry-refresh harness лежит в [studies/2026-04-27-rhc-100k-audit-v3-geometry-refresh/rhc_500k_study.json](studies/2026-04-27-rhc-100k-audit-v3-geometry-refresh/rhc_500k_study.json). В этом срезе staged harness для `100k+` сужает first-window geometry `RHC-ALNS` до `300/90`, уменьшая первый inner slice до `760` операций. Прогон доходит до `ALNS starting`, выполняет `55` итераций с `43` улучшениями, показывает `0` inner fallback и заканчивает с `4678/100000` назначенными операциями за `90.118s`. Этот артефакт нужно читать как доказательство, что в staged harness ALNS на 100K теперь реально входит в search, а не как доказательство, что 100K path уже закрыт: run остаётся частичным и `feasible=false`.

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

