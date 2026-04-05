"""Academic routing-boundary study for generated SynAPS instances.

This utility operationalizes Phase 1 benchmark research: instead of discussing
LBBD routing thresholds abstractly, it generates preset families across seeds,
profiles them, records deterministic router decisions, and optionally
materializes the study corpus for later solver runs.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from synaps.problem_profile import build_problem_profile
from synaps.solvers.router import route_solver_config

from benchmark.generate_instances import generate_problem, preset_spec, write_problem_instance


def study_routing_boundary(
    *,
    presets: list[str],
    seeds: list[int],
    write_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate a routing-boundary report for preset/seed combinations."""

    records: list[dict[str, Any]] = []
    grouped_records: dict[str, list[dict[str, Any]]] = {preset: [] for preset in presets}

    for preset in presets:
        for seed in seeds:
            spec = preset_spec(preset, seed=seed)
            instance_path: str | None = None
            if write_dir is not None:
                output_path = write_dir / f"{preset}_seed{seed}.json"
                write_problem_instance(output_path, spec)
                instance_path = str(output_path)

            problem = generate_problem(spec)
            profile = build_problem_profile(problem).as_dict()
            decision = route_solver_config(problem)

            record = {
                "preset": preset,
                "seed": seed,
                "instance_path": instance_path,
                "problem_profile": profile,
                "routing": {
                    "solver_config": decision.solver_config,
                    "reason": decision.reason,
                },
            }
            records.append(record)
            grouped_records[preset].append(record)

    return {
        "study_kind": "routing-boundary",
        "records": records,
        "summary_by_preset": {
            preset: _summarize_preset(records_for_preset)
            for preset, records_for_preset in grouped_records.items()
        },
    }


def _summarize_preset(records: list[dict[str, Any]]) -> dict[str, Any]:
    operation_counts = [record["problem_profile"]["operation_count"] for record in records]
    routing_counts = _count_values(record["routing"]["solver_config"] for record in records)
    size_band_counts = _count_values(record["problem_profile"]["size_band"] for record in records)
    aux_enabled_count = sum(1 for record in records if record["problem_profile"]["has_aux_constraints"])
    setup_enabled_count = sum(1 for record in records if record["problem_profile"]["has_nonzero_setups"])

    return {
        "instance_count": len(records),
        "routing_counts": routing_counts,
        "size_band_counts": size_band_counts,
        "routing_stable": len(routing_counts) == 1,
        "aux_constraints_fraction": round(aux_enabled_count / len(records), 3) if records else 0.0,
        "nonzero_setup_fraction": round(setup_enabled_count / len(records), 3) if records else 0.0,
        "operation_count": {
            "min": min(operation_counts) if operation_counts else 0,
            "max": max(operation_counts) if operation_counts else 0,
            "mean": round(statistics.mean(operation_counts), 3) if operation_counts else 0.0,
        },
    }


def _count_values(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Study SynAPS routing boundaries across generated presets")
    parser.add_argument(
        "--presets",
        nargs="+",
        default=["medium", "large"],
        choices=["tiny", "small", "medium", "large", "industrial"],
        help="Preset families to generate for the routing study",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=[1, 2, 3],
        help="Deterministic seeds to evaluate per preset",
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
    report = study_routing_boundary(
        presets=args.presets,
        seeds=args.seeds,
        write_dir=args.write_dir,
    )
    json.dump(report, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


__all__ = ["main", "study_routing_boundary"]


if __name__ == "__main__":
    raise SystemExit(main())