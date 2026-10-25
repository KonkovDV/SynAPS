# План для ИИ-исполнителя (после аудита 2026-10)

Входные документы: `docs/rfc/AUDIT_2026_10.md` (находки A/R/Q/P, триаж,
SOTA), `CHANGELOG.md` → `[Unreleased]`, `KNOWN_ISSUES.md`, `AGENTS.md`.

## 0. Жёсткие правила (нарушение = задача не принята)

1. Только ветка `main`; без дополнительных веток и PR (`AGENTS.md`).
2. Никогда `C:\plans`; GridPlan / MobiRoute / AeroBIM не кладутся в
   `synaps/domains/`; не заявлять N-1 / SAIDI / INFIMUM / live EL5 / MAST;
   не открывать C5a и не класть веса в COVER.
3. `FEASIBLE ⇒ proven_hard_violations = ∅`. Нотариус (`FeasibilityChecker`)
   не доверяет штампам солвера (A-02 / A-03): любые новые проверки выводят
   данные из задачи, а не из ответа солвера.
4. Hashed-evidence (`benchmark/evidence/**`, `run_*.json`, `SHA256SUMS*`) не
   переписывать. Новые числа — только новой сессией с путём к evidence в той
   же или соседней строке (`scripts/verify_claims.py`).
5. Ratchet'ы в `tests/test_architecture.py` только уменьшаются.
6. Любая новая публичная нижняя оценка — с тестом валидности против полного
   перебора (CONTRIBUTING, правило 6). BHK никогда не «дисконтировать» (KI-S3).
7. Рефакторинг «без изменения поведения» подтверждается golden-снимками на
   простаивающей машине (см. §2).

## 1. Ворота качества (Definition of Done для каждой задачи)

```bash
ruff check synaps tests benchmark
ruff format --check synaps tests benchmark
python -m mypy synaps --strict
python scripts/verify_claims.py
pytest -q -m "not slow"                       # плюс slow-набор, если трогали солверы
make native-check                              # если трогали native/
python scripts/golden_snapshot.py capture after.json --suite full   # для рефакторинга
python scripts/golden_snapshot.py compare before.json after.json
```

Таймбокс-тесты (`test_timebox_enforcement.py`, `test_guard_d3_*`)
чувствительны к нагрузке (R-07): перезапускать на свободной машине, прежде
чем считать красный результат регрессией.

## 2. Процедура golden-контроля

1. На базовом коммите: `capture before.json --suite full` (≈ 10 мин).
2. Рефакторинг.
3. `capture after.json --suite full`, `compare before.json after.json`.
4. Любое `DIFF`: либо это намеренное изменение поведения (тогда отдельный
   коммит с тестом и записью в CHANGELOG), либо ошибка рефакторинга. Для
   атрибуции — откатить одно исправление (monkeypatch) и сравнить снова; для
   нативного пути сравнить с `SYNAPS_DISABLE_NATIVE_ACCELERATION=1`.
5. Если golden не проходит через изменённую ветку (пример R-06: кейс LBBD-HD
   шёл только через неудачные подзадачи), сначала добавить кейс в
   `scripts/golden_snapshot.py`, снять `before` заново.

## 3. Бэклог

### P0 — сразу после применения поставки

| ID | Задача | Критерий приёмки |
| --- | --- | --- |
| T-01 | Применить патч / дерево из архива на `main`, прогнать §1 на Linux и Windows | все ворота зелёные; job `native-accelerator` зелёный с новыми шагами `cargo fmt --check`, `cargo clippy -D warnings`, `cargo test`, parity-тесты |
| T-02 | Проверить влияние A-01 на опубликованные числа | `benchmark-smoke` зелёный; если какие-то сессионные числа сдвинулись, новая сессия evidence + строка в CHANGELOG; hashed-файлы не трогать |
| T-03 | Убедиться, что новый clippy в CI (stable новее 1.97) не добавил предупреждений | при новых lint'ах — исправить код, не ослаблять `-D warnings` |
| T-03a (R-10/R-11) | Прогнать `release.yml` через `workflow_dispatch` без публикации | колёса собраны на всех трёх ОС; на Linux `objdump -d` по `.so` не содержит `zmm`/`ymm` (база `x86-64-v2`); колесо импортируется на машине без AVX2 (или в `qemu-x86_64 -cpu Nehalem`) |

