# SynAPS V2: Академический Аудит и Роадмап Масштабирования до 50 000+ Операций

**Статус документа:** Research note (v2, audited 2026-04-11)
**Цель:** Математически строгий анализ архитектурных пределов SynAPS v1 и план масштабирования до 50 000+ производственных операций уровня публично обсуждаемого cable-APS кейса при сохранении объяснимости решений.

**Дисклеймер:** Всё ниже — аналитика и план. Код не написан. Числа до 500 ops — измеренные, свыше — экстраполяции и теоретические оценки.

## Addendum (2026-04-25): Live 50K Stress Audit

По итогам live stress-matrix для `RHC-GREEDY` vs `RHC-ALNS` были зафиксированы два конкретных ALNS-режима деградации, которые теперь закрыты на уровне solver guardrails.

1. `initial seed` мог быть полным по покрытию операций, но не проходить полную feasibility-проверку. Это делало recovery-to-initial недостаточно строгим.
2. На части окон весь per-window budget выгорал ещё в phase-1 initial solution generation, то есть `ALNS` возвращал `iterations_completed = 0` и фактически не входил в destroy-repair loop.

Практический вывод: для честной 50K-оценки недостаточно смотреть только на solver-level makespan и scheduled ratio. Нужно отдельно анализировать `inner_window_summaries`, где теперь критичны поля `initial_solution_ms`, `time_limit_exhausted_before_search` и `final_violation_recovery_*`.

На завершённом артефакте `benchmark/studies/test-50k-academic-matrix-v1/rhc_50k_study.json` это видно напрямую:

- `RHC-GREEDY` дал `mean_scheduled_ratio = 0.3547`, но `mean_makespan_minutes = 11240.8`.
- `RHC-ALNS` дал `mean_scheduled_ratio = 0.1134`, но `mean_makespan_minutes = 4652.77`.
- В live-артефакте присутствуют окна с `iterations_completed = 0` и `time_limit_exhausted_before_search = true`, то есть solver-level objective у `RHC-ALNS` улучшался ценой слабого покрытия и деградации throughput.

Следовательно, академически корректная интерпретация current 50K state такова: `RHC-ALNS` уже полезен как локальный objective improver внутри частичного плана, но ещё не проходит как large-scale coverage solver без дополнительного контроля phase-1 seed cost и per-window admission geometry.

---

## 1. Деконструкция архитектурных пределов

### 1.1. Коллапс `AddCircuit` при масштабировании

**Текущая реализация** (`cpsat_solver.py`, строка 246): секвенирование SDST на каждом станке через `AddCircuit` — ограничение гамильтонова пути по дуговым литералам.

**Математика дуг.** Для $N$ операций на одном станке формируются:
- $N(N-1)$ направленных дуг «операция → операция» (каждая с булевой переменной + setup-интервал)
- $2N$ дуг от/к виртуальному депо
- $N + 1$ петель отсутствия (self-loops для операций не на этом станке + петля неиспользуемого депо)

Итого на станок: $N^2 + N + 1$ дуг. При $N = 500$: **250 501 дуг** с соответствующими протобуф-записями.

**Масштабирование до 50K.** При равномерном распределении 50 000 операций по 100 станкам: ~500 ops/станок. Каждый станок — отдельный `AddCircuit`, что само по себе решаемо. Проблема — суммарный размер CP-SAT модели: $100 \times 250\,501 \approx 25$ млн дуг + assignment переменные + cumulative constraints = protobuf модель > 2 ГБ. На практике OR-Tools CP-SAT 9.10 таймаутит на построении модели такого размера ещё до фазы Branch-and-Bound.

**Измеренные данные:** На 500 операциях CP-SAT (таймаут 60 с) достигает gap ~42%. Оптимум гарантированно находится только до ~200 ops. На 300+ ops gap растёт экспоненциально.

### 1.2. Коллапс LBBD Master Problem

**Текущая реализация** (`lbbd_solver.py`): HiGHS MIP мастер-задача назначает бинарные переменные $y_{ij} \in \{0, 1\}$ (операция $i$ на станок $j$).

**Реальный размер мастера.** В flexible job-shop каждая операция имеет 2–5 допустимых станков (не все 100). Поэтому число переменных: $\sum_i |E_i|$, где $E_i$ — множество допустимых станков для операции $i$. При среднем $|E_i| = 3$: $50\,000 \times 3 = 150\,000$ бинарных переменных (не 5 млн, как при полном перечислении).

