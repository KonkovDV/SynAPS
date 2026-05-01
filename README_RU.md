# SynAPS

Детерминированный движок производственного планирования для задач класса MO-FJSP-SDST-ARC.

Language: [EN](README.md) | **RU**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

SynAPS нужен там, где важно не просто получить расписание, а понять, почему оно именно такое, и воспроизвести результат.

- явный портфель решателей с именованными конфигурациями
- прозрачная маршрутизация с метаданными
- отдельная проверка допустимости
- воспроизводимые артефакты бенчмарков (включая отдельное исследование 50K)

## Зачем Это Нужно

В планировании главный вопрос обычно не "что получилось", а "почему система так решила".

Подход SynAPS - белый ящик:

- выбранная конфигурация решателя известна
- параметры запуска фиксируются (включая seed для стохастики)
- путь валидации независим от решателя
- артефакт запуска сохраняется рядом с кодом

## Текущее Состояние (апрель 2026)

Что подтверждено в этом репозитории:

- 23 публичные конфигурации решателей в реестре (`available_solver_configs()`)
- требование Python: `>=3.12` (`pyproject.toml`)
- базовые рабочие зависимости: `ortools`, `highspy`, `pydantic`, `numpy`
- стабильные JSON-контракты solve/repair (`synaps/contracts.py`)
- отдельный воспроизводимый 50K контур сравнения и поэтапный стенд исследования 500K (`benchmark/study_rhc_50k.py`, `benchmark/study_rhc_500k.py`)
- поэтапный стенд 500K теперь включает масштабируемый ALNS pre-search guard и опциональный ограниченный `max_windows_override` для запусков 100K+ в исследовательском режиме
- отдельный `FeasibilityChecker` (`synaps/solvers/feasibility_checker.py`)
- `ALNS` умеет принимать partial warm start, достраивать недостающие назначения и пересчитывать переналадки перед локальным поиском
- `ALNS` теперь отбрасывает infeasible full seed и reanchored warm start ещё до локального поиска, поэтому финальный recovery больше не может молча откатиться к неверной начальной базе
- `RHC` умеет переносить незавершённый overlap-tail в следующее `ALNS`-окно и пишет warm-start метаданные в результат
- после аудита усиление `RHC` добавляет full-frontier fallback для недозаполненных admission-окон (`admission_full_scan_*` в metadata)
- после аудита усиление `RHC` также добавляет auto-scaling ALNS repair budget по окну (`alns_effective_repair_time_limit_s` в telemetry)
- `RHC` теперь трактует `time_limit_exhausted_before_search && iterations_completed == 0` на ALNS-линии как явный повод уйти в fallback (`inner_time_limit_exhausted_before_search`), а не как успешное inner-решение без локального поиска
- candidate scoring в `RHC` подключён к NumPy/native batch seam, когда ускорение доступно
- TypeScript `control-plane` валидирует JSON-контракты, вызывает реальное Python-ядро для `solve/repair`, а CI поднимает Python runtime до запуска `control-plane` integration tests
- Закреплённые security-workflow в GitHub Actions покрывают Python, TypeScript и Rust через CodeQL и публикуют OSSF Scorecards SARIF-результаты

Что здесь не заявляется:

- промышленная валидация на живом заводе
- гарантированное построение полного feasible 50K расписания в текущих timebox

Перепроверка аудита в мае 2026:

- текущее состояние аудита зафиксировано в `AUDIT_VERIFICATION_2026_05_01.md`
- эта перепроверка подтвердила, что часть громких замечаний уже была закрыта на текущем `master`, а в этом проходе менялись только живые дефекты: эвристический ML advisory больше не переопределяет детерминированную маршрутизацию, публичная валидация стала exhaustive, а setup lower bound в `LBBD` / `LBBD-HD` теперь строится безопасно

## 50K Срез (industrial-50k)

Канонические артефакты:

- `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`
- Pre-fix live stress-артефакт: `benchmark/studies/test-50k-academic-matrix-v1/rhc_50k_study.json`
- Артефакт с защитными ограничителями для уже снятого с публикации профиля: `benchmark/studies/2026-04-26-rhc-alns-postfix-canonical-v4/rhc_50k_study.json`
- Аудит current-head до обновления профиля: `benchmark/studies/2026-04-27-rhc-50k-audit-v1/rhc_50k_study.json`
- Аудит current-head после обновления профиля: `benchmark/studies/2026-04-27-rhc-50k-audit-v2-current-head/rhc_50k_study.json`

