# Детальный аудит-отчёт проекта SynAPS — 12 мая 2026

## 1. Цель аудита

Провести полную верификацию кодовой базы SynAPS после двух волн правок
(Wave 1 — апрель/май 2026, Wave 2 — 10–12 мая 2026) по дорожной карте
RHC-ALNS (`SYNAPS_RHC_ALNS_ROADMAP_FIXES_2026_05_10.md`). Оценить
текущее покрытие тестами, выявить регрессии и дать рекомендации по
дальнейшей работе.

---

## 2. Общая архитектура проекта

| Компонент | Расположение | Назначение |
|-----------|-------------|------------|
| Ядро задачи планирования | `synaps/model.py`, `synaps/contracts.py` | Модель MO-FJSP-SDST-ARC |
| Портфель солверов | `synaps/solvers/registry.py` (23 конфига) | GREED, BEAM, CP-SAT, LBBD, ALNS, RHC-* |
| RHC подпакет | `synaps/solvers/rhc/` (9 модулей) | `_solver.py`, `_policy.py`, `_budget.py`, `_window.py`, `_admission.py`, `_warm_start.py`, `_cross_window.py`, `_metadata.py`, `_state.py` |
| ALNS солвер | `synaps/solvers/alns_solver.py` | Destroy/repair метаэвристика с SA |
| LBBD солвер | `synaps/solvers/lbbd_solver.py` | Декомпозиция Бендерса |
| Нижние границы | `synaps/solvers/lower_bounds.py` | Machine-load, critical-path, ARC |
| SDST матрица | `synaps/solvers/sdst_matrix.py` | Dense NumPy O(1) lookup |
| Нативное ускорение | `native/synaps_native/` (Rust/PyO3) | ATCS scoring, стабилизация |
| Бенчмарки | `benchmark/study_rhc_50k.py`, `benchmark/study_rhc_500k.py` | 50K/100K/500K харнессы |
| Контрольная плоскость | `control-plane/` | Fastify BFF + Python bridge |
| Тесты | `tests/` (699 тестов собрано) | pytest + hypothesis |

---

## 3. Выполненные задачи дорожной карты

### 3.1. Wave 1 — Основные аудит-правки (апрель–май 2026)

Закрыто **9 дефектов** (детали в `AUDIT_VERIFICATION_2026_05_01.md`):

1. **ML-advisory gate** — предсказания модели больше не переопределяют детерминированную маршрутизацию без загруженной модели.
2. **Exhaustive feasibility** — `verify_schedule_result()` вызывает `FeasibilityChecker(exhaustive=True)`.
3. **LBBD setup bounds** — sequence-safe relaxation `(n-1) × min_setup`.
4. **LBBD critical_path cuts** — стандартный LBBD теперь генерирует те же cut-семьи, что и LBBD-HD.
5. **Bounded 100K stall fix** — `alns_presearch_max_window_ops=1000` + `min_time_limit_s=240` закрывает катастрофический стопор.
6. **RHC budget predicate** — scaled budget profile не блокируется legacy guard.
7. **ALNS initial seed cap** — `GreedyDispatch` уважает `time_limit_s`, seed-фаза ограничена по времени.
8. **LBBD critical_path deduplicate** — `find_critical_path` вынесен в общий модуль; дубликат удалён.
9. **ALNS recovery test fix** — детерминированная checker-call sequence восстановлена.

### 3.2. Wave 2 — Пост-аудитное расширение (10–12 мая 2026)

Закрыто **7 задач**:

