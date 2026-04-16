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

## Математика коротко

CP-SAT формулировка: `AddCircuit` для гамильтоновой последовательности на каждом станке (вместо квадратичных дизъюнкций), `AddCumulative` для пулов вспомогательных ресурсов с явными demands на setup-интервалы, скаляризованная многокритериальная целевая.

LBBD разрезает задачу: HiGHS MIP мастер раздает операции по станкам, CP-SAT подзадачи секвенируют внутри кластеров. Четыре семейства отсечений: nogood, bottleneck capacity, setup-cost, load-balance (Hooker 2007).

Greedy ATCS работает в log-пространстве, чтобы не тонуть в underflow на тяжелохвостых распределениях переналадок.

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
