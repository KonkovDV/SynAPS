"""Benchmark runner for SynAPS solver portfolio.

Usage (CLI):
    python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED CPSAT-30
    python -m benchmark.run_benchmark benchmark/instances/ --compare --runs 3
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from statistics import NormalDist
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


_T_CRITICAL_95: dict[int, float] = {
    1: 12.706,
    2: 4.303,
    3: 3.182,
    4: 2.776,
    5: 2.571,
    6: 2.447,
    7: 2.365,
    8: 2.306,
    9: 2.262,
    10: 2.228,
    11: 2.201,
    12: 2.179,
    13: 2.16,
    14: 2.145,
    15: 2.131,
    16: 2.12,
    17: 2.11,
    18: 2.101,
    19: 2.093,
    20: 2.086,
    21: 2.08,
    22: 2.074,
    23: 2.069,
    24: 2.064,
    25: 2.06,
    26: 2.056,
    27: 2.052,
    28: 2.048,
    29: 2.045,
    30: 2.042,
}


def _mean_confidence_interval(samples: list[float], confidence_level: float = 0.95) -> dict[str, float] | None:
    """Return a mean confidence interval for repeated benchmark samples."""
    if len(samples) < 2:
        return None

    mean_value = statistics.mean(samples)
    std_dev = statistics.stdev(samples)
    if std_dev == 0:
        return {
            "confidence_level": confidence_level,
            "low": round(mean_value, 6),
            "high": round(mean_value, 6),
            "half_width": 0.0,
        }

    df = len(samples) - 1
    alpha = 1.0 - confidence_level
    critical = _T_CRITICAL_95.get(df)
    if critical is None:
        critical = NormalDist().inv_cdf(1.0 - alpha / 2.0)
    half_width = critical * std_dev / math.sqrt(len(samples))
    return {
        "confidence_level": confidence_level,
        "low": round(mean_value - half_width, 6),
        "high": round(mean_value + half_width, 6),
        "half_width": round(half_width, 6),
    }


def _two_sided_sign_test_pvalue(differences: list[float]) -> float | None:
    """Exact two-sided paired sign test p-value using wins/losses only."""
    wins = sum(1 for diff in differences if diff < 0)
    losses = sum(1 for diff in differences if diff > 0)
    trials = wins + losses
    if trials == 0:
        return None
    tail = min(wins, losses)
    cumulative = sum(math.comb(trials, k) for k in range(tail + 1)) / (2 ** trials)
    return round(min(1.0, 2.0 * cumulative), 6)


def _build_paired_metric_summary(candidate: list[float], baseline: list[float]) -> dict[str, Any] | None:
    """Summarize paired repeated-run differences between two solver metrics."""
    pair_count = min(len(candidate), len(baseline))
    if pair_count == 0:
        return None

    candidate_values = candidate[:pair_count]
    baseline_values = baseline[:pair_count]
    differences = [cand - base for cand, base in zip(candidate_values, baseline_values)]
    wins = sum(1 for diff in differences if diff < 0)
    losses = sum(1 for diff in differences if diff > 0)
    ties = pair_count - wins - losses
    mean_difference = statistics.mean(differences)
    ratio_samples = [
        cand / max(abs(base), 1e-9)
        for cand, base in zip(candidate_values, baseline_values)
    ]
    summary: dict[str, Any] = {
        "pairs": pair_count,
        "mean_difference": round(mean_difference, 6),
        "mean_ratio": round(statistics.mean(ratio_samples), 6),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_rate": round(wins / pair_count, 6),
        "sign_test_pvalue": _two_sided_sign_test_pvalue(differences),
    }
    ci = _mean_confidence_interval(differences)
    if ci is not None:
        summary["difference_confidence_interval"] = ci
    return summary


def _build_performance_profile(
    comparisons: list[dict[str, Any]],
    metric_key: str = "wall_time_s_samples",
    taus: tuple[float, ...] = (1.0, 1.05, 1.1, 1.25, 1.5, 2.0),
) -> dict[str, dict[str, float]]:
    """Compute Dolan-More-style performance profile ratios over repeated runs."""
    if not comparisons:
        return {}

    sample_lists = [
        comparison.get("statistics", {}).get(metric_key, [])
        for comparison in comparisons
    ]
    run_count = min((len(samples) for samples in sample_lists), default=0)
    if run_count == 0:
        return {}

    profile: dict[str, dict[str, float]] = {}
    for comparison in comparisons:
        solver_name = comparison["solver_config"]
        profile[solver_name] = {}
        solver_samples = comparison["statistics"][metric_key][:run_count]
        for tau in taus:
            good_runs = 0
            for run_idx in range(run_count):
                best_run_value = min(samples[run_idx] for samples in sample_lists)
                if solver_samples[run_idx] <= (best_run_value * tau) + 1e-12:
                    good_runs += 1
            profile[solver_name][f"tau_{tau:.2f}"] = round(good_runs / run_count, 6)
    return profile


def _build_compare_statistics(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    """Create paired repeated-run statistics across solver reports."""
    if len(comparisons) < 2:
        return {}

    baseline = comparisons[0]
    baseline_name = baseline["solver_config"]
    paired_comparisons: dict[str, dict[str, Any]] = {}
    for candidate in comparisons[1:]:
        paired_comparisons[candidate["solver_config"]] = {
            "against": baseline_name,
            "wall_time": _build_paired_metric_summary(
                candidate.get("statistics", {}).get("wall_time_s_samples", []),
                baseline.get("statistics", {}).get("wall_time_s_samples", []),
            ),
            "weighted_sum": _build_paired_metric_summary(
                candidate.get("statistics", {}).get("weighted_sum_samples", []),
                baseline.get("statistics", {}).get("weighted_sum_samples", []),
            ),
        }

    return {
        "study_design": {
            "paired_by_run_index": True,
            "confidence_level": 0.95,
            "baseline_solver": baseline_name,
            "effect_size_note": "Negative mean_difference favors the candidate solver.",
        },
        "paired_comparisons": paired_comparisons,
        "performance_profile": _build_performance_profile(comparisons),
    }


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
    weighted_sum_samples: list[float] = []
    makespan_samples: list[float] = []
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
        weighted_sum_samples.append(result.objective.weighted_sum)
        makespan_samples.append(result.objective.makespan_minutes)
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
    verify_t0 = time.perf_counter()
    verification = verify_schedule_result(problem, last_result)
    verification_time_ms = int((time.perf_counter() - verify_t0) * 1000)

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
        "verification_time_ms": verification_time_ms,
        "wall_time_s_samples": [round(value, 6) for value in wall_times],
        "weighted_sum_samples": [round(value, 6) for value in weighted_sum_samples],
        "makespan_minutes_samples": [round(value, 6) for value in makespan_samples],
    }
    if runs > 1:
        statistics_block["wall_time_s_median"] = round(statistics.median(wall_times), 4)
        if runs >= 3:
            statistics_block["wall_time_s_stdev"] = round(statistics.stdev(wall_times), 4)
        wall_time_ci = _mean_confidence_interval(wall_times)
        if wall_time_ci is not None:
            statistics_block["wall_time_s_mean_ci"] = wall_time_ci
        weighted_sum_ci = _mean_confidence_interval(weighted_sum_samples)
        if weighted_sum_ci is not None:
            statistics_block["weighted_sum_mean_ci"] = weighted_sum_ci
        makespan_ci = _mean_confidence_interval(makespan_samples)
        if makespan_ci is not None:
            statistics_block["makespan_minutes_mean_ci"] = makespan_ci
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
        "solver_metadata": meta,
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
            "comparison_statistics": _build_compare_statistics(comparisons),
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