Сводка по обновлённому public/default аудиту current-head:

| Solver | Время (с) | Feasibility rate | Mean scheduled ratio | Mean makespan (min) | Mean inner fallback ratio |
|---|---:|---:|---:|---:|---:|
| `RHC-GREEDY` | 600.878 | 0.0 | 0.3563 | 11514.33 | 0.0 |
| `RHC-ALNS` | 1207.869 | 0.0 | 0.0845 | 3059.82 | 0.6667 |

Как это правильно читать:

- Это по-прежнему срез профилирования и подтверждений, а не "50K уже решено".
- Pre-fix stress-matrix остаётся честной evidence-поверхностью для старого профиля деградации, где покрытие было слабым, но часть окон всё же входила в search.
- Артефакт 2026-04-26 с защитными ограничителями зафиксировал второй режим, где oversized ALNS-окна short-circuit'ятся до дорогой seed generation.
- Аудит `v1` от 2026-04-27 зафиксировал третий режим и опроверг слишком сильное старое чтение «ALNS вообще не входит в search»: ранние окна действительно входят в ALNS, но окна 2-3 тратят 100 repair attempts на нулевую по полезности CP-SAT micro-repair, а поздние окна уходят в fallback или timeout из-за hybrid CP-SAT routing.
- Аудит `v2` от 2026-04-27 теперь является текущим public/default якорем. Он подтверждает, что hybrid CP-SAT routing и CP-SAT micro-repair убраны из публичного пути, но также показывает, что bottleneck сместился, а не исчез: окна 1-2 входят в ALNS с greedy-only repair, а поздние окна уходят в fallback после `inner_time_limit_exhausted_before_search` уже на стадии seed construction.
- Артефакты `v1` и 2026-04-26 теперь нужно читать как evidence отказа старого CP-SAT-heavy профиля, а не как performance-утверждение для обновлённого default. Честный current-head public/default срез теперь задаёт именно `v2`.
- Для partial RHC результатов (`status=error`, когда `ops_scheduled < ops_total`) интерпретируйте границы только через `lower_bound_upper_bound_comparable`: текущий код выставляет `gap = null`, если расписан лишь committed-subset, и в этом режиме raw `lower_bound` / `upper_bound` математически несопоставимы.

Ключевые сравнения:

- Pre-fix `RHC-ALNS|throughput` в `test-50k-academic-matrix-v1` давал `mean_scheduled_ratio = 0.0946`, `mean_makespan_minutes = 4985.85` и `mean_inner_fallback_ratio = 0.1`.
- Guarded-profile `RHC-ALNS|throughput` в `2026-04-26-rhc-alns-postfix-canonical-v4` даёт `mean_scheduled_ratio = 0.3028`, `mean_makespan_minutes = 9675.18` и `mean_inner_fallback_ratio = 1.0`.
- Current-head до обновления профиля: `RHC-ALNS|throughput` в `2026-04-27-rhc-50k-audit-v1` даёт `mean_scheduled_ratio = 0.1243`, `mean_makespan_minutes = 4134.84` и `mean_inner_fallback_ratio = 0.625`.
- Current-head после обновления профиля: `RHC-ALNS|throughput` в `2026-04-27-rhc-50k-audit-v2-current-head` даёт `mean_scheduled_ratio = 0.0845`, `mean_makespan_minutes = 3059.82` и `mean_inner_fallback_ratio = 0.6667`.
- Current-head после обновления профиля: `RHC-GREEDY|throughput` в `2026-04-27-rhc-50k-audit-v2-current-head` остаётся более сильным базовым режимом максимального покрытия с `mean_scheduled_ratio = 0.3563` и `mean_inner_fallback_ratio = 0.0`.
- Нерешённая исследовательская задача теперь распадается на две части: обновлённый публичный 50K path больше не теряет бюджет на CP-SAT side-paths, но всё ещё проигрывает поздние окна из-за seed-construction exhaustion; `100k+` уже вернулся к стабильному bounded fallback parity, но всё ещё не даёт продуктивного active-search yield.

## 100K+ Срез (поэтапный стенд)

