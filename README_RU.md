# SynAPS

Открытый движок производственного планирования для задач класса MO-FJSP-SDST-ARC: гибкое цеховое планирование с последовательнозависимыми переналадками и вспомогательными ресурсами.

Language: [EN](README.md) | **RU**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Что Здесь Есть

SynAPS - это детерминированный стек планирования для случаев, где результат нужно не только получить, но и проверить, объяснить и воспроизвести.

Текущий репозиторий включает:

- точные и декомпозиционные решатели: `CP-SAT`, `LBBD`, `LBBD-HD`, `Pareto Slice`
- конструктивные и ремонтные слои: `Greedy ATCS`, `Beam Search`, `Incremental Repair`
- крупномасштабные поисковые пути: `ALNS` и `RHC`
- именованный реестр из 21 публичной solver-конфигурации
- независимый `FeasibilityChecker`, который запускается после каждого допустимого или оптимального solve-path
- необязательные native seams в [synaps/accelerators.py](synaps/accelerators.py) с безопасным Python fallback

На апрель 2026 года публичный портфель даёт 12 solver-семейств через 21 именованную конфигурацию.

## Граница Доказательности

SynAPS решает реальную и тяжёлую задачу планирования, но здесь важнее честная граница доказательности, чем красивый слоган.

| Поверхность | Что реально подтверждено |
|-------------|--------------------------|
| Точный слой | Самая сильная текущая база - малые и средние инстансы. `CP-SAT` и `LBBD` дают точный или почти точный слой с явной нижней границей или `gap`-семантикой. |
| Крупные инстансы | `ALNS`, `RHC` и `LBBD-HD` - текущий путь для синтетических исследований масштаба 5K-50K. Их задача сейчас - feasibility, runtime и поиск узких мест, а не доказательство оптимальности. |
| Валидация | Каждый допустимый или оптимальный результат проходит через независимый `FeasibilityChecker`, который проверяет полноту, допустимость станков, precedence, ёмкость станков, setup gaps, вспомогательные ресурсы и границы горизонта. |
| Отдельный 50K путь | Воспроизводимый 50K-study лежит в [benchmark/study_rhc_50k.py](benchmark/study_rhc_50k.py). Текущий материализованный артефакт - [benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json](benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json). |
| Живой завод | Утверждение о внедрении на реальном заводе в этом репозитории не делается. |

Если нужен роутер по документации, начинайте с [docs/README_RU.md](docs/README_RU.md). Если нужен публикационный draft, смотрите [docs/habr/synaps-open-source-habr-v3.md](docs/habr/synaps-open-source-habr-v3.md).

## Что Показал Текущий 50K Прогон

У репозитория теперь есть стабильная 50K evidence surface, и её ценность как раз в том, что она показывает текущую границу без косметики.

Артефакт [benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json](benchmark/studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json) фиксирует текущий детерминированный `industrial-50k` запуск для `RHC-GREEDY` и `RHC-ALNS` уже после динамического window cap и индексированного slot-search.

- `RHC-GREEDY` останавливается через `120.115s` и успевает зафиксировать `6959` назначений за `11` окон.
- `RHC-ALNS` останавливается через `366.23s` и успевает зафиксировать `1078` назначений за `3` окна.
- оба прогона завершились с `status=error` и `feasible=false`
- оба прогона всё ещё тянут почти весь earliest-frontier пул, доходя до `49 931` и `49 993` кандидатов
- глобальный fallback repair по-прежнему честно пропускается после исчерпания бюджета времени, поэтому артефакт сохраняет реальное узкое место вместо бесконечной уборки в конце

Это значит, что отдельный 50K profiling path уже существует и greedy-путь заметно ускорился, но текущий `industrial-50k` preset всё ещё нельзя называть закрытым промышленным benchmark-успехом. Узкое место сместилось: admission уже лучше, а теперь сильнее всего мешает throughput внутреннего solver-path, особенно у `RHC-ALNS`.

## Портфель Решателей

| Слой | Основные профили | Роль |
|------|------------------|------|
| Точный | `CPSAT-10`, `CPSAT-30`, `CPSAT-120` | точные solve-path для малых и средних инстансов |
| Декомпозиционный | `LBBD-5`, `LBBD-10`, `LBBD-5-HD`, `LBBD-10-HD`, `LBBD-20-HD` | точная или почти точная декомпозиция для более крупных ограниченных инстансов |
| Многокритериальные срезы | `CPSAT-EPS-SETUP-110`, `CPSAT-EPS-TARD-110`, `CPSAT-EPS-MATERIAL-110` | воспроизводимые `epsilon`-constraint запуски |
| Конструктивный | `GREED`, `GREED-K1-3`, `BEAM-3`, `BEAM-5` | быстрые допустимые расписания |
| Крупномасштабный поиск | `ALNS-300`, `ALNS-500`, `ALNS-1000`, `RHC-ALNS`, `RHC-CPSAT`, `RHC-GREEDY` | синтетические большие инстансы и временная декомпозиция |

Авторитетный реестр лежит в [synaps/solvers/registry.py](synaps/solvers/registry.py). Политика выбора - в [synaps/solvers/router.py](synaps/solvers/router.py).

## Быстрый Старт

```bash
git clone https://github.com/KonkovDV/SynAPS.git
cd SynAPS
pip install -e ".[dev]"
```

Решить маленький публичный инстанс:

```bash
python -m synaps solve benchmark/instances/tiny_3x3.json
```

Запустить benchmark-сравнение:

```bash
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-10 --compare
```

Запустить отдельный 50K study:

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/2026-04-13-rhc-50k-machine-index
```

Запустить Python test suite:

```bash
python -m pytest tests -q
```

## Карта Репозитория

- [docs/README_RU.md](docs/README_RU.md) - роутер по документации
- [benchmark/README_RU.md](benchmark/README_RU.md) - воспроизводимая benchmark-система
- [control-plane/README_RU.md](control-plane/README_RU.md) - TypeScript BFF и runtime boundary
- [docs/audit/ACADEMIC_AUDIT_L6_RESPONSE_2026_04_12.md](docs/audit/ACADEMIC_AUDIT_L6_RESPONSE_2026_04_12.md) - построчная академическая проверка ключевых утверждений
- [docs/habr/synaps-open-source-habr-v3.md](docs/habr/synaps-open-source-habr-v3.md) - актуальный Habr draft

## Текущее Состояние

Реализовано:

- детерминированный solver-портфель с точным, декомпозиционным, конструктивным и крупномасштабным слоями
- независимая проверка допустимости после каждого допустимого или оптимального solve-path
- публичный benchmark harness и детерминированная генерация синтетических инстансов
- отдельная команда для 50K study и материализованный артефакт с результатами
- необязательные native seams для hot-path scoring и capacity-check логики

Текущие узкие места:

- earliest-frontier давление в текущем `industrial-50k` preset всё ещё слишком широкое даже после динамического cap
- `RHC-GREEDY` заметно продвинулся, но `RHC-ALNS` по-прежнему слишком медленно проходит inner large-neighborhood path для сильного 50K результата

Как факт здесь не заявляется:

- валидация на живом заводе
- готовая интеграция с ERP или MES
- planner-facing production UI
- доказанный допустимый полный `industrial-50k` solve в рамках текущих публичных time budget
- обязательное compiled ядро beyond optional hot-path seams

## Лицензия

MIT.