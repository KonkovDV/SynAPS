# Wave 15 — Алгебра SynAPS: Red Team план для ИИ-программиста

> **Дата:** 2026-08-12  
> **Режим:** только план и маршрутизация. **Код в этой сессии не править.**  
> **Аудитория:** автономный ИИ-программист (следующая сессия).  
> **Контекст:** Waves 1–14 + RT-19/RT-20 (GridPlan) уже закрыли часть дыр; этот документ — **гиперглубокий алгебраический** backlog.

---

## 0. Исполнительная сводка (простыми словами)

SynAPS решает **MO-FJSP-SDST-ARC**: гибкий цех с переналадками (SDST) и общими ресурсами.  
Ядро честное там, где есть **нотариус** (`FeasibilityChecker`) + portfolio verify.  
Критический риск для академической и продуктовой репутации: **ложный `FEASIBLE`** у RHC/ALNS (покрытие ops ≠ выполнимость алгебры) и **композиция frozen** после очистки рёбер предшествования.

ИИ-программист должен сначала **закрыть теорему «статус = нотариус»**, потом dual-bound honesty, потом масштабирование RHC по литературе 2025–2026. Без этого любые цифры «оптимум / gap» — уязвимы для жюри и рецензентов.

---

## 1. Каноническая алгебра (что защищать)

SSOT математики: [`docs/architecture/02_CANONICAL_FORM.md`](../architecture/02_CANONICAL_FORM.md).  
SSOT полей × солверов: [`docs/architecture/SOLVER_FIELD_CONFORMANCE.md`](../architecture/SOLVER_FIELD_CONFORMANCE.md) + `tests/test_model_field_conformance.py`.

### 1.1 Объекты (код)

| Объект | Файл | Инварианты |
|--------|------|------------|
| `Order` | `synaps/model.py` | `release_date?`, `due_date`, `priority`, `quantity>0` |
| `Operation` | то же | линейная цепочка в заказе (`predecessor_op_id`); `eligible_wc_ids=[]` = все WC |
| `WorkCenter` | то же | `speed_factor>0`, `max_parallel≥1` |
| `SetupEntry` | то же | SDST `(wc, from_state, to_state) → minutes/material/energy` |
| `AuxiliaryResource` + `OperationAuxRequirement` | то же | concurrent pool |
| `Assignment` | то же | `[start,end)`, `setup_minutes`, optional `lane_id` |
| `ObjectiveValues` | то же + `synaps/objective.py` | coverage ≻ makespan ≻ weighted_sum |

### 1.2 Жёсткие ограничения (нотариус)

`FeasibilityChecker.check` (`synaps/solvers/feasibility_checker.py`):

| Kind | Смысл |
|------|--------|
| `MISSING_/DUPLICATE_ASSIGNMENT` | полнота |
| `UNKNOWN_OPERATION` / `UNKNOWN_WORK_CENTER` | референциальная целостность (RT-20) |
| `MACHINE_OVERLAP` / `MACHINE_CAPACITY_VIOLATION` | машины / lanes |
| `SETUP_GAP_VIOLATION` / `MISSING_SETUP_ENTRY` | SDST |
| `PRECEDENCE_VIOLATION` | цепочки заказов |
| `RELEASE_DATE_VIOLATION` | `start ≥ release` |
| `HORIZON_BOUND_VIOLATION` | горизонт |
| `AUX_RESOURCE_CAPACITY_VIOLATION` | ЗИП/инструмент как pool |
| `LANE_INFERENCE_UNPROVEN` | **advisory**, не hard (`ADVISORY_VIOLATION_KINDS`) |

### 1.3 Целевая алгебра

`synaps/objective.py`:

- **Coverage** — level-0 (брошенные ops не должны «улучшать» makespan).
- **Makespan** — max end offset.
- **Setup/material/energy** — по **lane**, не по WC целиком (параллель без phantom setup).
- **Tardiness** — незапланированный заказ = completion на конце горизонта (F10).
- **Scalarize** — явные веса; default makespan-only.

### 1.4 Портфель (гарантии ≠ маркетинг)

| Контур | Гарантирует | Не гарантирует |
|--------|-------------|----------------|
| GREED / BEAM | Быстрый feasible-first + dispatch rules | Оптимум |
| CP-SAT | Dual bound / OPTIMAL при доказательстве | Масштаб ≫ тысяч ops |
| LBBD / LBBD-HD | Декомпозиция + cuts (осторожно с soundness) | Всегда OPTIMAL |
| IncrementalRepair | Локальный ремонт + freeze | Asset topology (это GridPlan) |
| ALNS | Улучшение окрестностей | Что `FEASIBLE` = нотариус без дыр |
| RHC | Масштаб по окнам | Что покрытие = выполнимость |

