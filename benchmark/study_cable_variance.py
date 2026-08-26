"""Cable C6a/C6-R1 evidence: generator-seed distribution vs solver-seed freeze.

P1.1: 1600@8 COVER, waves=0, seeds 1..10 (generator). Then one frozen instance
(seed=1) re-solved with random_seed in {1,42,999}.
P1.2: C6-R1 waves=4 seed=2, capture notary_kinds (do not call it confirmed
unless this run is INFEASIBLE).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmark.evidence_common import REPO_ROOT, collect_environment, summarize_seed, write_hashes
from synaps.domains.cable import run_nervous_month, run_nervous_month_multiseed
from synaps.domains.cable.kpis import cable_kpis
from synaps.domains.cable.nervous_month import generate_nervous_month
from synaps.solvers.feasibility_checker import FeasibilityChecker, proven_hard_violations
from synaps.solvers.registry import create_solver

DEFAULT_OUT = REPO_ROOT / "benchmark" / "evidence" / "cable-c6-2026-08-25"


def generator_sweep(out_dir: Path) -> dict[str, Any]:
    seeds = tuple(range(1, 11))
    report = run_nervous_month_multiseed(
        seeds,
        n_orders=1600,
        machines_per_stage=8,
        drum_pool_size=48,
        waves=0,
        new_rush_orders=0,
        disruptions_per_wave=0,
    )
    tardiness = [int(x) for x in report["tardiness_minutes"]]
    payload = {
        "experiment": "generator_seed_1_to_10",
        "fixed": "solver path = nervous-month default COVER (ATCS windowed)",
        "varied": "instance generator seed",
        "all_feasible": report["all_feasible"],
        "tardiness_minutes": tardiness,
        "tardiness_stats": summarize_seed([float(x) for x in tardiness]),
        "spread_max_over_min": (max(tardiness) / min(tardiness)) if min(tardiness) else None,
        "notary_hard_violations": report["notary_hard_violations"],
        "solve_s": report["solve_s"],
        "runs": [
            {
                "seed": run["seed"],
                "status": run["status"],
                "notary_hard_violations": run["notary_hard_violations"],
                "tardiness_minutes": run["kpis"]["total_tardiness_minutes"],
                "n_operations": run["n_operations"],
                "solve_s": run["solve_s"],
            }
            for run in report["runs"]
        ],
    }
    path = out_dir / "generator_seed_1_to_10.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def solver_seed_sweep(out_dir: Path) -> dict[str, Any]:
    problem = generate_nervous_month(
        n_orders=1600,
        seed=1,
        machines_per_stage=8,
        drum_pool_size=48,
        family_dedicated_lines=True,
        colour_phase=True,
        colour_dedicated_lines=False,
    )
    rows = []
    for random_seed in (1, 42, 999):
        solver, kwargs = create_solver("RHC-GREEDY-COVER")
        kwargs = {
            **kwargs,
            "cover_ready_rule": "atcs",
            "cover_atcs_floor_window": 0.0,
            "cover_atcs_exhaust_window": 240.0,
            "random_seed": random_seed,
        }
        result = solver.solve(problem, **kwargs)
        hard = proven_hard_violations(
            FeasibilityChecker().check(problem, result.assignments, exhaustive=True)
        )
        kpis = cable_kpis(problem, result.assignments)
        rows.append(
            {
                "instance_seed": 1,
                "solver_random_seed": random_seed,
                "status": result.status.value,
                "notary_hard_violations": len(hard),
                "tardiness_minutes": kpis["total_tardiness_minutes"],
                "ops_scheduled": len(result.assignments),
                "ops_total": len(problem.operations),
                "global_greedy_cover": (result.metadata or {}).get("global_greedy_cover"),
                "determinism_violated": (result.metadata or {}).get("determinism_violated"),
            }
        )
    tardiness = [float(r["tardiness_minutes"]) for r in rows]
    payload = {
        "experiment": "fixed_instance_seed1_solver_random_seed",
        "fixed": "generate_nervous_month seed=1, 1600@8, family+colour-phase",
        "varied": "RHC-GREEDY-COVER random_seed",
        "rows": rows,
        "tardiness_stats": summarize_seed(tardiness),
        "identical_tardiness": len(set(tardiness)) == 1,
    }
    path = out_dir / "solver_seed_fixed_instance.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def c6_r1_seed2(out_dir: Path) -> dict[str, Any]:
    report = run_nervous_month(
        n_orders=1600,
        seed=2,
        machines_per_stage=8,
        drum_pool_size=48,
        waves=4,
        disruptions_per_wave=20,
        new_rush_orders=0,
    )
    waves = report.get("waves") or []
    dirty = [
        {
            "wave": row.get("wave"),
            "status": row.get("status"),
            "notary_hard_violations": row.get("notary_hard_violations"),
            "notary_kinds": row.get("notary_kinds"),
            "notary_sample": row.get("notary_sample"),
            "stability_hamming": row.get("stability_hamming"),
        }
        for row in waves
        if not row.get("skipped")
        and (
            row.get("status") != "feasible" or int(row.get("notary_hard_violations") or 0) != 0
        )
    ]
    payload = {
        "experiment": "C6-R1 seed=2 waves=4",
        "cover_status": report.get("status"),
        "cover_notary": report.get("notary_hard_violations"),
        "waves": waves,
        "dirty_waves": dirty,
        "reproduced_infeasible": bool(dirty),
        "confirmation": (
            "confirmed_this_run" if dirty else "not_reproduced_this_run_unconfirmed_historical"
        ),
    }
    path = out_dir / "c6_r1_seed2_waves4.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--skip-generator", action="store_true")
    parser.add_argument("--skip-solver-seed", action="store_true")
    parser.add_argument("--skip-c6r1", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "environment.json").write_text(
        json.dumps(collect_environment(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary: dict[str, Any] = {}
    if not args.skip_generator:
        summary["generator"] = generator_sweep(out_dir)
    if not args.skip_solver_seed:
        summary["solver_seed"] = solver_seed_sweep(out_dir)
    if not args.skip_c6r1:
        summary["c6_r1"] = c6_r1_seed2(out_dir)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_hashes(out_dir, sorted(out_dir.glob("*.json")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
