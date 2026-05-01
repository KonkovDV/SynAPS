# SynAPS — Пост-R1 план: устранение initial-seed bottleneck и продолжение к LBBD

> **Дата**: 2026-05-01 (Europe/Moscow, UTC+03:00).
> **Репозиторий**: head `26a2e55` (`fix(rhc): prefer scaled ALNS budget profile at 100k`).
> **Основание**: bounded 100K артефакт `benchmark/studies/2026-05-01-rhc-100k-audit-v8-post-predicate-fix/rhc_500k_study.json`.
> **Цель документа**: зафиксировать верификацию R1, задокументировать root-cause v8-блокера,
> дать точечный план минимально-необходимых правок, тестов и прогона, и только после
> этого продолжать усиление LBBD (Wave 3).

## 0. TL;DR

- Все заявленные правки приняты: R1 в `@c:/plans/SynAPS/synaps/solvers/rhc_solver.py:1910-1923`,
  регрессия `test_rhc_presearch_budget_guard_prefers_scaled_budget_profile_over_legacy_size_cut`
  в `@c:/plans/SynAPS/tests/test_alns_rhc_scaling.py:3006`, обновления в
  `AUDIT_VERIFICATION_2026_05_01.md`, `NEXT_WAVE_EXECUTION_PLAN_2026_05_01.md`,
  `benchmark/README.md`, `benchmark/README_RU.md`, артефакты v7 и v8 закоммичены.
- **v8 подтверждает корректность R1**: budget-guard больше не блокирует ALNS
  (`alns_presearch_budget_guard_skipped_windows = 0`), ALNS входит в поиск.
- **v8 вскрывает следующий корневой дефект**: `GreedyDispatch.solve()` не принимает
  `time_limit_s`, а ALNS на большом окне (n_ops ≈ 2078 > `frozen_initial_repair_max_ops = 512`)
  вызывает `GreedyDispatch().solve(problem)` **без бюджета** на строке
  `@c:/plans/SynAPS/synaps/solvers/alns_solver.py:1367`. В результате фаза 1 строит сид
  ≈808 с, фаза 2 отработать не успевает, `iterations_completed = 0`,
  `assigned_ops = 0`, `solve_ms = 818286`.
- Минимальный восходящий патч — 2 связанных правки:
  1. Добавить поддержку `time_limit_s` в `GreedyDispatch.solve()` с проверкой
     в основном `while remaining:` и статусом `TIMEOUT` при исчерпании.
  2. Во всех точках вызова `GreedyDispatch().solve(problem)` из `alns_solver.py`
     передавать `time_limit_s = max(1.0, time_limit_s − (time.monotonic() − t0))`,
     а при `TIMEOUT` возвращать `_initial_generation_error_result(...)` — RHC сам
     упадёт в свой внешний greedy-фоллбек.
- После патча прогнать bounded 100K:
  `python -m benchmark.study_rhc_500k --scales 100000 --solvers RHC-ALNS RHC-GREEDY
  --lane throughput --time-limit-cap-s 90 --max-windows-override 2
  --write-dir benchmark/studies/2026-05-08-rhc-100k-audit-v9-post-initial-seed-fix`.
  Критерии приёмки — см. § 5.3.
- Только после успешного v9 переходить к Wave 3: LBBD `machine_tsp` cuts,
  de-duplication, LB/UB trajectory metadata, ARC-aware LB (R4, R5, R6, R8 из
  `HYPERDEEP_ACADEMIC_AUDIT_2026_05_01.md`).

## 1. Верификация заявленных изменений

Все пункты — G3 (код + артефакт).

### 1.1 R1 в `rhc_solver.py`

`@c:/plans/SynAPS/synaps/solvers/rhc_solver.py:1909-1923`:

```python
budget_guard_estimated_run_hit = False
if alns_budget_auto_scaling_enabled and alns_budget_profile is not None:
    _estimated_total_run_s = (
        float(alns_budget_profile["estimated_repair_s_per_destroyed_op"])
        * int(alns_budget_profile["effective_max_destroy"])
        * int(alns_budget_profile["effective_max_iterations"])
    )
    budget_guard_estimated_run_hit = (
        selected_inner_solver_name == "alns"
        and alns_presearch_budget_guard_enabled
        and _estimated_total_run_s > per_window_limit
    )
    should_skip_alns_presearch = budget_guard_estimated_run_hit
else:
    should_skip_alns_presearch = legacy_alns_presearch_guard_hit
```

