# SynAPS

Детерминированный движок производственного планирования для задач класса MO-FJSP-SDST-ARC.

Language: [EN](README.md) | **RU**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

SynAPS нужен там, где важно не просто получить расписание, а понять, почему оно именно такое, и воспроизвести результат.

- явный портфель решателей с именованными конфигурациями
- прозрачная маршрутизация с метаданными
- отдельная проверка допустимости
- воспроизводимые benchmark-артефакты (включая отдельный 50K study)

## Зачем Это Нужно

В планировании главный вопрос обычно не "что получилось", а "почему система так решила".

Подход SynAPS - белый ящик:

- выбранная конфигурация решателя известна
- параметры запуска фиксируются (включая seed для стохастики)
- путь валидации независим от решателя
- артефакт запуска сохраняется рядом с кодом

## Текущее Состояние (апрель 2026)

Что подтверждено в этом репозитории:

- 22 публичные solver-конфигурации в реестре (`available_solver_configs()`)
- требование Python: `>=3.12` (`pyproject.toml`)
- базовые runtime-зависимости: `ortools`, `highspy`, `pydantic`, `numpy`
- стабильные JSON-контракты solve/repair (`synaps/contracts.py`)
- отдельный воспроизводимый 50K compare rail и staged 500K study harness (`benchmark/study_rhc_50k.py`, `benchmark/study_rhc_500k.py`)
- staged 500K harness теперь включает scale-aware ALNS pre-search guard scaling и опциональный bounded `max_windows_override` для 100K+ academic runs
- отдельный `FeasibilityChecker` (`synaps/solvers/feasibility_checker.py`)
- `ALNS` умеет принимать partial warm start, достраивать недостающие назначения и пересчитывать переналадки перед локальным поиском
- `ALNS` теперь отбрасывает infeasible full seed и reanchored warm start ещё до локального поиска, поэтому финальный recovery больше не может молча откатиться к неверной начальной базе
- `RHC` умеет переносить незавершённый overlap-tail в следующее `ALNS`-окно и пишет warm-start метаданные в результат
- post-audit усиление `RHC` добавляет full-frontier fallback для недозаполненных admission-окон (`admission_full_scan_*` в metadata)
- post-audit усиление `RHC` также добавляет auto-scaling ALNS repair budget по окну (`alns_effective_repair_time_limit_s` в telemetry)
- `RHC` теперь трактует `time_limit_exhausted_before_search && iterations_completed == 0` на ALNS-линии как явный повод уйти в fallback (`inner_time_limit_exhausted_before_search`), а не как успешное inner-решение без локального поиска
- candidate scoring в `RHC` подключён к NumPy/native batch seam, когда ускорение доступно
- TypeScript `control-plane` валидирует JSON-контракты, вызывает реальное Python-ядро для `solve/repair`, а CI поднимает Python runtime до запуска `control-plane` integration tests
- Pin-нутые GitHub Actions security workflows покрывают Python, TypeScript и Rust через CodeQL и публикуют OSSF Scorecards SARIF-результаты

Что здесь не заявляется:

- промышленная валидация на живом заводе
- гарантированное построение полного feasible 50K расписания в текущих timebox

## 50K Срез (industrial-50k)

Канонические артефакты:

- `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`
- Pre-fix live stress-артефакт: `benchmark/studies/test-50k-academic-matrix-v1/rhc_50k_study.json`
- Последний post-fix guarded-артефакт: `benchmark/studies/2026-04-26-rhc-alns-postfix-canonical-v4/rhc_50k_study.json`

Сводка по последнему post-fix guarded-артефакту:

| Solver | Время (с) | Feasibility rate | Mean scheduled ratio | Mean makespan (min) | Mean inner fallback ratio |
|---|---:|---:|---:|---:|---:|
| `RHC-ALNS` | 1201.146 | 0.0 | 0.3028 | 9675.18 | 1.0 |

Как это правильно читать:

