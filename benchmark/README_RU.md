# Система бенчмарков SynAPS

Language: [EN](README.md) | **RU**

Эта директория содержит воспроизводимую систему бенчмарков для solver-ов SynAPS.

## Быстрый старт

```bash
# Один solver, один пример
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED

# Автоматический выбор solver-а
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers AUTO

# Сравнение двух solver-ов
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

# Сравнение обычного точного профиля и профиля с допуском
python -m benchmark.run_benchmark benchmark/instances/pareto_setup_tradeoff_4op.json \
  --solvers CPSAT-10 CPSAT-EPS-SETUP-110 --compare

# Несколько прогонов для статистической устойчивости
python -m benchmark.run_benchmark benchmark/instances/medium_20x10.json \
  --solvers GREED CPSAT-10 --runs 5 --compare

# Все примеры в директории
python -m benchmark.run_benchmark benchmark/instances/ --solvers GREED CPSAT-30
```

## Конфигурации solver-ов

| Имя | Solver | Параметры |
|------|--------|------------|
| `GREED` | GreedyDispatch | K1=2.0, K2=0.5 |
| `GREED-K1-3` | GreedyDispatch | K1=3.0, K2=0.5 |
| `CPSAT-10` | CpSatSolver | time_limit=10s |
| `CPSAT-30` | CpSatSolver | time_limit=30s |
| `CPSAT-120` | CpSatSolver | time_limit=120s |
| `CPSAT-EPS-SETUP-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise setup under a `1.10x` makespan cap |
| `CPSAT-EPS-TARD-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise tardiness under a `1.10x` makespan cap |
| `CPSAT-EPS-MATERIAL-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, минимизация потерь материала при ограничении makespan `1.10x` |
| `LBBD-5` | LbbdSolver | HiGHS master + CP-SAT sub, 5 iterations, capacity + load-balance cuts |
| `LBBD-10` | LbbdSolver | HiGHS master + CP-SAT sub, 10 iterations |
| `AUTO` | Portfolio router | выбирает конкретную конфигурацию под задачу |

## Что важно понимать

`CPSAT-EPS-SETUP-110`, `CPSAT-EPS-TARD-110` и `CPSAT-EPS-MATERIAL-110` — это публичные профили с допуском, а не полный перебор фронта Парето.

Каждый профиль делает три шага:

1. на первом шаге находится сильное базовое решение через обычный CP-SAT;
2. на втором шаге makespan ограничивается в пределах `10%` от базы, после чего минимизируется вторичная цель: setup, tardiness или material loss;
3. внутри этого режима solver дополнительно выбирает более компактное решение по makespan, чтобы не оставлять лишний запас.

`LBBD-5` и `LBBD-10` показывают декомпозицию Logic-Based Benders: HiGHS решает мастер-задачу, а CP-SAT — подзадачи. Поэтому система бенчмарков покрывает не только одиночные solver-режимы, но и путь через декомпозицию.

## Формат вывода

### Один solver

```json
{
  "instance": "tiny_3x3.json",
  "solver_config": "GREED",
  "selected_solver_config": "GREED",
  "results": {
    "status": "feasible",
    "feasible": true,
    "proved_optimal": false,
    "solver_name": "greedy_dispatch",
    "makespan_minutes": 95.0,
    "total_setup_minutes": 18.0,
    "total_material_loss": 0.0,
    "assignments": 6
  },
  "statistics": {
    "runs": 1,
    "wall_time_s_mean": 0.0012,
    "wall_time_s_min": 0.0012,
    "wall_time_s_max": 0.0012,
    "peak_rss_mb": 85.0
  }
}
```

### Режим сравнения

```json
{
  "instance": "tiny_3x3.json",
  "comparisons": [
    {"solver_config": "GREED", "results": {...}, "statistics": {...}},
    {"solver_config": "CPSAT-30", "results": {...}, "statistics": {...}}
  ]
}
```

## Использование из кода

```python
from pathlib import Path
from benchmark.run_benchmark import load_problem, run_benchmark

problem = load_problem(Path("benchmark/instances/tiny_3x3.json"))
report = run_benchmark(Path("benchmark/instances/tiny_3x3.json"), solver_names=["GREED"], runs=3)
```

## Добавление новых solver-ов

Регистрируйте новые конфигурации в `synaps/solvers/registry.py`:

```python
_SOLVER_REGISTRY["MY-SOLVER"] = SolverRegistration(
  factory=build_my_solver,
  solve_kwargs={"param": value},
  description="short human-readable description",
)
```

Специальный режим `AUTO` используется только для маршрута с автоматическим выбором и идёт через `synaps.solve_schedule()`.

## Примеры входных данных

Формат instance-файлов и список включённых примеров описаны в [instances/README.md](instances/README.md).