Это ровно то, что рекомендовалось в `HYPERDEEP_ACADEMIC_AUDIT_2026_05_01.md` §3.4 R1.

### 1.2 Регрессионный тест

`@c:/plans/SynAPS/tests/test_alns_rhc_scaling.py:3006`:

```python
def test_rhc_presearch_budget_guard_prefers_scaled_budget_profile_over_legacy_size_cut(
    self,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A calibrated ALNS budget profile should override the legacy raw-count guard."""
```

Запуск, заявленный пользователем (3 passed, 90 deselected), закрывает контракт:
калиброванный профиль перекрывает raw-count guard.

### 1.3 Артефакты v7 и v8 и документация

- `@c:/plans/SynAPS/benchmark/studies/2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix/rhc_500k_study.json`
  (анкор «ALNS заблокирован guard, fallback-only»).
- `@c:/plans/SynAPS/benchmark/studies/2026-05-01-rhc-100k-audit-v8-post-predicate-fix/rhc_500k_study.json`
  (анкор «R1 снимает guard, но вскрывает initial-seed bottleneck»).
- Обновлены: `AUDIT_VERIFICATION_2026_05_01.md`, `NEXT_WAVE_EXECUTION_PLAN_2026_05_01.md`,
  `benchmark/README.md`, `benchmark/README_RU.md`.

Вывод по верификации: **всё, что должно было оказаться в `master`, там и есть**.

## 2. Root-cause v8: ALNS initial-seed path

### 2.1 Симптом из v8

`@c:/plans/SynAPS/benchmark/studies/2026-05-01-rhc-100k-audit-v8-post-predicate-fix/rhc_500k_study.json:232-287`
RHC-ALNS:

```json
"error": "no assignments produced",
"windows": 1,
"time_limit_reached": true,
"fallback_repair_attempted": false,
"fallback_repair_skipped": true,
"ops_unscheduled": 100000,
"assigned_ops": 0,
"solve_ms": 818286
```

И в summary: `mean_wall_time_s: 818.286`, `mean_scheduled_ratio: 0.0`.
RHC-GREEDY на том же прогоне: `7013/100000`, `90.376 с`.

818 с при заявленном лимите 90 с в кеп (harness `--time-limit-cap-s 90`) — это
в 9× выше. Значит, где-то есть вызов без уважения к `time_limit_s`.

### 2.2 Код-путь (G3)

Фаза 1 ALNS для первого окна RHC без warm-start и без frozen-assignments:

1. `@c:/plans/SynAPS/synaps/solvers/alns_solver.py:1220-1301` — warm-start path. На
   первом окне warm-start пуст → пропущен.
2. `@c:/plans/SynAPS/synaps/solvers/alns_solver.py:1303-1334` — frozen-compatible
   path. Ограничен `n_ops <= frozen_initial_repair_max_ops` (`default = 512`). На
   bounded 100K с окном ≈2078 операций — пропущен с причиной
   `frozen_greedy_seed_skipped_budget_or_size`.
3. `@c:/plans/SynAPS/synaps/solvers/alns_solver.py:1336-1376` — unbounded initial seed:

```python
if initial_result is None:
    if n_ops <= initial_beam_op_limit:      # default 60
        beam_result = BeamSearchDispatch(beam_width=3).solve(problem)
        greedy_result = GreedyDispatch().solve(problem)
        ...
    else:
        initial_solver_name = "greedy"
        initial_result = GreedyDispatch().solve(problem)

    if not _is_valid_complete_schedule(list(initial_result.assignments)):
        # Fall back to greedy if beam failed to cover the full instance.
        initial_solver_name = "greedy"
        initial_result = GreedyDispatch().solve(problem)     # <-- второй раз
        if not _is_valid_complete_schedule(list(initial_result.assignments)):
            return _initial_generation_error_result(...)
```

