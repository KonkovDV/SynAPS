"""Reproducible 50K benchmark study for the RHC large-instance path.

This study materializes deterministic benchmark instances, runs the public
benchmark harness for `RHC-GREEDY` and `RHC-ALNS`, and writes an artifact JSON
under `benchmark/` so large-instance evidence is preserved alongside the code.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from benchmark.generate_instances import preset_spec, write_problem_instance
from benchmark.run_benchmark import run_benchmark
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.benchmarks.run_scaling_benchmark import run_benchmark as run_scaling_case
from synaps.solvers.rhc_solver import RhcSolver
from synaps.solvers.sdst_matrix import SdstMatrix
from synaps.validation import verify_schedule_result

LaneMode = Literal["throughput", "strict", "both"]


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


def _apply_lane_profile(
    solver_name: str,
    solver_kwargs: dict[str, Any],
    *,
    lane: Literal["throughput", "strict"],
    seed: int,
) -> dict[str, Any]:
    """Apply reproducibility lane profile to solver kwargs."""

    profiled = deepcopy(solver_kwargs)
    if solver_name in {"RHC-ALNS", "RHC-ALNS-REFINE"}:
        # Fix top-level random stream so window-level deterministic offsets are stable.
        profiled.setdefault("random_seed", seed)
        inner_kwargs = profiled.setdefault("inner_kwargs", {})
        if isinstance(inner_kwargs, dict):
            inner_kwargs.setdefault("random_seed", seed)

        hybrid_kwargs = profiled.setdefault("hybrid_inner_kwargs", {})
        if isinstance(hybrid_kwargs, dict):
            hybrid_kwargs.setdefault("random_seed", seed)
            hybrid_kwargs["num_workers"] = 1 if lane == "strict" else 4

    return profiled


def _classify_solve_outcome(status: Any, *, feasible: bool) -> str:
    """Normalize solver status into a stable study-level outcome taxonomy."""

    status_text = str(status).strip().lower()
    if feasible or status_text in {"optimal", "feasible"}:
        return "completed"
    if status_text in {"timeout", "timed_out"}:
        return "solver_timeout"
    if status_text in {"cancelled", "canceled"}:
        return "solver_cancelled"
    if status_text in {"infeasible", "error", "not_run"}:
        return "solver_error"
    return "solver_error"


def _build_study_evidence(
    *,
    records: list[dict[str, Any]],
    summary_snapshot: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build a compact evidence section for reproducibility and publication rails."""

    process_outcomes: set[str] = set()
    solve_outcomes: set[str] = set()

    for record in records:
        for comparison in record.get("comparisons", []):
            process_outcomes.add(
                str(
                    comparison.get(
                        "process_outcome",
                        comparison.get("results", {}).get("process_outcome", "completed"),
                    )
                )
            )
            solve_outcomes.add(
                str(
                    comparison.get(
                        "solve_outcome",
                        comparison.get("results", {}).get("solve_outcome", "solver_error"),
                    )
                )
            )

    lane_outcome_summary: dict[str, dict[str, Any]] = {}
    for key, summary in summary_snapshot.items():
        lane_outcome_summary[key] = {
            "instance_count": int(summary.get("instance_count", 0)),
            "process_completed_count": int(summary.get("process_completed_count", 0)),
            "process_completed_rate": float(summary.get("process_completed_rate", 0.0)),
            "solve_completed_count": int(summary.get("solve_completed_count", 0)),
            "solve_completed_rate": float(summary.get("solve_completed_rate", 0.0)),
            "solver_timeout_count": int(summary.get("solver_timeout_count", 0)),
            "solver_cancelled_count": int(summary.get("solver_cancelled_count", 0)),
            "solver_error_count": int(summary.get("solver_error_count", 0)),
        }

    return {
        "outcome_taxonomy": {
            "version": "rhc-50k-v1",
            "process_outcomes": sorted(process_outcomes),
            "solve_outcomes": sorted(solve_outcomes),
        },
        "lane_outcome_summary": lane_outcome_summary,
    }