### P1 — надёжность и архитектура

| ID | Задача | Шаги | Критерий приёмки |
| --- | --- | --- | --- |
| T-04 (R-03) | Убрать `fork()` из многопоточного процесса в LBBD / LBBD-HD | создавать один `ProcessPoolExecutor(mp_context=get_context("forkserver"))` на весь `solve()` (а не на итерацию); на Windows — `spawn` как сейчас | нет `DeprecationWarning: ... fork()`; LBBD-тесты и golden идентичны; замер wall до/после в evidence |
| T-05 | Продолжить декомпозицию длинных функций под golden | порядок: `_solve_precedence_aware_master` (269), `_try_native_greedy_repair` (258), `_add_machine_order_and_adjacency` (240), `incremental_repair._solve_core` (239), `route_solver_config` (221), `_try_native_initial_seed` (221), `_destroy_critical_path` (203), `validate_cross_references` (202) | golden `full` идентичен; ratchet уменьшен; каждая новая функция ≤ 80 строк |
| T-06 | Звуковые отсечения LBBD (critical-path / аналитические) вместо одних no-good | формализовать отсечение, доказать валидность на бумаге, добавить Hypothesis-тест против полного перебора на малых инстансах; включать флагом | тест валидности; `lower_bound ≤ BKS` на Brandimarte (`test_public_instances_bks.py`); уменьшение среднего gap на `gen_120` / Brandimarte при том же бюджете, с evidence |
| T-07 | Control-plane: прогнать `npm ci && npm test` в CI-окружении | в этом аудите — только статика | зелёный job `control-plane`; отчёт о найденном |

### P2 — качество решений (только с измерениями)

| ID | Задача | Критерий приёмки |
| --- | --- | --- |
| T-08 | ALNS: discounted / sliding-window Thompson Sampling с наградой «улучшение в секунду» (после A-09 время ремонта корректно) | A/B по ≥ 3 сидам на `gen_120`, `gen_600`, Brandimarte; UCB1 остаётся умолчанием, пока нет evidence улучшения |
| T-09 (Q-01) | Эксперимент: `p̄` в ATCS по физическим длительностям | бенчмарк до/после; если лучше — отдельный коммит, golden-хэши greedy обновлены осознанно, запись в CHANGELOG |
| T-10 | Расширить замер `strict-parallel` (8–16 воркеров, ≥ 600 операций) | новый evidence-файл; доки ADR-0001 обновлены по фактам |
| T-11 | Публичный пакет LOS (DFKI 2024, FJSP с переналадками и транспортом) | загрузчик + проверка форм + BKS-тесты по образцу Brandimarte; лицензия совместима (GPL-наборы запрещены, см. KI-F16) |

### P3 — исследовательский трек (офлайн, за флагами)

| ID | Задача | Критерий приёмки |
| --- | --- | --- |
| T-12 | Обучаемая фиксация переменных в RHC в духе L-RHO | обучение на собственных трассах; в рантайме — только инференс за флагом; нотариус и golden без изменений при выключенном флаге |
| T-13 | Офлайн-эволюция операторов destroy/repair LLM-методами (G-LNS / LLM4EO) | фитнес = нотариус + golden + бенчмарк; сгенерированный код проходит ruff / mypy / ratchet; никакой генерации в рантайме |
| T-14 | Адаптер OptalCP / CP Optimizer как «второе мнение» по нижним оценкам | опциональная зависимость; оценка никогда не подменяет нотариус |

## 4. Шаблон задания для ИИ

```text
Репозиторий SynAPS, ветка main. Прочитай AGENTS.md, CONTRIBUTING.md,
docs/rfc/AUDIT_2026_10.md. Задача: <ID и текст из бэклога>.
Ограничения: правила §0 плана. До изменений сними golden before
(scripts/golden_snapshot.py capture before.json --suite full), если задача —
рефакторинг. После изменений прогони ворота §1. В отчёте: список файлов,
результаты ворот (вывод команд), golden compare, записи в CHANGELOG и
KNOWN_ISSUES, что осталось открытым. Не утверждай того, что не проверено
командой.
```