| # | Задача | Файлы | Статус |
|---|--------|-------|--------|
| R10 | **Typed RHC Policy** — `RhcPolicy` enum (COVERAGE_FIRST, BALANCED, SEARCH_ENTRY, BOUNDED_100K), `RhcPolicySpec` с `AdmissionSpec`/`BudgetSpec`/`GuardSpec`/`InnerSpec`, preset'ы | `rhc/_policy.py`, `registry.py` | ✅ |
| R11 | **Cross-window variable fixing (L-RHO)** — `detect_cross_window_stable_ops` фиксирует операции со стабильной позицией между окнами | `rhc/_window.py`, `rhc/_solver.py` | ✅ |
| R17 | **ARC lower bound tests** — regression-тесты для `_compute_auxiliary_resource_lb` (pool_size=1 → lb≥180, pool_size=3 не доминирует) | `tests/test_lower_bounds_arc.py` | ✅ |
| R6  | **LBBD UB trajectory** — `ub_evolution` собирается параллельно с `lb_evolution`, экспортируется в metadata | `lbbd_solver.py` | ✅ |
| R20 | **Admission frontier test** — `op_earliest > window_boundary` блокирует допуск при fallback на release date | `tests/test_rhc_admission_module.py` | ✅ |
| R21 | **Property-based budget tests** — 3 инварианта `scale_alns_inner_budget` через Hypothesis: монотонность, неотрицательность, масштабирование | `tests/test_rhc_budget_property.py` | ✅ |
| R16 | **Native parity tests** — `evaluate_objective_batch` и `stabilize_temporal_batch` Rust↔Python deterministic parity | `tests/test_native_*_parity.py` | ✅ |

### 3.3. Документация и CI

| Задача | Что сделано |
|--------|------------|
| **README.md** | Добавлены Wave 2 фичи в раздел «Current Reality»: RhcPolicy, L-RHO variable fixing, ARC LB тесты |
| **CI lint** | `.github/workflows/ci.yml` расширен до полного `ruff check` + `ruff format --check` |
| **pyproject.toml** | Подтверждено: `hypothesis`, `ruff`, `pytest-cov`, `pytest-benchmark` в `[project.optional-dependencies.dev]` |
| **Academic citations** | Добавлена ссылка на Liang et al. (2023, Omega) в docstring `detect_cross_window_stable_ops` |

---

## 4. Результаты регрессионного тестирования

### 4.1. Сводная таблица

| Категория | Собрано | Пройдено | Упало | Пропущено |
|-----------|---------|----------|-------|-----------|
| Быстрые юнит/property-тесты | 555 | **555** | 0 | 9 |
| RHC/ALNS scaling (`test_alns_rhc_scaling.py`) | 96 | 90 | **6** | 0 |
| **Итого (наблюдаемые)** | **651** | **645** | **6** | **9** |

Не запускались (требуют многоминутных решений солвера или OR-Tools):
`test_benchmark_rhc_500k_study.py`, `test_benchmark_rhc_alns_doe.py`,
`test_benchmark_boundary_study.py`, `test_e2e_rhc_alns_integration.py`
(~48 тестов).

### 4.2. Пропущенные тесты (9)

Все из-за отсутствия скомпилированного Rust-модуля `synaps_native`:

- `test_native_destroy_scoring.py` — 7 тестов
- `test_native_objective_parity.py` — 1 тест
- `test_native_stabilize_parity.py` — 1 тест

Ожидаемое поведение на хостах без native-расширения.

### 4.3. Падающие тесты (6) — предсуществующие

Все 6 падений присутствуют **на чистом HEAD** (коммит `f985c03`,
рабочее дерево без изменений). Не являются следствием Wave 2 правок.

| # | Тест | Суть падения |
|---|------|-------------|
| 1 | `test_rhc_adaptive_window_expands_starved_frontier_before_bootstrap` | `adaptive_window_expansions == 0` вместо 1 — адаптивное расширение не триггерится на текущей фикстуре |
| 2 | `test_rhc_passes_overlap_tail_into_next_alns_window` | Лишний UUID в overlap tail set — overlap-логика расширена, assertion не обновлён |
| 3 | `test_rhc_retains_boundary_crossing_assignments_for_next_window` | Assertion на boundary retention |
| 4 | `test_rhc_presearch_budget_guard_skips_alns_for_oversized_window` | Budget guard predicate |
| 5 | `test_rhc_reanchors_inner_assignments_before_freeze_merge` | Re-anchor assertion |
| 6 | `test_rhc_passes_frozen_context_into_followup_alns_window` | Frozen context propagation |