При `n_ops = 2078 > 60` идём в `else` и вызываем `GreedyDispatch().solve(problem)`
**без `time_limit_s`**. Если невалидно, вызываем ещё раз. Это и есть 2×≈400 с.

### 2.3 Почему `GreedyDispatch` так долог

`@c:/plans/SynAPS/synaps/solvers/greedy_dispatch.py:58-311`:

- Сигнатура: `def solve(self, problem, **kwargs)` — `time_limit_s` **не
  парсится**, в kwargs будет проигнорирован.
- Основной цикл `while remaining:` (line 76) не имеет проверки `t0`.
- На каждом шаге — перебор всех eligible work-centers × `find_earliest_feasible_slot`.
- Вычислительная стоимость ≈ O(n · m · k), где `n = 2078`, `m ≈ 200`,
  `k = средняя стоимость поиска слота (≈ log линии/ops)`. В чистом Python-пути с
  native-ускорением только скоринга — сотни секунд на одном окне.

### 2.4 Почему RHC не защитил себя

`@c:/plans/SynAPS/synaps/solvers/rhc_solver.py:1977-1993`:

```python
alns_budget_exhausted_before_search = bool(
    selected_inner_solver_name == "alns"
    and inner_result is not None
    and bool((inner_result.metadata or {}).get(
        "time_limit_exhausted_before_search"
    ))
    and int((inner_result.metadata or {}).get(
        "iterations_completed",
        0,
    ))
    == 0
)
```

Детектор срабатывает **после** возврата ALNS. К этому моменту 818 с уже потрачены.
`t0` RHC считает глобальный кеп → `time_limit_reached = True` → при проверке на
fallback greedy на `@c:/plans/SynAPS/synaps/solvers/rhc_solver.py:2368-2373`:
`fallback_repair_skipped = True` (глобальный лимит истёк).

Итого компаундная цепочка: ALNS тратит весь study budget внутри фазы 1 → RHC не
успевает откатиться на собственный greedy фоллбек → `0/100 000`.

### 2.5 Диагностические метаданные, подтверждающие картину

В v8 RHC-ALNS:

- `inner_window_summary.windows_observed = 0` — ни одно окно не дожило до
  commit-точки (ALNS вернул ошибку вместо assignments).
- `windows: 1` — одно окно было начато.
- `solve_ms = 818286` ≈ фаза 1 (seed) для этого одного окна.
- `solver_metadata.error = "no assignments produced"`.

Симптом воспроизведён и в v5 (445 с, одно окно, `no assignments produced`) — там
шла одна итерация `GreedyDispatch` на похожем окне. v7 скрыл дефект, скипнув
ALNS guard-ом. v8 (R1) снял guard → дефект снова проявился и стал виден в
однозначной форме.

## 3. Минимальный восходящий патч

Две связанных правки, обе должны выкатываться вместе, иначе регрессия
(возврат к unbounded greedy). Оценка объёма: ≤60 строк кода + 1 новый тест.

### 3.1 P1 — `GreedyDispatch` учитывает `time_limit_s`

Файл: `@c:/plans/SynAPS/synaps/solvers/greedy_dispatch.py`.

Внутри `GreedyDispatch.solve()` (строка 58):

1. Прочитать `time_limit_s` из kwargs:

```python
time_limit_s: float | None = kwargs.get("time_limit_s")
if time_limit_s is not None:
    time_limit_s = max(0.1, float(time_limit_s))
```

2. В основной цикл `while remaining:` (строка 76) добавить перед выборкой
   ready-ops:

```python
if time_limit_s is not None and (time.monotonic() - t0) > time_limit_s:
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return ScheduleResult(
        solver_name=self.name,
        status=SolverStatus.TIMEOUT,
        assignments=assignments,
        objective=ObjectiveValues(
            makespan_minutes=max(
                ((a.end_time - horizon_start).total_seconds() / 60.0
                 for a in assignments),
                default=0.0,
            ),
        ),
        duration_ms=elapsed_ms,
        metadata={
            "acceleration": acceleration_status,
            "partial_schedule": True,
            "scheduled_ops": len(assignments),
            "remaining_ops": len(remaining),
            "time_limit_s": time_limit_s,
        },
    )
```

