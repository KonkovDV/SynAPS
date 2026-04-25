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

Канонический артефакт:

- `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`
- Последний live stress-артефакт: `benchmark/studies/test-50k-academic-matrix-v1/rhc_50k_study.json`

Сводка из этого артефакта:

| Solver | Время (с) | Feasibility rate | Назначения |
|---|---:|---:|---:|
| `RHC-GREEDY` | 120.115 | 0.0 | 6 959 / 50 000 |
| `RHC-ALNS` | 366.23 | 0.0 | 1 078 / 50 000 |

Как это правильно читать:

- Это profiling/evidence-срез, а не "50K уже решено".
- Артефакт фиксирует честную границу: частичный прогресс и явные причины остановки.
- На текущем этапе главные узкие места - давление большого пула кандидатов и throughput ALNS внутри окна.
- Live-аудит stress-matrix от 25 апреля 2026 также выделил два ALNS-специфических режима деградации: infeasible recovery к initial seed и полное выгорание бюджета ещё на phase-1 seed generation до первой LNS-итерации.
- Post-audit смягчения по обоим направлениям уже включены в solver-код; для обновления публичных метрик нужен повторный 50K study.

Ключевые выводы из live stress-matrix `test-50k-academic-matrix-v1`:

- По покрытию `RHC-GREEDY` пока заметно сильнее: mean scheduled ratio `0.3547` против `0.1134` у `RHC-ALNS`.
- По частичному objective-профилю `RHC-ALNS` пока лучше: mean makespan `4652.77` против `11240.8` у `RHC-GREEDY`.
- Обе линии остаются non-feasible на 50K (`feasibility_rate = 0.0`), поэтому это артефакт диагностики узких мест, а не доказательство production-ready результата.
- Live-артефакт сохранил pre-fix evidence режима zero-iteration ALNS окна; текущий код репозитория уже переводит этот случай в явный fallback вместо принятия его как нормального inner solve.

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
