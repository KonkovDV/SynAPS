"""Academic solver-scaling study for generated SynAPS instances.

This utility extends the routing-boundary study into executable evidence:
generated preset families are solved by requested solver configurations and the
resulting runtime/quality metrics are aggregated by preset.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path
from typing import Any

from benchmark.generate_instances import preset_spec, write_problem_instance
from benchmark.run_benchmark import available_solvers, run_benchmark


def study_solver_scaling(
    *,
    presets: list[str],
    seeds: list[int],
    solver_names: list[str],
    write_dir: Path | None = None,
    runs: int = 1,
) -> dict[str, Any]:
    """Generate a solver-comparison report for preset/seed combinations."""

    records: list[dict[str, Any]] = []
    grouped_records: dict[str, list[dict[str, Any]]] = {preset: [] for preset in presets}

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)

        for preset in presets:
            for seed in seeds:
                spec = preset_spec(preset, seed=seed)
                output_path = (write_dir or temp_dir) / f"{preset}_seed{seed}.json"
                summary = write_problem_instance(output_path, spec)

                benchmark_report = run_benchmark(
                    output_path,
                    solver_names=solver_names,
                    runs=runs,
                    compare=len(solver_names) > 1,
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
                        }
                    ]

                record = {
                    "preset": preset,
                    "seed": seed,
                    "instance_path": str(output_path) if write_dir is not None else None,
                    "problem_profile": summary["problem_profile"],
                    "comparisons": comparisons,
                }
                records.append(record)
                grouped_records[preset].append(record)

    return {
        "study_kind": "solver-scaling",
        "requested_solver_names": solver_names,
        "runs": runs,
        "records": records,
        "summary_by_preset": {
            preset: _summarize_preset(records_for_preset)
            for preset, records_for_preset in grouped_records.items()
        },
    }


def _summarize_preset(records: list[dict[str, Any]]) -> dict[str, Any]:
    selected_solver_counts: dict[str, int] = {}
    wall_time_by_solver: dict[str, list[float]] = {}
    makespan_by_solver: dict[str, list[float]] = {}
    feasibility_by_solver: dict[str, list[bool]] = {}

    for record in records:
        for comparison in record["comparisons"]:
            selected_solver = comparison["selected_solver_config"]
            selected_solver_counts[selected_solver] = selected_solver_counts.get(selected_solver, 0) + 1
            wall_time_by_solver.setdefault(selected_solver, []).append(
                comparison["statistics"]["wall_time_s_mean"]
            )
            makespan_by_solver.setdefault(selected_solver, []).append(
                comparison["results"]["makespan_minutes"]
            )
            feasibility_by_solver.setdefault(selected_solver, []).append(
                bool(comparison["results"]["feasible"])
            )

    return {
        "instance_count": len(records),
        "solver_counts": selected_solver_counts,
        "mean_wall_time_s_by_solver": {
            solver: round(statistics.mean(values), 4)
            for solver, values in wall_time_by_solver.items()
        },
        "mean_makespan_by_solver": {
            solver: round(statistics.mean(values), 3)
            for solver, values in makespan_by_solver.items()
        },
        "feasibility_rate_by_solver": {
            solver: round(sum(1 for value in values if value) / len(values), 3)
            for solver, values in feasibility_by_solver.items()
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Study SynAPS solver scaling across generated presets")
    parser.add_argument(
        "--presets",
        nargs="+",
        default=["medium", "large"],
        choices=["tiny", "small", "medium", "large", "industrial"],
        help="Preset families to generate for the solver-scaling study",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[1, 2, 3],
        help="Deterministic seeds to evaluate per preset",
    )
    parser.add_argument(
        "--solvers",
        nargs="+",
        default=["GREED", "CPSAT-30", "LBBD-10", "AUTO"],
        choices=available_solvers(),
        help="Solver configurations to compare on each generated instance",
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
        help="Optional directory where generated JSON instances should be materialized",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    report = study_solver_scaling(
        presets=args.presets,
        seeds=args.seeds,
        solver_names=args.solvers,
        runs=args.runs,
        write_dir=args.write_dir,
    )
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


__all__ = ["main", "study_solver_scaling"]


if __name__ == "__main__":
    raise SystemExit(main())