Контракт:

- Если `time_limit_s` не задан, поведение идентично текущему.
- Если задан — `solve()` может вернуть `status = SolverStatus.TIMEOUT` с частичным
  расписанием и ключом `partial_schedule: True`.

Важно: не добавлять проверку в `BeamSearchDispatch` на этом этапе — у него собственный
путь, он не вызывается на окнах 2078+ ops (из-за `initial_beam_op_limit = 60`).

### 3.2 P2 — `alns_solver.py` вызывает greedy с бюджетом и обрабатывает TIMEOUT

Файл: `@c:/plans/SynAPS/synaps/solvers/alns_solver.py`.

Заменить блок `@c:/plans/SynAPS/synaps/solvers/alns_solver.py:1336-1376`:

```python
if initial_result is None:
    remaining_budget_s = max(1.0, time_limit_s - (time.monotonic() - t0))
    if n_ops <= initial_beam_op_limit:
        beam_result = BeamSearchDispatch(beam_width=3).solve(problem)
        greedy_result = GreedyDispatch().solve(
            problem,
            time_limit_s=remaining_budget_s,
        )

        beam_valid = _is_valid_complete_schedule(list(beam_result.assignments))
        greedy_valid = _is_valid_complete_schedule(list(greedy_result.assignments))

        if beam_valid and greedy_valid:
            beam_cost = _objective_cost(
                _evaluate_objective(problem, list(beam_result.assignments), sdst),
                objective_weights,
            )
            greedy_cost = _objective_cost(
                _evaluate_objective(problem, list(greedy_result.assignments), sdst),
                objective_weights,
            )
            if greedy_cost < beam_cost:
                initial_solver_name = "greedy"
                initial_result = greedy_result
            else:
                initial_solver_name = "beam"
                initial_result = beam_result
        elif beam_valid:
            initial_solver_name = "beam"
            initial_result = beam_result
        else:
            initial_solver_name = "greedy"
            initial_result = greedy_result
    else:
        initial_solver_name = "greedy"
        initial_result = GreedyDispatch().solve(
            problem,
            time_limit_s=remaining_budget_s,
        )

    # Any partial / timed-out initial seed must surface as an explicit error
    # so RHC falls back to its outer greedy path instead of burning the whole
    # window budget inside phase 1.
    if (
        initial_result.status == SolverStatus.TIMEOUT
        or bool((initial_result.metadata or {}).get("partial_schedule"))
    ):
        return _initial_generation_error_result(
            "initial_seed_greedy_timed_out"
        )

    if not _is_valid_complete_schedule(list(initial_result.assignments)):
        # Fall back to greedy if the preferred path failed coverage.
        remaining_budget_s = max(
            1.0,
            time_limit_s - (time.monotonic() - t0),
        )
        initial_solver_name = "greedy"
        initial_result = GreedyDispatch().solve(
            problem,
            time_limit_s=remaining_budget_s,
        )
        if (
            initial_result.status == SolverStatus.TIMEOUT
            or bool((initial_result.metadata or {}).get("partial_schedule"))
            or not _is_valid_complete_schedule(list(initial_result.assignments))
        ):
            return _initial_generation_error_result(
                "initial_seed_greedy_timed_out"
                if initial_result.status == SolverStatus.TIMEOUT
                or bool((initial_result.metadata or {}).get("partial_schedule"))
                else "initial solution generation failed"
            )
```

Ключевое:

- Каждый вызов `GreedyDispatch().solve(problem, ...)` получает оставшийся бюджет
  от `time_limit_s` с минимальной защитой `max(1.0, …)`.
- При `TIMEOUT` или `partial_schedule` возвращается
  `_initial_generation_error_result("initial_seed_greedy_timed_out")`.
