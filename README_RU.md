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
- отдельный `FeasibilityChecker` (`synaps/solvers/feasibility_checker.py`)

Что здесь не заявляется:

- промышленная валидация на живом заводе
- гарантированное построение полного feasible 50K расписания в текущих timebox

## 50K Срез (industrial-50k)

Канонический артефакт:

- `benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json`

Сводка из этого артефакта:

| Solver | Время (с) | Feasibility rate | Назначения |
|---|---:|---:|---:|
| `RHC-GREEDY` | 120.115 | 0.0 | 6 959 / 50 000 |
| `RHC-ALNS` | 366.23 | 0.0 | 1 078 / 50 000 |

Как это правильно читать:

- Это profiling/evidence-срез, а не "50K уже решено".
- Артефакт фиксирует честную границу: частичный прогресс и явные причины остановки.
- На текущем этапе главное узкое место - давление большого пула кандидатов.

## Портфель Решателей

Основные семейства:

- точные и почти точные: CP-SAT, LBBD, LBBD-HD
- конструктивные: Greedy ATCS, Beam
- многокритериальные срезы: epsilon/Pareto профили CP-SAT
- крупномасштабные контуры: ALNS, RHC
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

## Карта Репозитория

- `synaps/solvers/` - реализации решателей и реестр
- `synaps/model.py` - базовая Pydantic-модель
- `synaps/contracts.py` - стабильные JSON-контракты
- `synaps/problem_profile.py` - профилирование инстансов
- `synaps/validation.py` - проверка результатов solve
- `benchmark/` - harness и исследования
- `tests/` - тестовый контур
- `docs/` - архитектура, аудиты, публикационные материалы

## Что Читать Дальше

- Хабр-драфт (RU): `docs/habr/synaps-open-source-habr-v3.md`
- Publication pack: `docs/habr/synaps-open-source-habr-v3-pack.md`
- Benchmark guide: `benchmark/README_RU.md`
- Contributing: `CONTRIBUTING.md`
- Security policy: `SECURITY.md`

## Лицензия

MIT. См. [LICENSE](LICENSE).
