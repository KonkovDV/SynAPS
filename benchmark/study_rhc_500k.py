"""Reproducible scaling study up to 500K+ operations for RHC solvers.

This harness extends the 50K study with:
- staged scale ladder (default: 50k -> 100k -> 200k -> 300k -> 500k)
- resource projection and admission gate before expensive runs
- robust statistics (mean, median, IQR, CVaR)
- per-configuration quality gate for feasibility, fallback pressure, and objective drift

It is designed for scientific benchmarking and safe industrial stress-testing.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from benchmark.study_rhc_50k import _apply_lane_profile, _summarize_inner_windows
from synaps.model import (
    MAX_SCHEDULE_OPERATIONS,
    MAX_SCHEDULE_ORDERS,
    MAX_SCHEDULE_SETUP_ENTRIES,
    MAX_SCHEDULE_WORK_CENTERS,
)
from synaps.benchmarks.run_scaling_benchmark import run_benchmark as run_scaling_case

LaneMode = Literal["throughput", "strict", "both"]
ExecutionMode = Literal["plan", "gated", "full"]
QualityGateProfile = Literal["balanced", "feasibility-first"]


def _tail_cvar(values: list[float], alpha: float) -> float:
    """Compute empirical CVaR_alpha (tail mean beyond VaR_alpha)."""

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


def _iqr(values: list[float]) -> float:
    """Compute interquartile range with inclusive quantiles."""

    if len(values) < 2:
        return 0.0
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return float(max(0.0, quartiles[2] - quartiles[0]))


def _default_solver_specs() -> dict[str, dict[str, Any]]:
    """Default benchmark specs aligned with the 50K harness."""

    return {
        "RHC-GREEDY": {
            "solver_name": "rhc-greedy",
            "solver_kwargs": {
                "window_minutes": 480,
                "overlap_minutes": 60,
                "inner_solver": "greedy",
                "time_limit_s": 600,
                "max_ops_per_window": 10_000,
            },
        },
        "RHC-ALNS": {
            "solver_name": "rhc-alns",
            "solver_kwargs": {
                "window_minutes": 480,
                "overlap_minutes": 120,
                "inner_solver": "alns",
                "time_limit_s": 1_200,
                "alns_inner_window_time_cap_s": 180,
                "max_ops_per_window": 5_000,
                "progressive_admission_relaxation_enabled": True,
                "precedence_ready_candidate_filter_enabled": True,
                "due_admission_horizon_factor": 2.0,
                "admission_relaxation_min_fill_ratio": 0.30,
                "admission_full_scan_enabled": False,
                "alns_budget_auto_scaling_enabled": True,
                "alns_budget_estimated_repair_s_per_destroyed_op": 0.125,
                "hybrid_inner_routing_enabled": False,
                "hybrid_inner_solver": "cpsat",
                "hybrid_due_pressure_threshold": 0.35,
                "hybrid_candidate_pressure_threshold": 4.0,
                "hybrid_max_ops": 1_500,
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
                    "use_cpsat_repair": False,
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
            },
        },
    }


def _topology_for_scale(
    n_ops: int,
    *,
    ops_per_machine_target: int,
    min_machines: int,
    max_machines: int,
    base_states: int,
    state_growth_power: float,
) -> dict[str, int]:
    """Compute machine/state topology for a given operation scale."""

    target = max(1, ops_per_machine_target)
    machine_estimate = int(round(n_ops / target))
    n_machines = min(max_machines, max(min_machines, machine_estimate))

    if state_growth_power <= 0.0:
        n_states = max(2, base_states)
    else:
        growth = (n_ops / 50_000.0) ** state_growth_power
        n_states = max(2, int(round(base_states * growth)))

    return {
        "n_ops": n_ops,
        "n_machines": n_machines,
        "n_states": n_states,
    }


def _estimate_instance_footprint(
    *,
    n_ops: int,
    n_machines: int,
    n_states: int,
    machine_flexibility: float,
    setup_density: float,
    ops_per_order: int,
    setup_entry_overhead_bytes: int,
    eligible_ref_bytes: int,
    operation_model_bytes: int,
    order_model_bytes: int,
    working_set_multiplier: float,
) -> dict[str, Any]:
    """Estimate memory-sensitive dimensions before materializing a huge instance.

    The estimates are intentionally conservative and used only for a safety gate.
    """

    eligible_per_operation = max(1, int(round(n_machines * machine_flexibility)))
    expected_setup_entries = int(
        round(n_machines * n_states * max(n_states - 1, 0) * setup_density)
    )
    n_orders = max(1, math.ceil(n_ops / max(1, ops_per_order)))

    sdst_dense_bytes = int(n_machines * n_states * n_states * 12)
    setup_entries_bytes = int(expected_setup_entries * setup_entry_overhead_bytes)
    eligible_links = n_ops * eligible_per_operation
    eligible_links_bytes = int(eligible_links * eligible_ref_bytes)
    operation_objects_bytes = int(n_ops * operation_model_bytes)
    order_objects_bytes = int(n_orders * order_model_bytes)

    projected_bytes = (
        sdst_dense_bytes
        + setup_entries_bytes
        + eligible_links_bytes
        + operation_objects_bytes
        + order_objects_bytes
    )
    projected_working_set_bytes = int(projected_bytes * max(1.0, working_set_multiplier))

    def to_gb(num_bytes: int) -> float:
        return round(num_bytes / (1024**3), 3)

    return {
        "eligible_per_operation": eligible_per_operation,
        "eligible_links": eligible_links,
        "expected_setup_entries": expected_setup_entries,
        "n_orders": n_orders,
        "sdst_dense_gb": to_gb(sdst_dense_bytes),
        "setup_entries_gb": to_gb(setup_entries_bytes),
        "eligible_links_gb": to_gb(eligible_links_bytes),
        "operation_objects_gb": to_gb(operation_objects_bytes),
        "order_objects_gb": to_gb(order_objects_bytes),
        "estimated_model_gb": to_gb(projected_bytes),
        "estimated_working_set_gb": to_gb(projected_working_set_bytes),
    }


def _resource_gate(
    projection: dict[str, Any],
    *,
    n_ops: int,
    n_orders: int,
    n_machines: int,
    expected_setup_entries: int,
    max_estimated_memory_gb: float,
    max_setup_entries: int,
    max_eligible_links: int,
) -> dict[str, Any]:
    """Apply hard admission guard for expensive scales."""

    reasons: list[str] = []
    if float(projection.get("estimated_working_set_gb", 0.0)) > max_estimated_memory_gb:
        reasons.append("estimated_working_set_exceeds_limit")
    if int(projection.get("expected_setup_entries", 0)) > max_setup_entries:
        reasons.append("setup_entries_exceed_limit")
    if int(projection.get("eligible_links", 0)) > max_eligible_links:
        reasons.append("eligible_links_exceed_limit")

    if n_ops > MAX_SCHEDULE_OPERATIONS:
        reasons.append("operations_exceed_model_limit")
    if n_orders > MAX_SCHEDULE_ORDERS:
        reasons.append("orders_exceed_model_limit")
    if n_machines > MAX_SCHEDULE_WORK_CENTERS:
        reasons.append("work_centers_exceed_model_limit")
    if expected_setup_entries > MAX_SCHEDULE_SETUP_ENTRIES:
        reasons.append("setup_entries_exceed_model_schema_limit")

    return {
        "allowed": not reasons,
        "reasons": reasons,
        "limits": {
            "max_estimated_memory_gb": max_estimated_memory_gb,
            "max_setup_entries": max_setup_entries,
            "max_eligible_links": max_eligible_links,
        },
        "model_limits": {
            "max_operations": MAX_SCHEDULE_OPERATIONS,
            "max_orders": MAX_SCHEDULE_ORDERS,
            "max_work_centers": MAX_SCHEDULE_WORK_CENTERS,
            "max_setup_entries": MAX_SCHEDULE_SETUP_ENTRIES,
        },
    }


def _scale_solver_kwargs(
    solver_name: str,
    base_kwargs: dict[str, Any],
    *,
    n_ops: int,
    base_ops: int,
    time_limit_growth_power: float,
    max_window_growth_power: float,
    max_window_cap: int,
    time_limit_cap_s: int | None,
) -> dict[str, Any]:
    """Scale time/window controls from base profile to larger instances."""

    scaled = deepcopy(base_kwargs)
    ratio = max(1.0, n_ops / max(1, base_ops))

    base_time_limit = float(base_kwargs.get("time_limit_s", 600))
    scaled_time_limit = int(round(base_time_limit * (ratio ** time_limit_growth_power)))
    scaled["time_limit_s"] = max(60, scaled_time_limit)
    if time_limit_cap_s is not None:
        scaled["time_limit_s"] = max(60, min(int(time_limit_cap_s), scaled["time_limit_s"]))

    if "max_ops_per_window" in base_kwargs:
        base_window_cap = int(base_kwargs["max_ops_per_window"])
        scaled_window_cap = int(round(base_window_cap * (ratio ** max_window_growth_power)))
        scaled["max_ops_per_window"] = max(1000, min(max_window_cap, scaled_window_cap))

    if solver_name == "RHC-ALNS":
        # The 100K+ staged harness needs a narrower first-window geometry than the
        # 50K public profile; otherwise ALNS can burn the full budget constructing
        # the initial seed before search begins.
        if ratio >= 2.0:
            scaled["window_minutes"] = min(int(scaled.get("window_minutes", 480)), 300)
            scaled["overlap_minutes"] = min(int(scaled.get("overlap_minutes", 120)), 90)

        inner_kwargs = scaled.get("inner_kwargs")
        if isinstance(inner_kwargs, dict):
            # Keep ALNS iteration budget bounded to avoid quadratic explosion per window.
            max_iterations = int(inner_kwargs.get("max_iterations", 100))
            inner_kwargs["max_iterations"] = min(180, max_iterations)

        # Relax ALNS pre-search guard as scale grows to avoid permanent "not_run_budget_guard"
        # behavior on 100k+ instances while preserving conservative lower bounds.
        base_guard_ops = int(base_kwargs.get("alns_presearch_max_window_ops", 1000))
        base_guard_time_s = float(base_kwargs.get("alns_presearch_min_time_limit_s", 240.0))
        scaled_window_cap = int(scaled.get("max_ops_per_window", base_guard_ops))

        guard_from_ratio = int(round(base_guard_ops * (ratio ** 0.35)))
        guard_from_window_cap = int(round(scaled_window_cap * 0.5))
        effective_guard_ops = max(base_guard_ops, guard_from_ratio, guard_from_window_cap)
        scaled["alns_presearch_max_window_ops"] = min(scaled_window_cap, effective_guard_ops)

        effective_guard_time_s = max(30.0, base_guard_time_s * (ratio ** -0.35))
        scaled["alns_presearch_min_time_limit_s"] = round(
            min(base_guard_time_s, effective_guard_time_s),
            2,
        )
        scaled["alns_presearch_budget_guard_enabled"] = bool(
            scaled.get("alns_presearch_budget_guard_enabled", True)
        )

    return scaled


def _summarize_runs(runs: list[dict[str, Any]], *, cvar_alpha: float) -> dict[str, Any]:
    """Summarize a configuration run group with robust metrics."""

    run_count = len(runs)
    failures = [run for run in runs if run.get("error")]
    completed = [run for run in runs if not run.get("error")]

    summary: dict[str, Any] = {
        "run_count": run_count,
        "error_count": len(failures),
        "error_rate": round(len(failures) / max(1, run_count), 4),
    }

    if not completed:
        summary["status"] = "no_successful_runs"
        return summary

    feasible_flags = [bool(run["results"]["feasible"]) for run in completed]
    makespans = [float(run["results"]["makespan_minutes"]) for run in completed]
    wall_time_s = [float(run["results"]["solve_ms"]) / 1000.0 for run in completed]
    assigned_ops = [int(run["results"]["assigned_ops"]) for run in completed]
    total_ops = [int(run["results"]["n_ops"]) for run in completed]
    scheduled_ratios = [
        assigned / max(1, n_ops)
        for assigned, n_ops in zip(assigned_ops, total_ops, strict=True)
    ]
    throughput_ops_s = [
        assigned / max(1e-9, solve_s)
        for assigned, solve_s in zip(assigned_ops, wall_time_s, strict=True)
    ]

    fallback_ratios = [
        float(run["results"]["inner_fallback_ratio"])
        for run in completed
        if (
            "inner_fallback_ratio" in run["results"]
            and run["results"]["inner_fallback_ratio"] is not None
        )
    ]
    flattened_inner_window_summaries: list[dict[str, Any]] = []
    for run in completed:
        solver_metadata = run.get("solver_metadata", {})
        inner_window_summaries = solver_metadata.get("inner_window_summaries")
        if isinstance(inner_window_summaries, list):
            for summary_entry in inner_window_summaries:
                if isinstance(summary_entry, dict):
                    flattened_inner_window_summaries.append(summary_entry)

    summary.update(
        {
            "status": "ok",
            "feasibility_rate": round(
                sum(1 for flag in feasible_flags if flag) / len(feasible_flags),
                4,
            ),
            "mean_makespan_minutes": round(statistics.mean(makespans), 2),
            "median_makespan_minutes": round(statistics.median(makespans), 2),
            "iqr_makespan_minutes": round(_iqr(makespans), 2),
            "cvar_makespan_minutes": round(_tail_cvar(makespans, cvar_alpha), 2),
            "mean_wall_time_s": round(statistics.mean(wall_time_s), 3),
            "median_wall_time_s": round(statistics.median(wall_time_s), 3),
            "iqr_wall_time_s": round(_iqr(wall_time_s), 3),
            "cvar_wall_time_s": round(_tail_cvar(wall_time_s, cvar_alpha), 3),
            "mean_scheduled_ratio": round(statistics.mean(scheduled_ratios), 4),
            "cvar_unscheduled_ratio": round(
                _tail_cvar([1.0 - value for value in scheduled_ratios], cvar_alpha),
                4,
            ),
            "mean_throughput_ops_per_s": round(statistics.mean(throughput_ops_s), 3),
        }
    )

    if fallback_ratios:
        summary["mean_inner_fallback_ratio"] = round(statistics.mean(fallback_ratios), 4)
        summary["cvar_inner_fallback_ratio"] = round(
            _tail_cvar(fallback_ratios, cvar_alpha),
            4,
        )

    summary["inner_window_summary"] = _summarize_inner_windows(
        flattened_inner_window_summaries
    )

    return summary


def _evaluate_quality_gate(
    *,
    summaries: dict[str, dict[str, Any]],
    baseline_solver: str,
    min_scheduled_ratio: float,
    max_inner_fallback_ratio: float,
    max_makespan_degradation_ratio: float,
    profile: QualityGateProfile,
) -> dict[str, dict[str, Any]]:
    """Evaluate quality gate per solver|lane|scale key."""

    result: dict[str, dict[str, Any]] = {}
    required_checks = ["summary_ok", "feasibility", "scheduled_ratio", "fallback_ratio"]
    if profile == "balanced":
        required_checks.append("objective_degradation")

    for key, summary in summaries.items():
        solver_name, lane, scale_str = key.split("|")
        baseline_key = f"{baseline_solver}|{lane}|{scale_str}"
        baseline_summary = summaries.get(baseline_key)

        if solver_name == baseline_solver:
            degradation_ratio = 1.0
            objective_ok = True
        elif (
            baseline_summary
            and baseline_summary.get("status") == "ok"
            and float(baseline_summary.get("mean_makespan_minutes", 0.0)) > 0.0
            and summary.get("status") == "ok"
        ):
            baseline_mk = float(baseline_summary["mean_makespan_minutes"])
            current_mk = float(summary["mean_makespan_minutes"])
            degradation_ratio = current_mk / baseline_mk
            objective_ok = degradation_ratio <= max_makespan_degradation_ratio
        else:
            degradation_ratio = float("inf")
            objective_ok = False

        checks = {
            "summary_ok": summary.get("status") == "ok",
            "feasibility": float(summary.get("feasibility_rate", 0.0)) >= 1.0,
            "scheduled_ratio": (
                float(summary.get("mean_scheduled_ratio", 0.0))
                >= min_scheduled_ratio
            ),
            "fallback_ratio": (
                True
                if "mean_inner_fallback_ratio" not in summary
                else float(summary.get("mean_inner_fallback_ratio", 0.0))
                <= max_inner_fallback_ratio
            ),
            "objective_degradation": objective_ok,
        }

        result[key] = {
            "baseline_key": baseline_key,
            "profile": profile,
            "objective_degradation_ratio": round(degradation_ratio, 4)
            if math.isfinite(degradation_ratio)
            else None,
            "thresholds": {
                "min_scheduled_ratio": min_scheduled_ratio,
                "max_inner_fallback_ratio": max_inner_fallback_ratio,
                "max_makespan_degradation_ratio": max_makespan_degradation_ratio,
            },
            "checks": checks,
            "required_checks": required_checks,
            "passed": all(checks[name] for name in required_checks),
        }

    return result


def study_rhc_500k(
    *,
    scales: list[int] | None = None,
    seeds: list[int] | None = None,
    solver_names: list[str] | None = None,
    lane: LaneMode = "both",
    execution_mode: ExecutionMode = "gated",
    write_dir: Path | None = None,
    cvar_alpha: float = 0.95,
    quality_gate_baseline_solver: str = "RHC-GREEDY",
    quality_gate_profile: QualityGateProfile = "balanced",
    min_scheduled_ratio: float = 0.90,
    max_inner_fallback_ratio: float = 0.20,
    max_makespan_degradation_ratio: float = 1.10,
    ops_per_machine_target: int = 500,
    min_machines: int = 100,
    max_machines: int = 1_000,
    base_states: int = 20,
    state_growth_power: float = 0.0,
    machine_flexibility: float = 0.10,
    setup_density: float = 0.50,
    ops_per_order: int = 5,
    max_estimated_memory_gb: float = 64.0,
    max_setup_entries: int = 25_000_000,
    max_eligible_links: int = 60_000_000,
    setup_entry_overhead_bytes: int = 192,
    eligible_ref_bytes: int = 16,
    operation_model_bytes: int = 512,
    order_model_bytes: int = 256,
    working_set_multiplier: float = 1.6,
    time_limit_growth_power: float = 0.5,
    max_window_growth_power: float = 0.35,
    max_window_cap: int = 25_000,
    time_limit_cap_s: int | None = None,
    max_windows_override: int | None = None,
) -> dict[str, Any]:
    """Run staged RHC benchmark up to 500K+ operations with safety gating."""

    study_scales = scales or [50_000, 100_000, 200_000, 300_000, 500_000]
    study_seeds = seeds or [1]
    requested_solver_names = solver_names or ["RHC-GREEDY", "RHC-ALNS"]
    lane_profiles: list[Literal["throughput", "strict"]] = (
        ["throughput", "strict"] if lane == "both" else [lane]
    )

    solver_specs = _default_solver_specs()
    unknown_solvers = [name for name in requested_solver_names if name not in solver_specs]
    if unknown_solvers:
        raise ValueError(f"Unsupported solver labels: {unknown_solvers}")

    artifact_dir = write_dir or Path("benchmark") / "studies" / "rhc_500k"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    grouped_runs: dict[str, list[dict[str, Any]]] = {}
    scale_records: list[dict[str, Any]] = []

    for scale in study_scales:
        topology = _topology_for_scale(
            scale,
            ops_per_machine_target=ops_per_machine_target,
            min_machines=min_machines,
            max_machines=max_machines,
            base_states=base_states,
            state_growth_power=state_growth_power,
        )

        projection = _estimate_instance_footprint(
            n_ops=topology["n_ops"],
            n_machines=topology["n_machines"],
            n_states=topology["n_states"],
            machine_flexibility=machine_flexibility,
            setup_density=setup_density,
            ops_per_order=ops_per_order,
            setup_entry_overhead_bytes=setup_entry_overhead_bytes,
            eligible_ref_bytes=eligible_ref_bytes,
            operation_model_bytes=operation_model_bytes,
            order_model_bytes=order_model_bytes,
            working_set_multiplier=working_set_multiplier,
        )
        gate = _resource_gate(
            projection,
            n_ops=topology["n_ops"],
            n_orders=int(projection.get("n_orders", 0)),
            n_machines=topology["n_machines"],
            expected_setup_entries=int(projection.get("expected_setup_entries", 0)),
            max_estimated_memory_gb=max_estimated_memory_gb,
            max_setup_entries=max_setup_entries,
            max_eligible_links=max_eligible_links,
        )

        scale_record: dict[str, Any] = {
            "scale": scale,
            "topology": topology,
            "projection": projection,
            "resource_gate": gate,
            "runs": [],
        }

        should_execute = execution_mode == "full" or (
            execution_mode == "gated" and gate["allowed"]
        )

        if execution_mode == "plan" or not should_execute:
            scale_record["execution"] = "skipped"
            if execution_mode != "plan":
                scale_record["skip_reason"] = "resource_gate"
            scale_records.append(scale_record)
            continue

        for lane_name in lane_profiles:
            for solver_label in requested_solver_names:
                spec = solver_specs[solver_label]
                scaled_kwargs = _scale_solver_kwargs(
                    solver_label,
                    spec["solver_kwargs"],
                    n_ops=topology["n_ops"],
                    base_ops=50_000,
                    time_limit_growth_power=time_limit_growth_power,
                    max_window_growth_power=max_window_growth_power,
                    max_window_cap=max_window_cap,
                    time_limit_cap_s=time_limit_cap_s,
                )

                for seed in study_seeds:
                    profiled_kwargs = _apply_lane_profile(
                        solver_label,
                        scaled_kwargs,
                        lane=lane_name,
                        seed=seed,
                    )
                    if max_windows_override is not None:
                        profiled_kwargs["max_windows"] = int(max_windows_override)

                    run_record: dict[str, Any] = {
                        "scale": scale,
                        "lane": lane_name,
                        "solver_label": solver_label,
                        "solver_name": spec["solver_name"],
                        "seed": seed,
                    }
                    try:
                        raw = run_scaling_case(
                            n_ops=topology["n_ops"],
                            n_machines=topology["n_machines"],
                            n_states=topology["n_states"],
                            solver_name=spec["solver_name"],
                            solver_kwargs=profiled_kwargs,
                            seed=seed,
                        )
                        metadata = raw.get("metadata", {})
                        run_record["solver_metadata"] = (
                            metadata if isinstance(metadata, dict) else {}
                        )
                        run_record["results"] = {
                            "status": raw.get("status"),
                            "feasible": bool(raw.get("feasible", False)),
                            "violations": int(raw.get("violations", 0)),
                            "makespan_minutes": float(raw.get("makespan_min", 0.0)),
                            "total_setup_minutes": float(raw.get("total_setup_min", 0.0)),
                            "total_tardiness_minutes": float(raw.get("total_tardiness_min", 0.0)),
                            "assigned_ops": int(raw.get("assigned_ops", 0)),
                            "n_ops": int(raw.get("n_ops", topology["n_ops"])),
                            "solve_ms": int(raw.get("solve_ms", 0)),
                            "acceleration": (
                                metadata.get("acceleration")
                                if isinstance(metadata.get("acceleration"), dict)
                                else None
                            ),
                            "inner_fallback_ratio": (
                                float(metadata.get("inner_fallback_ratio", 0.0))
                                if "inner_fallback_ratio" in metadata
                                else None
                            ),
                        }
                    except Exception as exc:  # pragma: no cover - runtime harness protection
                        run_record["error"] = str(exc)

                    scale_record["runs"].append(run_record)
                    key = f"{solver_label}|{lane_name}|{scale}"
                    grouped_runs.setdefault(key, []).append(run_record)

        scale_record["execution"] = "executed"
        scale_records.append(scale_record)

    summary_by_config = {
        key: _summarize_runs(runs, cvar_alpha=cvar_alpha)
        for key, runs in grouped_runs.items()
    }

    quality_gate = _evaluate_quality_gate(
        summaries=summary_by_config,
        baseline_solver=quality_gate_baseline_solver,
        min_scheduled_ratio=min_scheduled_ratio,
        max_inner_fallback_ratio=max_inner_fallback_ratio,
        max_makespan_degradation_ratio=max_makespan_degradation_ratio,
        profile=quality_gate_profile,
    )

    report = {
        "study_kind": "rhc-500k",
        "execution_mode": execution_mode,
        "lane_mode": lane,
        "scales": study_scales,
        "requested_solver_names": requested_solver_names,
        "seed_count": len(study_seeds),
        "cvar_alpha": cvar_alpha,
        "scale_records": scale_records,
        "summary_by_config": summary_by_config,
        "quality_gate": {
            "baseline_solver": quality_gate_baseline_solver,
            "profile": quality_gate_profile,
            "results": quality_gate,
        },
        "resource_gate_defaults": {
            "max_estimated_memory_gb": max_estimated_memory_gb,
            "max_setup_entries": max_setup_entries,
            "max_eligible_links": max_eligible_links,
        },
    }

    report_path = artifact_dir / "rhc_500k_study.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact_path"] = str(report_path)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run staged RHC stress-study up to 500K+ operations"
    )
    parser.add_argument(
        "--scales",
        nargs="+",
        type=int,
        default=[50_000, 100_000, 200_000, 300_000, 500_000],
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--solvers", nargs="+", default=["RHC-GREEDY", "RHC-ALNS"])
    parser.add_argument("--lane", choices=["throughput", "strict", "both"], default="both")
    parser.add_argument("--execution-mode", choices=["plan", "gated", "full"], default="gated")
    parser.add_argument("--write-dir", type=Path)
    parser.add_argument("--cvar-alpha", type=float, default=0.95)
    parser.add_argument("--quality-gate-baseline", default="RHC-GREEDY")
    parser.add_argument(
        "--quality-gate-profile",
        choices=["balanced", "feasibility-first"],
        default="balanced",
    )
    parser.add_argument("--min-scheduled-ratio", type=float, default=0.90)
    parser.add_argument("--max-inner-fallback-ratio", type=float, default=0.20)
    parser.add_argument("--max-makespan-degradation-ratio", type=float, default=1.10)

    parser.add_argument("--ops-per-machine-target", type=int, default=500)
    parser.add_argument("--min-machines", type=int, default=100)
    parser.add_argument("--max-machines", type=int, default=1_000)
    parser.add_argument("--base-states", type=int, default=20)
    parser.add_argument("--state-growth-power", type=float, default=0.0)

    parser.add_argument("--machine-flexibility", type=float, default=0.10)
    parser.add_argument("--setup-density", type=float, default=0.50)
    parser.add_argument("--ops-per-order", type=int, default=5)

    parser.add_argument("--max-estimated-memory-gb", type=float, default=64.0)
    parser.add_argument("--max-setup-entries", type=int, default=25_000_000)
    parser.add_argument("--max-eligible-links", type=int, default=60_000_000)
    parser.add_argument("--setup-entry-overhead-bytes", type=int, default=192)
    parser.add_argument("--eligible-ref-bytes", type=int, default=16)
    parser.add_argument("--operation-model-bytes", type=int, default=512)
    parser.add_argument("--order-model-bytes", type=int, default=256)
    parser.add_argument("--working-set-multiplier", type=float, default=1.6)

    parser.add_argument("--time-limit-growth-power", type=float, default=0.5)
    parser.add_argument("--max-window-growth-power", type=float, default=0.35)
    parser.add_argument("--max-window-cap", type=int, default=25_000)
    parser.add_argument("--time-limit-cap-s", type=int)
    parser.add_argument("--max-windows-override", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = study_rhc_500k(
        scales=args.scales,
        seeds=args.seeds,
        solver_names=args.solvers,
        lane=args.lane,
        execution_mode=args.execution_mode,
        write_dir=args.write_dir,
        cvar_alpha=args.cvar_alpha,
        quality_gate_baseline_solver=args.quality_gate_baseline,
        quality_gate_profile=args.quality_gate_profile,
        min_scheduled_ratio=args.min_scheduled_ratio,
        max_inner_fallback_ratio=args.max_inner_fallback_ratio,
        max_makespan_degradation_ratio=args.max_makespan_degradation_ratio,
        ops_per_machine_target=args.ops_per_machine_target,
        min_machines=args.min_machines,
        max_machines=args.max_machines,
        base_states=args.base_states,
        state_growth_power=args.state_growth_power,
        machine_flexibility=args.machine_flexibility,
        setup_density=args.setup_density,
        ops_per_order=args.ops_per_order,
        max_estimated_memory_gb=args.max_estimated_memory_gb,
        max_setup_entries=args.max_setup_entries,
        max_eligible_links=args.max_eligible_links,
        setup_entry_overhead_bytes=args.setup_entry_overhead_bytes,
        eligible_ref_bytes=args.eligible_ref_bytes,
        operation_model_bytes=args.operation_model_bytes,
        order_model_bytes=args.order_model_bytes,
        working_set_multiplier=args.working_set_multiplier,
        time_limit_growth_power=args.time_limit_growth_power,
        max_window_growth_power=args.max_window_growth_power,
        max_window_cap=args.max_window_cap,
        time_limit_cap_s=args.time_limit_cap_s,
        max_windows_override=args.max_windows_override,
    )
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