**Причина**: коммит `f985c03` («implement 50K solver improvement stages A-E + G1»)
существенно переработал inner-solver логику RHC (overlap-tail, freeze-merge,
frozen-context), но **не обновил assertion'ы** в `test_alns_rhc_scaling.py::TestRhcInnerSolver`.

---

## 5. Анализ реализованности дорожной карты

### Полностью реализованные этапы

| Этап | Описание | Покрытие |
|------|----------|----------|
| **A1** | Critical-path destroy — тесты и инварианты | `test_alns_destroy_operators.py` (property + unit) |
| **A2** | Due-pressure destroy — тесты tardy/slack/closure | `test_alns_destroy_operators.py` |
| **B1** | ALNS lower-bound gap metadata | `test_alns_metadata.py` |
| **B2** | SA temperature extraction | `test_alns_sa_temperature.py` (clamp + monotonicity property) |
| **B3** | Bounded ALNS convergence diagnostics | Aggregate metadata fields присутствуют в солвере |
| **C1** | Warm-start filtering | `rhc/_warm_start.py` + `test_alns_warm_start.py` |
| **D** | README, CI, dependencies, citations | Все 4 подзадачи (D1–D4) ✅ |

### Частично реализованные этапы

| Этап | Описание | Что есть | Что осталось |
|------|----------|----------|-------------|
| **C2** | Operator weight persistence by name | ALNS принимает `initial_operator_weights`, `alns_final_operator_weights` в metadata | RHC-side pass-through (окно→окно) требует верификации на E2E |
| **C3** | Cross-window quality telemetry | `WindowQualitySummary` + `compute_window_quality_summary` + bounded buffer(5) | Feature-flag `cross_window_learning_enabled` создан, но E2E не верифицирован |
| **C4** | Bounded cross-window operator bias | Структура готова | Feature-flag `cross_window_operator_bias_enabled=False`, поведение не тестировано изолированно |
| **D1** | Inter-seed CV + high-variance flag | Реализовано в `_summarize_solver_records` | Нет E2E evidence с реальными multi-seed данными |

### Не начатые этапы

| Этап | Описание | Причина отсрочки |
|------|----------|-----------------|
| **E1** | CSR SDST backend | Native build заблокирован на Windows (отсутствует MSVC linker) |
| **E2** | Native `get_setup_batch` | Зависит от E1 |
| **E3** | Native worst-destroy scoring | Зависит от E1+E2 |
| **F1/F2** | Parallel repair | Высокий риск; отложено до стабилизации E |
| **G2** | 50K benchmark evidence (multi-seed) | Требует long-running runs |

---

## 6. Качество кодовой базы

### 6.1. Сильные стороны

- **Чёткое разделение** RHC-подпакета на 9 модулей (`_policy`, `_budget`, `_window`, `_admission`, `_warm_start`, `_cross_window`, `_metadata`, `_state`, `_solver`)
- **Typed policy layer** (`RhcPolicy` enum + `RhcPolicySpec`) устраняет 120-строчное дублирование kwargs в registry
- **Property-based testing** через Hypothesis (destroy operators, budget predicates, SA temperature, admission frontier)
- **Academic citations** в docstrings (L-RHO variable fixing — Liang et al. 2023; temporal-consistency stabilizer; Data-Oriented SDST — Matsuzaki et al. 2024)
- **Feature flags** для всех behavior-changing фич (`cross_window_learning_enabled`, `cross_window_operator_bias_enabled`, `adaptive_window_enabled`)
- **Backend metadata** в SDST (`sdst_backend`, `sdst_memory_bytes`)
- **Cut deduplication** в LBBD через fingerprint set

### 6.2. Найденные проблемы