- Существующий RHC-контракт уже ловит этот путь через
  `alns_budget_exhausted_before_search` в
  `@c:/plans/SynAPS/synaps/solvers/rhc_solver.py:1977-1993`, потому что
  `_initial_generation_error_result` ставит `time_limit_exhausted_before_search`
  (`@c:/plans/SynAPS/synaps/solvers/alns_solver.py:1046-1048`) и
  `iterations_completed = 0` (line 1049).

### 3.3 P3 — Диагностическая причина fallback

Добавить в `_initial_generation_error_result` (`@c:/plans/SynAPS/synaps/solvers/alns_solver.py:1032-1052`)
параметр `reason_key` (optional) и ключ в метаданных:

```python
def _initial_generation_error_result(
    error_message: str,
    *,
    reason_key: str | None = None,
) -> ScheduleResult:
    ...
    metadata={
        "error": error_message,
        "initial_seed_fallback_reason": reason_key or error_message,
        ...
    }
```

Это позволит в RHC отличать `initial_seed_greedy_timed_out` от
`initial solution generation failed`. Полезно для телеметрии в study summary.

## 4. Тесты

Три новых/расширенных теста, все детерминированные.

### 4.1 T1 — `GreedyDispatch` уважает `time_limit_s`

Файл: новый `@c:/plans/SynAPS/tests/test_greedy_dispatch_time_limit.py` или
расширение существующего `test_greedy_dispatch.py`.

```python
def test_greedy_dispatch_returns_timeout_when_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GreedyDispatch must honour time_limit_s and return TIMEOUT + partial."""
    problem = build_medium_problem(n_ops=300)

    # Force-slow find_earliest_feasible_slot to guarantee we exceed the budget.
    import synaps.solvers.greedy_dispatch as gd
    original = gd.find_earliest_feasible_slot

    def slow(*args, **kwargs):
        time.sleep(0.01)
        return original(*args, **kwargs)

    monkeypatch.setattr(gd, "find_earliest_feasible_slot", slow)

    result = gd.GreedyDispatch().solve(problem, time_limit_s=0.5)

    assert result.status == SolverStatus.TIMEOUT
    assert result.metadata["partial_schedule"] is True
    assert result.metadata["remaining_ops"] > 0
    assert len(result.assignments) < 300
    assert result.duration_ms >= 400
```

### 4.2 T2 — ALNS возвращает `initial_seed_greedy_timed_out` вместо зависания

Файл: расширить `@c:/plans/SynAPS/tests/test_alns_rhc_scaling.py`.

```python
def test_alns_reports_initial_seed_timeout_when_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ALNS must surface an initial-seed timeout as ERROR so RHC can fall back."""
    problem = build_medium_problem(n_ops=300)

    import synaps.solvers.alns_solver as alns_module

    class SlowGreedy:
        def solve(self, problem, **kwargs):
            time.sleep(1.5)
            return ScheduleResult(
                solver_name="greedy_dispatch",
                status=SolverStatus.TIMEOUT,
                assignments=[],
                duration_ms=1500,
                metadata={"partial_schedule": True, "remaining_ops": len(problem.operations)},
            )

    monkeypatch.setattr(alns_module, "GreedyDispatch", lambda: SlowGreedy())

    solver = alns_module.AlnsSolver()
    result = solver.solve(problem, time_limit_s=1.0, max_iterations=10)

    assert result.status == SolverStatus.ERROR
    assert result.metadata.get("error") in {
        "initial_seed_greedy_timed_out",
        "initial solution generation failed",
    }
    assert result.metadata.get("iterations_completed", 0) == 0
    assert result.metadata.get("time_limit_exhausted_before_search") is True
```

### 4.3 T3 — RHC корректно откатывается, когда ALNS возвращает timeout

Файл: расширить `@c:/plans/SynAPS/tests/test_alns_rhc_scaling.py`.

Сценарий:

1. Запустить `RhcSolver` на маленькой проблеме, в которой ALNS (замоканный)
   возвращает `status=ERROR` с `time_limit_exhausted_before_search=True` и
   `iterations_completed=0`.
2. Проверить, что RHC переключается на `fallback_greedy` и схема содержит
   `inner_resolution_counts.fallback_greedy >= 1`.
3. Проверить, что `windows_observed > 0` (RHC всё-таки закрыл окно).

