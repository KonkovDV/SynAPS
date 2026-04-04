# SynAPS: Глубокий Технический Аудит (Deep Technical Audit)

> **Дата**: Апрель 2026
> **Версия**: 1.0.0
> **Статус**: COMPLETE — Фундаментальный аудит алгоритмического ядра, математическая архитектура, софтверный и аппаратный стек
> **Область**: `synaps/solvers/`, `synaps/model/`, целевая архитектура v2.0+

---

## Содержание

- [Часть I. Аудит Алгоритмического Ядра (5 Критических Дефектов)](#часть-i-аудит-алгоритмического-ядра)
- [Часть II. Математический Blueprint Целевой Архитектуры](#часть-ii-математический-blueprint-целевой-архитектуры)
- [Часть III. Квантовый и Нейро-Символический Уровень](#часть-iii-квантовый-и-нейро-символический-уровень)
- [Часть IV. Софтверный Стек (Software BOM)](#часть-iv-софтверный-стек)
- [Часть V. Аппаратный Стек (Hardware)](#часть-v-аппаратный-стек)
- [Часть VI. Дорожная Карта Имплементации](#часть-vi-дорожная-карта-имплементации)

---

## Часть I. Аудит Алгоритмического Ядра

На основе инспекции исходного кода (`synaps/solvers/`) выявлены **5 фундаментальных алгоритмических и математических дефектов** в детерминированном базисе (Greedy, CP-SAT, Repair). Эти ошибки **не связаны с ML-заглушками**, а касаются реализации ядра, делая планировщик непригодным для индустриальных масштабов без исправлений.

### Дефект 1. Катастрофическая сложность O(N³) в CP-SAT

**Файл**: `synaps/solvers/cpsat_solver.py`

Моделирование Sequence-Dependent Setup Times (SDST) реализовано через наивные вложенные циклы `first_operation → second_operation → third_operation` для каждой машины с генерацией булевых переменных связности (adjacency) и транзитивности (before).

```python
model.add(adjacent_var + before[(op1, op3)] + before[(op3, op2)] <= 2)
```

**Проблема**: Для одной машины с 50 операциями генерируется O(50³) = 125,000 булевых ограничений (clauses) ещё до начала решения (на этапе компиляции модели).

**Последствие**: Экспоненциальный взрыв памяти (RAM) и времени сборки SAT-модели (Presolve phase).

**Решение**: В OR-Tools (CP-SAT) для моделирования SDST следует использовать `CircuitConstraint` с дуговыми литералами (literal arcs) или `OptionalIntervalVar` для транзитных состояний, что переносит тяжесть комбинаторики внутрь C++ SAT-решателя.

### Дефект 2. Игнорирование Tardiness (сроков сдачи) в CP-SAT

**Файл**: `synaps/solvers/cpsat_solver.py`

Функция `_build_weighted_objective` формирует целевую функцию как взвешенную сумму:

```python
model.minimize(makespan * 100 + total_setup_penalty + total_material_penalty)
```

**Проблема**: В то время как `greedy_dispatch.py` корректно учитывает сроки сдачи (`due_date`), в математической модели CP-SAT штрафы за срыв сроков (Tardiness) **абсолютно отсутствуют**.

**Последствие**: Точный решатель (CP-SAT) не видит разницы между срочным заказом и заказом на следующий месяц. Он будет минимизировать только Makespan и переналадки, откладывая приоритетные заказы ради уплотнения расписания.

**Решение**: Добавить переменные завершения для каждого заказа (как максимум от `ends` его операций), вычитать `due_offset` и вводить штраф `total_tardiness_penalty` в `model.minimize()`.

### Дефект 3. Игнорирование приоритетов при инкрементальном ремонте (Priority Starvation)

**Файл**: `synaps/solvers/incremental_repair.py`

Алгоритм сортирует список операций на перепланирование по `seq_in_order` и `priority`. Однако в самом цикле выбора кандидата:

```python
candidate_key = (slot.end_offset, slot.start_offset, operation.seq_in_order)
if best_candidate is None or candidate_key < best_candidate[:3]:
    best_candidate = ...
```

**Проблема**: Выбор кандидата производится **исключительно** по метрике раннего завершения (`end_offset`). Сортировка исходного списка игнорируется, так как в блоке `ready` перебираются все доступные операции, и выигрывает та, которая завершится раньше.

**Последствие**: Если в слот влезает низкоприоритетная короткая операция, она всегда обойдет высокоприоритетную критическую задачу, которая дольше выполняется. Это приводит к сильным искажениям JIT/Priority метрик после любого локального ремонта.

**Решение**: Заменить кортеж `candidate_key` на `(-orders_by_id[operation.order_id].priority, slot.end_offset, ...)`, чтобы приоритет стал критическим фактором выбора первой доступной операции.

### Дефект 4. Десинхронизация Assignment.setup_minutes при вставке в Gap

**Файлы**: `synaps/solvers/_dispatch_support.py`, `synaps/solvers/greedy_dispatch.py`

Алгоритм `evaluate_gap` учитывает новые переналадки перед вставляемой операцией и после нее (`setup_after`). 

**Проблема**: В решателях (`greedy_dispatch.py`, `incremental_repair.py`) происходит корректный пересчёт глобальной метрики `ObjectiveValues.total_setup_minutes` в самом конце. Однако в самом расписании (объектах `Assignment`) значение `setup_minutes` для смещенной (следующей) операции **никогда не обновляется**.

**Последствие**: Клиент системы (UI, цифровой двойник) получает объекты `Assignment`, в которых `setup_minutes` содержит устаревшие данные (от старой последовательности до инкрементальной вставки), что ломает визуализацию диаграммы Ганта и тарификацию работы бригад.

**Решение**: Внедрить процедуру обновления, которая после каждой вставки в Gap обновляет мутабельный объект `Assignment` для смещённой `following` операции.

### Дефект 5. Игнорирование AuxiliaryResources во время переналадки

**Файлы**: `synaps/solvers/cpsat_solver.py`, `synaps/solvers/_dispatch_support.py`

Математическая модель в обоих решателях накладывает ресурсные ограничения (cumulative constraints) исключительно на отрезки процессинга (Processing Intervals).

**Проблема**: Если переналадка длится 60 минут (setup_minutes), она не резервирует AuxiliaryResource (например, бригаду наладчиков). Система считает, что переналадки происходят «магически».

**Последствие**: Если две машины требуют переналадки одновременно, а бригада одна — расписание окажется физически невыполнимым (Infeasible in real-world).

**Решение**: Интервалы вспомогательных ресурсов должны покрывать [T_start − SETUP_DURATION, T_end] (от начала переналадки до конца процессинга), либо переналадка должна быть выделена в отдельный зависимый IntervalVar (Dummy Operation).

---

## Часть II. Математический Blueprint Целевой Архитектуры

### 1. Рефакторинг CP-SAT: Optional Interval Variables + CircuitConstraint

Вместо N³ булевых ограничений, для каждой машины создаётся `NoOverlap` над массивом интервалов с `CircuitConstraint`.

Пусть O_{ik} — интервал выполнения операции i на машине k.
Вводятся Dummy Transition Intervals S_{ijk} (фиктивные интервалы переналадки):

1. Создаём интервальные переменные операций: `Presence(i,k) ⇒ Interval(start_i, end_i, duration_i)`.
2. Создаём дуговые булевы переменные x_{ijk} ∈ {0, 1}, равные 1 если операция j следует за i на машине k.
3. Замыкаем в `CircuitConstraint` — автоматическое отсечение субтуров, O(N) внутри SAT-движка.
4. Интервал переналадки S_{ijk}: `Start = end_i`, `End = start_j`, `Duration = SetupMatrix(State(i), State(j))`.

**Решение проблемы ARC**: Интервал S_{ijk} передаётся в глобальное `CumulativeConstraint`:

```
∑_{i,j,k} I(t ∈ S_{ijk}) · Demand(R_a) ≤ Capacity(R_a)   ∀t
```

**Итог**: Модель сжимается с 125,000 ограничений до ~500 высокоуровневых Global Constraints.

### 2. Logic-Based Benders Decomposition (LBBD)

Для масштаба >10,000 операций — декомпозиция по Hooker & Ottosson (2003).

**Master Problem (HiGHS)**: Назначение операций на машины y_{ik} ∈ {0, 1}:
```
min C_max
s.t. ∑_{k ∈ Eligible(i)} y_{ik} = 1    ∀i
     ∑_i P_{ik} · y_{ik} ≤ C_max       ∀k
```

**Subproblem (CP-SAT)**: Для фиксированного вектора ȳ — независимые подзадачи на каждую машину k.

**Benders Cut**: Если CP-SAT находит C^{CP}_{max} > C*_{max}:
```
C_max ≥ C^{CP}_{max} − ∑_{i ∈ BottleneckSet} P_{ik} · (1 − y_{ik})
```

### 3. Heterogeneous Graph Attention Networks (HGAT)

Завод как гетерогенный граф G = (V, E):
- V_{op}: Узлы операций. Features: [p_i, DueDate, Priority, Slack, StateEmbedding].
- V_{mc}: Узлы машин. Features: [SpeedFactor, QueueLength, CurrentState].
- E_{prec}: Рёбра маршрута (Precedence).
- E_{elig}: Рёбра совместимости (Operation → Machine).

Message Passing с Attention и учётом Setup:
```
h_i^{(l+1)} = σ( ∑_r ∑_{j ∈ N_r(i)} α_{ij}^r · W_r · h_j^{(l)} )
α_{ij}^r = softmax_j( LeakyReLU( a_r^T [W_r h_i || W_r h_j || ΔS_{ij}] ) )
```

Выход сети предсказывает: динамические K₁, K₂ для ATCS и вероятности ветвления для CP-SAT.

### 4. Conservative Q-Learning (CQL) — Offline RL

MDP-формализация:
- **State s_t**: Выходные эмбеддинги HGAT.
- **Action a_t**: Выбор операции j из очереди `ready` и машины k. Action Masking.
- **Reward r_t**: Степенная скаляризация 6 критериев.

CQL Loss (Kumar et al., 2020):
```
L(θ) = α · E_{s~D, a~μ}[Q_θ(s,a)] − α · E_{s,a~D}[Q_θ(s,a)]
       + ½ · E_{s,a,s'~D}[(Q_θ − B̂^π Q_θ)²]
```

---

## Часть III. Квантовый и Нейро-Символический Уровень

### 1. QUBO-трансляция для квантовых аннилеров

Бинарная параметризация: x_{i,m,t} ∈ {0,1} (операция i, машина m, момент t).

Энергетическая функция (Ising Hamiltonian):
```
min H = H_Obj + α·H_Assign + β·H_Prec + γ·H_Overlap + δ·H_SDST
```

**H_Assign** (уникальность назначения):
```
H_Assign = ∑_i (1 − ∑_{m,t} x_{i,m,t})²
```

**H_SDST** (Sequence-Dependent Setup — квадратичная часть QUBO):
```
H_SDST = ∑_m ∑_{i≠j} ∑_t ∑_{t'=t+p+1}^{t+p+S-1} x_{i,m,t} · x_{j,m,t'}
```

На квантовой решётке (D-Wave Advantage, 5000+ qubits, Pegasus topology) квадратичная часть решается параллельными кубитами за O(1) мкс (эффект туннелирования).

### 2. QAOA (Gate-Based)

Для IBM Quantum (Condor 1000+ qubits) через PennyLane v0.44:
1. Классический контур ищет параметры γ, β.
2. QPU симулирует эволюцию, возвращает градиенты (Parameter Shift Rule).
3. PennyLane v0.44 NEW: QRAM, IQP circuits, Resource Estimation для FTQC.

### 3. Differentiable CP (Нейро-символический солвер)

Gumbel-Sinkhorn Softmax + Blackbox Differentiation:
```
min_θ E_{y ~ P_θ(·|G)} [F(y)] + λ·Φ(y)
```
Φ(y) — нейро-дифференцируемый пенализатор нарушений физики.

### 4. Diffusion Decision Transformer (Diff-DT)

Диффузионная модель генерирует расписание как «картинку» (матрицу стартов x_{i,m}). Кондиционируется на граф текущего состояния цеха. Безопасное offline обучение на исторических данных ERP/MES.

### 5. Robust Optimization (Bertsimas-Sim)

Допуск неопределённости (Budget of Uncertainty Γ):
```
min (cx + zΓ + ∑p_j)
```
Расписание на 3-5% медленнее абсолютного оптимума, но шанс выжить при сбоях возрастает на ~80%.

### 6. Federated GNN (FedGraph)

Каждый завод обучает локальную GIN модель θ_K.
Глобальная агрегация:
```
θ_global = ∑ (n_k / N) · θ_K    (FedAvg / FedProx)
```
Дистиллированное «знание об изоморфных бутылочных горлышках» скачивается обратно на заводы.

---

## Часть IV. Софтверный Стек

### 1. Ядро Constraint Programming и Mixed-Integer Optimization

| Компонент | Версия (Апрель 2026) | Роль в SynAPS |
|---|---|---|
| **Google OR-Tools** | **v9.15** (Январь 2026) | CP-SAT, CircuitConstraint, NoOverlap, Cumulative. Set Variables (experimental), Scheduling Cuts, Shared Tree Workers, Column Generation CFT |
| **HiGHS** | **v1.12.0** | Master Problem в LBBD (LP/MIP), балансировка нагрузки. Solution Hints из MathOpt |
| **SCIP** | **v10.0.0** | Резервный MIP для MINLP. Переход с GLOP на SOPLEX |
| **Gurobi** | **13.0.0** | Коммерческий (опционально). Lazy Constraints, XPressMP |

### 2. Machine Learning & Graph Neural Networks

| Компонент | Версия | Роль |
|---|---|---|
| **PyTorch** | 2.6+ | Базовый фреймворк (Autograd, CUDA, TorchScript) |
| **PyTorch Geometric (PyG)** | 2.7+ | HGAT (HeteroData, HGTConv, to_hetero) |
| **TorchRL** | 0.8+ | Offline RL (CQL, Decision Transformer) |
| **ONNX Runtime** | 1.21+ | Кросс-платформенный edge-инференс |
| **NVIDIA TensorRT** | 10.9+ | Квантизация FP8/FP4/INT8. Tripy frontend |
| **TensorRT Model Optimizer** | 0.25+ | AWQ, Speculative Decoding, Pruning/Distillation |
| **JAX** | 0.5+ | Дифференцируемые солверы (Gumbel-Sinkhorn, DFL) |

### 3. Цифровой Двойник (Discrete-Event Simulation)

| Компонент | Версия | Роль |
|---|---|---|
| **SimPy** | 4.1+ | DES-ядро (процессы, ресурсы, очереди) |
| **Polars** | 1.20+ | Обработка логов (10× быстрее Pandas) |
| **DuckDB** | 1.3+ | OLAP-аналитика внутри процесса |

### 4. Квантовые вычисления

| Компонент | Версия | Роль |
|---|---|---|
| **D-Wave Ocean SDK** | 8.0+ | QUBO, QPU Advantage 5000+ qubits |
| **PennyLane** | **v0.44** (Январь 2026) | QAOA, QRAM (NEW), IQP, Resource Estimation FTQC |
| **PennyLane Catalyst** | **v0.14** | JIT-компиляция квантовых программ |
| **Qiskit** | 1.4+ | Резервный backend (IBM Condor 1000+ qubits) |

### 5. Federated Learning

| Компонент | Версия | Роль |
|---|---|---|
| **Flower (flwr)** | 1.16+ | FedAvg, FedProx, FedOpt |
| **gRPC** | 1.70+ | Транспорт (secure, mTLS) |

### 6. Высокопроизводительный бэкенд (Rust FFI)

| Компонент | Версия | Роль |
|---|---|---|
| **Rust** | 1.84+ | Критический путь: парсинг Setup Matrix, графы, ATCS-индекс |
| **PyO3** | 0.24+ | Rust → Python (GIL-free) |
| **Maturin** | 1.9+ | Сборка Rust-расширений в wheel |
| **Rayon** | 1.10+ | Параллелизм (thread pool) |

### 7. API и Развертывание

| Компонент | Версия | Роль |
|---|---|---|
| **FastAPI** | 0.115+ | REST/WebSocket API |
| **Uvicorn** | 0.34+ | ASGI-сервер |
| **PostgreSQL** | 17+ | Расписания, SDST-матрицы |
| **pgvector** | 0.8+ | Embeddings GNN |
| **TimescaleDB** | 2.18+ | IoT-телеметрия |
| **Redis** | 7.4+ | Кеш расписаний, Lock |
| **Docker** | 27+ | Multi-stage (Rust+Python build) |
| **Kubernetes** | 1.32+ | Solver-поды, ML-поды, Edge-синхронизация |

### 8. Observability

| Компонент | Версия | Роль |
|---|---|---|
| **OpenTelemetry** | 1.30+ | Трейсинг (build_model → solve → extract) |
| **Prometheus** | 2.58+ | Метрики: makespan, solve_time_ms, tardiness |
| **Grafana** | 11+ | Dashboards, Gantt, Парето-фронт |

### 9. Тестирование и CI/CD

| Компонент | Версия | Роль |
|---|---|---|
| **pytest** | 8.4+ | Unit/Integration |
| **Hypothesis** | 6.120+ | Property-Based Testing |
| **pytest-benchmark** | 5.1+ | Бенчмарки солверов |
| **Ruff** | 0.9+ | Линтер/форматтер |
| **mypy** | 1.14+ | Статическая типизация |

### 10. Software BOM (Bill of Materials)

```yaml
# SynAPS Software BOM — April 2026 (pinned)
python: ">=3.12,<3.15"

# OR / Solvers
ortools: "9.15.6755"
highspy: "1.12.0"

# ML / DL
torch: ">=2.6.0"
torch-geometric: ">=2.7.0"
torchrl: ">=0.8.0"
onnxruntime-gpu: ">=1.21.0"

# Simulation
simpy: ">=4.1.0"
polars: ">=1.20.0"
duckdb: ">=1.3.0"

# Quantum
pennylane: "0.44.0"
pennylane-lightning: "0.44.0"
dwave-ocean-sdk: ">=8.0.0"

# API
fastapi: ">=0.115.0"
uvicorn: ">=0.34.0"
pydantic: ">=2.11.0"

# DB
asyncpg: ">=0.30.0"
pgvector: ">=0.3.7"
redis: ">=5.2.0"

# Observability
opentelemetry-sdk: ">=1.30.0"
prometheus-client: ">=0.22.0"

# Rust Extensions (via maturin)
pyo3: "0.24"
maturin: "1.9"

# Testing
pytest: ">=8.4.0"
hypothesis: ">=6.120.0"
pytest-benchmark: ">=5.1.0"
ruff: ">=0.9.0"
mypy: ">=1.14.0"

# Federated Learning
flwr: ">=1.16.0"
```

---

## Часть V. Аппаратный Стек

### 1. Серверная инфраструктура (Data Center / Cloud)

| Уровень | Рекомендация (Апрель 2026) | Спецификация | Назначение |
|---|---|---|---|
| **CPU (Solver)** | AMD EPYC 9654 (Genoa) / Intel Xeon w9-3595X | 96C/192T, 384MB L3 | CP-SAT Shared Tree Workers, HiGHS MIP |
| **GPU (Train)** | NVIDIA H100 SXM (80GB) | 3958 TFLOPS FP8, NVLink 4.0 | Обучение HGAT + CQL |
| **GPU (Infer)** | NVIDIA L40S / L4 | 362 TFLOPS FP8 (L40S) | Инференс GNN, TensorRT FP8 |
| **RAM** | DDR5-5600 ECC, 512GB+ | — | CP-SAT модели >50K переменных потребляют 64-128 GB |
| **Storage** | NVMe PCIe 5.0, 2TB+ | 14 GB/s seq read | Логи симуляций (Polars/DuckDB) |
| **Quantum Cloud** | D-Wave Leap (Advantage QPU) | 5000+ qubits, Pegasus | QUBO-подзадачи (<200 переменных) |
| **Quantum Gate** | IBM Quantum (Condor 1000+ q) | 99.5% 2Q gate fidelity | QAOA через PennyLane/Qiskit |

### 2. Edge-уровень (Производственный цех)

| Устройство | Спецификация | Назначение | Цена (USD) |
|---|---|---|---|
| **Jetson AGX Orin 64GB** | **275 TOPS**, 2048 CUDA, 64 Tensor Cores, 60W | Edge-контроллер: GNN-инференс (<5 мс), Greedy Dispatch, Incremental Repair | ~$1,999 |
| **Jetson Orin NX 16GB** | **157 TOPS**, 1024 CUDA, 25W | Edge-узел на станок (Predictive Maintenance) | ~$599 |
| **Jetson Orin Nano Super** | **67 TOPS**, 1024 CUDA, 25W | Бюджетный датчиковый узел | $249 |
| **NVIDIA IGX Orin** | Industrial IP67, -25..+80°C | IEC 61508 SIL-2 (фармацевтика, атомная) | ~$3,500 |

### 3. Edge Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FACTORY FLOOR                         │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│  │ CNC #1   │  │ CNC #2   │  │ Press #1 │  ...         │
│  │ OPC UA   │  │ OPC UA   │  │ OPC UA   │              │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘              │
│       └──────────────┼──────────────┘                    │
│                      │ MQTT v5 / OPC UA                  │
│              ┌───────▼────────┐                          │
│              │ Jetson AGX     │  ← GNN Inference (5ms)   │
│              │ Orin 64GB      │  ← Greedy Dispatch       │
│              │ (275 TOPS)     │  ← Incremental Repair    │
│              └───────┬────────┘                          │
│                      │ 5G URLLC / Wi-Fi 7                │
└──────────────────────┼──────────────────────────────────┘
                       │
              ┌────────▼────────┐
              │  Data Center    │  ← CP-SAT (full solve)
              │  EPYC + H100   │  ← LBBD Master Problem
              │                 │  ← CQL Training
              │                 │  ← D-Wave QUBO (cloud)
              └─────────────────┘
```

### 4. Networking и IoT-протоколы

| Протокол | Использование |
|---|---|
| **OPC UA** (IEC 62541) | SCADA/PLC → SynAPS: данные станков |
| **MQTT v5** (ISO/IEC 20922) | IoT-телеметрия, триггеры перерасчёта |
| **gRPC + mTLS** | Inter-service, Federated Learning (Flower) |
| **5G URLLC** | Ultra-Reliable Low Latency (<1 мс) |
| **Wi-Fi 7** (802.11be) | Внутрицеховая (>40 Гбит/с, Multi-Link) |

### 5. Конфигурации по масштабу

| Параметр | Минимум (PoC) | Рекомендация (Средний завод) | Максимум (10+ заводов) |
|---|---|---|---|
| **CPU** | Ryzen 9 7950X (16C) | EPYC 9354 (32C) | 2× EPYC 9654 (192C) |
| **RAM** | 64 GB DDR5 | 256 GB DDR5 ECC | 1 TB DDR5 ECC |
| **GPU (Train)** | RTX 4090 (24GB) | 1× H100 (80GB) | 8× H100 NVLink |
| **GPU (Infer)** | CPU-only ONNX | 1× L4 (24GB) | 4× L40S |
| **Edge** | Jetson Orin Nano Super ($249) | Jetson AGX Orin 64GB | IGX Orin Industrial |
| **Quantum** | PennyLane Lightning Sim | D-Wave Leap Hybrid v2 | D-Wave Advantage + IBM Condor |
| **Storage** | 1TB NVMe | 4TB NVMe RAID-1 | 100TB+ (NetApp/Pure Storage) |
| **Бюджет (HW)** | ~$5K | ~$50K-100K | ~$500K-2M |

---

## Часть VI. Дорожная Карта Имплементации

| Фаза | Вектор | Практический шаг | Срок |
|---|---|---|---|
| **Q2 2026** | Differentiable Heuristics | Переписать `greedy_dispatch.py` с JAX/PyTorch тензорами. Градиентная оптимизация K₁, K₂ | 1-2 мес |
| **Q2 2026** | Critical Bug Fixes | Исправить Дефекты 1-5 (CP-SAT CircuitConstraint, Tardiness per-order, Radius buffer, Setup metrics, ARC during setup) | 1 мес |
| **Q3 2026** | Robust LBBD | HiGHS Master + CP-SAT Subproblems + Bertsimas-Sim Robust Optimization | 2-3 мес |
| **Q4 2026** | GNN + Diffusion Advisory | PyG 2.7 HGAT, Diffusion Decision Transformer, CQL через TorchRL | 3-4 мес |
| **H1 2027** | Quantum API (QUBO) | QuboTranslator(BaseSolver) на D-Wave Ocean SDK + PennyLane QAOA | 3 мес |
| **H1 2027** | Rust Critical Path | PyO3 FFI для ATCS-индекса, Setup Matrix парсинга, граф-хеширования | 2 мес |
| **H2 2027** | Federated Learning | Flower FedGraph для мультизаводской агрегации GNN | 2-3 мес |
| **H2 2027** | Edge Deployment | TensorRT FP8 + Jetson AGX Orin. Digital Twin (SimPy + MQTT) | 3-4 мес |

---

## Ссылки

### Академические публикации
- Laborie, P., Rogerie, J., Shaw, P., & Vilím, P. (2018). IBM ILOG CP Optimizer for Scheduling. *Constraints*, 23(2), 210-250.
- Perron, L., & Furnon, V. (2023). OR-Tools. Google.
- Hooker, J. N., & Ottosson, G. (2003). Logic-Based Benders Decomposition. *Mathematical Programming*, 96(1), 33-60.
- Kumar, A., et al. (2020). Conservative Q-Learning for Offline RL. *NeurIPS*.
- Wang, X., et al. (2022). Heterogeneous Graph Attention Network. *WWW*.
- Bertsimas, D., & Sim, M. (2004). The price of robustness. *Operations Research*, 52(1), 35-53.

### Связанные документы SynAPS
- `research/SYNAPS_MASTER_BLUEPRINT.md` — Сводный стратегический отчёт V3-V4
- `research/SYNAPS_OSS_STACK_2026.md` — Аудит Open-Source стека (предыдущая версия)
- `docs/architecture/03_SOLVER_PORTFOLIO.md` — Архитектура солверного портфеля
- `docs/research/LITERATURE_REVIEW.md` — Обзор литературы
- `docs/research/RESEARCH_ROADMAP_2025_2075.md` — Исследовательская дорожная карта