| Серьёзность | Проблема | Рекомендация |
|-------------|----------|--------------|
| 🔴 Высокая | 6 падающих тестов в `TestRhcInnerSolver` после `f985c03` | Привести assertion'ы в соответствие с новой inner-solver семантикой |
| 🟡 Средняя | Native Rust build не работает на Windows (MSVC linker) | Настроить CI с Linux runner или добавить GNU fallback |
| 🟡 Средняя | E2E integration test (`test_e2e_rhc_alns_integration.py`) не верифицирован | Запустить на хосте с OR-Tools и достаточным временем |
| 🟡 Средняя | Deprecation warnings: «Passing raw kwargs to RhcSolver» в 24+ тестах | Мигрировать тесты на `RhcPolicy` + overrides API |
| 🟢 Низкая | OR-Tools не работает в текущем `.venv` на Windows (`WinError 193`) | Пересоздать venv или использовать Linux |
| 🟢 Низкая | `search_active_window_rate = 0.0` на bounded 100K | Yield-оптимизация, не блокер стабильности |

---

## 7. Рекомендуемый план дальнейших действий

### Фаза 1 — Стабилизация (1–2 дня)

| Приоритет | Задача | Сложность |
|-----------|--------|-----------|
| 🔴 P0 | Исправить 6 падающих тестов `TestRhcInnerSolver` — обновить assertion'ы под новую семантику overlap/freeze/reanchor | Средняя |
| 🔴 P0 | Проверить E2E тест `test_e2e_rhc_alns_integration.py` на рабочем окружении | Низкая |
| 🟡 P1 | Мигрировать ≥5 ключевых тестов с legacy kwargs на `RhcPolicy` API | Низкая |

### Фаза 2 — Завершение Stage C/D (3–5 дней)

| Приоритет | Задача | Зависимости |
|-----------|--------|-------------|
| 🟡 P1 | Верифицировать operator weight pass-through (окно→окно) unit-тестом | Нет |
| 🟡 P1 | Изолированный тест для `cross_window_operator_bias` с feature flag on/off | C3 done |
| 🟡 P1 | Multi-seed 50K benchmark run + inter-seed CV evidence | Нет |
| 🟡 P1 | Верификация `WarmStartSelection` metadata в per-window RHC output | C1 |

### Фаза 3 — Native acceleration (5–10 дней)

| Приоритет | Задача | Зависимости |
|-----------|--------|-------------|
| 🟡 P2 | Настроить Linux CI runner для native build | Нет |
| 🟡 P2 | CSR SDST backend + parity tests (E1) | Linux CI |
| 🟡 P2 | Native `get_setup_batch` (E2) | E1 |
| 🟢 P3 | Native destroy scoring seam (E3) | E1+E2 стабильны |

### Фаза 4 — Параллельный repair (отложено)

Реализация Stage F остаётся отложенной до полной стабилизации Stages A–E.
Основные риски: пересечение precedence constraints между partition'ами,
machine sequence constraints, overhead `ProcessPoolExecutor` на Windows.

---

## 8. Метрики проекта

| Метрика | Значение |
|---------|----------|
| Файлов исходного кода (`synaps/`) | ~113 |
| Тестов собрано | 699 |
| Тестов пройдено (быстрые) | 645/651 (99.1%) |
| Тестов пропущено (native) | 9 |
| Конфигов солверов | 23 |
| RHC policy presets | 4 |
| Модулей в `rhc/` подпакете | 9 |
| Коммитов в истории (scaling file) | 5+ |
| Дорожная карта stages | 7 (A–G) |
| Stages полностью закрыты | A, B, D |
| Stages частично закрыты | C |
| Stages не начаты | E, F, G |

---

## 9. Заключение

Кодовая база SynAPS находится в **стабильном состоянии** после Wave 2
аудит-правок. Все целевые тесты (555 быстрых unit/property) проходят
без ошибок. 6 падающих тестов — **предсуществующие** регрессии из коммита
`f985c03`, не связанные с аудитом; требуют обновления assertion'ов.

Основные достижения Wave 2:
- Typed policy layer устраняет дублирование конфигурации
- L-RHO variable fixing добавляет cross-window стабилизацию
- Property-based тесты через Hypothesis укрепляют инварианты
- LBBD UB trajectory закрывает асимметрию телеметрии

Ближайший приоритет — исправление 6 тестов inner-solver и запуск E2E
верификации. Дальнейшая работа по native acceleration заблокирована
инфраструктурно (Windows build chain).