**Проблема — не переменные, а отсечения.** Каждая итерация Бендерса добавляет nogood/capacity/setup-cost отсечения. После 10 итераций набирается $O(K \times I)$ ограничений ($K$ — число кластеров, $I$ — итерации). При $K = 500$ кластерах и 15 итерациях — до 30 000 отсечений, каждое с коэффициентами по ~50 переменным. LP-релаксация деградирует.

**Измеренные данные:** LBBD сходится за 3–5 итераций до gap < 5% на 500 ops (с greedy warm start). На 1000+ ops — 10+ итераций, gap растёт. На 5000+ — конвергенция не гарантирована в разумное время.

### 1.3. Коллапс Greedy/Beam на 50K

Greedy ATCS и Beam Search масштабируются полиномиально ($O(N^2 M)$ и $O(B \cdot N^2 M)$), но теряют качество:
- Greedy: gap ~30% на малых задачах, на 50K без локального поиска — gap может достигать 50–80%
- Beam Search: помогает на SDST (20–50% улучшение vs жадный), но не даёт нижнюю границу

Вывод: жадные эвристики масштабируются по времени, но не по качеству. Нужен механизм локальных оптимизаций.

---

## 2. Архитектура масштабирования: Matheuristics

Подход к 50K операций строится на трёх академических направлениях: **крупномасштабная метаэвристика** (ALNS), **точная локальная оптимизация** (micro-CP-SAT), и **ML-ускорение** (GNN variable fixing). Каждое — с явными ограничениями и ссылками.

### 2.1. ALNS + Micro-CP-SAT: Large Neighborhood Search с точными подзадачами

**Источники:** Shaw (1998) — оригинальная LNS; Ropke & Pisinger (2006, Transportation Science, 3300+ цитирований) — адаптивный выбор операторов; Laborie & Godard (2007, CPAIOR) — LNS+CP для scheduling.

**Идея:** заменить глобальный LBBD мастер на итеративный процесс destroy-repair.

1. **Initial Solution** — Greedy ATCS + Beam Search (существующий код), ~1 с на 50K ops
2. **Destroy** — выбрать блок из 200–500 «плохих» операций:
   - Random removal (baseline)
   - Worst removal (операции с наибольшим вкладом в штраф)
   - Related removal (операции на одном станке / с общими ресурсами)
   - Shaw removal (операции, похожие по характеристикам) — Shaw, 1998
3. **Repair (Micro-CP-SAT)** — передать вырванный блок в `cpsat_solver.py` с фиксированными переменными окружения. При $N \leq 300$: CP-SAT находит хороший gap (<5%) за 5–10 с. При $N \leq 200$: близкий к оптимуму за <2 с
4. **Accept/Reject** — Simulated Annealing acceptance criterion + FeasibilityChecker на каждом шаге
5. Повторить 1 000–5 000 итераций (не 10 000 — каждая итерация с micro-CP-SAT стоит 2–10 с)

**Отличие от IncrementalRepair:** Существующий `incremental_repair.py` (281 LOC) замораживает окрестность и делает greedy re-dispatch. ALNS-repair использует *точный* CP-SAT на вырванном блоке — гарантированный локальный оптимум вместо жадной эвристики.

**Оценка времени на 50K:**
- 3 000 итераций × 5 с (Micro-CP-SAT на 300 ops) = ~4 часа
- С параллелизмом (4 независимых ALNS потока) = ~1 час

**Честные ограничения:**
- ALNS не даёт глобальную нижнюю границу. Gap неизвестен
- Качество зависит от дизайна destroy-операторов (требует экспериментов)
- Адаптивный выбор операторов (probabilities по Ropke-Pisinger) требует настройки на реальных данных

### 2.2. Branch-and-Price / Column Generation

**Источники:** Desrosiers & Lübbecke (2005, "Column Generation"); van den Akker et al. (2000, Mathematical Programming) — B&P для scheduling.

**Модель:** вместо «назначить операцию на станок», строится модель «выбрать готовую смену для станка». Каждая «смена» — допустимая последовательность операций на одном станке с учётом SDST.

**Pricing subproblem:** SPPRC (Shortest Path Problem with Resource Constraints) — найти новую «смену» с отрицательной приведённой стоимостью. Для SDST — это sequence-dependent shortest path, решаемый динамическим программированием.

