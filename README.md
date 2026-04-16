# SynAPS

Детерминированный движок планирования производства для задач класса MO-FJSP-SDST-ARC.

Language: [EN](#synaps-in-english) | **RU**

---

## Зачем это

Осенью в МИСиС я слушал кейс MOSITLAB для Москабельмета: 50 000 операций, 100 рабочих центров, 700 000 вариантов переналадок. Пять целевых функций, которые грызутся между собой. Результат внедрения - 27 дней экономии, ~1.2 млрд рублей в год. Архитектура: жадная эвристика, нейросетевое ядро, жадная эвристика. Работает. Но нейросеть - черный ящик. Она скажет "ставь заказ 4817 на станок 23", а почему - не скажет.

Я написал SynAPS - движок, где каждое решение можно вскрыть и ткнуть пальцем: *вот почему*. Детерминированный портфель решателей. Независимый валидатор после каждого вызова. Невыполнимое расписание не выходит из движка.

Коммерческие APS (Siemens Opcenter, DELMIA Ortems, Asprova) решают задачу за закрытым кодом. SynAPS - open source.

## Статус

Код работает, тесты проходят, бенчмарки воспроизводятся. На живом заводе **не тестировалось**. Зазор между текущим портфелем решателей и полной целевой архитектурой документирован честно.

## Фактчек (2026-04-16)

- Публичный реестр решателей: **22 конфигурации** (`available_solver_configs()`).
- Коллекция тестов: **293 tests collected** (`pytest --collect-only -q tests`).
- Требование Python: **>=3.12** (`pyproject.toml`).
- Базовые зависимости ядра: `ortools`, `highspy`, `pydantic`, `numpy`.

## 50K benchmark snapshot (industrial-50k)

Канонический артефакт: `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`.

Сводка `summary_by_solver`:

| Solver | mean_wall_time_s | feasibility_rate | mean_peak_window_candidate_count | windows_solved | assignments |
|---|---:|---:|---:|---:|---:|
| `RHC-GREEDY` | 120.11 | 0.0 | 49 931 | 11 | 6 959 / 50 000 |
| `RHC-ALNS` | 366.23 | 0.0 | 49 993 | 3 | 1 078 / 50 000 |

Это **частичный (не-feasible)** profiling-срез 50K, а не claim о полностью решенной задаче. 

**Почему мы это публикуем?** Как показано в [SynAPS Habr-v3](docs/habr/synaps-open-source-habr-v3.md), если "черный ящик" (нейросеть) ломается, он часто просто выдает плохой план или зависает. "Белый ящик" SynAPS завершается со `status=error` по исчерпанию времени, фиксируя частичный результат и явно показывая узкое место: пиковый пул кандидатов (`peak_window_candidate_count`) остается на уровне 49.9К, и RHC тратит бюджет на попытки назначить задачи из гигантского earliest-frontier. Это позволяет объективно диагностировать проблему и делать следующие шаги (ужесточение работы с early-frontier массой), не гадая.

### Настоящее узкое место

После закрытия проблемы первого окна (динамический limit cap и индексированный slot-search позволили greedy-пути пройти 11 окон и почти 7000 операций), узкое место сдвинулось. Текущая проблема - throughput внутреннего solver-path (`ALNS`) на фоне гигантского earliest-frontier пула. ALNS успевает сделать лишь 1078 назначений за 366 секунд. Следующий фокус:
1. еще более агрессивно отсекать и приоритезировать массу `earliest-frontier`.
2. ускорять внутренние операции large-neighborhood, а не только внешний greedy fallback.
3. усиливать `due-pressure path`.

## Портфель решателей

Базовых solver-классов сейчас 9, а публичных конфигураций в реестре - 22.

| Решатель | Алгоритм | Когда нужен |
|----------|----------|-------------|
| **CP-SAT Exact** | Circuit + NoOverlap + Cumulative через OR-Tools 9.10 | Малые/средние, доказуемый оптимум |
| **LBBD** | HiGHS MIP мастер + CP-SAT подзадачи + 4 семейства отсечений Бендерса | Средние/крупные, сходимость по gap |
| **LBBD-HD** | Параллельные подзадачи + ARC-aware разбиение + топологическая сборка | Тысячи операций |
| **Greedy ATCS** | Логарифмический ATCS-индекс (Lee, Bhaskaran & Pinedo 1997) | Допустимое расписание за < 1 с |
| **Pareto Slice** | Двухэтапный epsilon-constraint (Haimes 1971, Mavrotas 2009) | Сравнение альтернатив |
| **Incremental Repair** | Заморозка + окрестностный re-dispatch + micro-CP-SAT | Ремонт на лету, < 5% нервозности |
| **ALNS** | Adaptive Large Neighborhood Search с micro-repair | Большие задачи (10k+) |
| **RHC** | Receding Horizon Control с inner solver | Long-horizon и very-large сценарии |
| **Portfolio Router** | Детерминированное дерево режим x размер + опциональный ML advisory | Один вход - один решатель |
| **FeasibilityChecker** | 7 классов, независимый event-sweep валидатор | После каждого solve(), не доверяет никому |

Дополнительно: графовое разбиение, реестр из 22 публичных конфигураций, Pydantic-модель, профилировщик задач, ресурсные ограничители, инструментация метрик, версионированные JSON-контракты, TypeScript control-plane BFF.

**Тесты:** 293 tests collected (по `pytest --collect-only`).

## Что обновлено весной 2026

- `RHC` и `ALNS` переведены в публичный runtime contour.
- Реализован pressure-adaptive контур ALNS: динамический `max_no_improve_iters` с учетом `due_pressure` и `candidate_pressure`.
- Прокидывание pressure-контекста из RHC в inner ALNS по каждому окну.
- `RHC` теперь сохраняет частичный прогресс, если исчерпан time budget (fallbacks), явно выдает `status=error`, а не теряет результат в вечном attempt-loop.
- Frontier-health telemetry в RHC metadata: `candidate_pressure`, `due_drift_minutes`, `spillover_ops` и агрегаты.
- Обновленная стратегическая дорожная карта в `docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md`.

## Чем SynAPS отличается

**Детерминированное ядро.** CP-SAT и LBBD дают доказуемые границы. Роутер - дерево решений, не обученная модель. Один вход дает один выбор решателя и одно расписание.

**Независимая валидация.** FeasibilityChecker проверяет 7 классов ограничений на каждом решении: полнота, допустимость станков, прецеденты, ёмкость, зазоры переналадок, вспомогательные ресурсы (включая setup-интервалы - исправление "ghost setup"), горизонт. Он не знает, какой решатель работал.

**Прозрачная маршрутизация.** Роутер логирует решение и причину текстом. Оператор может перекрыть. Плановик может проверить.

**Setup-aware с первого дня.** Переналадки, зависящие от последовательности, потери материала и энергозатраты - полноценные граждане модели, а не заплатка сверху.

**Любой завод.** Кабель, сталь, фармацевтика, автопром, пищевка, PCB - заполняете матрицу переналадок и поехали.

## Быстрый старт

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"

# Расчет через portfolio router
python -m synaps solve benchmark/instances/tiny_3x3.json

# Тесты
pytest tests/ -v

# Линтинг
ruff check synaps tests benchmark --select F,E9

# Сравнение решателей на бенчмарке
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare
```

## Архитектура, алгоритмы и математика подробно

За фасадом OpenAPI/TypeScript скрыто глубоко эшелонированное математическое ядро. Задачи класса MO-FJSP-SDST-ARC (Multi-Objective Flexible Job Shop Scheduling with Sequence-Dependent Setup Times and Additional Resource Constraints) NP-трудны даже в базовых вариантах. SynAPS использует гибридный подход.

### 1. Формулировка CP-SAT (Exact)
Вместо классической MIP-формулировки с квадратичными или Big-M дизъюнкциями, которые дают слабые нижние оценки (LP-relaxations), SynAPS компилирует задачу в термины интервальных переменных для Constraint Programming (через стэк OR-Tools):
- **Секвенирование и переналадки (SDST):** Моделируется через графовый контур `AddCircuit`, где узлы — это операции, а веса рёбер — время переналадки. Формулировка гарантирует гамильтонов путь с точным расчётным временем setup-перехода.
- **Вспомогательные ресурсы (ARC):** Моделируются через глобальное ограничение `AddCumulative`. Demand-профили формируются не только на время обработки, но и на *setup-интервалы*, ликвидируя известный баг "ghost setup" (переналадка без выделения бригады).
- **Скаляризация целей:** Multi-objective базируется на динамических весах через `Pareto Slice` или линейную агрегацию (makespan, tardiness, setups, material loss, cost).

### 2. Декомпозиция Бендерса (LBBD и LBBD-HD)
Когда CP-SAT задыхается на 10 000+ операций, активируется Logic-Based Benders Decomposition (LBBD):
- **Master Problem (MIP на HiGHS):** Решает задачу назначения (assignment), релаксируя точное время. Это чистый MILP, где переменные $y_{ij} \in \{0, 1\}$ отправляют операцию $i$ на машину $j$.
- **Subproblems (CP-SAT):** Получив жесткое назначение от Master, распадаются на независимые кластеры (машины или ячейки). В `LBBD-HD` подзадачи решаются строго параллельно через `ProcessPoolExecutor`.
- **Отсечения (Benders Cuts):** Если подзадача не укладывается в заданный Master-этапом `makespan` (или невозможна из-за SDST+ARC), генерируются логические отсечения и возвращаются в Master. Используется 4 семейства отсечений (по Hooker 2007 и Nasirian 2025): *nogood cuts, bottleneck capacity cuts, setup-cost cuts, load-balance cuts*.

### 3. Эвристики для больших масштабов (ALNS и RHC)
Для индустриальных объемов (50 000+ операций), точные методы работают только как "двигатели" внутри локальных окрестностей.
- **ALNS (Adaptive Large Neighborhood Search):** Мета-эвристика. Из текущего расписания вырываются куски через 4 `destroy`-оператора (`random`, `worst`, `related`, `machine_segment`). Разрушенная "дыра" восстанавливается через greedy-repair, а для малых окрестностей может включаться `micro-CP-SAT repair` (`use_cpsat_repair`, `cpsat_max_destroy_ops`). Критерий принятия нового расписания базируется на Simulated Annealing (SA), чтобы не застрять в локальном оптимуме (Ropke & Pisinger 2006).
- **RHC (Receding Horizon Control):** Горизонт планирования нарезается на перекрывающиеся окна (по умолчанию `window_minutes=480`, `overlap_minutes=120`) с cap на число операций в окне (типично до 5000). Окно решается через ALNS/CP-SAT/greedy, затем часть расписания "замораживается", и окно сдвигается вправо. Изменения апреля 2026 года ввели *pressure-adaptive early-stop* — динамическое завершение окна в зависимости от плотности оставшегося фронтира (`due_pressure`, `candidate_pressure`), предотвращая избыточное "шлифование" локальных участков, если впереди много срочных задач.

### 4. Жадное диспетчирование (Greedy-ATCS)
Для получения допустимого расписания за < 1 сек используется индекс ATCS (Apparent Tardiness Cost with Setups). В SynAPS он модифицирован:
- **Log-space трансформация:** На заводах с тяжелохвостыми распределениями (setup в 2 часа, а обработка 5 секунд) оригинальная экспонента ATCS уходит в `float64 underflow` (становится нулём для многих альтернатив). Логарифмирование индекса спасает ранжирование.
- **Beam Search:** Настраиваемый расширенный луч (K=3..5) предотвращает фатальную близорукость жадной логики в узких бутылочных горлышках.

### 5. Софт: Архитектура чистого контура и независимая валидация
- **Моделирование данных:** Строгий `Pydantic v2` в `synaps/model.py`. Ошибка входных данных отваливается на парсинге, а не при сборке графа. Матрицы переходов (`SdstMatrix`) хранятся в эффективных `NumPy`-массивах с $\mathcal{O}(1)$ доступом.
- **Профилировщик задач:** Перед запуском `ProblemProfile` вычисляет профиль признаков (объем, плотность setup-матрицы, наличие non-zero setups, доля hard-deadline заказов, max-parallel профиль), чтобы выбирать подходящий solver-path без лишних вычислений.
- **Control-Plane BFF:** Типизированный TypeScript/Fastify мост для индустриальных сервисов, изолирующий процесс оптимизации от web-слоя.
- **Feasibility Checker:** Абсолютный "zero-trust" барьер. Независимый 7-классовый event-sweep алгоритм прочесывает финальное расписание. Если RHC сломал прецедент или ALNS превысил емкость инструмента — расписание маркируется как `feasible = False` вне зависимости от внутренних репортов решателя.
- **Инструментация:** Подключаемые логгеры метрик собирают телеметрию (глубина фронтира, счетчики отсечений, тайминги) без загрязнения алгоритмического кода.

## Что реализовано, а что нет

### Реализовано (в этом репо, протестировано)

- Детерминированный портфель решателей (22 публичные конфигурации в реестре)
- CP-SAT с SDST, ARC, max_parallel
- LBBD и LBBD-HD с 4 семействами отсечений и параллельными подзадачами
- Greedy ATCS с log-пространством и штрафом за потери материала
- epsilon-constraint профили для trade-off по setup/tardiness/material-loss
- Incremental repair с настраиваемым порогом нервозности
- 7-классная валидация допустимости после каждого solve
- Профилировщик задач (ProblemProfile)
- Ресурсные ограничители (timeout, memory limits)
- Структурированная инструментация с подключаемыми коллекторами
- Версионированные JSON-контракты для TypeScript-интеграции
- ML advisory-слой с эвристическим предиктором и хуком в роутере
- Публичный реестр из 22 solver-конфигураций
- ALNS- и RHC-линейка для крупных и long-horizon сценариев
- Pressure-adaptive контур ALNS/RHC (dynamic no-improve + frontier-health metadata)
- Property-based тесты через Hypothesis
- Cross-solver consistency тесты
- Benchmark harness с регрессионными границами

### Не реализовано (roadmap)

- Event sourcing / CQRS
- Rust hot-path через PyO3 (шов есть, модуля нет)
- GNN-отсечения Бендерса (плейсхолдер в ml_advisory.py)
- LLM-пояснения для оператора
- Квантовый бэкенд
- NUMA pinning
- Промышленное развертывание на живом заводе

## Карта репозитория

| Путь | Что |
|------|-----|
| `synaps/solvers/` | Портфель решателей |
| `synaps/model.py` | Pydantic-модель данных |
| `synaps/ml_advisory.py` | ML advisory-слой |
| `synaps/guards.py` | Ресурсные ограничители |
| `synaps/instrumentation.py` | Сбор метрик |
| `synaps/contracts.py` | Версионированные JSON-контракты |
| `synaps/problem_profile.py` | Профилировщик задач |
| `benchmark/` | Воспроизводимый benchmark harness |
| `tests/` | 293 tests collected |
| `schema/contracts/` | JSON Schema для TypeScript |
| `control-plane/` | Минимальный TypeScript BFF |
| `docs/` | Архитектура, домены, исследования |

## Зависимости

| Пакет | Зачем | Лицензия |
|-------|-------|----------|
| OR-Tools 9.10 | CP-SAT солвер (C++ ядро) | Apache-2.0 |
| HiGHS 1.8+ | MIP солвер для LBBD мастера | MIT |
| Pydantic v2 | Модель данных и валидация | MIT |
| NumPy 2.1+ | Численные структуры и матрицы в solver-контуре | BSD-3-Clause |
| Hypothesis | Property-based тесты | MPL-2.0 |

Базовое ядро опирается на OR-Tools + HiGHS + Pydantic + NumPy. PyTorch присутствует только в optional extras для экспериментальных ML/RL треков.

## Границы заявлений

- Репозиторий не заявляет промышленную готовность, регуляторную готовность или сертифицированную интеграцию.
- Портфель решателей тестируется на синтетических бенчмарках (tiny/medium/medium-stress), не на данных живого завода.
- LOC и количество тестов измеряются автоматически и могут меняться между коммитами.

## Литература

- Pinedo M.L. (2016). *Scheduling: Theory, Algorithms, and Systems*, 4th ed.
- Allahverdi A. et al. (2008). A survey of scheduling problems with setup times or costs. *EJOR* 187(3).
- Lee Y.H., Bhaskaran K., Pinedo M. (1997). A heuristic to minimize total weighted tardiness with sequence-dependent setups. *IIE Transactions* 29(1).
- Hooker J.N., Ottosson G. (2003). Logic-Based Benders Decomposition. *Math. Programming* 96.
- Hooker J.N. (2007). *Integrated Methods for Optimization*, 2nd ed.
- Mavrotas G. (2009). Effective implementation of the epsilon-constraint method. *AMC* 213(2).

## Ссылки

- [Архитектура](docs/architecture/01_OVERVIEW.md) | [Бенчмарки](benchmark/README.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

---

<a id="synaps-in-english"></a>

# SynAPS in English

Deterministic-first scheduling engine for MO-FJSP-SDST-ARC planning problems.

## The problem

A cable factory: 50,000 operations, 100 work centers, 700,000 setup transitions. Five conflicting objectives. Commercial APS systems solve this behind closed code. Neural networks solve it without explanations. SynAPS solves it with a deterministic solver portfolio, an independent feasibility validator, and zero black boxes.

## Status

Code runs, tests pass, benchmarks reproduce. **Not tested on a live factory.** The gap between the current solver portfolio and the full target architecture is documented honestly.

## Fact-check (2026-04-16)

- Public solver registry: **22 configurations** (`available_solver_configs()`).
- Test collection: **293 tests collected** (`pytest --collect-only -q tests`).
- Python requirement: **>=3.12** (`pyproject.toml`).
- Core runtime dependencies: `ortools`, `highspy`, `pydantic`, `numpy`.

## 50K benchmark snapshot (industrial-50k)

Canonical artifact: `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`.

`summary_by_solver` snapshot:

| Solver | mean_wall_time_s | feasibility_rate | mean_peak_window_candidate | windows_solved | assignments |
|---|---:|---:|---:|---:|---:|
| `RHC-GREEDY` | 120.11 | 0.0 | 49 931 | 11 | 6 959 / 50 000 |
| `RHC-ALNS` | 366.23 | 0.0 | 49 993 | 3 | 1 078 / 50 000 |

This is a reproducible **partial** profiling slice (no full-fledged schedule), demonstrating the deterministic engine hitting an `error=status` time-budget limit. White-box telemetry immediately proves the next bottleneck isn't the first-window admission cap, but a massive dense `earliest-frontier candidate mass` (~49.9k). We publish this un-glamorous, erroring slice purposefully: deterministic tracking enables diagnostic progress on real bottlenecks instead of blinding black-box neural-network timeouts.

### The True Bottleneck

Following our recent elimination of the first-window trap (via dynamic limit capping and indexed slot-searches which boosted greedy progression out of hundreds and into nearly 7000 assignments), the bottleneck has receded directly into internal solver-route bandwidth. ALNS manages only `1078` assignments in 366 seconds against an overwhelming bulk of unassigned candidates. Going forward:
1. aggressively truncate and prioritize the `earliest-frontier` weight;
2. dramatically expedite internal large-neighborhood algorithms under dense constraints;
3. stiffen the `due-pressure path`.

## Spring 2026 updates

- `ALNS` and `RHC` models migrated thoroughly to public runtime surface.
- Fallback saving loops in `RHC` ensure that long-running tasks terminating with `status=error` or timeout correctly serialize partial assignments for bottleneck analysis instead of looping indefinitely.
- Pressure-adaptive ALNS no-improve controls (`due_pressure`, `candidate_pressure` factors on early termination).
- RHC-to-ALNS pressure context propagation across active windows.
- Frontier-health telemetry in RHC metadata (`candidate_pressure`, `due_drift_minutes`, `spillover_ops`).
- Updated strategic track reflecting recent 50k constraints: `docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md`.

## Solver portfolio

9 base solver classes, 22 public registry configurations, and 293 collected tests.

| Solver | Algorithm | Use case |
|--------|-----------|----------|
| CP-SAT Exact | Circuit + NoOverlap + Cumulative (OR-Tools 9.10) | Small/medium, provable optimality |
| LBBD | HiGHS MIP master + CP-SAT subproblems + 4 Benders cut families | Medium/large, gap-bounded |
| LBBD-HD | Parallel subproblems + ARC-aware partitioning | Thousands of operations |
| Greedy ATCS | Log-space ATCS (Lee, Bhaskaran & Pinedo 1997) | Feasible in < 1 s |
| Pareto Slice | Epsilon-constraint (Mavrotas 2009) | Trade-off comparison |
| Incremental Repair | Neighbourhood freeze + micro-CP-SAT | Live rescheduling |
| ALNS | Adaptive Large Neighborhood Search + micro repair | Large-scale instances (10k+) |
| RHC | Receding Horizon Control with inner solver | Long-horizon and very-large workloads |
| Portfolio Router | Deterministic tree + optional ML advisory | Same input, same solver |
| FeasibilityChecker | 7-class event-sweep | After every solve |

Additional: graph partitioning, registry with 22 public configurations, Pydantic data model, problem profiler, resource guards, instrumentation, versioned JSON contracts, TypeScript control-plane BFF.

## Architecture, Algorithms & Mathematics Detailed

Behind the OpenAPI/TypeScript facade lies a deeply layered mathematical core. The MO-FJSP-SDST-ARC problem (Multi-Objective Flexible Job Shop Scheduling with Sequence-Dependent Setup Times and Additional Resource Constraints) is notoriously NP-hard even in pure forms. SynAPS applies a hybrid methodology.

### 1. CP-SAT Formulation (Exact)
Instead of pure MIP with Big-M disjunctions (yielding weak LP relaxations), SynAPS directly compiles the problem into interval variables within a Constraint Programming paradigm (OR-Tools backend):
- **Sequencing & SDST:** Modeled using `AddCircuit` on machine-specific graphs to form a Hamiltonian sequence. The edge costs represent exact setup times. 
- **Additional Resources (ARC):** Modeled with global `AddCumulative` constraints. Resource demands span not just the processing periods, but also *setup intervals*, successfully mitigating the "ghost setup" bug common in simpler solvers (where setups occur without the necessary workforce/tooling allocated).
- **Multi-Objective Scalarization:** Objectives (makespan, tardiness, setups, material loss) are mapped dynamically via `Pareto Slice` (a 2-stage epsilon-constraint method) or linear aggregation.

### 2. Logic-Based Benders Decomposition (LBBD and LBBD-HD)
When CP-SAT crashes against 10,000+ operations, LBBD scales the exact logic:
- **Master Problem (HiGHS MIP):** Performs the assignment of operations to machines without explicit sequencing constraints, providing a robust lower bound.
- **Subproblems (CP-SAT):** Groups are segmented by machine/cluster and solved to check sequence feasibility. In `LBBD-HD` (High Density), subproblems run strictly in parallel via `ProcessPoolExecutor`.
- **Benders Cuts:** If a subproblem proves a sequence exceeds the Master's estimated makespan (due to SDST crowding or ARC bottlenecks), analytical logic constraints are generated. SynAPS uses 4 Benders cut families: *nogood, bottleneck capacity, setup-cost, and load-balance cuts* (Nasirian et al. 2025; Hooker 2007).

### 3. Large-Scale Meta-Heuristics (ALNS and RHC)
For industrial 50K+ benchmarks, the system relies on advanced meta-heuristics using exact engines as local repair operators:
- **ALNS (Adaptive Large Neighborhood Search):** The scheduler punches scheduling "holes" via 4 adaptive `destroy` operators (`random`, `worst`, `related`, `machine_segment`). The gap is repaired with greedy repair, and for small neighborhoods an optional `micro-CP-SAT repair` path can be enabled (`use_cpsat_repair`, `cpsat_max_destroy_ops`). Simulated Annealing (SA) acceptance avoids early local-minimum lock-in (Ropke & Pisinger 2006).
- **RHC (Receding Horizon Control):** Dissects the 50,000 timeline into overlapping windows (defaults: `window_minutes=480`, `overlap_minutes=120`) with operation caps per window (typically up to 5000). A window is solved (ALNS/CP-SAT/greedy), a fraction is committed (frozen), then the window slides right. April 2026 introduced *pressure-adaptive early-stop*: completion budgets adapt to `due_pressure` and `candidate_pressure` from the earliest-frontier queue.

### 4. Greedy Dispatching (Log-ATCS)
Securing an admissible schedule in < 1 second utilizes the Apparent Tardiness Cost with Setups (ATCS) index, massively hardened:
- **Log-space ATCS:** Operations with heavy-tailed setup distributions (e.g., 5 seconds processing vs. 2-hour setups) typically trigger deadly `float64 underflow` in raw exponential ATCS formulas. Ranking occurs in log-space entirely removing numerical collapse.
- **Beam Search:** An adjustable width (K=3..5) node expansion counters the hyper-myopia of naive greedy dispatchers, allowing limited lookahead at critical machine bottlenecks.

### 5. Software Architecture & Governance
- **Data Modeling:** Strict `Pydantic v2` definitions reject invalid domain contracts upfront. Transitional matrices (`SdstMatrix`) reside in memory-contiguous `NumPy` arrays for $O(1)$ solver reads.
- **Problem Profiler:** On ingest, `ProblemProfile` computes a compact feature profile (problem scale, setup density, non-zero setup presence, hard-deadline share, max-parallel profile) used to select the most suitable solver path.
- **Feasibility Checker:** The definitive zero-trust firewall. Uses a 7-class event-sweep algorithm outside the control of the active solver logic. If RHC or LBBD hallucinates an illegal precedence overlap or ARC violation, the schedule is explicitly flagged `feasible = False`. 
- **TypeScript Control-Plane BFF:** An enterprise-facing typed bridge that isolates non-deterministic UI/integrator logic from the rigorous Python kernel.

## Quick start

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"
python -m synaps solve benchmark/instances/tiny_3x3.json
pytest tests/ -v
```

## What's implemented vs. planned

**Implemented:** deterministic solver portfolio (including ALNS and RHC paths), SDST/ARC/max_parallel in CP-SAT, LBBD with 4 cut families, greedy ATCS in log-space, epsilon-constraint profiles, incremental repair, pressure-adaptive ALNS/RHC controls, feasibility validation, problem profiler, resource guards, instrumentation, versioned contracts, ML advisory layer, 22 public registry configurations, property-based and cross-solver tests.

**Roadmap:** event sourcing, Rust/PyO3 hot-path, GNN Benders cuts, LLM explanations, quantum backend, NUMA pinning, live factory deployment.

## Dependencies

OR-Tools 9.10+ (Apache-2.0), HiGHS 1.8+ (MIT), Pydantic v2 (MIT), NumPy 2.1+ (BSD-3-Clause), Hypothesis (MPL-2.0). PyTorch appears only in optional extras for experimental ML/RL tracks.

## References

Pinedo (2016), Allahverdi et al. (2008), Lee-Bhaskaran-Pinedo (1997), Hooker-Ottosson (2003), Hooker (2007), Mavrotas (2009).

## Links

[Architecture](docs/architecture/01_OVERVIEW.md) | [Benchmarks](benchmark/README.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

## License

MIT
