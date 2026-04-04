"""Benchmark runner for SynAPS solver portfolio.

Usage (CLI):
    python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED CPSAT-30
    python -m benchmark.run_benchmark benchmark/instances/ --compare --runs 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from synaps import solve_schedule
from synaps.model import ScheduleProblem, ScheduleResult
from synaps.problem_profile import build_problem_profile
from synaps.solvers.registry import available_solver_configs, create_solver

# ---------------------------------------------------------------------------
# Solver registry — shared package surface used by tooling and runtime routing.
# ---------------------------------------------------------------------------


def available_solvers() -> list[str]:
    """Return registered solver configuration names."""

    return ["AUTO", *available_solver_configs()]


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_problem(path: Path) -> ScheduleProblem:
    """Deserialise a JSON instance into a ScheduleProblem."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return ScheduleProblem.model_validate(data)


# ---------------------------------------------------------------------------
# Single solver execution
# ---------------------------------------------------------------------------


def _run_single(
    problem: ScheduleProblem,
    solver_name: str,
    runs: int = 1,
) -> dict[str, Any]:
    """Execute *solver_name* on *problem* for *runs* repetitions."""
    solver = None
    solve_kwargs: dict[str, object] = {}
    selected_solver_config = solver_name

    if solver_name != "AUTO":
        solver, solve_kwargs = create_solver(solver_name)

    wall_times: list[float] = []
    last_result: ScheduleResult | None = None

    for _ in range(runs):
        t0 = time.perf_counter()
        if solver_name == "AUTO":
            result = solve_schedule(problem, verify_feasibility=False)
            portfolio_metadata = result.metadata.get("portfolio", {})
            resolved_solver_config = portfolio_metadata.get("solver_config")
            if isinstance(resolved_solver_config, str):
                selected_solver_config = resolved_solver_config
        else:
            assert solver is not None
            result = solver.solve(problem, **solve_kwargs)
        wall_times.append(time.perf_counter() - t0)
        last_result = result

    assert last_result is not None
    obj = last_result.objective

    return {
        "solver_config": solver_name,
        "selected_solver_config": selected_solver_config,
        "results": {
            "status": last_result.status.value,
            "feasible": last_result.status.value in ("optimal", "feasible"),
            "solver_name": last_result.solver_name,
            "makespan_minutes": obj.makespan_minutes,
            "total_setup_minutes": obj.total_setup_minutes,
            "total_tardiness_minutes": obj.total_tardiness_minutes,
            "total_material_loss": obj.total_material_loss,
            "weighted_sum": obj.weighted_sum,
            "assignments": len(last_result.assignments),
        },
        "statistics": {
            "runs": runs,
            "wall_time_s_mean": round(statistics.mean(wall_times), 4),
            "wall_time_s_min": round(min(wall_times), 4),
            "wall_time_s_max": round(max(wall_times), 4),
        },
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_benchmark(
    instance_path: Path,
    solver_names: list[str] | None = None,
    runs: int = 1,
    compare: bool = False,
) -> dict[str, Any]:
    """Run one or more solver configurations on an instance.

    Args:
        instance_path: Path to a JSON instance file.
        solver_names: Solver config keys (see ``available_solvers``).
        runs: Repetitions per configuration.
        compare: If True, return a comparison report across all configs.

    Returns:
        A dict with either a single-solver report or a ``comparisons`` list.
    """
    names = solver_names or ["GREED"]
    problem = load_problem(instance_path)
    problem_profile = build_problem_profile(problem).as_dict()

    if compare and len(names) > 1:
        comparisons = [_run_single(problem, n, runs) for n in names]
        return {
            "instance": instance_path.name,
            "problem_profile": problem_profile,
            "comparisons": comparisons,
        }

    # Single-solver mode (first name only)
    report = _run_single(problem, names[0], runs)
    report["instance"] = instance_path.name
    report["problem_profile"] = problem_profile
    return report


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="SynAPS Benchmark Runner")
    parser.add_argument("path", type=Path, help="Instance JSON file or directory")
    parser.add_argument(
        "--solvers",
        nargs="*",
        default=["GREED"],
        choices=available_solvers(),
        help="Solver configurations to benchmark",
    )
    parser.add_argument("--runs", type=int, default=1, help="Repetitions per solver")
    parser.add_argument("--compare", action="store_true", help="Compare all solvers side-by-side")

    args = parser.parse_args()
    path: Path = args.path

    instances = sorted(path.glob("*.json")) if path.is_dir() else [path]

    all_reports: list[dict[str, Any]] = []
    for inst in instances:
        report = run_benchmark(inst, args.solvers, runs=args.runs, compare=args.compare)
        all_reports.append(report)

    json.dump(all_reports if len(all_reports) > 1 else all_reports[0], sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