**Master (restricted):** Set Partitioning — выбрать непересекающиеся смены, покрывающие все операции.

**Когда работает:** заводы с повторяющейся номенклатурой (20–50 типов деталей, 1000+ партий одного типа). Pricing формирует ограниченный набор шаблонов.

**Когда не работает:** высокая вариативность деталей (каждая деталь уникальна) → pricing генерирует экспоненциально много столбцов. Москабельмет с 50K операций и разнородной номенклатурой — скорее этот случай.

**Честная оценка:** B&P — более элегантен математически, но сложнее в реализации, чем ALNS. Для SynAPS рекомендую ALNS как основной путь, B&P — как альтернативу для специфических случаев.

### 2.3. GNN для ускорения (Variable Fixing)

**Источники:** Nair et al. (2020, "Solving Mixed Integer Programs Using Neural Network Branching"); Gasse et al. (2019, NeurIPS, "Exact Combinatorial Optimization with Graph Convolutional Neural Networks"); Hottung & Tierney (2020, "Neural Large Neighborhood Search for CVRP"); Yang et al. (2025, Applied Sciences) — GNN variable fixation для unit commitment; Nguyen et al. (2024, ISORA) — GNN для employee scheduling.

**Идея:** GNN анализирует граф задачи и предсказывает, какие назначения $x_{ij}$ вероятнее всего равны 0 в хорошем решении. Эти переменные фиксируются до запуска CP-SAT/ALNS, уменьшая пространство поиска.

**Архитектура:**
- **Входной граф:** операции (узлы) + станки (узлы) + рёбра допустимости + SDST-рёбра
- **GNN:** GIN (Graph Isomorphism Network, Xu et al. 2019) или GAT (Veličković et al. 2018) — 3–5 слоёв
- **Выход:** вероятность $p_{ij} \in [0, 1]$ для каждого ребра (операция $i$, станок $j$)
- **Фиксация:** рёбра с $p_{ij} < \theta$ фиксируются в 0 (переменная заблокирована)

**НЕ является White-Box.** Фиксация переменных по предсказанию нейросети — это grey-box подход. GNN решает «какие ветки отрезать», это непрозрачное решение. Честно:
- Финальное расписание *допустимо* (FeasibilityChecker гарантирует)
- Финальное расписание *объяснимо* (CP-SAT/ALNS дают детерминированный ответ на фиксированном пространстве)
- Но *выбор пространства* (какие переменные зафиксированы) — непрозрачен

**Оценка потерь (из литературы):**
- Nair et al. (2020): фиксация 70–90% переменных → потеря 1–5% от оптимума на MILP benchmarks
- Yang et al. (2025): фиксация 80–95% для power unit commitment → потеря <2% на стандартных инстансах
- **Для job-shop с SDST:** нет прямых бенчмарков. Экстраполяция: потеря 3–10% на средних задачах, больше на экстремальных

Заявлять «~2% потери» без бенчмарка на FJSP-SDST — нечестно. Реалистичный диапазон: **3–10% от лучшего известного решения** при фиксации 70–85% переменных. При агрессивной фиксации (95%) — потери могут достигать 15%.

---

## 3. Инженерная реализация (Rust PyO3 + Data-Oriented Design)

### 3.1. Проблема: Python-накладные расходы на 50K

Текущий стек: `Pydantic v2 → Python dict (SDST) → OR-Tools protobuf`. При 500 ops Python overhead = 68 мс из 28.5 с (0.24%). При 50K ops пропорции меняются:

| Операция | 500 ops | 50K ops (экстраполяция) |
|----------|---------|------------------------|
| Pydantic parse | 12 мс | ~500 мс |
| SDST lookup (dict) | Negligible | ~200 мс/итерацию ALNS |
| Beam Search scoring | ~1 мс | ~500 мс (dict overhead) |
| CP-SAT model build | 45 мс | ~10 с (модель не влезает) |

ALNS с 3 000 итерациями: dict-lookup overhead = $3\,000 \times 200$ мс = 10 мин чистого Python overhead.

### 3.2. Решение: CSR-матрица в Rust

**Array of Structures → Structure of Arrays.** Текущие `SetupEntry` — Python-объекты с `__dict__`. Каждое обращение — pointer chase (60–100 нс при L3 cache miss).