Это защищает existing поведение от регрессии, когда будет добавляться новая
логика.

### 4.4 Обновление контрактных тестов

`@c:/plans/SynAPS/tests/test_benchmark_rhc_500k_study.py` менять не нужно: harness
контракт касается guard-параметров, а не initial-seed пути.

## 5. Прогон и критерии приёмки

### 5.1 Команда

```powershell
python -m benchmark.study_rhc_500k `
  --scales 100000 `
  --solvers RHC-ALNS RHC-GREEDY `
  --lane throughput `
  --time-limit-cap-s 90 `
  --max-windows-override 2 `
  --write-dir benchmark/studies/2026-05-08-rhc-100k-audit-v9-post-initial-seed-fix
```

На Windows командная строка PowerShell; для POSIX — тот же набор флагов через
`\`. Хеш head-коммита фиксируется в `study_meta.json` автоматически.

### 5.2 Предварительные прогоны

Перед полным 100K прогоном прогнать фокусные тесты:

```powershell
pytest tests/test_greedy_dispatch_time_limit.py -v
pytest tests/test_alns_rhc_scaling.py::TestRhcAlnsScalingProfile -v
pytest tests/test_benchmark_rhc_500k_study.py::test_scale_solver_kwargs_keeps_alns_presearch_guard_stable_for_100k_plus -v
```

Все три — зелёные, иначе не прогонять 100K.

### 5.3 Критерии приёмки v9

Сопоставление с v7 (guard-only) и v8 (R1, но без initial-seed fix):

| Метрика | v7 | v8 | Требуется v9 (RHC-ALNS) |
|---|---:|---:|---:|
| `mean_wall_time_s` | 90.281 | 818.286 | ≤ 95 |
| `mean_scheduled_ratio` | 0.069 | 0.0 | ≥ greedy v9 − 0.01 |
| `inner_window_summary.windows_observed` | 2 | 0 | ≥ 1 |
| `inner_resolution_counts.inner` | 0 | 0 | может быть 0; допустимо, если `fallback_greedy ≥ 1` |
| `inner_resolution_counts.fallback_greedy` | 2 | 0 | ≥ 1 |
| `inner_fallback_reason_counts["inner_time_limit_exhausted_before_search"]` | 2 | 0 | ≥ 1 (legal) или 0 (если поиск реально стартовал) |
| `fallback_repair_skipped` | false | true | false |
| `solver_metadata.error` | n/a | `"no assignments produced"` | отсутствует или `null` |

**Ключевое**: `mean_wall_time_s` должно вернуться под 95 с (или `time_limit_cap_s + overhead`).
`mean_scheduled_ratio` должен быть близок к RHC-GREEDY на том же прогоне
(± 1 процентный пункт). Если ALNS реально вошёл в поиск, он может обойти greedy;
если нет — как минимум должен не ухудшать результат.

### 5.4 Что будет ОК и что НЕ ОК

ОК:

- ALNS в обоих окнах вернул `initial_seed_greedy_timed_out` → RHC откатился в
  fallback_greedy → покрытие приблизилось к RHC-GREEDY.
- ALNS в одном окне вошёл в поиск (несколько итераций) → покрытие равно или выше
  greedy.

НЕ ОК:

- `mean_wall_time_s > 150` (восстановить unbounded greedy).
- `mean_scheduled_ratio = 0` и `fallback_repair_skipped = true` (компаундный
  сбой повторился).
- `iterations_completed = 0` во всех окнах и `inner_fallback_reason_counts`
  пустой (ALNS не детектирует timeout правильно).

## 6. Дальнейший план (после зелёного v9)

### 6.1 Приоритет 0 — закрытие wave A

- Коммит патча P1+P2+P3 одним атомарным MR: «fix(alns): bound initial seed
  construction by time_limit_s».
- Добавить v9 артефакт в репозиторий, обновить `benchmark/STUDIES_INDEX.md`,
  зафиксировать строки в `AUDIT_VERIFICATION_2026_05_01.md` и
  `NEXT_WAVE_EXECUTION_PLAN_2026_05_01.md`.
- Обновить README EN/RU 100K-секцию: «R2 (initial-seed budget) закрывает
  v8-регрессию; bounded 100K ALNS теперь паритетен greedy по покрытию».

### 6.2 Приоритет 1 — Wave B (LBBD strengthening)

По `HYPERDEEP_ACADEMIC_AUDIT_2026_05_01.md` Wave B, ровно в заявленном порядке:

1. R5 — `machine_tsp` cut family (Naderi & Roshanaei 2021; Bellman-Held-Karp для
   `|states| ≤ 12`, иначе — нижняя оценка через Christofides).
2. R4 — cut pool de-duplication по `(kind, frozenset(bottleneck_ops),
   round(rhs, 3))`.
3. R6 — `lb_evolution` + `cut_kind_lb_contribution` в `iteration_log` (arXiv
   2504.16106).
4. R16 — тест LP-tightening для `critical_path` (численная проверка ≥10 %).
5. R17 — тест ARC-aware LB, когда R8 будет в scope (может быть следующим
   приоритетом).
6. Валидация на `medium_20x10` и `medium_stress_20x4`, 50K rerun.

### 6.3 Риски перед переходом на LBBD

- Если R1 без P1/P2/P3 останется — любой новый LBBD-путь, который будет
  дёргать ALNS/greedy через portfolio, может снова попасть на unbounded greedy.
- Если P1 будет внедрён без P2 — ALNS снова проигнорирует timeout от greedy и
  продолжит фазу 2 на неполной сиде. Отказ только совместный.

### 6.4 Улучшения Wave C, дополнительные к P1-P3 (обязательно-предпочтительно)

- **R2 (M)** — EMA-калибровка `alns_budget_estimated_repair_s_per_destroyed_op`
  из реальных измерений в предыдущем окне. Убирает зависимость от
  `repair_time_limit_s / requested_max_destroy` эвристики.
- **Дополнительный R11' (M)** — поднять `frozen_initial_repair_max_ops` для
  профиля `RHC-ALNS-100K` с 512 до 3000. Это расширяет frozen-compatible путь
  на окна bounded-100K и сохраняет качество сида, если текущий
  `_repair_greedy_outcome` справится с 2000-3000 операций.

  Проверка перед включением: замерить `_repair_greedy_outcome` на 2078-op окне с
  `time_limit_s = 20`. Если стоит в бюджет — поднимать. Если нет — оставлять
  как есть.

## 7. Открытые исследовательские вопросы

1. **Нужен ли `GreedyDispatch` с warm-start?** Сейчас на каждом окне RHC ALNS
   делает `GreedyDispatch().solve(problem)` с нуля. При наличии
   `warm_start_assignments` можно инкрементально репарить, а не переплавлять
   всё окно. Это **R41 (M, H)** — отдельная research-задача, не блокер v9.
2. **Можно ли частичный partial-schedule использовать как seed ALNS?** Если
   `GreedyDispatch` успевает расписать 1500 из 2000 ops до timeout, сейчас мы
   просто возвращаем ошибку. Альтернатива — передать partial в ALNS как
   warm-start. Риск: partial может нарушать прецедентность. Нужен валидатор,
   прежде чем это делать.
3. **Существует ли гипотеза «parallel initial seed»?** Запускать `GreedyDispatch`
   и `BeamSearch` параллельно (через `ProcessPoolExecutor`) и брать первый
   успешный. На 2078 ops beam невозможно (out of scope из-за
   `initial_beam_op_limit = 60`), но на 500 ops оба могут успеть.

## 8. Ссылки внутрь проекта

- `@c:/plans/SynAPS/HYPERDEEP_ACADEMIC_AUDIT_2026_05_01.md` — академический
  аудит с R1-R41.
- `@c:/plans/SynAPS/AUDIT_VERIFICATION_2026_05_01.md` — актуальный статус
  верификации.
- `@c:/plans/SynAPS/NEXT_WAVE_EXECUTION_PLAN_2026_05_01.md` — план волн.
- `@c:/plans/SynAPS/benchmark/STUDIES_INDEX.md` — индекс артефактов.

## 9. Ссылки на внешние источники

- Ropke, S., Pisinger, D. (2006). An adaptive large neighborhood search
  heuristic for the pickup and delivery problem with time windows.
  *Transportation Science*, 40(4): 455-472. *(Контракт ALNS: initial seed
  всегда должен быть ограничен бюджетом и отделён от main loop.)*
- Shaw, P. (1998). Using constraint programming and local search methods to
  solve vehicle routing problems. *CP 1998*: 417-431. *(Shaw removal, текущая
  операторная база.)*
- Hooker, J. N. (2007). Planning and scheduling by logic-based Benders
  decomposition. *Operations Research*, 55(3): 588-602. *(Контекст Wave B.)*
- Naderi, B., Roshanaei, V. (2021). Critical-Path-Search Logic-Based Benders
  Decomposition Approaches for Flexible Job Shop Scheduling. *INFORMS JoO*,
  4(1): 1-28. *(Wave B: machine_tsp cut family.)*
- Jia, C., Liu, Y., Zhao, K. et al. (2025). L-RHO: Learning-augmented
  Rolling-Horizon Optimization for scheduling. *ICLR 2025.* *(Wave C:
  variable-fixing.)*
- arXiv 2504.16106 (Apr 2025). LB/UB trajectory reporting standard. *(Wave B:
  R6.)*

## Appendix A — Короткая картина поведения ALNS phase 1 по артефактам

| Артефакт | n_ops окна ≈ | Фаза 1 (мс) | Итераций | Scheduled | Причина |
|---|---:|---:|---:|---:|---|
| `v5` post-critical-fixes | 2078 | ≈445 000 | 0 | 0/100 000 | Один unbounded greedy. |
| `v7` post-guard-harness-fix | 2078 | n/a (skipped) | 0 | 6 933/100 000 (fallback) | Guard заблокировал ALNS. |
| `v8` post-predicate-fix | 2078 | ≈818 000 | 0 | 0/100 000 | Два unbounded greedy (retry). |
| v9 (ожидаемо после P1/P2) | 2078 | ≤ per_window_limit | может быть 0 | ≥ greedy − 0.01 | ALNS либо входит в поиск, либо чисто откатывается в RHC fallback. |

## Appendix B — Инвариант, который должен держаться после P1-P3

> «**ALNS phase 1 не может превысить `time_limit_s`. Если предел исчерпан, ALNS
> возвращает `status=ERROR` с `time_limit_exhausted_before_search=True` и
> `iterations_completed=0`, и RHC откатывается на свой внешний greedy-фоллбек
> в том же окне.**»

Этот инвариант должен быть отражён в комментарии шапки
`@c:/plans/SynAPS/synaps/solvers/alns_solver.py` перед классом `AlnsSolver` и
закреплён контрактным тестом T2 из § 4.2.

## Appendix C — Чек-лист перед мержем P1-P3

- [ ] `ruff check synaps/solvers/greedy_dispatch.py synaps/solvers/alns_solver.py`
- [ ] `mypy --strict synaps/solvers/greedy_dispatch.py synaps/solvers/alns_solver.py`
- [ ] `pytest tests/test_greedy_dispatch.py tests/test_greedy_dispatch_time_limit.py tests/test_alns_rhc_scaling.py -v`
- [ ] `pytest tests/test_benchmark_rhc_500k_study.py -v`
- [ ] `pytest -q` (full suite smoke)
- [ ] Bounded 100K v9 прогон, артефакт положен в `benchmark/studies/2026-05-08-rhc-100k-audit-v9-post-initial-seed-fix/`.
- [ ] Приёмка по § 5.3.
- [ ] `benchmark/STUDIES_INDEX.md` обновлён.
- [ ] `AUDIT_VERIFICATION_2026_05_01.md` обновлён секцией «ALNS initial-seed
      budget contract».
- [ ] `NEXT_WAVE_EXECUTION_PLAN_2026_05_01.md` — отметка «Wave A closed».
- [ ] README EN/RU 100K-секция — обновлена.
- [ ] Коммит с сообщением вида «fix(alns): bound initial seed construction by
      time_limit_s (closes v8 100k stall)».