---

## 2. Академический ландшафт (авг 2026) — якоря для решений

ИИ-программист **обязан** перечитать primary sources перед фиксом класса задач (не полагаться на память).

| Тема | Якорь | Что взять в SynAPS |
|------|-------|-------------------|
| Learning-guided RHO / FJSP | arXiv:2502.15791 + ICLR 2025 L-RHO | Не «учить оптимум», а учить **какие переменные фиксировать** между окнами; CP-SAT внутри окна |
| ALNS-CP для FJSP + ресурсы | EJOR 2024/25 unified ALNS-CP (City Research Online / openaccess.city.ac.uk/33482) | Long-term memory пар операций → доп. constraints для CP repair |
| LBBD DFJSP | EJOR 329 (2026) | Sound master; отказываться от невалидных optimality cuts |
| RFJSP-SDST + IL/CP | TST 2026 | Frozen aux должен резервировать pool |
| JIT JSSP + SDST | COR / Polito RVNS+CP-SAT | CP-SAT как seed; metaheuristic чинит timing |
| CP-SAT scheduling practice | Perron Scheduling Seminar; CP-SAT Primer (Krupke) | Tight horizon, hints, circuit/SDST gaps; dual bound honesty |
| ASP / multi-shot JSP | LMCS 2025/26 decomposition | Альтернатива декомпозиции — не цель Wave 15, но benchmark-контекст |
| Промышленные конкуренты | **Timefold 2.0 (Mar 2026)**; DELMIA Ortems/Quintiq; FICO/Xpress APS | Дифференциация SynAPS: **нотариус + dual bound + repair algebra**, не UI APS |

Внутренние lit-briefs уже есть: `docs/rfc/LIT_AUG2026_SYNAPS_BRIEF.md`, `LIT_AUG2026_WAVE13_BRIEF.md`, W14 audit.

---

## 3. Red Team: открытый реестр угроз алгебре

### 3.1 Уже закрыто (не трогать без регрессии)

| ID | Что | Где закрыто |
|----|-----|-------------|
| RT-19 L3 | Repair игнорировал `release_date` | `incremental_repair.py` + тесты |
| RT-20 S1 | Phantom op/wc | `UNKNOWN_*` в checker |
| RT-20 S3 | RHC greedy без release floor | `rhc/_solver.py` `op_floor` ×2 |
| RT-20 S4/S5/S6 | repair kwargs, time-limit meta, zip strict | `portfolio.py`, `accelerators.py` |
| Waves 5–14 | Lane exact search, frozen CP-SAT SDST, RHC→ALNS offsets (частично) | RFC WAVE*_DELTA |

### 3.2 Открыто — P0 (делать первым)

| ID | Угроза | Файлы | Атака | Требование к фиксу |
|----|--------|-------|-------|-------------------|
| **A15-P0-1** | RHC ставит `FEASIBLE` по `scheduled_count == total_ops` **без** финального `FeasibilityChecker` | `rhc/_solver.py` ~2468–2471 | Любой residual после stabilize / release edge | После финального stabilize: `hard_violations(check(...))`; иначе `ERROR` + kinds в metadata |
| **A15-P0-2** | ALNS: cleared `predecessor_op_id` + frozen pred → succ раньше pred; checker не видит cleared edge | `alns_solver.py`, `rhc/_solver.py` pred-clear | Window-2 op на другой машине до конца frozen pred | Либо не чистить рёбра для проверки; либо передавать frozen precedence offsets **везде**; финальный check с restored graph |
| **A15-P0-3** | ALNS: setup vs frozen не в `_has_machine_overlap` | `alns_solver.py` ~2014–2024, accept ~3936 | `end_frozen == start_free` при setup>0 | Setup-aware gap к frozen timeline; тест SETUP_GAP |
| **A15-P0-4** | Stabilize исчерпал `max_passes` → residual conflict + `FEASIBLE` | `rhc/_window.py` stabilize | Длинная SDST-цепь | Если `changed` после cap → `ERROR` / refuse commit |
| **A15-P0-5** | Portfolio: `base_assignments` без integrity / empty disruption = «легализация» подмены | `portfolio.py`, `contracts.py` | `disrupted_op_ids=[]` + сдвинутый base | Fingerprint / verify base vs commitment; fail-closed |

### 3.3 Открыто — P1