**CSR (Compressed Sparse Row):** 700K ячеек SDST = 3 массива в continuous memory:
- `row_ptr[M+1]` — указатели начала строк (M станков × состояний)
- `col_idx[NNZ]` — индексы столбцов (целевое состояние)
- `values[NNZ × 3]` — `(setup_minutes, material_loss, energy_kwh)` packed

Размер: ~700K × (4 + 4 + 12) байт ≈ **14 МБ** → помещается в L3 кэш целиком.

**PyO3 интеграция** через существующий шов в `accelerators.py` (67 LOC):
- Python: `SdstMatrix.from_pydantic(problem)` → Rust struct
- Rust: `fn score_atcs(matrix: &CsrSdst, candidates: &[u32], current_state: u32) -> Vec<f64>`

**Реалистичная оценка:** 50K ATCS-оценок в Rust с SIMD ≈ **5–15 мс** (не 1.5–3 мс — overhead на PyO3 FFI и CSR lookup не позволяет). Для сравнения: чистый Python — ~500 мс. Ускорение: **30–100×**.

### 3.3. Flattening модели

Конвертер `ScheduleProblem` → плоские массивы NumPy (zero-copy в PyO3 через `numpy` crate):
- `op_durations: np.ndarray[int32]` — длительности операций
- `op_eligible: List[np.ndarray[int32]]` — допустимые станки
- `precedences: np.ndarray[int32, (N, 2)]` — пары (pred, succ)
- `sdst_csr: RustCsrMatrix` — переналадки

Не FlatBuffers (избыточно для in-process), а прямой memoryview.

---

## 4. Пошаговый план (роадмап)

### Этап I. Rust-ядро для горячих путей

**Цель:** убрать Python из SDST-lookup и ATCS-scoring.

1. CSR-структура для SDST-матрицы в Rust (через PyO3 из `accelerators.py`)
2. `log_atcs_score()` в Rust с SIMD (autovectorization через `-C target-cpu=native`)
3. Beam Search scoring: Python оркестрирует, Rust считает
4. Бенчмарк: 50K операций × B=5 лучей, цель < 50 мс на оценку луча

**Не меняет:** API солверов, FeasibilityChecker, Router, Pydantic-модель.

### Этап II. ALNS-фреймворк

**Цель:** масштабируемая оркестрация для 5K–50K операций.

1. `AlnsSolver` — новый солвер в `synaps/solvers/`
2. 4 destroy-оператора: random, worst, related, Shaw
3. Repair через существующий `CpSatSolver` с frozen-переменными (minimal API change: `frozen_assignments: dict[UUID, UUID] | None`)
4. SA acceptance + FeasibilityChecker на каждом шаге
5. Параллелизм: `ProcessPoolExecutor` для независимых ALNS-потоков

**Зависит от:** Этапа I (CSR-матрица для быстрого scoring в destroy-операторах).

### Этап III. Receding Horizon Control (RHC)

**Источник:** Rawlings & Mayne (2009), "Model Predictive Control"; Subramanian et al. (2012) — RHC для scheduling.

**Цель:** ограничить горизонт перепланирования.

1. Скользящее окно ~48 часов: полная оптимизация внутри окна, frozen-агрегаты снаружи
2. Операции за горизонтом → макрообъекты (агрегированная нагрузка без детализации)
3. Совместим с ALNS (destroy только внутри окна) и с IncrementalRepair

**Не требует:** Rust-ядра. Может реализоваться на чистом Python поверх существующих солверов.

### Этап IV. GNN-ускорение (исследовательский)

**Цель:** сократить пространство поиска для ALNS/CP-SAT.

1. Dataset: 10 000+ решённых инстансов (CP-SAT оптимумы на 100–500 ops)
2. GNN модель: edge classification (вероятность назначения)
3. Интеграция: pre-filter перед ALNS (фиксация low-probability переменных)
4. Валидация: A/B сравнение с/без GNN на 1000+ инстансах

**Статус:** чисто исследовательский. Требует ML-инфраструктуры, которой в SynAPS нет.

---

## 5. Оценка целевых метрик

