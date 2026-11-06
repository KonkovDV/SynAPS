"""T-06 A/B: LBBD with and without the sound master rows at the same budget.

For every instance the same registry configuration (``LBBD-5`` by default:
5 iterations, 30 s) runs twice — the default master (cut-free relaxation as
the reported bound, no-goods only) and ``sound_cuts=True``. The study records
the incumbent makespan (UB), the reported lower bound (LB), the gap
``(UB - LB) / UB``, wall time and the row pool, checks every schedule with
the independent FeasibilityChecker and asserts ``LB <= BKS`` on Brandimarte.

LBBD's incumbent is wall-clock path dependent (cluster budgets clamp to the
remaining deadline), so a single run per mode mixes the effect with host
noise. ``--repeats`` alternates the modes per repetition; the summary pairs
the per-instance MEDIANS of UB, LB and gap.

Usage::

    python -m benchmark.study_lbbd_sound_cuts --repeats 3 --out-dir benchmark/results/sound
    python -m benchmark.study_lbbd_sound_cuts --quick --out-dir /tmp/sound   # 3 instances
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any

from benchmark.evidence_common import REPO_ROOT, collect_environment, write_hashes
from benchmark.fjs_loader import load_fjs_problem
from benchmark.public_bks import BRANDIMARTE_BKS
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.model import ScheduleProblem
from synaps.solvers.feasibility_checker import FeasibilityChecker, hard_violations
from synaps.solvers.registry import create_solver

if TYPE_CHECKING:
    from collections.abc import Callable

#: gen_120 of ``scripts/golden_snapshot.py`` and two more generator seeds.
GEN_120 = {
    "n_operations": 120,
    "n_machines": 6,
    "n_states": 4,
    "horizon_hours": 96,
    "n_aux_resources": 2,
    "aux_requirement_prob": 0.2,
}
GEN_SEEDS = (7, 8, 9)
LOCAL_INSTANCES = ("tiny_3x3", "medium_stress_20x4", "medium_4state_tsp_dominance_16x4")
#: Same shape as ``scripts/golden_snapshot.py`` ``gen_600``.
GEN_600 = {
    "n_operations": 600,
    "n_machines": 12,
    "n_states": 6,
    "horizon_hours": 240,
    "n_aux_resources": 3,
    "aux_requirement_prob": 0.1,
    "seed": 11,
}


def _instances(quick: bool, only: set[str]) -> list[tuple[str, Callable[[], ScheduleProblem]]]:
    brandimarte = REPO_ROOT / "benchmark" / "instances" / "public" / "brandimarte"
    local = REPO_ROOT / "benchmark" / "instances"
    cases: list[tuple[str, Callable[[], ScheduleProblem]]] = [
        (f"gen_120_s{seed}", lambda seed=seed: generate_large_instance(**GEN_120, seed=seed))
        for seed in GEN_SEEDS
    ]
    cases += [
        (
            name,
            lambda name=name: ScheduleProblem.model_validate(
                json.loads((local / f"{name}.json").read_text("utf-8"))
            ),
        )
        for name in LOCAL_INSTANCES
    ]
    cases += [
        (stem, lambda stem=stem: load_fjs_problem(brandimarte / f"{stem}.fjs"))
        for stem in sorted(BRANDIMARTE_BKS)
    ]
    if quick:
        keep = {"gen_120_s7", "tiny_3x3", "mk01"}
        cases = [case for case in cases if case[0] in keep]
    if "gen_600" in only:
        cases.append(
            ("gen_600", lambda: generate_large_instance(**GEN_600)),
        )
    if only:
        cases = [case for case in cases if case[0] in only]
    return cases


def run_case(problem: ScheduleProblem, config: str, sound: bool, seed: int) -> dict[str, Any]:
    solver, kwargs = create_solver(config)
    started = time.monotonic()
    result = solver.solve(problem, **{**kwargs, "random_seed": seed, "sound_cuts": sound})
    wall = time.monotonic() - started
    meta = result.metadata
    ub = result.objective.makespan_minutes if result.assignments else None
    lb = float(meta.get("lower_bound", 0.0) or 0.0)
    violations = hard_violations(FeasibilityChecker().check(problem, result.assignments))
    return {
        "mode": "sound" if sound else "default",
        "status": str(result.status),
        "makespan": ub,
        "lower_bound": lb,
        "gap": (ub - lb) / ub if ub else None,
        "wall_s": round(wall, 3),
        "iterations": meta.get("iterations"),
        "lower_bound_method": meta.get("lower_bound_method"),
        "lower_bound_invariant_violated": meta.get("lower_bound_invariant_violated"),
        "sound_cuts": meta.get("sound_cuts"),
        "hard_violations": len(violations),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--config", default="LBBD-5")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated instance names; include gen_600 to add that instance",
    )
    args = parser.parse_args(argv)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    only = {name.strip() for name in args.only.split(",") if name.strip()}
    rows: list[dict[str, Any]] = []
    for name, load in _instances(args.quick, only):
        problem = load()
        for repeat, sound in itertools.product(range(args.repeats), (False, True)):
            if repeat % 2:
                sound = not sound  # alternate which mode runs first
            row = {
                "instance": name,
                "ops": len(problem.operations),
                "config": args.config,
                "repeat": repeat,
            }
            row.update(run_case(problem, args.config, sound, args.seed))
            bks = BRANDIMARTE_BKS.get(name)
            row["bks"] = bks
            if bks is not None and row["lower_bound"] > bks + 1e-6:
                raise SystemExit(f"{name}: lower bound {row['lower_bound']} > BKS {bks}")
            rows.append(row)
            print(
                f"{name:34s} {row['mode']:7s} ub={row['makespan']} lb={row['lower_bound']:.2f} "
                f"gap={row['gap']} wall={row['wall_s']}s viol={row['hard_violations']}",
                flush=True,
            )
    summary = _summarize(rows)
    runs = args.out_dir / "runs.json"
    runs.write_text(json.dumps({"runs": rows, "summary": summary}, indent=1), encoding="utf-8")
    env = args.out_dir / "environment.json"
    env.write_text(json.dumps(collect_environment(), indent=1), encoding="utf-8")
    write_hashes(args.out_dir, [runs, env])
    print(json.dumps(summary, indent=1))
    return 0


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-instance medians per mode, then means over the paired instances."""
    by_instance: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        by_instance.setdefault(row["instance"], {}).setdefault(row["mode"], []).append(row)
    paired: list[tuple[dict[str, float], dict[str, float]]] = []
    for modes in by_instance.values():
        medians = {}
        for mode, runs in modes.items():
            if any(r["gap"] is None for r in runs):
                break
            medians[mode] = {
                key: float(median(r[key] for r in runs))
                for key in ("gap", "lower_bound", "makespan", "wall_s")
            }
        else:
            if {"default", "sound"} <= medians.keys():
                paired.append((medians["default"], medians["sound"]))
    if not paired:
        return {"paired_instances": 0}
    n = len(paired)
    return {
        "paired_instances": n,
        "statistic": "per-instance median over repeats, then mean over instances",
        "mean_gap_default": sum(d["gap"] for d, _ in paired) / n,
        "mean_gap_sound": sum(s["gap"] for _, s in paired) / n,
        "instances_gap_lower": sum(s["gap"] < d["gap"] - 1e-9 for d, s in paired),
        "instances_gap_higher": sum(s["gap"] > d["gap"] + 1e-9 for d, s in paired),
        "instances_lb_raised": sum(s["lower_bound"] > d["lower_bound"] + 1e-6 for d, s in paired),
        "instances_lb_lowered": sum(s["lower_bound"] < d["lower_bound"] - 1e-6 for d, s in paired),
        "instances_ub_better": sum(s["makespan"] < d["makespan"] - 1e-6 for d, s in paired),
        "instances_ub_worse": sum(s["makespan"] > d["makespan"] + 1e-6 for d, s in paired),
        "any_lb_invariant_violated": any(bool(r["lower_bound_invariant_violated"]) for r in rows),
        "any_hard_violations": any(r["hard_violations"] for r in rows),
    }


if __name__ == "__main__":
    raise SystemExit(main())