Текущий `100K+` статус нужно читать как поэтапную исследовательскую поверхность, а не как заявление о готовности к промышленной эксплуатации.

Что теперь реализовано и проверено:

- `benchmark.study_rhc_500k` поддерживает лестницу масштабов (`50k -> 100k -> 200k -> 300k -> 500k`)
- активны resource projection и gated execution
- bounded staged `100k` прогоны теперь сохраняют проверенный envelope `alns_presearch_max_window_ops=1000` / `alns_presearch_min_time_limit_s=240.0` при именованной геометрии `RHC-ALNS-100K`
- для воспроизводимых bounded 100K+ прогонов добавлен параметр `--max-windows-override`

Что установил последний аудит:

- `200k` ещё находится внутри текущего public model limit по операциям
- `300k` и `500k` сейчас блокируются по `operations_exceed_model_limit`, а не по прогнозируемой RAM
- Ограниченный аудит `100k` от 2026-04-27 на уже снятом с публикации CP-SAT-heavy профиле показал: `RHC-GREEDY` успевает за `90.226s` расписать `8144/100000` операций, тогда как `RHC-ALNS` расписывает `0/100000` и тратит `400518 ms` на initial solution generation ещё до первой ALNS-итерации.
- Именно этот 100K результат объясняет, почему публичные defaults для `RHC-ALNS` теперь отключают hybrid CP-SAT routing и CP-SAT micro-repair, но он же показывает, что более глубокое узкое место initial-seed выше этого профиля пока не устранено.
- Второй ограниченный 100K-срез от 2026-04-27 на staged geometry-refresh harness (`300/90` вместо снятой с публикации first-window geometry `480/120` для `100k+`) уже дошёл до `ALNS starting`, выполнил `55` итераций с `43` улучшениями и `0` inner fallback и завершился с `4678/100000` назначенными операциями за `90.118s`.
- Это geometry-refresh evidence теперь поднято в публичный портфель как именованный runtime-profile `RHC-ALNS-100K`, так что геометрия search-entry `300/90` больше не живёт только внутри staged harness.
- Свежий same-run current-head comparison в `benchmark/studies/2026-04-27-rhc-100k-audit-v4-current-head/rhc_500k_study.json` сохраняет этот факт входа в search, но уже против честного базового сравнения: `RHC-GREEDY` расписывает `7852/100000` операций за `90.213s`, а `RHC-ALNS` расписывает `3420/100000` за `90.113s`, входя в search в обоих bounded окнах (`56` и `30` итераций, `45` и `18` улучшений, `0` CP-SAT repairs, `0` inner fallback).
- Вместе артефакты `v3` и `v4` опровергают старое чтение вида «на 100K ALNS вообще не доходит до search»: контролирующим узким местом были geometry первого окна и давление initial seed generation, а не только более поздний CP-SAT repair flag.
- Артефакт `v7` с восстановленным guard envelope (`benchmark/studies/2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix/rhc_500k_study.json`) закрыл catastrophic `0/100000` collapse за счёт безопасного greedy fallback, но оставил bounded rail в fallback-only режиме.
- Артефакт `v8` после predicate-fix (`benchmark/studies/2026-05-01-rhc-100k-audit-v8-post-predicate-fix/rhc_500k_study.json`) доказал, что `R1` действительно возвращает вход в ALNS на bounded окне из `1501` операций, но одновременно вскрыл следующий bottleneck: initial solution generation тратит около `808843 ms`, выполняет `0` search-итераций и снова уводит run к `0/100000` назначенным операциям.
- Свежий bounded rerun `v11` в `benchmark/studies/2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap/rhc_500k_study.json` закрывает и это, уже более глубокое initial-seed stall семейство на текущем `master`: `RHC-ALNS` даёт `7236/100000` операций за `90.255s`, тогда как same-run `RHC-GREEDY` даёт `7230/100000` за `90.365s`, при `windows_observed = 2`, `fallback_repair_skipped = false` и отсутствии `solver_metadata.error`.
- Этот `v11` артефакт всё ещё не означает production-readiness и не доказывает продуктивный ALNS-search на `100k`: `search_active_window_rate` остаётся `0.0`, а `inner_fallback_ratio` остаётся `1.0`. Но он закрывает bounded-stability acceptance gate, который раньше блокировал следующую algorithm wave.
- Значит, следующий жёсткий engineering boundary теперь раздваивается: `300k` и `500k` по-прежнему режутся model/schema capacity, а `100k` и `200k` теперь требуют роста active-search yield и упрощения seed/admission policies, а не просто containment catastrophic stall family.

