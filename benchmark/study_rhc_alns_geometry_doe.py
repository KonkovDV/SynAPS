"""Bounded DOE sweep for RHC-ALNS window geometry on industrial-50k.

This study keeps the current canonical ALNS inner profile fixed and varies only
the RHC window geometry. The goal is to isolate whether geometry controls the
transition from pre-search guard/fallback behavior to genuine ALNS search on
50K instances.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from benchmark.study_rhc_50k import _apply_lane_profile
from synaps.benchmarks.run_scaling_benchmark import run_benchmark as run_scaling_case


def _tail_cvar(values: list[float], alpha: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    clamped_alpha = min(max(alpha, 0.0), 0.999999)
    var_index = min(
        len(sorted_values) - 1,
        max(0, math.ceil(clamped_alpha * len(sorted_values)) - 1),
    )
    var_alpha = sorted_values[var_index]
    tail = [value for value in sorted_values if value >= var_alpha]
    return float(statistics.mean(tail)) if tail else float(var_alpha)


def _parse_geometry(value: str) -> tuple[int, int]:
    pieces = value.replace("/", ":").split(":")
    if len(pieces) != 2:
        raise argparse.ArgumentTypeError(
            f"Invalid geometry '{value}'. Expected WINDOW:OVERLAP."
        )
    try:
        window_minutes = int(pieces[0])
        overlap_minutes = int(pieces[1])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid geometry '{value}'. Expected integer WINDOW:OVERLAP."
        ) from exc
    if window_minutes <= 0 or overlap_minutes < 0 or overlap_minutes >= window_minutes:
        raise argparse.ArgumentTypeError(
            f"Invalid geometry '{value}'. Require window > 0 and 0 <= overlap < window."
        )
    return window_minutes, overlap_minutes


def _canonical_solver_kwargs() -> dict[str, Any]:
    return {
        "window_minutes": 480,
        "overlap_minutes": 120,
        "inner_solver": "alns",
        "time_limit_s": 1200,
        "fallback_repair_enabled": False,
        "alns_inner_window_time_cap_s": 180,
        "max_ops_per_window": 5000,
        # Admission-pressure stabilization: widen due-release horizon so
        # short-window DOE keeps a non-zero frontier before ALNS budget guards.
        "due_admission_horizon_factor": 2.0,
        "progressive_admission_relaxation_enabled": True,
        "admission_relaxation_min_fill_ratio": 0.30,
        "alns_budget_auto_scaling_enabled": True,
        "alns_budget_estimated_repair_s_per_destroyed_op": 0.125,
        "hybrid_inner_routing_enabled": True,
        "hybrid_inner_solver": "cpsat",
        "hybrid_due_pressure_threshold": 0.35,
        "hybrid_candidate_pressure_threshold": 4.0,
        "hybrid_max_ops": 1500,
        "backtracking_enabled": True,
        "backtracking_tail_minutes": 60,
        "backtracking_max_ops": 24,
        "hybrid_inner_kwargs": {
            "num_workers": 4,
        },
        "inner_fallback_kpi_threshold": 0.10,
        "inner_kwargs": {
            "max_iterations": 100,
            "destroy_fraction": 0.03,
            "min_destroy": 10,
            "max_destroy": 40,
            "max_no_improve_iters": 30,
            "use_cpsat_repair": True,
            "repair_time_limit_s": 5,
            "repair_num_workers": 1,
            "cpsat_max_destroy_ops": 32,
            "sa_auto_calibration_enabled": True,
            "dynamic_sa_enabled": True,
            "sa_due_alpha": 0.35,
            "sa_candidate_beta": 0.15,
            "sa_pressure_cooling_gamma": 0.0015,
            "sa_temp_min": 50.0,
            "sa_temp_max": 500.0,
        },
    }


def _run_scaling_case_with_timeout(
    *,
    n_ops: int,
    n_machines: int,
    n_states: int,
    solver_name: str,
    solver_kwargs: dict[str, Any],
    seed: int,
    timeout_s: float | None,
) -> tuple[dict[str, Any] | None, bool, str | None]:
    if timeout_s is None:
        try:
            return (
                run_scaling_case(
                    n_ops=n_ops,
                    n_machines=n_machines,
                    n_states=n_states,
                    solver_name=solver_name,
                    solver_kwargs=solver_kwargs,
                    seed=seed,
                ),
                False,
                None,
            )
        except Exception as exc:
            return None, False, str(exc)

    payload = {
        "n_ops": n_ops,
        "n_machines": n_machines,
        "n_states": n_states,
        "solver_name": solver_name,
        "solver_kwargs": solver_kwargs,
        "seed": seed,
    }

    with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as tmp_file:
        out_path = tmp_file.name

    script = (
        "import json,sys;"
        "from synaps.benchmarks.run_scaling_benchmark import run_benchmark as run_scaling_case;"
        "payload=json.loads(sys.argv[1]);"
        "result=run_scaling_case("
        "n_ops=payload['n_ops'],"
        "n_machines=payload['n_machines'],"
        "n_states=payload['n_states'],"
        "solver_name=payload['solver_name'],"
        "solver_kwargs=payload['solver_kwargs'],"
        "seed=payload['seed']"
        ");"
        "json.dump(result,open(sys.argv[2],'w',encoding='utf-8'))"
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])

    try:
        subprocess.run(
            [sys.executable, "-c", script, json.dumps(payload), out_path],
            check=True,
            timeout=timeout_s,
            capture_output=True,
            text=True,
            env=env,
        )
        raw = json.loads(Path(out_path).read_text(encoding="utf-8"))
        return raw, False, None
    except subprocess.TimeoutExpired:
        return None, True, None
    except subprocess.CalledProcessError as exc:
        stdout = (exc.stdout or "").strip()
        stderr = (exc.stderr or "").strip()
        details = [f"subprocess failed: returncode={exc.returncode}"]
        if stderr:
            details.append(f"stderr: {stderr}")
        if stdout:
            details.append(f"stdout: {stdout}")
        return None, False, " | ".join(details)
    except Exception as exc:
        return None, False, str(exc)
    finally:
        try:
            Path(out_path).unlink(missing_ok=True)
        except OSError:
            pass


def _summarize_inner_windows(inner_window_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    if not inner_window_summaries:
        return {
            "windows_observed": 0,
            "search_active_windows": 0,
            "search_active_window_rate": 0.0,
            "budget_guard_skipped_windows": 0,
            "fallback_windows": 0,
            "total_iterations_completed": 0,
            "mean_iterations_completed": 0.0,
            "mean_iterations_completed_active": 0.0,
            "mean_improvements": 0.0,
            "mean_ops_in_window": 0.0,
        }

    iterations = [int(summary.get("iterations_completed", 0)) for summary in inner_window_summaries]
    active_iterations = [value for value in iterations if value > 0]
    improvements = [int(summary.get("improvements", 0)) for summary in inner_window_summaries]
    ops_in_window = [int(summary.get("ops_in_window", 0)) for summary in inner_window_summaries]
    fallback_windows = sum(
        1 for summary in inner_window_summaries if summary.get("resolution_mode") == "fallback_greedy"
    )
    budget_guard_skipped_windows = sum(
        1
        for summary in inner_window_summaries
        if bool(summary.get("budget_guard_skipped_initial_search", False))
    )
    search_active_windows = len(active_iterations)

    return {
        "windows_observed": len(inner_window_summaries),
        "search_active_windows": search_active_windows,
        "search_active_window_rate": round(
            search_active_windows / max(1, len(inner_window_summaries)),
            4,
        ),
        "budget_guard_skipped_windows": budget_guard_skipped_windows,
        "fallback_windows": fallback_windows,
        "total_iterations_completed": sum(iterations),
        "mean_iterations_completed": round(statistics.mean(iterations), 2),
        "mean_iterations_completed_active": round(
            statistics.mean(active_iterations),
            2,
        )
        if active_iterations
        else 0.0,
        "mean_improvements": round(statistics.mean(improvements), 2),
        "mean_ops_in_window": round(statistics.mean(ops_in_window), 2),
    }


def _render_markdown_table(config_summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# RHC-ALNS Geometry DOE",
        "",
        "| geometry | proc-completed | solve-completed | solver-errors | censored | fallback | guard-skipped | search-active | total-iters | mean-iters-active | scheduled-ratio | assigned-ops | wall-time-s |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for config in config_summaries:
        summary = config["summary"]
        inner = summary["inner_window_summary"]
        lines.append(
            "| {geometry} | {process_completed} | {solve_completed} | {solver_errors} | {censored} | {fallback:.4f} | {guard} | {active:.4f} | {iters} | {active_iters:.2f} | {sched:.4f} | {assigned:.0f} | {wall:.2f} |".format(
                geometry=config["geometry_label"],
                process_completed=summary["process_completed_seed_count"],
                solve_completed=summary["solve_completed_seed_count"],
                solver_errors=summary["solver_error_seed_count"],
                censored=summary["censored_seed_count"],
                fallback=summary["mean_inner_fallback_ratio"],
                guard=inner["budget_guard_skipped_windows"],
                active=inner["search_active_window_rate"],
                iters=inner["total_iterations_completed"],
                active_iters=inner["mean_iterations_completed_active"],
                sched=summary["mean_scheduled_ratio"],
                assigned=summary["mean_assigned_ops"],
                wall=summary["mean_wall_time_s"],
            )
        )
    return "\n".join(lines) + "\n"


def _build_report(
    *,
    lane: str,
    study_seeds: list[int],
    max_windows: int,
    time_limit_s: float,
    cvar_alpha: float,
    study_geometries: list[tuple[int, int]],
    config_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "study_kind": "rhc-alns-geometry-doe",
        "preset_name": "industrial-50k",
        "lane": lane,
        "seed_count": len(study_seeds),
        "seeds": study_seeds,
        "bounded_max_windows": max_windows,
        "bounded_time_limit_s": time_limit_s,
        "cvar_alpha": cvar_alpha,
        "geometries": [
            {"window_minutes": window, "overlap_minutes": overlap}
            for window, overlap in study_geometries
        ],
        "config_summaries": config_summaries,
        "top_configs": config_summaries[: min(10, len(config_summaries))],
    }


def _write_report_artifacts(
    *,
    artifact_dir: Path,
    report: dict[str, Any],
    config_summaries: list[dict[str, Any]],
) -> dict[str, Any]:
    report_path = artifact_dir / "rhc_alns_geometry_doe.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    markdown_path = artifact_dir / "summary.md"
    markdown_path.write_text(
        _render_markdown_table(config_summaries),
        encoding="utf-8",
    )
    report["artifact_path"] = str(report_path)
    report["markdown_summary_path"] = str(markdown_path)
    return report


def run_rhc_alns_geometry_doe(
    *,
    geometries: list[tuple[int, int]] | None = None,
    seeds: list[int] | None = None,
    lane: str = "throughput",
    cvar_alpha: float = 0.95,
    max_windows: int = 2,
    time_limit_s: float = 200.0,
    per_run_timeout_s: float | None = None,
    write_dir: Path | None = None,
) -> dict[str, Any]:
    study_geometries = geometries or [(480, 120), (360, 90), (300, 90), (240, 60)]
    study_seeds = seeds or [1]
    artifact_dir = write_dir or Path("benchmark") / "studies" / "rhc_alns_geometry_doe"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    config_summaries: list[dict[str, Any]] = []

    for window_minutes, overlap_minutes in study_geometries:
        runs: list[dict[str, Any]] = []
        for seed in study_seeds:
            solver_kwargs = deepcopy(_canonical_solver_kwargs())
            solver_kwargs["window_minutes"] = window_minutes
            solver_kwargs["overlap_minutes"] = overlap_minutes
            solver_kwargs["max_windows"] = max_windows
            solver_kwargs["time_limit_s"] = time_limit_s

            profiled_kwargs = _apply_lane_profile(
                "RHC-ALNS",
                solver_kwargs,
                lane="strict" if lane == "strict" else "throughput",
                seed=seed,
            )

            raw_result, timed_out, run_error = _run_scaling_case_with_timeout(
                n_ops=50_000,
                n_machines=100,
                n_states=20,
                solver_name="rhc-alns",
                solver_kwargs=profiled_kwargs,
                seed=seed,
                timeout_s=per_run_timeout_s,
            )
            if timed_out:
                runs.append(
                    {
                        "seed": seed,
                        "process_outcome": "timeout_censored",
                        "solve_outcome": "not_executed",
                        "status": "timeout_censored",
                        "censored": True,
                        "feasible": False,
                        "assigned_ops": 0,
                        "scheduled_ratio": 0.0,
                        "makespan_minutes": 0.0,
                        "wall_time_s": float(per_run_timeout_s or 0.0),
                        "inner_fallback_ratio": 0.0,
                        "alns_presearch_budget_guard_skipped_windows": 0,
                        "inner_window_summary": _summarize_inner_windows([]),
                        "solver_metadata": {},
                    }
                )
                continue

            if raw_result is None:
                runs.append(
                    {
                        "seed": seed,
                        "process_outcome": "run_error",
                        "solve_outcome": "not_executed",
                        "status": "run_error",
                        "censored": True,
                        "error": run_error or "unknown error",
                        "feasible": False,
                        "assigned_ops": 0,
                        "scheduled_ratio": 0.0,
                        "makespan_minutes": 0.0,
                        "wall_time_s": 0.0,
                        "inner_fallback_ratio": 0.0,
                        "alns_presearch_budget_guard_skipped_windows": 0,
                        "inner_window_summary": _summarize_inner_windows([]),
                        "solver_metadata": {},
                    }
                )
                continue

            metadata = raw_result.get("metadata", {})
            inner_window_summaries = metadata.get("inner_window_summaries", [])
            if not isinstance(inner_window_summaries, list):
                inner_window_summaries = []

            raw_status = str(raw_result.get("status", "error")).lower()
            solve_completed = raw_status in {"feasible", "optimal"}

            runs.append(
                {
                    "seed": seed,
                    "process_outcome": "completed",
                    "solve_outcome": "completed" if solve_completed else "solver_error",
                    "status": raw_result["status"],
                    "censored": False,
                    "feasible": bool(raw_result["feasible"]),
                    "assigned_ops": int(raw_result["assigned_ops"]),
                    "scheduled_ratio": round(
                        int(raw_result["assigned_ops"]) / max(1, int(raw_result["n_ops"])),
                        6,
                    ),
                    "makespan_minutes": float(raw_result["makespan_min"]),
                    "wall_time_s": round(float(raw_result["solve_ms"]) / 1000.0, 4),
                    "inner_fallback_ratio": float(metadata.get("inner_fallback_ratio", 0.0)),
                    "alns_presearch_budget_guard_skipped_windows": int(
                        metadata.get("alns_presearch_budget_guard_skipped_windows", 0)
                    ),
                    "inner_window_summary": _summarize_inner_windows(inner_window_summaries),
                    "solver_metadata": metadata,
                }
            )

        process_completed_runs = [
            run for run in runs if run.get("process_outcome") == "completed"
        ]
        solve_completed_runs = [
            run for run in process_completed_runs if run.get("solve_outcome") == "completed"
        ]
        solver_error_runs = [
            run for run in process_completed_runs if run.get("solve_outcome") == "solver_error"
        ]
        censored_count = len(runs) - len(process_completed_runs)

        assigned_ops = [float(run["assigned_ops"]) for run in process_completed_runs] or [0.0]
        scheduled_ratios = [float(run["scheduled_ratio"]) for run in process_completed_runs] or [0.0]
        makespans = [float(run["makespan_minutes"]) for run in process_completed_runs] or [0.0]
        wall_times = [float(run["wall_time_s"]) for run in process_completed_runs] or [0.0]
        fallback_ratios = [float(run["inner_fallback_ratio"]) for run in process_completed_runs] or [0.0]
        guard_skips = [
            float(run["alns_presearch_budget_guard_skipped_windows"])
            for run in process_completed_runs
        ] or [0.0]
        search_active_rates = [
            float(run["inner_window_summary"]["search_active_window_rate"])
            for run in process_completed_runs
        ] or [0.0]
        total_iterations = [
            float(run["inner_window_summary"]["total_iterations_completed"])
            for run in process_completed_runs
        ] or [0.0]
        mean_active_iterations = [
            float(run["inner_window_summary"]["mean_iterations_completed_active"])
            for run in process_completed_runs
        ] or [0.0]

        config_summaries.append(
            {
                "geometry": {
                    "window_minutes": window_minutes,
                    "overlap_minutes": overlap_minutes,
                },
                "geometry_label": f"{window_minutes}/{overlap_minutes}",
                "runs": runs,
                "summary": {
                    "seed_count": len(runs),
                    "process_completed_seed_count": len(process_completed_runs),
                    "solve_completed_seed_count": len(solve_completed_runs),
                    "completed_seed_count": len(solve_completed_runs),
                    "solver_error_seed_count": len(solver_error_runs),
                    "censored_seed_count": censored_count,
                    "feasibility_rate": round(
                        sum(1 for run in solve_completed_runs if run["feasible"])
                        / max(1, len(solve_completed_runs)),
                        4,
                    ),
                    "mean_assigned_ops": round(statistics.mean(assigned_ops), 2),
                    "mean_scheduled_ratio": round(statistics.mean(scheduled_ratios), 4),
                    "cvar_unscheduled_ratio": round(
                        _tail_cvar([1.0 - value for value in scheduled_ratios], cvar_alpha),
                        4,
                    ),
                    "mean_makespan_minutes": round(statistics.mean(makespans), 2),
                    "cvar_makespan_minutes": round(_tail_cvar(makespans, cvar_alpha), 2),
                    "mean_wall_time_s": round(statistics.mean(wall_times), 2),
                    "mean_inner_fallback_ratio": round(statistics.mean(fallback_ratios), 4),
                    "cvar_inner_fallback_ratio": round(
                        _tail_cvar(fallback_ratios, cvar_alpha),
                        4,
                    ),
                    "mean_guard_skipped_windows": round(statistics.mean(guard_skips), 2),
                    "mean_search_active_window_rate": round(
                        statistics.mean(search_active_rates),
                        4,
                    ),
                    "mean_total_iterations_completed": round(
                        statistics.mean(total_iterations),
                        2,
                    ),
                    "mean_iterations_completed_active": round(
                        statistics.mean(mean_active_iterations),
                        2,
                    ),
                    "inner_window_summary": {
                        "windows_observed": round(
                            statistics.mean(
                                float(run["inner_window_summary"]["windows_observed"])
                                for run in runs
                            ),
                            2,
                        ),
                        "search_active_windows": round(
                            statistics.mean(
                                float(run["inner_window_summary"]["search_active_windows"])
                                for run in runs
                            ),
                            2,
                        ),
                        "search_active_window_rate": round(
                            statistics.mean(search_active_rates),
                            4,
                        ),
                        "budget_guard_skipped_windows": round(
                            statistics.mean(
                                float(run["inner_window_summary"]["budget_guard_skipped_windows"])
                                for run in runs
                            ),
                            2,
                        ),
                        "fallback_windows": round(
                            statistics.mean(
                                float(run["inner_window_summary"]["fallback_windows"])
                                for run in runs
                            ),
                            2,
                        ),
                        "total_iterations_completed": round(
                            statistics.mean(total_iterations),
                            2,
                        ),
                        "mean_iterations_completed": round(
                            statistics.mean(
                                float(run["inner_window_summary"]["mean_iterations_completed"])
                                for run in runs
                            ),
                            2,
                        ),
                        "mean_iterations_completed_active": round(
                            statistics.mean(mean_active_iterations),
                            2,
                        ),
                        "mean_improvements": round(
                            statistics.mean(
                                float(run["inner_window_summary"]["mean_improvements"])
                                for run in runs
                            ),
                            2,
                        ),
                        "mean_ops_in_window": round(
                            statistics.mean(
                                float(run["inner_window_summary"]["mean_ops_in_window"])
                                for run in runs
                            ),
                            2,
                        ),
                    },
                },
            }
        )

        config_summaries.sort(
            key=lambda item: (
                float(item["summary"]["mean_inner_fallback_ratio"]),
                -float(item["summary"]["mean_total_iterations_completed"]),
                -float(item["summary"]["mean_scheduled_ratio"]),
                float(item["summary"]["mean_wall_time_s"]),
            )
        )

        partial_report = _build_report(
            lane=lane,
            study_seeds=study_seeds,
            max_windows=max_windows,
            time_limit_s=time_limit_s,
            cvar_alpha=cvar_alpha,
            study_geometries=study_geometries,
            config_summaries=config_summaries,
        )
        _write_report_artifacts(
            artifact_dir=artifact_dir,
            report=partial_report,
            config_summaries=config_summaries,
        )

    config_summaries.sort(
        key=lambda item: (
            float(item["summary"]["mean_inner_fallback_ratio"]),
            -float(item["summary"]["mean_total_iterations_completed"]),
            -float(item["summary"]["mean_scheduled_ratio"]),
            float(item["summary"]["mean_wall_time_s"]),
        )
    )

    report = _build_report(
        lane=lane,
        study_seeds=study_seeds,
        max_windows=max_windows,
        time_limit_s=time_limit_s,
        cvar_alpha=cvar_alpha,
        study_geometries=study_geometries,
        config_summaries=config_summaries,
    )
    return _write_report_artifacts(
        artifact_dir=artifact_dir,
        report=report,
        config_summaries=config_summaries,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bounded geometry DOE for RHC-ALNS on industrial-50k"
    )
    parser.add_argument(
        "--geometries",
        nargs="+",
        type=_parse_geometry,
        default=[(480, 120), (360, 90), (300, 90), (240, 60)],
        help="Geometry list as WINDOW:OVERLAP pairs",
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--lane", choices=["throughput", "strict"], default="throughput")
    parser.add_argument("--max-windows", type=int, default=2)
    parser.add_argument("--time-limit-s", type=float, default=200.0)
    parser.add_argument(
        "--per-run-timeout-s",
        type=float,
        default=None,
        help="Hard timeout per seed/geometry run in wall seconds (marks run as timeout_censored).",
    )
    parser.add_argument("--cvar-alpha", type=float, default=0.95)
    parser.add_argument("--write-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_rhc_alns_geometry_doe(
        geometries=args.geometries,
        seeds=args.seeds,
        lane=args.lane,
        cvar_alpha=args.cvar_alpha,
        max_windows=args.max_windows,
        time_limit_s=args.time_limit_s,
        per_run_timeout_s=args.per_run_timeout_s,
        write_dir=args.write_dir,
    )
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())