def _run_two_phase_refinement_case(
    *,
    n_ops: int,
    n_machines: int,
    n_states: int,
    seed: int,
    baseline_solver_name: str,
    baseline_solver_kwargs: dict[str, Any],
    refinement_solver_name: str,
    refinement_solver_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Run a greedy RHC baseline pass, then warm-start an ALNS refinement pass."""

    t_gen = time.monotonic()
    problem = generate_large_instance(
        n_operations=n_ops,
        n_machines=n_machines,
        n_states=n_states,
        setup_density=0.5,
        seed=seed,
    )
    gen_ms = int((time.monotonic() - t_gen) * 1000)

    sdst = SdstMatrix.from_problem(problem)

    baseline_solver = RhcSolver()
    t_baseline = time.monotonic()
    baseline_result = baseline_solver.solve(problem, **deepcopy(baseline_solver_kwargs))
    baseline_solve_ms = int((time.monotonic() - t_baseline) * 1000)

    refinement_kwargs = deepcopy(refinement_solver_kwargs)
    refinement_kwargs["warm_start_assignments"] = list(baseline_result.assignments)

    refinement_solver = RhcSolver()
    t_refinement = time.monotonic()
    result = refinement_solver.solve(problem, **refinement_kwargs)
    refinement_solve_ms = int((time.monotonic() - t_refinement) * 1000)

    t_verify = time.monotonic()
    verification = verify_schedule_result(problem, result)
    verify_ms = int((time.monotonic() - t_verify) * 1000)

    metadata = dict(result.metadata)
    metadata.update(
        {
            "two_phase_refinement_enabled": True,
            "two_phase_baseline_solver": baseline_solver_name,
            "two_phase_baseline_status": str(baseline_result.status),
            "two_phase_baseline_assigned_ops": len(baseline_result.assignments),
            "two_phase_baseline_makespan_min": round(
                baseline_result.objective.makespan_minutes,
                2,
            ),
            "two_phase_baseline_solve_ms": baseline_solve_ms,
            "two_phase_refinement_solve_ms": refinement_solve_ms,
            "two_phase_assignment_delta": len(result.assignments)
            - len(baseline_result.assignments),
            "two_phase_makespan_improvement_min": round(
                baseline_result.objective.makespan_minutes
                - result.objective.makespan_minutes,
                2,
            ),
        }
    )

    return {
        "n_ops": n_ops,
        "n_machines": n_machines,
        "n_states": n_states,
        "solver": refinement_solver_name,
        "status": str(result.status),
        "feasible": verification.feasible,
        "violations": verification.violation_count,
        "makespan_min": round(result.objective.makespan_minutes, 2),
        "total_setup_min": round(result.objective.total_setup_minutes, 2),
        "total_tardiness_min": round(result.objective.total_tardiness_minutes, 2),
        "total_material_loss": round(result.objective.total_material_loss, 2),
        "assigned_ops": len(result.assignments),
        "solve_ms": baseline_solve_ms + refinement_solve_ms,
        "gen_ms": gen_ms,
        "verify_ms": verify_ms,
        "sdst_memory_bytes": sdst.memory_bytes(),
        "metadata": metadata,
    }


def _evaluate_quality_gate(
    *,
    summaries: dict[str, dict[str, Any]],
    baseline_solver: str,
    min_scheduled_ratio: float,
    max_makespan_degradation_ratio: float,
    max_inner_fallback_ratio: float,
) -> dict[str, dict[str, Any]]:
    """Evaluate multi-criterion quality gate per solver summary."""

    results: dict[str, dict[str, Any]] = {}
    for key, summary in summaries.items():
        solver_name, _, lane_suffix = key.partition("|")
        baseline_key = (
            f"{baseline_solver}|{lane_suffix}"
            if lane_suffix
            else baseline_solver
        )
        baseline_summary = summaries.get(baseline_key)
        baseline_makespan = (
            float(baseline_summary.get("mean_makespan_minutes", 0.0))
            if baseline_summary
            else 0.0
        )
        current_makespan = float(summary.get("mean_makespan_minutes", 0.0))

        if solver_name == baseline_solver:
            objective_ratio = 1.0
            objective_ok = True
        elif baseline_makespan > 0.0:
            objective_ratio = current_makespan / baseline_makespan
            objective_ok = objective_ratio <= max_makespan_degradation_ratio
        else:
            objective_ratio = float("inf")
            objective_ok = False

        fallback_ratio = float(summary.get("mean_inner_fallback_ratio", 0.0))
        fallback_ok = (
            True
            if "mean_inner_fallback_ratio" not in summary
            else fallback_ratio <= max_inner_fallback_ratio
        )
        feasibility_ok = float(summary.get("feasibility_rate", 0.0)) >= 1.0

        checks = {
            "feasibility": feasibility_ok,
            "scheduled_ratio": (
                float(summary.get("mean_scheduled_ratio", 0.0))
                >= min_scheduled_ratio
            ),
            "fallback_ratio": fallback_ok,
            "objective_degradation": objective_ok,
        }

        results[key] = {
            "baseline_key": baseline_key,
            "objective_degradation_ratio": round(objective_ratio, 4)
            if math.isfinite(objective_ratio)
            else None,
            "min_scheduled_ratio": min_scheduled_ratio,
            "max_makespan_degradation_ratio": max_makespan_degradation_ratio,
            "max_inner_fallback_ratio": max_inner_fallback_ratio,
            "checks": checks,
            "passed": all(checks.values()),
        }

    return results


def study_rhc_50k(
    *,
    preset_name: str = "industrial-50k",
    seeds: list[int] | None = None,
    solver_names: list[str] | None = None,
    runs: int = 1,
    write_dir: Path | None = None,
    lane: LaneMode = "throughput",
    cvar_alpha: float = 0.95,
    quality_gate_enabled: bool = True,
    quality_gate_baseline_solver: str = "RHC-GREEDY",
    min_scheduled_ratio: float = 0.90,
    max_makespan_degradation_ratio: float = 1.05,
    max_inner_fallback_ratio: float = 0.10,
) -> dict[str, Any]:
    """Run and persist a deterministic RHC large-instance benchmark study."""

    if preset_name == "industrial-50k":
        return _study_industrial_50k(
            seeds=seeds or [1],
            solver_names=solver_names or ["RHC-GREEDY", "RHC-ALNS"],
            runs=runs,
            write_dir=write_dir,
            lane=lane,
            cvar_alpha=cvar_alpha,
            quality_gate_enabled=quality_gate_enabled,
            quality_gate_baseline_solver=quality_gate_baseline_solver,
            min_scheduled_ratio=min_scheduled_ratio,
            max_makespan_degradation_ratio=max_makespan_degradation_ratio,
            max_inner_fallback_ratio=max_inner_fallback_ratio,
        )

    study_seeds = seeds or [1]
    requested_solver_names = solver_names or ["RHC-GREEDY", "RHC-ALNS"]
    artifact_dir = write_dir or Path("benchmark") / "studies" / "rhc_50k"
    instance_dir = artifact_dir / "instances"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    instance_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    grouped_by_solver: dict[str, list[dict[str, Any]]] = {
        solver_name: [] for solver_name in requested_solver_names
    }

    for seed in study_seeds:
        spec = preset_spec(preset_name, seed=seed)
        instance_path = instance_dir / f"{preset_name}_seed{seed}.json"
        instance_summary = write_problem_instance(instance_path, spec)
        benchmark_report = run_benchmark(
            instance_path=instance_path,
            solver_names=requested_solver_names,
            runs=runs,
            compare=len(requested_solver_names) > 1,
        )

        comparisons = benchmark_report.get("comparisons")
        if comparisons is None:
            comparisons = [
                {
                    "solver_config": benchmark_report["solver_config"],
                    "selected_solver_config": benchmark_report["selected_solver_config"],
                    "results": benchmark_report["results"],
                    "verification": benchmark_report["verification"],
                    "statistics": benchmark_report["statistics"],
                    "solver_metadata": benchmark_report.get("solver_metadata", {}),
                }
            ]

        record = {
            "preset_name": preset_name,
            "seed": seed,
            "instance": instance_summary,
            "problem_profile": benchmark_report["problem_profile"],
            "comparisons": comparisons,
        }
        records.append(record)
        for comparison in comparisons:
            grouped_by_solver.setdefault(comparison["solver_config"], []).append(comparison)

    report = {
        "study_kind": "rhc-50k",
        "preset_name": preset_name,
        "requested_solver_names": requested_solver_names,
        "lane_mode": lane,
        "cvar_alpha": cvar_alpha,
        "runs": runs,
        "records": records,
        "summary_by_solver": {
            solver_name: _summarize_solver_records(
                solver_records,
                cvar_alpha=cvar_alpha,
            )
            for solver_name, solver_records in grouped_by_solver.items()
            if solver_records
        },
    }
    if quality_gate_enabled:
        report["quality_gate"] = {
            "enabled": True,
            "baseline_solver": quality_gate_baseline_solver,
            "max_makespan_degradation_ratio": max_makespan_degradation_ratio,
            "max_inner_fallback_ratio": max_inner_fallback_ratio,
            "results": _evaluate_quality_gate(
                summaries=report["summary_by_solver"],
                baseline_solver=quality_gate_baseline_solver,
                min_scheduled_ratio=min_scheduled_ratio,
                max_makespan_degradation_ratio=max_makespan_degradation_ratio,
                max_inner_fallback_ratio=max_inner_fallback_ratio,
            ),
        }
    else:
        report["quality_gate"] = {"enabled": False}

    evidence_scope = (
        report["summary_by_solver_lane"]
        if lane == "both"
        else report["summary_by_solver"]
    )
    report["evidence"] = _build_study_evidence(
        records=records,
        summary_snapshot=evidence_scope,
    )

    report_path = artifact_dir / "rhc_50k_study.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact_path"] = str(report_path)
    return report


def _study_industrial_50k(
    *,
    seeds: list[int],
    solver_names: list[str],
    runs: int,
    write_dir: Path | None,
    lane: LaneMode,
    cvar_alpha: float,
    quality_gate_enabled: bool,
    quality_gate_baseline_solver: str,
    min_scheduled_ratio: float,
    max_makespan_degradation_ratio: float,
    max_inner_fallback_ratio: float,
) -> dict[str, Any]:
    artifact_dir = write_dir or Path("benchmark") / "studies" / "rhc_50k"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    rhc_greedy_kwargs = {
        "window_minutes": 480,
        "overlap_minutes": 60,
        "inner_solver": "greedy",
        "time_limit_s": 600,
        "max_ops_per_window": 10_000,
    }
    rhc_alns_kwargs = {
        "window_minutes": 480,
        "overlap_minutes": 120,
        "inner_solver": "alns",
        "time_limit_s": 1200,
        "alns_inner_window_time_cap_s": 180,
        "max_ops_per_window": 5_000,
        "progressive_admission_relaxation_enabled": True,
        "precedence_ready_candidate_filter_enabled": True,
        "due_admission_horizon_factor": 2.0,
        "admission_relaxation_min_fill_ratio": 0.30,
        "admission_full_scan_enabled": False,
        "alns_budget_auto_scaling_enabled": True,
        "alns_presearch_max_window_ops": 5_000,
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
    }

    solver_specs = {
        "RHC-GREEDY": {
            "solver_name": "rhc-greedy",
            "solver_kwargs": deepcopy(rhc_greedy_kwargs),
        },
        "RHC-ALNS": {
            "solver_name": "rhc-alns",
            "solver_kwargs": deepcopy(rhc_alns_kwargs),
        },
        "RHC-ALNS-REFINE": {
            "solver_name": "rhc-alns-refine",
            "baseline_solver_name": "rhc-greedy",
            "baseline_solver_kwargs": deepcopy(rhc_greedy_kwargs),
            "solver_kwargs": deepcopy(rhc_alns_kwargs),
            "two_phase_refinement": True,
        },
    }

    records: list[dict[str, Any]] = []
    grouped_by_solver: dict[str, list[dict[str, Any]]] = {
        solver_name: [] for solver_name in solver_names
    }
    grouped_by_solver_lane: dict[str, list[dict[str, Any]]] = {}
    lane_profiles: list[Literal["throughput", "strict"]] = (
        ["throughput", "strict"] if lane == "both" else [lane]
    )

    for seed in seeds:
        per_seed: list[dict[str, Any]] = []
        for lane_name in lane_profiles:
            for solver_name in solver_names:
                spec = solver_specs[solver_name]
                solver_kwargs = _apply_lane_profile(
                    solver_name,
                    spec["solver_kwargs"],
                    lane=lane_name,
                    seed=seed,
                )
                if spec.get("two_phase_refinement"):
                    raw_result = _run_two_phase_refinement_case(
                        n_ops=50_000,
                        n_machines=100,
                        n_states=20,
                        seed=seed,
                        baseline_solver_name=spec["baseline_solver_name"],
                        baseline_solver_kwargs=spec["baseline_solver_kwargs"],
                        refinement_solver_name=spec["solver_name"],
                        refinement_solver_kwargs=solver_kwargs,
                    )
                else:
                    raw_result = run_scaling_case(
                        n_ops=50_000,
                        n_machines=100,
                        n_states=20,
                        solver_name=spec["solver_name"],
                        solver_kwargs=solver_kwargs,
                        seed=seed,
                    )
                comparison = {
                    "process_outcome": "completed",
                    "solve_outcome": _classify_solve_outcome(
                        raw_result["status"],
                        feasible=bool(raw_result["feasible"]),
                    ),
                    "solver_config": solver_name,
                    "selected_solver_config": solver_name,
                    "lane": lane_name,
                    "results": {
                        "process_outcome": "completed",
                        "solve_outcome": _classify_solve_outcome(
                            raw_result["status"],
                            feasible=bool(raw_result["feasible"]),
                        ),
                        "status": raw_result["status"],
                        "feasible": raw_result["feasible"],
                        "solver_name": raw_result["solver"],
                        "makespan_minutes": raw_result["makespan_min"],
                        "total_setup_minutes": raw_result["total_setup_min"],
                        "total_tardiness_minutes": raw_result["total_tardiness_min"],
                        "total_material_loss": raw_result["total_material_loss"],
                        "assignments": raw_result["assigned_ops"],
                    },
                    "verification": {
                        "feasible": raw_result["feasible"],
                        "violation_count": raw_result["violations"],
                    },
                    "statistics": {
                        "runs": runs,
                        "wall_time_s_mean": round(raw_result["solve_ms"] / 1000, 4),
                        "wall_time_s_min": round(raw_result["solve_ms"] / 1000, 4),
                        "wall_time_s_max": round(raw_result["solve_ms"] / 1000, 4),
                        "generation_time_ms": raw_result["gen_ms"],
                        "verification_time_ms": raw_result["verify_ms"],
                    },
                    "solver_metadata": raw_result.get("metadata", {}),
                    "benchmark_config": {
                        "n_ops": raw_result["n_ops"],
                        "n_machines": raw_result["n_machines"],
                        "n_states": raw_result["n_states"],
                        "sdst_memory_bytes": raw_result["sdst_memory_bytes"],
                    },
                }
                per_seed.append(comparison)
                grouped_by_solver[solver_name].append(comparison)
                lane_key = f"{solver_name}|{lane_name}"
                grouped_by_solver_lane.setdefault(lane_key, []).append(comparison)

        records.append(
            {
                "preset_name": "industrial-50k",
                "seed": seed,
                "problem_profile": {
                    "operation_count": 50_000,
                    "work_center_count": 100,
                    "state_count": 20,
                    "size_band": "mega",
                },
                "comparisons": per_seed,
            }
        )

    report = {
        "study_kind": "rhc-50k",
        "preset_name": "industrial-50k",
        "requested_solver_names": solver_names,
        "lane_mode": lane,
        "cvar_alpha": cvar_alpha,
        "runs": runs,
        "records": records,
        "summary_by_solver": {
            solver_name: _summarize_solver_records(
                solver_records,
                cvar_alpha=cvar_alpha,
            )
            for solver_name, solver_records in grouped_by_solver.items()
            if solver_records
        },
        "summary_by_solver_lane": {
            key: _summarize_solver_records(
                solver_records,
                cvar_alpha=cvar_alpha,
            )
            for key, solver_records in grouped_by_solver_lane.items()
            if solver_records
        },
    }
    if quality_gate_enabled:
        gate_scope = (
            report["summary_by_solver_lane"]
            if lane == "both"
            else report["summary_by_solver"]
        )
        report["quality_gate"] = {
            "enabled": True,
            "baseline_solver": quality_gate_baseline_solver,
            "max_makespan_degradation_ratio": max_makespan_degradation_ratio,
            "max_inner_fallback_ratio": max_inner_fallback_ratio,
            "results": _evaluate_quality_gate(
                summaries=gate_scope,
                baseline_solver=quality_gate_baseline_solver,
                min_scheduled_ratio=min_scheduled_ratio,
                max_makespan_degradation_ratio=max_makespan_degradation_ratio,
                max_inner_fallback_ratio=max_inner_fallback_ratio,
            ),
        }
    else:
        report["quality_gate"] = {"enabled": False}

    evidence_scope = (
        report["summary_by_solver_lane"]
        if lane == "both"
        else report["summary_by_solver"]
    )
    report["evidence"] = _build_study_evidence(
        records=records,
        summary_snapshot=evidence_scope,
    )

    report_path = artifact_dir / "rhc_50k_study.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact_path"] = str(report_path)
    return report


def _summarize_solver_records(
    records: list[dict[str, Any]],
    *,
    cvar_alpha: float,
) -> dict[str, Any]:
    process_outcomes = [
        str(record.get("process_outcome", record.get("results", {}).get("process_outcome", "completed")))
        for record in records
    ]
    solve_outcomes = [
        str(record.get("solve_outcome", record.get("results", {}).get("solve_outcome", "solver_error")))
        for record in records
    ]

    wall_times = [record["statistics"]["wall_time_s_mean"] for record in records]
    verification_times = [record["statistics"]["verification_time_ms"] for record in records]
    makespans = [record["results"]["makespan_minutes"] for record in records]
    setup_minutes = [record["results"]["total_setup_minutes"] for record in records]
    assigned_counts = [
        float(record.get("results", {}).get("assignments", 0.0))
        for record in records
    ]
    total_ops = [
        float(
            record.get("benchmark_config", {}).get(
                "n_ops",
                max(1.0, record.get("results", {}).get("assignments", 0.0)),
            )
        )
        for record in records
    ]
    scheduled_ratios = [
        assigned / max(1.0, total)
        for assigned, total in zip(assigned_counts, total_ops, strict=True)
    ]
    preprocessing = [
        float(record.get("solver_metadata", {}).get("preprocessing_ms", 0.0))
        for record in records
        if "preprocessing_ms" in record.get("solver_metadata", {})
    ]
    peak_candidates = [
        float(record.get("solver_metadata", {}).get("peak_window_candidate_count", 0.0))
        for record in records
        if "peak_window_candidate_count" in record.get("solver_metadata", {})
    ]
    due_pressure_counts = [
        float(record.get("solver_metadata", {}).get("due_pressure_selected_ops", 0.0))
        for record in records
        if "due_pressure_selected_ops" in record.get("solver_metadata", {})
    ]
    inner_fallback_ratios = [
        float(record.get("solver_metadata", {}).get("inner_fallback_ratio", 0.0))
        for record in records
        if "inner_fallback_ratio" in record.get("solver_metadata", {})
    ]
    fallback_kpi_pass_flags = [
        bool(record.get("solver_metadata", {}).get("inner_fallback_kpi_passed", False))
        for record in records
        if "inner_fallback_kpi_passed" in record.get("solver_metadata", {})
    ]
    native_acceleration_flags: list[bool] = []
    warm_start_window_flags: list[bool] = []
    warm_start_completed_counts: list[float] = []

    for record in records:
        solver_metadata = record.get("solver_metadata", {})
        acceleration = solver_metadata.get("acceleration")
        if isinstance(acceleration, dict):
            backend = acceleration.get(
                "rhc_candidate_metrics_np_backend",
                acceleration.get("rhc_candidate_metrics_backend"),
            )
            if backend in {"native", "python"}:
                native_acceleration_flags.append(backend == "native")

        inner_window_summaries = solver_metadata.get("inner_window_summaries")
        if isinstance(inner_window_summaries, list):
            for summary in inner_window_summaries:
                if not isinstance(summary, dict):
                    continue
                if "warm_start_used" in summary:
                    warm_start_window_flags.append(bool(summary["warm_start_used"]))
                if "warm_start_completed_assignments" in summary:
                    warm_start_completed_counts.append(
                        float(summary["warm_start_completed_assignments"])
                    )

    summary: dict[str, Any] = {
        "instance_count": len(records),
        "process_completed_count": sum(1 for value in process_outcomes if value == "completed"),
        "solve_completed_count": sum(1 for value in solve_outcomes if value == "completed"),
        "solver_timeout_count": sum(1 for value in solve_outcomes if value == "solver_timeout"),
        "solver_cancelled_count": sum(1 for value in solve_outcomes if value == "solver_cancelled"),
        "solver_error_count": sum(1 for value in solve_outcomes if value == "solver_error"),
        "mean_wall_time_s": round(statistics.mean(wall_times), 4),
        "median_wall_time_s": round(statistics.median(wall_times), 4),
        "mean_verification_time_ms": round(statistics.mean(verification_times), 2),
        "mean_makespan_minutes": round(statistics.mean(makespans), 2),
        "median_makespan_minutes": round(statistics.median(makespans), 2),
        "mean_total_setup_minutes": round(statistics.mean(setup_minutes), 2),
        "feasibility_rate": round(
            sum(1 for record in records if record["verification"]["feasible"]) / len(records),
            3,
        ),
        "mean_scheduled_ratio": round(statistics.mean(scheduled_ratios), 4),
        "cvar_unscheduled_ratio": round(
            _tail_cvar([1.0 - value for value in scheduled_ratios], cvar_alpha),
            4,
        ),
        "cvar_alpha": round(cvar_alpha, 4),
        "cvar_makespan_minutes": round(_tail_cvar(makespans, cvar_alpha), 2),
    }
    summary["process_completed_rate"] = round(
        summary["process_completed_count"] / max(1, summary["instance_count"]),
        4,
    )
    summary["solve_completed_rate"] = round(
        summary["solve_completed_count"] / max(1, summary["instance_count"]),
        4,
    )
    if len(wall_times) >= 2:
        wall_quartiles = statistics.quantiles(wall_times, n=4, method="inclusive")
        q1_wall, q3_wall = wall_quartiles[0], wall_quartiles[2]
        summary["iqr_wall_time_s"] = round(max(0.0, q3_wall - q1_wall), 4)
    if len(makespans) >= 2:
        makespan_quartiles = statistics.quantiles(makespans, n=4, method="inclusive")
        q1_make, q3_make = makespan_quartiles[0], makespan_quartiles[2]
        summary["iqr_makespan_minutes"] = round(max(0.0, q3_make - q1_make), 2)
    if preprocessing:
        summary["mean_preprocessing_ms"] = round(statistics.mean(preprocessing), 2)
    if peak_candidates:
        summary["mean_peak_window_candidate_count"] = round(
            statistics.mean(peak_candidates),
            2,
        )
    if due_pressure_counts:
        summary["mean_due_pressure_selected_ops"] = round(
            statistics.mean(due_pressure_counts),
            2,
        )
    if inner_fallback_ratios:
        summary["mean_inner_fallback_ratio"] = round(
            statistics.mean(inner_fallback_ratios),
            4,
        )
        summary["max_inner_fallback_ratio"] = round(max(inner_fallback_ratios), 4)
        summary["cvar_inner_fallback_ratio"] = round(
            _tail_cvar(inner_fallback_ratios, cvar_alpha),
            4,
        )
    if fallback_kpi_pass_flags:
        summary["inner_fallback_kpi_pass_rate"] = round(
            sum(1 for passed in fallback_kpi_pass_flags if passed)
            / len(fallback_kpi_pass_flags),
            3,
        )
    if native_acceleration_flags:
        summary["native_acceleration_rate"] = round(
            sum(1 for enabled in native_acceleration_flags if enabled)
            / len(native_acceleration_flags),
            3,
        )
    if warm_start_window_flags:
        summary["mean_warm_start_window_rate"] = round(
            sum(1 for used in warm_start_window_flags if used)
            / len(warm_start_window_flags),
            3,
        )
    if warm_start_completed_counts:
        summary["mean_warm_start_completed_assignments"] = round(
            statistics.mean(warm_start_completed_counts),
            3,
        )
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a reproducible 50K RHC benchmark study and write an artifact report"
    )
    parser.add_argument(
        "--preset",
        default="industrial-50k",
        help="Generated benchmark preset to materialize for the study",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[1],
        help="Deterministic seeds to execute",
    )
    parser.add_argument(
        "--solvers",
        nargs="+",
        default=["RHC-GREEDY", "RHC-ALNS"],
        help="Benchmark solver configurations to compare",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Repetitions per solver configuration",
    )
    parser.add_argument(
        "--lane",
        choices=["throughput", "strict", "both"],
        default="throughput",
        help="Reproducibility lane: throughput (multi-worker), strict (single-worker), or both",
    )
    parser.add_argument(
        "--cvar-alpha",
        type=float,
        default=0.95,
        help="Tail confidence level for CVaR metrics (default: 0.95)",
    )
    parser.add_argument(
        "--no-quality-gate",
        dest="quality_gate",
        action="store_false",
        default=True,
        help="Disable multi-criterion quality gate on study summaries",
    )
    parser.add_argument(
        "--quality-gate-baseline",
        default="RHC-GREEDY",
        help="Baseline solver used for objective degradation check",
    )
    parser.add_argument(
        "--min-scheduled-ratio",
        type=float,
        default=0.90,
        help="Minimum allowed mean scheduled ratio for the quality gate (default: 0.90)",
    )
    parser.add_argument(
        "--max-makespan-degradation-ratio",
        type=float,
        default=1.05,
        help="Maximum allowed mean makespan ratio vs baseline (default: 1.05)",
    )
    parser.add_argument(
        "--max-inner-fallback-ratio",
        type=float,
        default=0.10,
        help="Maximum allowed mean inner fallback ratio (default: 0.10)",
    )
    parser.add_argument(
        "--write-dir",
        type=Path,
        help=(
            "Artifact directory under benchmark/ where the report and "
            "materialized instances are written"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = study_rhc_50k(
        preset_name=args.preset,
        seeds=args.seeds,
        solver_names=args.solvers,
        runs=args.runs,
        write_dir=args.write_dir,
        lane=args.lane,
        cvar_alpha=args.cvar_alpha,
        quality_gate_enabled=args.quality_gate,
        quality_gate_baseline_solver=args.quality_gate_baseline,
        min_scheduled_ratio=args.min_scheduled_ratio,
        max_makespan_degradation_ratio=args.max_makespan_degradation_ratio,
        max_inner_fallback_ratio=args.max_inner_fallback_ratio,
    )
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


__all__ = ["main", "study_rhc_50k"]


if __name__ == "__main__":
    raise SystemExit(main())