## Портфель Решателей

Основные семейства:

- точные и почти точные: CP-SAT, LBBD, LBBD-HD
- конструктивные: Greedy ATCS, Beam
- многокритериальные срезы: epsilon/Pareto профили CP-SAT
- крупномасштабные контуры: ALNS, RHC с переносом overlap-tail и опциональным пакетным нативным скорингом
- ремонт: IncrementalRepair
- валидация: FeasibilityChecker

Авторитетный реестр:

- `synaps/solvers/registry.py`

Политика выбора решателя:

- `synaps/solvers/router.py`

## Нюанс По Детерминизму

Часть портфеля стохастическая по определению и поддерживает seed.

Для CP-SAT (OR-Tools):

- `num_workers > 1` может ухудшать бит-в-бит повторяемость между запусками и машинами
- если нужна более строгая воспроизводимость, фиксируйте `random_seed` и ставьте однопоточный режим (`num_workers = 1`)
- strict benchmark lane дополнительно отключает вариативные CP-SAT флаги (`randomize_search`, `permute_variable_randomly`, `permute_presolve_constraint_order`, `use_absl_random`) и пишет эффективный снимок SatParameters в metadata решателя для replay/audit

## Быстрый Старт

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
python -m pip install -e ".[dev]"
```

Решить маленький пример:

```bash
python -m synaps solve benchmark/instances/tiny_3x3.json
```

Сравнить решатели на benchmark-инстансе:

```bash
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare
```

Запустить отдельный 50K study:

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/_local-rhc-50k
```

Запустить именованный max-push 50K profile (агрессивный ALNS budget + дефолтный набор с `RHC-ALNS-REFINE`):

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --study-profile max-push-50k \
  --write-dir benchmark/studies/_local-rhc-50k-max
```

Запустить bounded 100K ALNS audit slice:

```bash
python -m benchmark.study_rhc_500k \
  --execution-mode gated \
  --scales 100000 \
  --solvers RHC-ALNS \
  --lane throughput \
  --seeds 1 \
  --time-limit-cap-s 90 \
  --max-windows-override 2 \
  --write-dir benchmark/studies/_local-rhc-100k
```

Запустить тесты:

```bash
python -m pytest tests -q
```

Запустить строгую type-check проверку, которая используется в CI:

```bash
python -m mypy synaps --strict --no-error-summary
```

Запустить boundary-тесты TypeScript control-plane:

```bash
cd control-plane
npm install
npm test
```

Пакет `control-plane` вызывает `python -m synaps`, поэтому сначала нужно установить
Python-пакет репозитория в активный интерпретатор (`python -m pip install -e ".[dev]"`).

## Нативное Ускорение

SynAPS включает опциональное Rust-ядро ускорения (`synaps_native` v0.3.0) для горячих путей вычислений через PyO3.

**Профилированное целевое железо**: Intel 12–14 поколение (Raptor Lake) с гибридной архитектурой P/E-ядер и поддержкой AVX2+FMA3. AVX-512 **не используется** в этом профиле, потому что он аппаратно отключён на гибридных процессорах.

Реализованные оптимизации (v0.3.0):

| Оптимизация | Механизм | Ожидаемый эффект |
|---|---|---|
| **Branchless-скоринг** | `cmov`/blend вместо ветвления для overdue-буста | 5–15% (устраняет ~50% промахов предсказателя) |
| **Гибридный параллелизм** | Rayon `with_min_len(256)` для work-stealing P/E-ядер | 10–25% (устраняет эффект «отстающих» E-ядер) |
| **Zero-copy NumPy + CSR** | Прямая запись в буферы, без промежуточных аллокаций | 2–3× по сравнению с Vec-путём |
| **target-cpu=native** | LLVM AVX2/FMA3 авто-векторизация | 10–40% (зависит от структуры цикла) |
| **fast_exp (Шраудольф)** | IEEE-754 bit trick с residual correction, clamp и endian-защитой | Бесплатно vs `libm::exp()` без схлопывания близких pressure-значений |

Ядро опционально — SynAPS автоматически переключается на чистый Python при его отсутствии.

Эти заметки про оптимизацию описывают именно профилированную Raptor Lake машину, а не универсальный ISA-предел для всех будущих развёртываний SynAPS. На non-hybrid серверах с AVX-512 в принципе возможна отдельная ветка runtime-dispatch или split wheel, но текущий репозиторий поставляет и бенчмаркует только путь AVX2/FMA3.

Недавнее native hardening также закрывает корректное поведение на extreme slack и добавляет regression-тест на очень близкие positive slack значения, чтобы установленный native path сохранял строгий порядок candidate pressure там, где старая bucketed-аппроксимация могла схлопывать соседние значения.

Сборка нативного расширения:

```bash
cd native/synaps_native
maturin develop --release
```

Проверить, что runtime действительно видит native backend, и затем измерить speedup на больших candidate-масштабах:

```bash
python -c "from synaps import accelerators; print(accelerators.get_acceleration_status())"
python -m benchmark.study_native_rhc_candidate_acceleration \
  --sizes 50000,100000,500000 \
  --repeats 5 \
  --output benchmark/results/native-rhc-candidate-acceleration.json