| Масштаб | Текущий SynAPS (v1) | Целевой SynAPS (v2, ALNS+Rust) | Публичный AI-first APS кейс (не side-by-side benchmark) |
|---------|---------------------|--------------------------------|---------------------|
| 500 ops | Gap <5%, 40 с (LBBD) | Gap <3%, 20 с (ALNS + micro-CP-SAT) | Секунды (NN) |
| 5 000 ops | Greedy only, gap неизвестен | Gap ~10–15%, ~15 мин (ALNS) | Секунды–минуты (NN) |
| 10 000 ops | Greedy, gap >>30% | Gap ~15–20%, ~30 мин (ALNS) | Минуты (NN) |
| 50 000 ops | Неприменимо | Gap ~20–30%, 1–2 ч (ALNS+RHC) | Минуты (NN) |

**Реалистичные ожидания:** SynAPS v2 вряд ли сравняется по latency-профилю с агрегированным AI-first APS кейсом без сопоставимого production data loop. Преимущество SynAPS — объяснимость, аудируемость и возможность проверять подзадачи и артефакты напрямую по коду.

---

## 6. Литература

1. Shaw P. (1998). "Using Constraint Programming and Local Search Methods to Solve Vehicle Routing Problems." CP-98. — *оригинальная LNS*
2. Ropke S., Pisinger D. (2006). "An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows." Transportation Science, 40(4), 455–472. — *ALNS framework, 3300+ цитирований*
3. Laborie P., Godard D. (2007). "Self-Adapting Large Neighborhood Search." CPAIOR. — *LNS+CP для scheduling*
4. Hooker J.N., Ottosson G. (2003). "Logic-Based Benders Decomposition." Mathematical Programming, 96, 33–60. — *LBBD*
5. Desrosiers J., Lübbecke M. (2005). "Column Generation." Springer. — *Branch-and-Price*
6. van den Akker J.M. et al. (2000). "Solving Set Partitioning Problems with Column Generation." Mathematical Programming, 88, 13–34. — *B&P для scheduling*
7. Gasse M. et al. (2019). "Exact Combinatorial Optimization with Graph Convolutional Neural Networks." NeurIPS. — *GNN для branching*
8. Nair V. et al. (2020). "Solving Mixed Integer Programs Using Neural Network Branching." — *GNN variable fixing*
9. Hottung A., Tierney K. (2020). "Neural Large Neighborhood Search for the Capacitated Vehicle Routing Problem." — *Neural LNS*
10. Yang L. et al. (2025). "Stable Variable Fixation for Accelerated Unit Commitment via GNN." Applied Sciences, 15(8), 4498. — *GNN variable fixing с промышленной валидацией*
11. Nguyen D.H. et al. (2024). "Faster, Larger, Stronger: Optimally Solving Employee Scheduling Problems with GNN." ISORA. — *GNN fix & reduce для scheduling*
12. Rawlings J.B., Mayne D.Q. (2009). "Model Predictive Control: Theory and Design." Nob Hill. — *RHC framework*
13. Veličković P. et al. (2018). "Graph Attention Networks." ICLR. — *GAT architecture*
14. Xu K. et al. (2019). "How Powerful are Graph Neural Networks?" ICLR. — *GIN*
15. Bagheri F. et al. (2024). "An ALNS Algorithm for Blocking Flowshop Scheduling with SDST." IJOR, 138924. — *ALNS для SDST scheduling*

---

## Итоги

Масштаб 50 000 операций в режиме полной объяснимости требует принципиально другой архитектуры, чем текущий CP-SAT / LBBD. Три ключевых изменения:

1. **ALNS вместо глобального MILP** — разрушить-починить вместо «решить всё разом» (Этапы I–II)
2. **Rust-ядро для горячих путей** — CSR-матрица + SIMD scoring вместо Python dict (Этап I)
3. **Receding Horizon** — скользящее окно вместо полного перепланирования (Этап III)

GNN (Этап IV) — исследовательский бонус, не блокер. ALNS + micro-CP-SAT + RHC могут работать без ML.

**Что остаётся прозрачным:** каждый micro-CP-SAT repair даёт локальный gap, FeasibilityChecker валидирует каждый шаг, destroy/repair логика полностью детерминирована (при фиксированном seed). Нейросеть (если добавлена) влияет только на скорость, не на допустимость.

**Что мы честно теряем:** глобальную нижнюю границу. ALNS не доказывает, что решение на X% от оптимума. Это — цена масштабируемости. APS Infimum тоже не даёт bound.
