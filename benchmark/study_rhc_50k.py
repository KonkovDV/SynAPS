"""Reproducible 50K benchmark study for the RHC large-instance path.

This study materializes deterministic benchmark instances, runs the public
benchmark harness for `RHC-GREEDY` and `RHC-ALNS`, and writes an artifact JSON
under `benchmark/` so large-instance evidence is preserved alongside the code.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from benchmark.generate_instances import preset_spec, write_problem_instance
from benchmark.run_benchmark import run_benchmark
from synaps.benchmarks.run_scaling_benchmark import run_benchmark as run_scaling_case


def study_rhc_50k(
    *,
    preset_name: str = "industrial-50k",
    seeds: list[int] | None = None,
    solver_names: list[str] | None = None,
    runs: int = 1,
    write_dir: Path | None = None,
) -> dict[str, Any]:
    """Run and persist a deterministic RHC large-instance benchmark study."""

    if preset_name == "industrial-50k":
        return _study_industrial_50k(
            seeds=seeds or [1],
            solver_names=solver_names or ["RHC-GREEDY", "RHC-ALNS"],
            runs=runs,
            write_dir=write_dir,
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
        "runs": runs,
        "records": records,
        "summary_by_solver": {
            solver_name: _summarize_solver_records(solver_records)
            for solver_name, solver_records in grouped_by_solver.items()
            if solver_records
        },
    }

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
) -> dict[str, Any]:
    artifact_dir = write_dir or Path("benchmark") / "studies" / "rhc_50k"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    solver_specs = {
        "RHC-GREEDY": {
            "solver_name": "rhc-greedy",
            "solver_kwargs": {
                "window_minutes": 480,
                "overlap_minutes": 60,
                "inner_solver": "greedy",
                "time_limit_s": 120,
                "max_ops_per_window": 10_000,
            },
        },
        "RHC-ALNS": {
            "solver_name": "rhc-alns",
            "solver_kwargs": {
                "window_minutes": 480,
                "overlap_minutes": 120,
                "inner_solver": "alns",
                "time_limit_s": 300,
                "max_ops_per_window": 5_000,
                "inner_kwargs": {
                    "max_iterations": 100,
                    "time_limit_s": 45,
                    "repair_time_limit_s": 5,
                    "min_destroy": 20,
                    "max_destroy": 200,
                },
            },
        },
    }

    records: list[dict[str, Any]] = []
    grouped_by_solver: dict[str, list[dict[str, Any]]] = {solver_name: [] for solver_name in solver_names}

    for seed in seeds:
        per_seed: list[dict[str, Any]] = []
        for solver_name in solver_names:
            spec = solver_specs[solver_name]
            raw_result = run_scaling_case(
                n_ops=50_000,
                n_machines=100,
                n_states=20,
                solver_name=spec["solver_name"],
                solver_kwargs=spec["solver_kwargs"],
                seed=seed,
            )
            comparison = {
                "solver_config": solver_name,
                "selected_solver_config": solver_name,
                "results": {
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
        "runs": runs,
        "records": records,
        "summary_by_solver": {
            solver_name: _summarize_solver_records(solver_records)
            for solver_name, solver_records in grouped_by_solver.items()
            if solver_records
        },
    }
    report_path = artifact_dir / "rhc_50k_study.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["artifact_path"] = str(report_path)
    return report


def _summarize_solver_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    wall_times = [record["statistics"]["wall_time_s_mean"] for record in records]
    verification_times = [record["statistics"]["verification_time_ms"] for record in records]
    makespans = [record["results"]["makespan_minutes"] for record in records]
    setup_minutes = [record["results"]["total_setup_minutes"] for record in records]
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

    summary: dict[str, Any] = {
        "instance_count": len(records),
        "mean_wall_time_s": round(statistics.mean(wall_times), 4),
        "mean_verification_time_ms": round(statistics.mean(verification_times), 2),
        "mean_makespan_minutes": round(statistics.mean(makespans), 2),
        "mean_total_setup_minutes": round(statistics.mean(setup_minutes), 2),
        "feasibility_rate": round(
            sum(1 for record in records if record["verification"]["feasible"]) / len(records),
            3,
        ),
    }
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
        "--write-dir",
        type=Path,
        help="Artifact directory under benchmark/ where the report and materialized instances are written",
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
    )
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


__all__ = ["main", "study_rhc_50k"]


if __name__ == "__main__":
    raise SystemExit(main())