```

Для geometry-driven 50K admission/search исследований запускайте bounded DOE rail напрямую:

```bash
python -m benchmark.study_rhc_alns_geometry_doe \
  --lane throughput \
  --seeds 1 \
  --max-windows 2 \
  --time-limit-s 300 \
  --geometries 480:120 360:90 300:90 240:60 \
  --write-dir benchmark/studies/_local-geo-doe
```

См.: [HPC-дорожная карта оптимизаций уровня кремния](docs/architecture/08_HPC_SILICON_OPTIMIZATION_ROADMAP.md)

## Карта Репозитория

- `synaps/solvers/` - реализации решателей и реестр
- `synaps/model.py` - базовая Pydantic-модель
- `synaps/contracts.py` - стабильные JSON-контракты
- `synaps/problem_profile.py` - профилирование инстансов
- `synaps/validation.py` - проверка результатов solve
- `benchmark/` - harness и исследования
- `control-plane/` - минимальный TypeScript BFF поверх зафиксированных solve/repair-контрактов
- `tests/` - тестовый контур
- `docs/` - архитектура, аудиты, публикационные материалы

## Что Читать Дальше

- Хабр-драфт (RU): `docs/habr/synaps-open-source-habr-v7.md`
- Publication pack: `docs/habr/synaps-open-source-habr-v7-pack.md`
- Benchmark guide: `benchmark/README_RU.md`
- Post-audit implementation note: `docs/audit/SYNAPS_UPDATE_AUDIT_2026_04_25.md`
- HPC-дорожная карта: `docs/architecture/08_HPC_SILICON_OPTIMIZATION_ROADMAP.md`
- Протокол воспроизводимости и робастности: `docs/architecture/06_BENCHMARK_REPRODUCIBILITY_AND_ROBUSTNESS.md`
- Contributing: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`

## Академический Стандарт Отчётности

### Граница Утверждений

Этот README разделяет подтверждённые факты репозитория и плановые намерения.

- Подтверждённые утверждения привязаны к исполнимым артефактам, зафиксированным контрактам, выгрузкам бенчмарков или CI-проверкам.
- Плановые элементы всегда помечаются как roadmap и не формулируются как уже поставленная функциональность.
- Числа производительности контекстны: они валидны для указанного артефакта и профилированного железа, а не как универсальная гарантия.

### Базовый Протокол Воспроизводимости

Минимальный набор для проверки и воспроизведения:

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q
python -m mypy synaps --strict --no-error-summary
python -m synaps list-solver-configs
```

Для утверждений по бенчмаркам публикуйте точную команду запуска, список seed, профиль решателя и путь к итоговому JSON-артефакту в `benchmark/studies/`.

### Цитирование И Научное Переиспользование

- Предпочтительный источник метаданных для цитирования: `CITATION.cff`.
- При ссылке на benchmark-результаты указывайте URL репозитория, commit SHA, путь к артефакту и дату исполнения.
- При сравнении с внешними методами обязательно фиксируйте обе границы: feasibility и wall-time.

## Управление проектом

- `SUPPORT.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `MAINTAINERS.md`
- `RELEASE_POLICY.md`
- `CITATION.cff`

## Лицензия

MIT. См. [LICENSE](LICENSE).


