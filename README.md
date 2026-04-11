# SynAPS

Детерминированный движок планирования производства для задач класса **MO-FJSP-SDST-ARC** (multi-objective flexible job-shop scheduling with sequence-dependent setup times and auxiliary resource constraints).

Восемь решателей. Независимый валидатор после каждого вызова. Невыполнимое расписание не выходит из движка. Открытый код.

Language: [EN](#synaps-in-english) | **RU**

---

## Предыстория

29 марта 2026 года я был на [открытой лекции Яна Анисова](https://www.mkm.ru/news/AKTIVNAYA-IT-VESNA-S--MOSITLAB---SERIYA-MEROPRIYATIY-S-YANOM-ANISOVYM/) (гендиректор «МОСИТЛАБ», руководитель направления развития производственной инфраструктуры ГК «Москабельмет») в НИТУ МИСиС. На слайдах — кейс APS Инфимум для кабельного завода: 50 000 операций, 100 рабочих центров, 700 000 вариантов переналадок. Пять целевых функций, которые грызутся между собой. Результат внедрения — 27 дней экономии в год, ~1.2 млрд рублей.

Архитектура на слайде: GREED → Encoder (сжатие 50 000 операций в 10 000 агрегированных) → нейросетевое ядро → GREED → готовый план. Работает. Но нейросеть — чёрный ящик: скажет «ставь заказ 4817 на станок 23 в 14:20», а почему — не скажет.

Я начал писать SynAPS — движок, где каждое решение можно вскрыть: *вот почему*. Не нейросеть. Портфель детерминированных решателей, каждый прогоняется через независимый валидатор допустимости.

## Статус

Код работает, тесты проходят, бенчмарки воспроизводятся. На живом заводе **не тестировалось**. Зазор между текущим портфелем решателей и полной целевой архитектурой документирован в разделе «Что реализовано, а что нет».

**Метрики:** `synaps/` 6 967 LOC · solvers 4 719 LOC · 218 тестов в 31 модуле (5 283 LOC тестового кода).

---

## Задача: MO-FJSP-SDST-ARC

В академии это зовут **multi-objective flexible job-shop scheduling with sequence-dependent setup times and auxiliary resource constraints**. Конкретика:

- $N$ операций раскидать по $M$ рабочим центрам (у Москабельмета: $N = 50\,000$, $M = 100$).
- $\lvert\text{SDST}\rvert$ вариантов переналадок — длительность перехода зависит от пары (что стояло → что встаёт). У Москабельмета: $700\,000$ ячеек.
- Вспомогательные ресурсы (краны, операторы, стенды) с ограниченным пулом.
- Пять конфликтующих целевых функций: простои, переналадки, потери материала, отклонение от предыдущего плана, равномерность загрузки.

NP-трудность. Allahverdi et al. (2008) написали обзор на 60 страниц только про задачи с переналадками.

---

## Портфель решателей

| Решатель | Алгоритм | LOC | Когда нужен |
|----------|----------|-----|-------------|
| **CP-SAT Exact** | `AddCircuit` + `NoOverlap` + `Cumulative`, OR-Tools 9.10 | 688 | Малые/средние, доказуемый оптимум |
| **LBBD** | HiGHS MIP мастер + CP-SAT подзадачи + 4 семейства отсечений Бендерса | 856 | Средние/крупные, сходимость по gap |
| **LBBD-HD** | `ProcessPoolExecutor` + ARC-aware разбиение + топологическая сборка по Кану | 1 247 | Тысячи операций, параллельные кластеры |
| **Greedy ATCS** | Логарифмический ATCS-индекс (Lee, Bhaskaran & Pinedo 1997) с расширенным K3 | 261 | Допустимое расписание за < 1 с |
| **Pareto Slice** | Двухэтапный ε-constraint (Haimes 1971, Mavrotas 2009) | 86 | Сравнение альтернатив для планового отдела |
| **Incremental Repair** | Заморозка + окрестностный re-dispatch + micro-CP-SAT fallback | 281 | Ремонт на лету, < 5% нервозности |
| **Portfolio Router** | Детерминированное дерево: режим × размер × латентность + ML advisory хук | 275 | Один вход → один решатель → строка в логе |
| **FeasibilityChecker** | 7-классный event-sweep валидатор. Не знает, кто работал | 356 | После каждого `solve()` |

Дополнительно: графовое разбиение (213 LOC), реестр решателей с 13 отраслевыми пресетами, ML advisory-слой, версионированные JSON-контракты, TypeScript control-plane BFF.

---

## Математика

### CP-SAT: constraint programming + SAT + linear relaxation

Google OR-Tools CP-SAT — гибрид: constraint propagation + clause learning + lazy clause generation + LP relaxation. C++ ядро, Python — только генерация protobuf-модели.

**Переменные:**
- $x_{ij} \in \{0,1\}$: операция $i$ назначена на рабочий центр $j$
- $\text{start}_i, \text{end}_i \in \mathbb{Z}$: интервал операции
- $\pi_{jk}$: переменная порядка для `AddCircuit` (гамильтонов путь на станке)

**Ключевые ограничения:**

1. **Назначение:** каждая операция ровно на одном станке из допустимых.

$$\sum_{j \in E_i} x_{ij} = 1 \quad \forall i$$

2. **No-overlap с переналадками:** `AddCircuit` задаёт гамильтонов путь по дуговым литералам. Каждая дуга $(i, j)$ на станке $m$ привязана к литералу $l_{ij}^m$ и setup-интервалу длины $s_{\text{state}(i) \to \text{state}(j)}^m$ из SDST-матрицы. Вместо квадратичного числа дизъюнктивных ограничений — один граф. На 120 операциях разница между «решил за 8 секунд» и «не решил за 60».

3. **Cumulative для вспомогательных ресурсов:** мостовой кран с `pool_size=1` — кумулятивное ограничение. Операции *и переналадки* резервируют ресурс одновременно (ghost setup fix):

$$\sum_{i: \text{active}(i, t)} q_{ir} \leq C_r \quad \forall r, \forall t$$

4. **Прецеденты:** $\text{end}_{\text{pred}(i)} \leq \text{start}_i$

5. **Целевая функция:** скаляризованная комбинация:

$$\min \; \alpha \cdot C_{\max} + \beta \cdot \sum_i T_i + \gamma \cdot \sum_{(i,j)} s_{ij} + \delta \cdot \sum_{(i,j)} m_{ij}$$

где $T_i = \max(0, \text{end}_i - d_i)$, $s_{ij}$ — время переналадки, $m_{ij}$ — потери материала.

### LBBD: Logic-Based Benders Decomposition

Hooker & Ottosson (2003). Разрезаем задачу: мастер раздаёт операции по станкам, подзадачи секвенируют внутри кластеров.

**Master (HiGHS MIP):**

$$\min \; \eta + c^T y \quad \text{s.t.} \quad \sum_{j \in E_i} y_{ij} = 1 \; \forall i, \quad \eta \geq \text{Benders cuts}$$

**Subproblems (CP-SAT по кластерам):** локальный scheduling с фиксированными назначениями, SDST, cumulative для ARC.

**Четыре семейства отсечений:**

| Отсечение | Формула | Что делает |
|-----------|---------|------------|
| **Nogood** | $\sum_{(i,j) \in S_\text{inf}} (1 - y_{ij}) \geq 1$ | Запрещает несовместимую комбинацию назначений |
| **Capacity** | $\eta \geq \frac{\sum_{i \in \mathcal{C}_k} p_i + \sum s_{ij}}{\lvert\text{machines}\rvert}$ | Нижняя граница по bottleneck-ресурсу |
| **Setup-cost** | $\eta \geq \text{actual\_cost}_k$ | Мастер недооценил SDST — вот реальная стоимость |
| **Load-balance** | $C_{\max} \geq \sum_i p_i / M$ | Тривиальная, но мастер-релаксация её забывает |

На 500 операциях LBBD сходится за 3–5 итераций до gap < 5%, когда монолитный CP-SAT застывает на gap 42%.

### LBBD-HD: параллельная промышленная декомпозиция

Самый толстый модуль (1 247 LOC). `ProcessPoolExecutor` с числом воркеров = числу кластеров. GIL обходится через процессы, не потоки. ARC-aware кластеризация: операции с общим вспомогательным ресурсом попадают в один кластер, чтобы cumulative-ограничения решались локально. Greedy warm start ускоряет CP-SAT подзадачи через `model.AddHint()`. Топологическая пост-сборка по Кану для глобальной консистентности прецедентов.

### Greedy ATCS: log-пространство и underflow

ATCS — Apparent Tardiness Cost with Setups (Lee, Bhaskaran & Pinedo, 1997):

$$I_j = \frac{w_j}{p_j} \cdot \exp\!\left(-\frac{\max(d_j - p_j - t, 0)}{K_1 \bar{p}}\right) \cdot \exp\!\left(-\frac{s_{lj}}{K_2 \bar{s}}\right)$$

На жирнохвостых распределениях переналадок (металлургия: 5 мин или 240 мин) `exp(-480)` = $10^{-208}$. IEEE 754 double отдаёт ноль. Все кандидаты с тяжёлой переналадкой схлопываются в 0.0, argmax тыкает пальцем в небо.

Перевод в log-пространство + расширение формулы коэффициентом $K_3$ за потери материала:

$$\log I_j = \log w_j - \log p_j - \frac{\text{slack}_j}{K_1 \bar{p}} - \frac{s_{lj}}{K_2 \bar{s}} - \frac{m_{lj}}{K_3 \bar{m}}$$

$K_3$ — расширение оригинальной формулы. У Lee-Bhaskaran-Pinedo (1997) потери материала не моделировались: в их задаче переналадка — только время. В кабельном производстве, металлургии, фармацевтике переналадка — это ещё тонны лома и мегаватт-часы.

### Почему не генетические алгоритмы

GA не дают нижнюю границу. GA скажет «makespan 420 мин». Лучше ли, чем 415? GA не знает. CP-SAT и LBBD дают gap — расстояние от решения до доказанного оптимума. Для планового отдела: «расписание на 5% хуже оптимума» vs «расписание, и мы не знаем насколько хорошее».

У метаэвристик нет встроенной гарантии допустимости. SA может пересечь два задания на станке — узнаете, когда кран приедет не туда.

---

## Переналадки: SDST-матрица

Длительность перехода зависит от пары (что стояло → что встаёт). Квадратичная матрица.

Каждая ячейка в SynAPS — отдельный объект:

```python
class SetupEntry(BaseModel):
    work_center_id: UUID
    from_state_id: UUID
    to_state_id: UUID
    setup_minutes: int
    material_loss: float = 0.0   # доля потерь
    energy_kwh: float = 0.0      # энергозатраты
```

**Примеры по индустриям:**

| Индустрия | Операция перехода | Время | Асимметрия | ARC |
|-----------|-------------------|-------|------------|-----|
| **Кабель** | Смена оснастки экструдера | 15–240 мин (по диаметру жилы) | Средняя | Мостовой кран, ОТК |
| **Сталь** | Высокоуглер. → низкоуглер. | 4 часа | Обратно — 30 мин | Ковш, МНЛЗ |
| **Фарма** | GMP-валидация между сериями | 8–12 часов | Слабая | Чистая комната, аналитика |
| **Автопром** | Смена цвета камеры окраски | 15 мин – 2 часа | Белый→пурпурный ≫ белый→белый | Конвейер |
| **Пищевка** | Молоко → кефир vs кефир → молоко | 45 мин vs 90 мин + стерилизация | Аллерген-контроль | Линия розлива |
| **PCB** | Смена фидеров pick-and-place | Секунды–минуты | Слабая | AOI-инспекция |

Все кейсы описываются одной моделью `ScheduleProblem`. Одна Pydantic-схема, заполняете SDST-матрицу — и поехали.

---

## Ghost Setup: баг, который прошёл 100% тестов

Ранняя версия моделировала переналадку как «мёртвое время» на таймлайне станка. После добавления вспомогательных ресурсов (краны, операторы): во время четырёхчасовой замены футеровки мостовой кран *занят* — но планировщик считал его свободным. Три операции на соседних станках, все требуют тот же кран.

**Исправление:** каждая переналадка создаёт опциональный интервал в CP-SAT, и этот интервал входит в cumulative-ограничения по ARC наравне с интервалами обработки. Greedy резервирует setup-окно и processing-окно атомарно.

Баг прошёл все юнит-тесты — ни в одном инстансе переналадка и ARC не пересекались. Hypothesis (property-based) поймал бы, но был добавлен *после* бага.

---

## FeasibilityChecker: 7 классов валидации

После каждого `solve()` — независимый валидатор. Он не знает, какой решатель работал. Семь проверок:

| # | Класс | Проверяет |
|---|-------|-----------|
| 1 | **Полнота** | Каждая операция назначена ровно на один станок |
| 2 | **Допустимость** | Операция на станке из своего `eligible_wc_ids` |
| 3 | **Прецеденты** | Операция 2 не начинается раньше конца операции 1 |
| 4 | **Ёмкость** | Никакие два интервала (обработка + setup) не перекрываются на станке |
| 5 | **Setup gaps** | Зазор между операциями ≥ SDST-матрице |
| 6 | **ARC** | $\sum_{i: \text{active}(i,t)} q_{ir} \leq C_r$ включая setup-интервалы |
| 7 | **Горизонт** | Ни одна операция не выходит за `planning_horizon_end` |

Три уровня защиты от бага в самом валидаторе: cross-solver consistency тесты, property-based Hypothesis, 49 ручных инстансов-ловушек (7 ловушек × 7 типов).

---

## Железо и перформанс

Python — только клей. Вычислительное ядро — C++ (OR-Tools, HiGHS). Профиль на medium-stress (500 оп., плотная SDST):

| Фаза | Время | Узкое место |
|------|-------|-------------|
| JSON → Pydantic | 12 мс | Python |
| Model building | 45 мс | Python → protobuf |
| **CP-SAT solve** | **28 400 мс** | **C++ ядро OR-Tools** |
| Result extraction | 8 мс | Python |
| FeasibilityChecker | 3 мс | Python |

Python-код: 68 мс из 28 468. Это **0.24%**.

CP-SAT использует portfolio search (N стратегий параллельно, берёт лучший). Больше ядер — лучше, но после 16 — убывающая отдача.

LBBD-HD параллелит **собственные** подзадачи через `ProcessPoolExecutor`. Каждый воркер — свой CP-SAT инстанс, межпроцессная коммуникация через сериализованные protobuf (~5 мс на кластер). GIL обхо́дится через процессы, не потоки.

### Рекомендации по железу

| Сценарий | CPU | RAM | Масштаб |
|----------|-----|-----|---------|
| Разработка | i5 / Ryzen 5 | 8 ГБ | До 200 операций |
| Рабочая станция | i7 / Ryzen 7 | 32 ГБ | До 1 000 операций |
| Серверная | EPYC / Xeon, 16+ ядер | 64+ ГБ | LBBD-HD параллелизм |

**GPU не используется.** OR-Tools не имеет CUDA-бэкенда.

SDST-матрица хранится в sparse-представлении (`dict[tuple[UUID, UUID], SetupEntry]`): при 700K ячеек экономия ~4 ГБ RAM по сравнению с dense array.

---

## Софтверный стек

| Пакет | Зачем | Лицензия | Почему именно он |
|-------|-------|----------|------------------|
| **OR-Tools 9.10** | CP-SAT солвер | Apache-2.0 | Лучший OSS CP-солвер (тройка MiniZinc Challenge). C++ ядро, SIMD, многопоточный поиск |
| **HiGHS 1.7+** | MIP для LBBD мастера | MIT | Production-grade замена GLPK. Прямой вызов `highspy` через C API без PuLP/pyomo |
| **Pydantic v2** | Модель данных + валидация | MIT | 14 доменных классов, `model_validator` с 20+ перекрёстными проверками, авто-генерация JSON Schema |
| **Hypothesis** | Property-based тесты | MPL-2.0 | 1000 случайных инстансов на каждый PR |
| **Ruff** | Линтинг | MIT | Rust-скорость, замена flake8+isort |
| **pytest + mypy** | Тесты + типы | MIT | `--strict` mode |

**Чего нет и почему:** NumPy (SDST в sparse dict, не в dense array), pandas (JSON→Pydantic→JSON), TensorFlow/PyTorch (нет ML в ядре).

---

## Быстрый старт

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"

# Расчёт через portfolio router
python -m synaps solve benchmark/instances/tiny_3x3.json

# Тесты
pytest tests/ -v

# Линтинг
ruff check synaps tests benchmark --select F,E9

# Сравнение решателей на бенчмарке
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare
```

---

## Карта репозитория

| Путь | Что | LOC |
|------|-----|-----|
| `synaps/solvers/cpsat_solver.py` | CP-SAT: `AddCircuit`, SDST, ARC | 688 |
| `synaps/solvers/lbbd_hd_solver.py` | LBBD-HD: параллельный Бендерс + warm start | 1 247 |
| `synaps/solvers/lbbd_solver.py` | LBBD: MIP мастер + CP-SAT подзадачи | 856 |
| `synaps/solvers/feasibility_checker.py` | 7-классный валидатор | 356 |
| `synaps/solvers/router.py` | Детерминированный роутер | 275 |
| `synaps/solvers/greedy_dispatch.py` | Log-ATCS эвристика | 261 |
| `synaps/solvers/incremental_repair.py` | Ремонт на лету | 281 |
| `synaps/solvers/partitioning.py` | Графовое разбиение | 213 |
| `synaps/model.py` | Pydantic-модель данных | — |
| `synaps/ml_advisory.py` | ML advisory-слой | — |
| `synaps/guards.py` | Ресурсные ограничители | — |
| `synaps/contracts.py` | Версионированные JSON-контракты | — |
| `benchmark/` | Воспроизводимый benchmark harness | — |
| `tests/` | 218 тестов, 31 модуль | 5 283 |
| `control-plane/` | TypeScript BFF | — |
| `docs/` | Архитектура, аудит, исследования | — |

---

## ε-Constraint: три расписания вместо одного

Скаляризация по умолчанию — makespan доминирует. Для реальной работы планового отдела: ε-constraint профили (Mavrotas 2009).

| Профиль | Оптимизирует |
|---------|-------------|
| `CPSAT-EPS-SETUP-110` | Минимум переналадок (при makespan ≤ 110% от оптимума) |
| `CPSAT-EPS-TARD-110` | Минимум просрочки |
| `CPSAT-EPS-MATERIAL-110` | Минимум потерь материала |

Плановик получает три расписания с числами: «Переналадок меньше, makespan +8%». «Потерь меньше, makespan +4%». Выбирай.

---

## Incremental Repair: станок сдох посреди смены

Полная перетасовка — хаос (schedule nervousness). `IncrementalRepair` замораживает всё за пределами окрестности сбоя:

- Поломка → 2 × зависимые переналадки вниз по цепочке
- Срочный заказ → ±30 мин на затронутом станке
- Нехватка материала → операции в той же state-группе

Внутри: greedy re-dispatch. Не влезает — micro-CP-SAT на маленьком подмножестве. Цель: нервозность ниже 5%.

Роутер дёргает `IncrementalRepair` автоматически при `regime=BREAKDOWN` или `regime=RUSH_ORDER`.

---

## ML Advisory Layer

Опциональный слой поверх роутера. Не принимает решений — советует. Эвристический предиктор оценивает сложность задачи и рекомендует решатель. Хук в роутере: если advisory включен, рекомендация учитывается наравне с детерминированным деревом.

GNN для отсечений Бендерса — roadmap. Идея: обучить GNN предсказывать маску вероятностей назначений → `model.AddHint()` в CP-SAT (Bengio et al. 2021).

---

## Квантовые вычисления: честная оценка

QUBO-формулировка scheduling:

$$H = A \sum_i \left(1 - \sum_j x_{ij}\right)^2 + B \sum_j \text{penalty}_\text{overlap}(j) + C \cdot \text{objective}$$

D-Wave Advantage (2024): 5 000+ кубитов. Для задачи на 50 операций и 10 станков: ~2 000 QUBO-переменных, ~8 000 физических кубитов после вложения в Pegasus-граф — на пределе. 50 000 операций Москабельмета → ~10 миллионов физических кубитов → горизонт 2035–2040.

Архитектура SynAPS *не* привязана к бэкенду. Добавляется ветка в роутер:

```python
if ctx.quantum_backend_available and op_count <= 50:
    return SolverRoutingDecision(
        solver_config="QAOA-HYBRID",
        reason="small instance fits current quantum hardware limits",
    )
```

---

## Что реализовано, а что нет

### Реализовано (в этом репо, протестировано)

- 8 решателей с детерминированной маршрутизацией
- CP-SAT с SDST, ARC, `max_parallel` через `AddCircuit` + `Cumulative`
- LBBD и LBBD-HD с 4 семействами отсечений и параллельными подзадачами (`ProcessPoolExecutor`)
- Greedy ATCS в log-пространстве с K3-расширением за потери материала
- ε-constraint Pareto-профили для trade-off по setup/tardiness/material-loss
- Incremental repair с настраиваемым порогом нервозности и CP-SAT fallback
- 7-классная FeasibilityChecker-валидация после каждого solve
- ML advisory-слой с эвристическим предиктором и хуком в роутер
- 13 отраслевых пресетов (металлургия, кабель, фарма, авто, пищевка, PCB...)
- Профилировщик задач, ресурсные ограничители, структурированная инструментация
- Версионированные JSON-контракты для TypeScript-интеграции
- Property-based тесты (Hypothesis), cross-solver consistency тесты
- Benchmark harness с регрессионными границами

### Не реализовано (roadmap)

- Event sourcing / CQRS
- Rust hot-path через PyO3 (шов в `accelerators.py`, нативный модуль не собирается)
- GNN-отсечения Бендерса
- LLM-пояснения для оператора
- Квантовый бэкенд
- NUMA pinning (пока `taskset` руками)
- Промышленное развёртывание

---

## Границы заявлений

- Репозиторий не заявляет промышленную, регуляторную или сертифицированную готовность.
- Бенчмарки на синтетических инстансах (tiny/medium/medium-stress), не на данных завода.
- LOC и количество тестов измерены из кода и могут меняться между коммитами.

## Литература

- Pinedo M.L. (2016). *Scheduling: Theory, Algorithms, and Systems*, 4th ed. Springer.
- Allahverdi A. et al. (2008). A survey of scheduling problems with setup times or costs. *EJOR* 187(3).
- Lee Y.H., Bhaskaran K., Pinedo M. (1997). A heuristic to minimize total weighted tardiness with sequence-dependent setups. *IIE Transactions* 29(1).
- Hooker J.N., Ottosson G. (2003). Logic-Based Benders Decomposition. *Math. Programming* 96.
- Hooker J.N. (2007). *Integrated Methods for Optimization*, 2nd ed. Springer.
- Mavrotas G. (2009). Effective implementation of the ε-constraint method. *AMC* 213(2).
- Shingo S. (1985). *A Revolution in Manufacturing: The SMED System*. Productivity Press.
- Farhi E., Goldstone J., Gutmann S. (2014). A Quantum Approximate Optimization Algorithm. arXiv:1411.4028.
- Bengio Y. et al. (2021). Machine Learning for Combinatorial Optimization: a Methodological Tour d'Horizon. *EJOR* 290(2).
- Laborie P. et al. (2018). IBM ILOG CP Optimizer for Scheduling. *Constraints* 23(2).
- Venturelli D. et al. (2016). Quantum Annealing Implementation of Job-Shop Scheduling. arXiv:1506.08479.
- MiniZinc Challenge (2024). Results.

## Ссылки

[Архитектура](docs/architecture/01_OVERVIEW.md) | [Аудиторские отчёты](docs/audit/) | [Бенчмарки](benchmark/README.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

---

<a id="synaps-in-english"></a>

# SynAPS in English

Deterministic scheduling engine for **MO-FJSP-SDST-ARC** problems (multi-objective flexible job-shop scheduling with sequence-dependent setup times and auxiliary resource constraints).

Eight solvers. Independent feasibility validator after every call. No infeasible schedule leaves the engine. Open source.

## Background

On March 29, 2026, I attended an [open lecture by Yan Anisov](https://www.mkm.ru/news/AKTIVNAYA-IT-VESNA-S--MOSITLAB---SERIYA-MEROPRIYATIY-S-YANOM-ANISOVYM/) (CEO of MOSITLAB, head of production infrastructure development at Moskabelmet Group) at NITU MISiS. The slides showed a case study for their APS Infimum system at a cable factory: 50,000 operations, 100 work centers, 700,000 setup transitions. Five conflicting objectives. Result: 27 days of savings per year, ~1.2 billion rubles.

The architecture: GREED → Encoder (compress 50,000 ops into 10,000 aggregated) → neural network core → GREED → schedule. It works. But the neural net is a black box — it says "put order 4817 on machine 23 at 14:20" without saying *why*.

I started building SynAPS — an engine where every decision can be cracked open: *here's why*. Not a neural network. A portfolio of deterministic solvers, each validated by an independent feasibility checker.

## Status

Code runs, tests pass, benchmarks reproduce. **Not tested on a live factory.** The gap between the current solver portfolio and the full target architecture is documented in "What's implemented vs. planned."

**Metrics:** `synaps/` 6,967 LOC · solvers 4,719 LOC · 218 tests across 31 modules (5,283 LOC of test code).

---

## The Problem: MO-FJSP-SDST-ARC

- $N$ operations across $M$ work centers (Moskabelmet case: $N = 50{,}000$, $M = 100$).
- Sequence-dependent setup times: transition duration depends on (previous state → next state). Moskabelmet: 700,000 SDST matrix cells.
- Auxiliary resource constraints (cranes, operators, inspection stands) with limited pool sizes.
- Five conflicting objectives: makespan, setup time, tardiness, material loss, load balance.

NP-hard. Allahverdi et al. (2008) needed 60 pages just to survey setup-dependent scheduling.

---

## Solver Portfolio

| Solver | Algorithm | LOC | When to use |
|--------|-----------|-----|-------------|
| **CP-SAT Exact** | `AddCircuit` + `NoOverlap` + `Cumulative`, OR-Tools 9.10 | 688 | Small/medium, provable optimality |
| **LBBD** | HiGHS MIP master + CP-SAT subproblems + 4 Benders cut families | 856 | Medium/large, gap-bounded convergence |
| **LBBD-HD** | `ProcessPoolExecutor` + ARC-aware partitioning + topological assembly (Kahn) | 1,247 | Thousands of ops, parallel clusters |
| **Greedy ATCS** | Log-space ATCS (Lee, Bhaskaran & Pinedo 1997) with K3 extension | 261 | Feasible schedule in < 1 s |
| **Pareto Slice** | Two-stage ε-constraint (Haimes 1971, Mavrotas 2009) | 86 | Trade-off comparison |
| **Incremental Repair** | Freeze + neighbourhood re-dispatch + micro-CP-SAT fallback | 281 | Live rescheduling, < 5% nervousness |
| **Portfolio Router** | Deterministic tree: regime × size × latency + ML advisory hook | 275 | One input → one solver → log entry |
| **FeasibilityChecker** | 7-class event-sweep validator (solver-agnostic) | 356 | After every `solve()` |

Additional: graph partitioning (213 LOC), solver registry with 13 industry presets, ML advisory layer, versioned JSON contracts, TypeScript control-plane BFF.

---

## Mathematics

### CP-SAT Formulation

Google OR-Tools CP-SAT: constraint propagation + clause learning + lazy clause generation + LP relaxation. C++ core; Python only generates the protobuf model.

**Variables:** $x_{ij} \in \{0,1\}$ (operation $i$ on machine $j$), $\text{start}_i, \text{end}_i \in \mathbb{Z}$ (interval bounds), $\pi_{jk}$ (circuit ordering).

**Key constraints:**

1. **Assignment:** $\sum_{j \in E_i} x_{ij} = 1 \; \forall i$

2. **No-overlap with setups:** `AddCircuit` defines a Hamiltonian path per machine. Each arc $(i,j)$ on machine $m$ carries a setup interval of length $s_{\text{state}(i) \to \text{state}(j)}^m$.

3. **Cumulative for ARC:** $\sum_{i: \text{active}(i,t)} q_{ir} \leq C_r \; \forall r, t$ — including setup intervals (ghost setup fix).

4. **Precedence:** $\text{end}_{\text{pred}(i)} \leq \text{start}_i$

5. **Objective:** $\min \; \alpha \cdot C_{\max} + \beta \sum_i T_i + \gamma \sum s_{ij} + \delta \sum m_{ij}$

### LBBD (Hooker & Ottosson 2003)

Master (HiGHS MIP) assigns operations to machines. Subproblems (CP-SAT per cluster) sequence with SDST + ARC. Four cut families:

| Cut | Formula | Purpose |
|-----|---------|---------|
| **Nogood** | $\sum_{(i,j) \in S_\text{inf}} (1 - y_{ij}) \geq 1$ | Forbids infeasible assignment combination |
| **Capacity** | $\eta \geq \frac{\sum p_i + \sum s_{ij}}{\lvert\text{machines}\rvert}$ | Bottleneck lower bound |
| **Setup-cost** | $\eta \geq \text{actual\_cost}_k$ | Corrects SDST underestimate |
| **Load-balance** | $C_{\max} \geq \sum p_i / M$ | Obvious but often ignored by relaxation |

On 500 ops: gap < 5% in 3–5 iterations vs. 42% gap for monolithic CP-SAT.

### LBBD-HD: Parallel Industrial Decomposition

1,247 LOC. `ProcessPoolExecutor` with adaptive workers. GIL bypassed via processes, not threads. ARC-aware clustering: operations sharing auxiliary resources land in the same cluster so cumulative constraints solve locally. Greedy warm start via `model.AddHint()` accelerates CP-SAT subproblems. Topological post-assembly (Kahn's algorithm) for global precedence consistency.

### Greedy ATCS: Log-Space and Underflow

ATCS (Lee, Bhaskaran & Pinedo 1997) dies on fat-tailed setup distributions: `exp(-480)` = $10^{-208}$ → IEEE 754 zero → all heavy-setup candidates collapse to 0.0.

Fix: log-space + K3 extension for material loss:

$$\log I_j = \log w_j - \log p_j - \frac{\text{slack}_j}{K_1 \bar{p}} - \frac{s_{lj}}{K_2 \bar{s}} - \frac{m_{lj}}{K_3 \bar{m}}$$

### Why Not Genetic Algorithms

GAs provide no lower bound: "makespan 420 min" — better than 415? GA doesn't know. CP-SAT and LBBD give a gap. Metaheuristics have no built-in feasibility guarantee.

---

## SDST Matrix

Each cell is a structured object with time, material loss, and energy cost:

```python
class SetupEntry(BaseModel):
    work_center_id: UUID
    from_state_id: UUID
    to_state_id: UUID
    setup_minutes: int
    material_loss: float = 0.0
    energy_kwh: float = 0.0
```

Stored as sparse dict — saves ~4 GB RAM vs. dense array at 700K cells.

**Industry examples:**

| Industry | Transition | Time | Asymmetry | ARC |
|----------|-----------|------|-----------|-----|
| **Cable** | Extruder die change | 15–240 min (by core diameter) | Medium | Bridge crane, QC |
| **Steel** | High-carbon → low-carbon | 4 hours | Reverse = 30 min | Ladle, CCM |
| **Pharma** | GMP validation between batches | 8–12 hours | Weak | Clean room, analytics |
| **Auto** | Paint booth color change | 15 min–2 hours | White→purple ≫ purple→purple | Conveyor |
| **Food** | Milk→kefir vs kefir→milk | 45 min vs 90 min + sterilization | Allergen control | Bottling line |
| **PCB** | Pick-and-place feeder swap | Seconds–minutes | Weak | AOI inspection |

All described by the same `ScheduleProblem` Pydantic schema.

---

## Ghost Setup Bug

Early versions modeled setup as "dead time." After adding auxiliary resources: during a 4-hour relining, the bridge crane is occupied — but the scheduler treated it as free. Three ops on adjacent machines, all requiring the same crane.

**Fix:** every setup creates an optional interval in CP-SAT entering cumulative constraints alongside processing intervals. The bug passed 100% of unit tests — no test instance had overlapping setup + ARC. Hypothesis (property-based) would have caught it, but was added *after* the bug.

---

## FeasibilityChecker: 7 Validation Classes

After every `solve()` — solver-agnostic validator. 7 checks:

| # | Class | Validates |
|---|-------|-----------|
| 1 | **Completeness** | Every operation assigned to exactly one machine |
| 2 | **Eligibility** | Operation on machine from its `eligible_wc_ids` |
| 3 | **Precedence** | Op 2 doesn't start before op 1 ends |
| 4 | **Capacity** | No overlapping intervals (processing + setup) on a machine |
| 5 | **Setup gaps** | Gap between operations ≥ SDST matrix |
| 6 | **ARC** | $\sum q_{ir} \leq C_r$ including setup intervals |
| 7 | **Horizon** | No operation exceeds `planning_horizon_end` |

Three defenses against checker bugs: cross-solver consistency tests, Hypothesis property-based tests, 49 hand-crafted trap instances (7 traps × 7 types).

---

## Hardware and Performance

Python is glue (0.24% of runtime). Computational core: C++ (OR-Tools, HiGHS).

Profile on medium-stress (500 ops, dense SDST):

| Phase | Time | Bottleneck |
|-------|------|-----------|
| JSON → Pydantic | 12 ms | Python |
| Model building | 45 ms | Python → protobuf |
| **CP-SAT solve** | **28,400 ms** | **C++ core (OR-Tools)** |
| Result extraction | 8 ms | Python |
| FeasibilityChecker | 3 ms | Python |

CP-SAT uses portfolio search internally (N strategies in parallel, takes the best). More cores help — diminishing returns past 16.

LBBD-HD parallelizes *its own* subproblems via `ProcessPoolExecutor`. Each worker is a separate CP-SAT instance; inter-process communication via serialized protobuf (~5 ms per cluster). GIL bypassed via processes, not threads.

### Hardware Recommendations

| Scenario | CPU | RAM | Scale |
|----------|-----|-----|-------|
| Dev laptop | i5 / Ryzen 5 | 8 GB | Up to 200 ops |
| Workstation | i7 / Ryzen 7 | 32 GB | Up to 1,000 ops |
| Server | EPYC / Xeon, 16+ cores | 64+ GB | LBBD-HD parallelism |

**No GPU.** OR-Tools has no CUDA backend.

SDST stored as sparse dict (`dict[tuple[UUID, UUID], SetupEntry]`): ~4 GB savings vs. dense array at 700K cells.

---

## Software Stack

| Package | Purpose | License | Why |
|---------|---------|---------|-----|
| **OR-Tools 9.10** | CP-SAT solver | Apache-2.0 | Best OSS CP solver (MiniZinc Challenge top 3). C++ core, SIMD, multi-threaded search |
| **HiGHS 1.7+** | MIP for LBBD master | MIT | Production-grade GLPK replacement. Direct `highspy` C API — no PuLP/pyomo |
| **Pydantic v2** | Data model + validation | MIT | 14 domain classes, `model_validator` with 20+ cross-checks, auto JSON Schema generation |
| **Hypothesis** | Property-based tests | MPL-2.0 | 1,000 random instances per PR |
| **Ruff** | Linting | MIT | Rust speed, replaces flake8+isort |
| **pytest + mypy** | Tests + types | MIT | `--strict` mode |

**What's absent and why:** NumPy (SDST in sparse dict), pandas (JSON→Pydantic→JSON), TensorFlow/PyTorch (no ML in core).

---

## Quick Start

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"
python -m synaps solve benchmark/instances/tiny_3x3.json
pytest tests/ -v
```

---

## ε-Constraint: Three Schedules Instead of One

Default scalarization: makespan dominates. For real planning: ε-constraint profiles (Mavrotas 2009).

| Profile | Optimizes |
|---------|-----------|
| `CPSAT-EPS-SETUP-110` | Minimum setups (makespan ≤ 110% of optimum) |
| `CPSAT-EPS-TARD-110` | Minimum tardiness |
| `CPSAT-EPS-MATERIAL-110` | Minimum material loss |

The planner gets three schedules with numbers. Choose.

---

## Incremental Repair

Full reshuffle = chaos (schedule nervousness). `IncrementalRepair` freezes everything outside the disruption neighbourhood:

- Breakdown → 2× dependent setups downstream
- Rush order → ±30 min on affected machine
- Material shortage → operations in same state group

Inside: greedy re-dispatch. Doesn't fit → micro-CP-SAT on small subset. Target: nervousness below 5%.

Router triggers `IncrementalRepair` automatically on `regime=BREAKDOWN` or `regime=RUSH_ORDER`.

---

## ML Advisory Layer

Optional layer on top of router. Doesn't decide — advises. Heuristic predictor estimates problem difficulty and recommends solver. Hook in router: if advisory enabled, recommendation is weighted alongside deterministic tree.

GNN for Benders cuts — roadmap. Idea: train GNN to predict assignment probability mask → `model.AddHint()` in CP-SAT (Bengio et al. 2021).

---

## Quantum Computing: Honest Assessment

QUBO formulation for scheduling:

$$H = A \sum_i \left(1 - \sum_j x_{ij}\right)^2 + B \sum_j \text{penalty}_\text{overlap}(j) + C \cdot \text{objective}$$

D-Wave Advantage (2024): 5,000+ qubits. For 50 ops / 10 machines: ~2,000 QUBO variables, ~8,000 physical qubits after Pegasus embedding — at the limit. 50,000 ops (Moskabelmet) → ~10M physical qubits → horizon 2035–2040.

SynAPS architecture is *not* backend-locked. Add a branch to the router:

```python
if ctx.quantum_backend_available and op_count <= 50:
    return SolverRoutingDecision(
        solver_config="QAOA-HYBRID",
        reason="small instance fits current quantum hardware limits",
    )
```

---

## What's Implemented vs. Planned

**Implemented:** 8-solver portfolio, CP-SAT with SDST/ARC/max_parallel via `AddCircuit` + `Cumulative`, LBBD and LBBD-HD with 4 cut families and parallel subproblems (`ProcessPoolExecutor`), greedy ATCS in log-space with K3 material-loss extension, ε-constraint Pareto profiles, incremental repair with CP-SAT fallback, 7-class feasibility validation, ML advisory layer, 13 industry presets, problem profiler, resource guards, instrumentation, versioned JSON contracts, property-based and cross-solver tests, benchmark harness.

**Roadmap:** event sourcing, Rust/PyO3 hot-path, GNN Benders cuts, LLM explanations, quantum backend, NUMA pinning, live factory deployment.

---

## Claim Boundaries

- No claim of production, regulatory, or certified readiness.
- Benchmarks run on synthetic instances (tiny/medium/medium-stress), not factory data.
- LOC and test counts measured from code; may change between commits.

## References

Pinedo (2016), Allahverdi et al. (2008), Lee-Bhaskaran-Pinedo (1997), Hooker-Ottosson (2003), Hooker (2007), Mavrotas (2009), Shingo (1985), Farhi et al. (2014), Bengio et al. (2021), Laborie et al. (2018), Venturelli et al. (2016), MiniZinc Challenge (2024).

## Links

[Architecture](docs/architecture/01_OVERVIEW.md) | [Audit Reports](docs/audit/) | [Benchmarks](benchmark/README.md) | [Contributing](CONTRIBUTING.md) | [Security](SECURITY.md) | [Support](SUPPORT.md)

## License

MIT
