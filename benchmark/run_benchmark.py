"""Benchmark runner for SynAPS solver portfolio.

Usage (CLI):
    python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED CPSAT-30
    python -m benchmark.run_benchmark benchmark/instances/ --compare --runs 3
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from synaps import solve_schedule
from synaps.model import ScheduleProblem, ScheduleResult
from synaps.problem_profile import build_problem_profile
from synaps.replay import build_benchmark_replay_artifact, write_replay_artifact
from synaps.solvers.registry import available_solver_configs, create_solver
from synaps.validation import verify_schedule_result

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
    instance_path: Path,
    problem_profile: dict[str, int | float | bool | str],
    solver_name: str,
    runs: int = 1,
    include_replay: bool = False,
    replay_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute *solver_name* on *problem* for *runs* repetitions."""
    try:
        import resource as _resource  # noqa: PLC0415
    except ImportError:
        _resource = None  # type: ignore[assignment]

    solver = None
    solve_kwargs: dict[str, object] = {}
    selected_solver_config = solver_name

    if solver_name != "AUTO":
        solver, solve_kwargs = create_solver(solver_name)

    wall_times: list[float] = []
    last_result: ScheduleResult | None = None
    peak_rss_kb = 0

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
        try:
            getrusage = getattr(_resource, "getrusage", None) if _resource is not None else None
            usage_scope = getattr(_resource, "RUSAGE_SELF", None) if _resource is not None else None
            if callable(getrusage) and usage_scope is not None:
                peak_rss_kb = max(peak_rss_kb, getrusage(usage_scope).ru_maxrss)
        except Exception:
            pass

    assert last_result is not None
    obj = last_result.objective
    verification = verify_schedule_result(problem, last_result)

    meta = last_result.metadata or {}
    portfolio_metadata = meta.get("portfolio", {})
    if not isinstance(portfolio_metadata, dict):
        portfolio_metadata = {}
    best_bound = meta.get("best_objective_bound")
    gap_pct: float | None = None
    if best_bound is not None and obj.weighted_sum:
        gap_pct = round(
            (obj.weighted_sum - best_bound) / max(abs(best_bound), 1e-9) * 100,
            3,
        )

    peak_rss_mb: float | None = None
    try:
        if os.name == "nt":
            import psutil  # type: ignore[import-untyped]  # noqa: PLC0415

            peak_rss_mb = round(psutil.Process().memory_info().peak_wset / 1024 / 1024, 1)
        elif peak_rss_kb > 0:
            peak_rss_mb = round(peak_rss_kb / 1024, 1)
    except Exception:
        pass

    statistics_block: dict[str, Any] = {
        "runs": runs,
        "wall_time_s_mean": round(statistics.mean(wall_times), 4),
        "wall_time_s_min": round(min(wall_times), 4),
        "wall_time_s_max": round(max(wall_times), 4),
    }
    if runs > 1:
        statistics_block["wall_time_s_median"] = round(statistics.median(wall_times), 4)
        if runs >= 3:
            statistics_block["wall_time_s_stdev"] = round(statistics.stdev(wall_times), 4)
    if peak_rss_mb is not None:
        statistics_block["peak_rss_mb"] = peak_rss_mb

    results_block: dict[str, Any] = {
        "status": last_result.status.value,
        "feasible": last_result.status.value in ("optimal", "feasible"),
        "proved_optimal": last_result.status.value == "optimal",
        "solver_name": last_result.solver_name,
        "makespan_minutes": obj.makespan_minutes,
        "total_setup_minutes": obj.total_setup_minutes,
        "total_tardiness_minutes": obj.total_tardiness_minutes,
        "total_material_loss": obj.total_material_loss,
        "weighted_sum": obj.weighted_sum,
        "assignments": len(last_result.assignments),
    }
    if best_bound is not None:
        results_block["best_objective_bound"] = best_bound
    if gap_pct is not None:
        results_block["gap_pct"] = gap_pct
    if meta.get("warm_started"):
        results_block["warm_started"] = True

    verification_block: dict[str, Any] = {
        "feasible": verification.feasible,
        "violation_count": verification.violation_count,
        "violation_kinds": verification.violation_kinds,
    }

    report = {
        "solver_config": solver_name,
        "selected_solver_config": selected_solver_config,
        "results": results_block,
        "verification": verification_block,
        "statistics": statistics_block,
    }
    if include_replay or replay_output_dir is not None:
        replay_artifact = build_benchmark_replay_artifact(
            instance_path=instance_path,
            solver_config=solver_name,
            selected_solver_config=selected_solver_config,
            results=results_block,
            verification=verification_block,
            statistics=statistics_block,
            problem_profile=problem_profile,
            portfolio_metadata=portfolio_metadata,
        )
        if include_replay:
            report["replay"] = replay_artifact.model_dump(mode="json")
        if replay_output_dir is not None:
            replay_path = write_replay_artifact(
                replay_output_dir,
                replay_artifact,
                stem_parts=(instance_path.stem, selected_solver_config, "benchmark-run"),
            )
            report["replay_artifact_path"] = str(replay_path)
    return report


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_benchmark(
    instance_path: Path,
    solver_names: list[str] | None = None,
    runs: int = 1,
    compare: bool = False,
    include_replay: bool = False,
    replay_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Run one or more solver configurations on an instance.

    Args:
        instance_path: Path to a JSON instance file.
        solver_names: Solver config keys (see ``available_solvers``).
        runs: Repetitions per configuration.
        compare: If True, return a comparison report across all configs.
        include_replay: If True, attach a canonical replay artifact per run.
        replay_output_dir: If provided, write replay artifacts to this directory.

    Returns:
        A dict with either a single-solver report or a ``comparisons`` list.
    """
    names = solver_names or ["GREED"]
    problem = load_problem(instance_path)
    problem_profile = build_problem_profile(problem).as_dict()

    if compare and len(names) > 1:
        comparisons = [
            _run_single(
                problem,
                instance_path,
                problem_profile,
                n,
                runs,
                include_replay=include_replay,
                replay_output_dir=replay_output_dir,
            )
            for n in names
        ]
        return {
            "instance": instance_path.name,
            "problem_profile": problem_profile,
            "comparisons": comparisons,
        }

    # Single-solver mode (first name only)
    report = _run_single(
        problem,
        instance_path,
        problem_profile,
        names[0],
        runs,
        include_replay=include_replay,
        replay_output_dir=replay_output_dir,
    )
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
    parser.add_argument(
        "--include-replay",
        action="store_true",
        help="Attach canonical replay artifacts to the emitted benchmark report",
    )
    parser.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Directory where replay artifacts should be written as JSON files",
    )

    args = parser.parse_args()
    path: Path = args.path

    instances = sorted(path.glob("*.json")) if path.is_dir() else [path]

    all_reports: list[dict[str, Any]] = []
    for inst in instances:
        report = run_benchmark(
            inst,
            args.solvers,
            runs=args.runs,
            compare=args.compare,
            include_replay=args.include_replay,
            replay_output_dir=args.replay_output_dir,
        )
        all_reports.append(report)

    json.dump(all_reports if len(all_reports) > 1 else all_reports[0], sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