- Это по-прежнему profiling/evidence-срез, а не "50K уже решено".
- Pre-fix stress-matrix остаётся честной evidence surface для случая, где ALNS давал лучший partial objective при слабом покрытии.
- Последний post-fix артефакт показывает уже другой режим: oversized ALNS-окна теперь явно short-circuit'ятся до дорогой phase-1 seed generation, чтобы не сжигать весь бюджет окна.
- На `industrial-50k` это заметно улучшает throughput относительно неудачных post-fix rerun'ов (`mean_scheduled_ratio` восстановился до `0.3028`), но ценой того, что ALNS вообще не входит в destroy-repair search на этих окнах.
- Поэтому текущую throughput-линию `RHC-ALNS` нужно читать как guarded fallback controller, а не как доказательство эффективности large-window ALNS search на 50K.

Ключевые сравнения:

- Pre-fix `RHC-ALNS|throughput` в `test-50k-academic-matrix-v1` давал `mean_scheduled_ratio = 0.0946`, `mean_makespan_minutes = 4985.85` и `mean_inner_fallback_ratio = 0.1`.
- Post-fix guarded `RHC-ALNS|throughput` в `2026-04-26-rhc-alns-postfix-canonical-v4` даёт `mean_scheduled_ratio = 0.3028`, `mean_makespan_minutes = 9675.18` и `mean_inner_fallback_ratio = 1.0`.
- Post-fix `RHC-GREEDY|throughput` из `test-50k-after-fix` остаётся более сильным pure-coverage baseline с `mean_scheduled_ratio = 0.37` и `mean_inner_fallback_ratio = 0.0`.
- Нерешённая исследовательская задача теперь уже уже локализована: нужна такая window geometry и routing policy, при которой ALNS реально успевает войти в search, а не сгорает на phase-1 seed generation или принудительно уходит в fallback.

## 100K+ Срез (staged harness)

Текущий `100K+` статус нужно читать как staged research surface, а не как claim о production-ready поведении.

Что теперь реализовано и проверено:

- `benchmark.study_rhc_500k` поддерживает scale ladder (`50k -> 100k -> 200k -> 300k -> 500k`)
- активны resource projection и gated execution
- ALNS pre-search guard в harness теперь масштабируется вместе с размером задачи, а не остаётся зафиксированным на 50K порогах
- для воспроизводимых bounded 100K+ прогонов добавлен параметр `--max-windows-override`

Что установил последний аудит:

- `200k` ещё находится внутри текущего public model limit по операциям
- `300k` и `500k` сейчас блокируются по `operations_exceed_model_limit`, а не по прогнозируемой RAM
- значит, следующий жёсткий engineering boundary — это model/schema capacity, а не память рабочей станции

## Портфель Решателей

Основные семейства:

- точные и почти точные: CP-SAT, LBBD, LBBD-HD
- конструктивные: Greedy ATCS, Beam
- многокритериальные срезы: epsilon/Pareto профили CP-SAT
- крупномасштабные контуры: ALNS, RHC с переносом overlap-tail и опциональным native batch scoring
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

- Хабр-драфт (RU): `docs/habr/synaps-open-source-habr-v3.md`
- Publication pack: `docs/habr/synaps-open-source-habr-v3-pack.md`
- Benchmark guide: `benchmark/README_RU.md`
- Post-audit implementation note: `docs/audit/SYNAPS_UPDATE_AUDIT_2026_04_25.md`
- HPC-дорожная карта: `docs/architecture/08_HPC_SILICON_OPTIMIZATION_ROADMAP.md`
- Протокол воспроизводимости и робастности: `docs/architecture/06_BENCHMARK_REPRODUCIBILITY_AND_ROBUSTNESS.md`
- Contributing: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`

## Академический Стандарт Отчётности

### Граница Утверждений

Этот README разделяет подтверждённые факты репозитория и плановые намерения.

- Подтверждённые утверждения привязаны к исполнимым артефактам, зафиксированным контрактам, benchmark-выгрузкам или CI-проверкам.
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

Для benchmark-утверждений публикуйте точную команду запуска, список seed, профиль решателя и путь к итоговому JSON-артефакту в `benchmark/studies/`.

### Цитирование И Научное Переиспользование

- Предпочтительный источник метаданных для цитирования: `CITATION.cff`.
- При ссылке на benchmark-результаты указывайте URL репозитория, commit SHA, путь к артефакту и дату исполнения.
- При сравнении с внешними методами обязательно фиксируйте обе границы: feasibility и wall-time.

## Governance

- `SUPPORT.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `MAINTAINERS.md`
- `RELEASE_POLICY.md`
- `CITATION.cff`

## Лицензия

MIT. См. [LICENSE](LICENSE).