| ID | Угроза | Действие |
|----|--------|----------|
| **A15-P1-1** | `exact_required` игнорируется early regime branches | `router.py`: exact побеждает INTERACTIVE/latency≤1 или явный reject |
| **A15-P1-2** | Имя `CPSAT-30` при clamp 5s | Публиковать `effective_time_limit_s` (частично есть `solver_time_limit_s`) + не лгать в `solver_config` |
| **A15-P1-3** | ALNS tier shadowing (ALNS-300 при latency 400) | Поправить ветвление latency в router |
| **A15-P1-4** | Replay top-level `feasible` vs verification.performed | Развести поля; consumers читают verification |
| **A15-P1-5** | Replay без seed / kwargs fingerprint | Добавить в artifact |
| **A15-P1-6** | RHC stabilize двигает committed («frozen») окна | Stabilize не трогает committed или помечает `commitment_broken` |
| **A15-P1-7** | Commit precedence gate off вне SEARCH_COVER | Default BALANCED: gate on **или** обязательный финальный нотариус (P0-1) |
| **A15-P1-8** | `_violates_frozen_precedence` offset path мёртв без `horizon_start` | Протащить horizon во все call sites |
| **A15-P1-9** | Soft-only resource timeout | Документировать честно + hard wall где возможно |
| **A15-P1-10** | Fan-in precedence (модель только цепочка) | Либо reject multi-pred на ingest, либо расширить модель (отдельный RFC; GridPlan уже fail-closed) |

### 3.4 P2 / hygiene

Wall-clock nondeterminism ALNS/RHC; native greedy eligible-CSR `[]≠all`; advisory swallow; accel status OR-mask; stale ALNS flake tests (`test_alns_*` на pristine master).

---

## 4. Детальный план работ для ИИ-программиста

### Режим исполнения

1. Читать этот файл + `02_CANONICAL_FORM.md` + `SOLVER_FIELD_CONFORMANCE.md` + последний WAVE14 delta.  
2. **Каждый P0** = probe-тест (красный) → минимальный фикс → зелёный + полный focused suite.  
3. Не расширять scope на native ABI / GPL / UI.  
4. После ≥3 файлов или нового порта — 4-phase protocol (если в репо активен).  
5. На Windows: после правок `pip install -e . --force-reinstall --no-deps` + `inspect.getsource` (урок RT-19/20).  
6. Коммит/пуш — только по явной команде пользователя (если в правилах сессии иначе — следовать правилам сессии).

### Фаза 0 — Карта и probes (½–1 день)

| Шаг | Действие | Exit |
|-----|----------|------|
| 0.1 | Таблица «солвер × проверка нотариусом в конце» | Документ 1 страница в RFC |
| 0.2 | Написать `tests/test_algebra_rt15_probes.py` с **ожидаемо красными** кейсами A15-P0-1…4 | Probes воспроизводят ложный FEASIBLE |
| 0.3 | Зафиксировать baseline: `pytest tests/test_rt20_probes.py tests/test_model_field_conformance.py -q` | Зелёный |

### Фаза 1 — Теорема статуса (P0-1…4) (2–4 дня) — **критический путь**

| Шаг | ID | Работа | Тесты | Exit |
|-----|-----|--------|-------|------|
| 1.1 | P0-1 | Финальный hard-check в RHC перед статусом | probe + `test_rhc_*` | Нет FEASIBLE при hard kinds |
| 1.2 | P0-4 | Stabilize: если не сошлось → ERROR | unit на max_passes | |
| 1.3 | P0-2 | Frozen precedence после pred-clear | ALNS+RHC composition | |
| 1.4 | P0-3 | Setup vs frozen в accept + final | SETUP_GAP probe | |
| 1.5 | | `npm`/pytest focused: repair, rhc, alns_rhc_scaling (без flake-only) | | Зелёный critical path |

**Теорема (записать в metadata RFC):**  
∀ solver S ∈ {RHC, ALNS, Repair, GREED, CPSAT}:  
`status ∈ {FEASIBLE, OPTIMAL} ⇒ hard_violations(check(problem, assignments)) = ∅`.

### Фаза 2 — Portfolio honesty (P0-5 + P1-1…5) (1–2 дня)

| Шаг | Работа | Exit |
|-----|--------|------|
| 2.1 | Integrity `base_assignments` (hash / verify / refuse empty-disruption forgery) | Probe forge fails |
| 2.2 | Router: `exact_required` семантика | Test matrix regimes |
| 2.3 | Effective time limit vs config name | Metadata contract test |
| 2.4 | Replay feasible vs verification | Contract test |

### Фаза 3 — Dual bound & objective algebra (1–2 дня)

| Шаг | Работа | Exit |
|-----|--------|------|
| 3.1 | Аудит CP-SAT: `best_objective_bound` единицы = claimed units | Уже частично в GridPlan; повторить в SynAPS metadata |
| 3.2 | Все эвристики финальный objective только через `objective.evaluate` + `scalarize` | Grep запрет локальных сумм |
| 3.3 | Публикация gap: `(obj − bound) / bound` только если bound comparable | Doc + test |

