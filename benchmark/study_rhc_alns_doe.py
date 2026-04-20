"""DOE sweep for RHC-ALNS admission and SA pressure parameters.

This harness runs a bounded grid of policy parameters and reports robust
statistics (mean + CVaR) with a quality-gate verdict per configuration.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
import sys
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


def _default_solver_kwargs() -> dict[str, Any]:
    return {
        "window_minutes": 480,
        "overlap_minutes": 120,
        "inner_solver": "alns",
        "time_limit_s": 1200,
        "max_ops_per_window": 5_000,
        "hybrid_inner_routing_enabled": True,
        "hybrid_inner_solver": "cpsat",
        "hybrid_due_pressure_threshold": 0.35,
        "hybrid_candidate_pressure_threshold": 1.75,
        "hybrid_max_ops": 1_500,
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
            "use_cpsat_repair": False,
            "dynamic_sa_enabled": True,
            "sa_due_alpha": 0.35,
            "sa_candidate_beta": 0.15,
            "sa_pressure_cooling_gamma": 0.0015,
            "sa_temp_min": 50.0,
            "sa_temp_max": 500.0,
        },
    }


def _build_doe_grid(
    *,
    due_thresholds: list[float],
    candidate_thresholds: list[float],
    hybrid_max_ops_values: list[int],
    sa_due_alphas: list[float],
    sa_candidate_betas: list[float],
    max_combinations: int | None,
) -> list[dict[str, Any]]:
    grid = [
        {
            "hybrid_due_pressure_threshold": due_threshold,
            "hybrid_candidate_pressure_threshold": candidate_threshold,
            "hybrid_max_ops": hybrid_max_ops,
            "sa_due_alpha": sa_due_alpha,
            "sa_candidate_beta": sa_candidate_beta,
        }
        for (
            due_threshold,
            candidate_threshold,
            hybrid_max_ops,
            sa_due_alpha,
            sa_candidate_beta,
        ) in itertools.product(
            due_thresholds,
            candidate_thresholds,
            hybrid_max_ops_values,
            sa_due_alphas,
            sa_candidate_betas,
        )
    ]
    if max_combinations is not None:
        return grid[: max(1, max_combinations)]
    return grid


def run_rhc_alns_doe(
    *,
    seeds: list[int] | None = None,
    lane: str = "throughput",
    n_ops: int = 10_000,
    n_machines: int = 50,
    n_states: int = 15,
    cvar_alpha: float = 0.95,
    max_makespan_degradation_ratio: float = 1.05,
    max_inner_fallback_ratio: float = 0.10,
    due_thresholds: list[float] | None = None,
    candidate_thresholds: list[float] | None = None,
    hybrid_max_ops_values: list[int] | None = None,
    sa_due_alphas: list[float] | None = None,
    sa_candidate_betas: list[float] | None = None,
    max_combinations: int | None = 24,
    write_dir: Path | None = None,
) -> dict[str, Any]:
    study_seeds = seeds or [1, 2, 3]

    grid = _build_doe_grid(
        due_thresholds=due_thresholds or [0.25, 0.35, 0.45],
        candidate_thresholds=candidate_thresholds or [1.5, 1.75, 2.0],
        hybrid_max_ops_values=hybrid_max_ops_values or [1_000, 1_500],
        sa_due_alphas=sa_due_alphas or [0.25, 0.35],
        sa_candidate_betas=sa_candidate_betas or [0.10, 0.15],
        max_combinations=max_combinations,
    )

    configs: list[dict[str, Any]] = []

    for index, params in enumerate(grid, start=1):
        per_run: list[dict[str, Any]] = []
        for seed in study_seeds:
            solver_kwargs = _default_solver_kwargs()
            solver_kwargs["hybrid_due_pressure_threshold"] = params[
                "hybrid_due_pressure_threshold"
            ]
            solver_kwargs["hybrid_candidate_pressure_threshold"] = params[
                "hybrid_candidate_pressure_threshold"
            ]
            solver_kwargs["hybrid_max_ops"] = params["hybrid_max_ops"]
            inner_kwargs = solver_kwargs.get("inner_kwargs", {})
            if isinstance(inner_kwargs, dict):
                inner_kwargs["sa_due_alpha"] = params["sa_due_alpha"]
                inner_kwargs["sa_candidate_beta"] = params["sa_candidate_beta"]

            profiled_kwargs = _apply_lane_profile(
                "RHC-ALNS",
                solver_kwargs,
                lane="strict" if lane == "strict" else "throughput",
                seed=seed,
            )

            raw_result = run_scaling_case(
                n_ops=n_ops,
                n_machines=n_machines,
                n_states=n_states,
                solver_name="rhc-alns",
                solver_kwargs=profiled_kwargs,
                seed=seed,
            )

            per_run.append(
                {
                    "seed": seed,
                    "status": raw_result["status"],
                    "feasible": raw_result["feasible"],
                    "makespan_minutes": float(raw_result["makespan_min"]),
                    "solve_ms": int(raw_result["solve_ms"]),
                    "inner_fallback_ratio": float(
                        raw_result.get("metadata", {}).get("inner_fallback_ratio", 0.0)
                    ),
                }
            )

        makespans = [run["makespan_minutes"] for run in per_run]
        fallback_ratios = [run["inner_fallback_ratio"] for run in per_run]
        feasibility_rate = sum(1 for run in per_run if run["feasible"]) / len(per_run)

        configs.append(
            {
                "config_id": f"cfg_{index:03d}",
                "lane": lane,
                "params": params,
                "runs": per_run,
                "summary": {
                    "seed_count": len(per_run),
                    "feasibility_rate": round(feasibility_rate, 3),
                    "mean_makespan_minutes": round(statistics.mean(makespans), 2),
                    "median_makespan_minutes": round(statistics.median(makespans), 2),
                    "cvar_alpha": cvar_alpha,
                    "cvar_makespan_minutes": round(_tail_cvar(makespans, cvar_alpha), 2),
                    "mean_inner_fallback_ratio": round(statistics.mean(fallback_ratios), 4),
                    "cvar_inner_fallback_ratio": round(
                        _tail_cvar(fallback_ratios, cvar_alpha),
                        4,
                    ),
                    "mean_solve_ms": round(statistics.mean(run["solve_ms"] for run in per_run), 2),
                },
            }
        )

    baseline = next(
        (
            config
            for config in configs
            if config["params"]
            == {
                "hybrid_due_pressure_threshold": 0.35,
                "hybrid_candidate_pressure_threshold": 1.75,
                "hybrid_max_ops": 1500,
                "sa_due_alpha": 0.35,
                "sa_candidate_beta": 0.15,
            }
        ),
        None,
    )
    baseline_makespan = (
        float(baseline["summary"]["mean_makespan_minutes"]) if baseline else None
    )

    for config in configs:
        summary = config["summary"]
        if baseline_makespan is None or baseline_makespan <= 0.0:
            ratio = None
            objective_ok = False
        else:
            ratio = float(summary["mean_makespan_minutes"]) / baseline_makespan
            objective_ok = ratio <= max_makespan_degradation_ratio

        checks = {
            "feasibility": float(summary["feasibility_rate"]) >= 1.0,
            "fallback_ratio": float(summary["mean_inner_fallback_ratio"]) <= max_inner_fallback_ratio,
            "objective_degradation": objective_ok,
        }
        config["quality_gate"] = {
            "objective_degradation_ratio": round(ratio, 4) if ratio is not None else None,
            "max_makespan_degradation_ratio": max_makespan_degradation_ratio,
            "max_inner_fallback_ratio": max_inner_fallback_ratio,
            "checks": checks,
            "passed": all(checks.values()),
        }

    configs.sort(
        key=lambda item: (
            not bool(item["quality_gate"]["passed"]),
            -float(item["summary"]["feasibility_rate"]),
            float(item["summary"]["mean_makespan_minutes"]),
            float(item["summary"]["mean_inner_fallback_ratio"]),
        )
    )

    report = {
        "study_kind": "rhc-alns-doe",
        "lane": lane,
        "n_ops": n_ops,
        "n_machines": n_machines,
        "n_states": n_states,
        "seed_count": len(study_seeds),
        "cvar_alpha": cvar_alpha,
        "max_makespan_degradation_ratio": max_makespan_degradation_ratio,
        "max_inner_fallback_ratio": max_inner_fallback_ratio,
        "baseline_config_id": baseline["config_id"] if baseline else None,
        "config_summaries": configs,
        "top_configs": configs[: min(10, len(configs))],
    }

    artifact_dir = write_dir or Path("benchmark") / "studies" / "rhc_alns_doe"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / "rhc_alns_doe.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact_path"] = str(report_path)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run DOE sweep for RHC-ALNS policy parameters"
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    parser.add_argument("--lane", choices=["throughput", "strict"], default="throughput")
    parser.add_argument("--n-ops", type=int, default=10_000)
    parser.add_argument("--n-machines", type=int, default=50)
    parser.add_argument("--n-states", type=int, default=15)
    parser.add_argument("--cvar-alpha", type=float, default=0.95)
    parser.add_argument("--max-combinations", type=int, default=24)
    parser.add_argument("--write-dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = run_rhc_alns_doe(
        seeds=args.seeds,
        lane=args.lane,
        n_ops=args.n_ops,
        n_machines=args.n_machines,
        n_states=args.n_states,
        cvar_alpha=args.cvar_alpha,
        max_combinations=args.max_combinations,
        write_dir=args.write_dir,
    )
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