Лит-якорь: Perron (energetic relaxations); CP-SAT Primer; GridPlan Scenario D как продуктовый образец честности.

### Фаза 4 — RHC масштабирование по SOTA (опционально, после P0) (3–5 дней)

| Шаг | Работа | Не делать |
|-----|--------|-----------|
| 4.1 | Протокол сравнения vs L-RHO идеи: какие vars freeze между окнами | Не тащить полный DRL pipeline в runtime |
| 4.2 | ALNS-CP memory constraints (EJOR ALNS-CP) как **optional** hints | Не ломать determinism lane |
| 4.3 | Бенчмарк 50k/500k по `docs/research/RHC_500K_SCALING_PROTOCOL_2026.md` | Не заявлять SOTA без таблицы |

### Фаза 5 — Модель / доменные дыры (согласовать с человеком)

| Тема | Решение | Почему escalation |
|------|---------|-------------------|
| Fan-in/fan-out precedence | RFC: reject vs expand DAG | Меняет публичный контракт модели |
| Asset topology | Остаётся в GridPlan | Не раздувать SynAPS kernel |
| Stability objective R в каноне | Roadmap | Нет runtime |

### Фаза 6 — Закрытие

| Шаг | Exit |
|-----|------|
| 6.1 | RFC `WAVE15_REDTEAM_DELTA.md` (таблица ID → commit) |
| 6.2 | Обновить `SOLVER_FIELD_CONFORMANCE.md` если поведение изменилось |
| 6.3 | Focused suites + architecture ratchet | Все зелёные |
| 6.4 | ALNS flake: либо quarantine `@pytest.mark.flaky`, либо починить seed — **отдельно**, не маскировать P0 |

---

## 5. Порядок чтения кода (обязательный onboarding)

1. `synaps/model.py` — валидаторы цепочек  
2. `synaps/objective.py` — evaluate / scalarize / F10  
3. `synaps/solvers/feasibility_checker.py` — нотариус  
4. `synaps/solvers/_dispatch_support.py` — `find_earliest_feasible_slot`  
5. `synaps/solvers/cpsat_solver.py` — exact + bounds  
6. `synaps/solvers/incremental_repair.py` — repair algebra  
7. `synaps/solvers/rhc/_solver.py` + `_window.py` + `_policy.py`  
8. `synaps/solvers/alns_solver.py` — destroy/repair/accept  
9. `synaps/portfolio.py` + `solvers/router.py` + `solvers/registry.py`  
10. `synaps/replay.py` + `contracts.py`  
11. Тесты: `test_model_field_conformance.py`, `test_rt20_probes.py`, `test_incremental_repair.py`, `test_feasibility_*`

---

## 6. Критерии успеха Wave 15

| # | Критерий | Измерение |
|---|----------|-----------|
| 1 | Теорема статуса | 0 ложных FEASIBLE на P0 probes |
| 2 | Conformance matrix | Все представители зелёные |
| 3 | Dual bound honesty | Нет «OPTIMAL» без bound==obj (в единицах) |
| 4 | Portfolio forgery | Empty-disruption + moved base → reject |
| 5 | Документация | WAVE15 delta + обновлённый lit brief |
| 6 | Не регрессировать GridPlan 0.1.9 pin path | После merge — прогон GridPlan adversarial + RES (not slow) |

---

## 7. Анти-паттерны для ИИ-программиста

- «Починил эвристику, нотариус потом» — наоборот: сначала нотариус на выходе.  
- Молчаливый fallback GREED с брендом CPSAT/ALNS.  
- Расширение модели без RFC (fan-in).  
- Заявление SOTA по L-RHO без воспроизводимой таблицы.  
- Игнор stale editable install на Windows.  
- Править flake ALNS вместо P0 ложного FEASIBLE.

---

## 8. Рекомендуемая первая команда следующей сессии

```text
Выполни Wave 15 Фазу 0–1 по docs/rfc/WAVE15_ALGEBRA_REDTEAM_PLAN_2026_08_12.md:
сначала красные probes A15-P0-1..4, затем финальный FeasibilityChecker в RHC,
затем ALNS frozen precedence/setup. Код править. Коммит только когда попрошу.
```

---

## 9. Карта связей с GridPlan / Марафоном

- Демо-путь Марафона: GREED + IncrementalRepair + CPSAT-30 — **уже усилен RT-19/20**.  
- Wave 15 критичен, если жюри/заказчик включает **RHC/ALNS** или BFF repair API.  
- Asset exclusivity остаётся в GridPlan (`ASSET_OVERLAP`) — не дублировать в SynAPS без RFC.

---

*Конец плана. Код в подготовительной сессии не изменялся.*
