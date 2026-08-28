"""COVER scale ladder: hashed, multi-seed evidence for RHC-GREEDY-COVER.

Re-runs the Unreleased CHANGELOG scales at seeds 1, 42, 999. Does not retune
thresholds. Writes JSON under benchmark/evidence/ (tracked) because
benchmark/studies/ is gitignored and cannot carry SHA-256 claims.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from benchmark.evidence_common import (
    REPO_ROOT,
    collect_environment,
    peak_rss_bytes,
    summarize_seed,
    write_hashes,
)
from synaps.accelerators import get_acceleration_status
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.solvers.registry import create_solver
from synaps.validation import verify_schedule_result

DEFAULT_OUT = REPO_ROOT / "benchmark" / "evidence" / "cover-ladder-2026-08-25"
SEEDS = (1, 42, 999)
SOLVER_CONFIG = "RHC-GREEDY-COVER"

# Topology copied from CHANGELOG [Unreleased] generator kwargs (keyword form;
# the positional `generate_large_instance(500000, ...)` in CHANGELOG is invalid
# because the function is keyword-only).
SCALES: tuple[dict[str, Any], ...] = (
    {
        "scale_id": "60k@100",
        "n_operations": 60_000,
        "n_machines": 100,
        "horizon_hours": 720,
    },
    {
        "scale_id": "100k@200",
        "n_operations": 100_000,
        "n_machines": 200,
        "horizon_hours": 720,
    },
    {
        "scale_id": "200k@400",
        "n_operations": 200_000,
        "n_machines": 400,
        "n_aux_resources": 40,
        "horizon_hours": 720,
    },
    {
        "scale_id": "500k@1000",
        "n_operations": 500_000,
        "n_machines": 1000,
        "n_aux_resources": 100,
        "machine_flexibility": 0.05,
        "horizon_hours": 720,
    },
)


def _run_path(out_dir: Path, scale_id: str, seed: int) -> Path:
    safe = scale_id.replace("@", "_at_")
    return out_dir / f"run_{safe}_seed{seed}.json"


def run_one(scale: dict[str, Any], seed: int) -> dict[str, Any]:
    gen_kwargs = {k: v for k, v in scale.items() if k != "scale_id"}
    gen_kwargs["seed"] = seed
    gen_t0 = time.perf_counter()
    problem = generate_large_instance(**gen_kwargs)
    generate_s = time.perf_counter() - gen_t0
    horizon_min = (
        problem.planning_horizon_end - problem.planning_horizon_start
    ).total_seconds() / 60.0
    solver, kwargs = create_solver(SOLVER_CONFIG)
    kwargs = {**kwargs, "random_seed": seed}
    rss_before = peak_rss_bytes()
    print(f"  solving {len(problem.operations)} ops...", flush=True)
    solve_t0 = time.perf_counter()
    result = solver.solve(problem, **kwargs)
    wall_s = time.perf_counter() - solve_t0
    rss_after = peak_rss_bytes()
    print(f"  solved in {wall_s:.1f}s, independent notary...", flush=True)
    verification = verify_schedule_result(problem, result)
    meta = dict(result.metadata or {})
    accel = meta.get("acceleration") or get_acceleration_status()
    notary_count = int(meta.get("notary_hard_violation_count", -1))
    notary_kinds = list(meta.get("notary_hard_violation_kinds") or [])
    scheduled = len(result.assignments)
    total = len(problem.operations)
    rss_mb = None
    if rss_after is not None:
        rss_mb = round(rss_after / (1024 * 1024), 1)
    return {
        "scale_id": scale["scale_id"],
        "seed": seed,
        "generator_kwargs": gen_kwargs,
        "ops_generated": total,
        "ops_scheduled": scheduled,
        "scheduled_ratio": scheduled / total if total else 0.0,
        "status": result.status.value,
        "verified_feasible": verification.feasible,
        "independent_violation_count": verification.violation_count,
        "independent_violation_kinds": verification.violation_kinds,
        "notary_hard_violation_count": notary_count,
        "notary_hard_violation_kinds": notary_kinds,
        "notary_empty": notary_count == 0 and verification.feasible,
        "makespan_minutes": result.objective.makespan_minutes if result.objective else None,
        "horizon_minutes": horizon_min,
        "generate_s": round(generate_s, 3),
        "wall_time_s": round(wall_s, 3),
        "peak_rss_bytes": rss_after,
        "peak_rss_mb": rss_mb,
        "rss_before_bytes": rss_before,
        "native_backend": accel.get("list_schedule_cover_backend"),
        "native_available": accel.get("native_available"),
        "global_greedy_cover": meta.get("global_greedy_cover"),
        "commit_precedence_gate_enabled": meta.get("commit_precedence_gate_enabled"),
        "determinism": meta.get("determinism"),
        "determinism_violated": meta.get("determinism_violated"),
        "time_limit_reached": meta.get("time_limit_reached"),
        "search_stop_reason": meta.get("search_stop_reason"),
        "horizon_clipped_assignments": meta.get("horizon_clipped_assignments"),
        "ops_unscheduled": meta.get("ops_unscheduled"),
        "temporal_stabilization": meta.get("temporal_stabilization"),
    }


def aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_scale: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        by_scale.setdefault(run["scale_id"], []).append(run)
    summary = {}
    for scale_id, group in by_scale.items():
        completed = [
            r for r in group if not r.get("stalled") and r.get("scheduled_ratio") is not None
        ]
        makespans = [
            float(row["makespan_minutes"])
            for row in completed
            if row.get("makespan_minutes") is not None
        ]
        walls = [float(r["wall_time_s"]) for r in completed if r.get("wall_time_s") is not None]
        ratios = [float(r["scheduled_ratio"]) for r in completed]
        rss = [float(r["peak_rss_mb"]) for r in completed if r.get("peak_rss_mb") is not None]
        summary[scale_id] = {
            "n_seeds": len(group),
            "n_completed": len(completed),
            "n_stalled": sum(1 for r in group if r.get("stalled")),
            "seeds": [r["seed"] for r in group],
            "all_verified_feasible": bool(completed)
            and all(r.get("verified_feasible") for r in completed)
            and not any(r.get("stalled") for r in group),
            "all_notary_empty": bool(completed) and all(r.get("notary_empty") for r in completed),
            "any_determinism_violated": any(r.get("determinism_violated") for r in completed),
            "scheduled_ratio": summarize_seed(ratios),
            "makespan_minutes": summarize_seed(makespans),
            "wall_time_s": summarize_seed(walls),
            "peak_rss_mb": summarize_seed(rss),
            "ops_generated": [r.get("ops_generated") for r in group],
        }
    return summary


def _ci_gate_failures(runs: list[dict[str, Any]], *, max_wall_s: float) -> list[str]:
    """Linux PR COVER cell: native list-schedule, full coverage, not a stall."""

    failures: list[str] = []
    if not runs:
        return ["no COVER runs"]
    for record in runs:
        label = f"{record.get('scale_id')} seed={record.get('seed')}"
        if record.get("stalled"):
            failures.append(f"{label}: stalled")
            continue
        if record.get("scheduled_ratio") != 1.0:
            failures.append(f"{label}: scheduled_ratio={record.get('scheduled_ratio')}")
        if record.get("verified_feasible") is not True:
            failures.append(f"{label}: verified_feasible={record.get('verified_feasible')}")
        if record.get("native_backend") != "native":
            failures.append(f"{label}: native_backend={record.get('native_backend')}")
        wall = record.get("wall_time_s")
        if not isinstance(wall, int | float) or wall > max_wall_s:
            failures.append(f"{label}: wall_time_s={wall} exceeds {max_wall_s}")
    return failures


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seeds", default="1,42,999")
    parser.add_argument(
        "--scales",
        default=",".join(item["scale_id"] for item in SCALES),
        help="Comma-separated scale_id values",
    )
    parser.add_argument("--resume", action="store_true", help="Skip existing run_*.json files")
    parser.add_argument(
        "--session-id",
        default="",
        help="Write this run under out_dir/sessions/<id>/ (does not replace historical files)",
    )
    parser.add_argument(
        "--ci-gate",
        action="store_true",
        help="Exit 1 unless every run is native, ratio 1.0, verified, and under --max-wall-s",
    )
    parser.add_argument(
        "--max-wall-s",
        type=float,
        default=180.0,
        help="CI gate wall-time cap per cell (seconds)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir: Path = args.out_dir
    if str(args.session_id).strip():
        out_dir = out_dir / "sessions" / str(args.session_id).strip()
    out_dir.mkdir(parents=True, exist_ok=True)
    env = collect_environment()
    env_path = out_dir / "environment.json"
    if not (args.resume and env_path.exists()):
        env_path.write_text(json.dumps(env, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seeds = tuple(int(item.strip()) for item in str(args.seeds).split(",") if item.strip())
    wanted = {item.strip() for item in str(args.scales).split(",") if item.strip()}
    runs: list[dict[str, Any]] = []
    for scale in SCALES:
        if scale["scale_id"] not in wanted:
            continue
        for seed in seeds:
            path = _run_path(out_dir, scale["scale_id"], seed)
            if args.resume and path.exists():
                runs.append(json.loads(path.read_text(encoding="utf-8")))
                print(f"resume {path.name}", flush=True)
                continue
            print(f"run {scale['scale_id']} seed={seed}", flush=True)
            record = run_one(scale, seed)
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            runs.append(record)
            ratio = record.get("scheduled_ratio")
            ratio_s = f"{ratio:.4f}" if isinstance(ratio, int | float) else str(ratio)
            print(
                f"  ratio={ratio_s} "
                f"feasible={record.get('verified_feasible')} "
                f"notary={record.get('notary_hard_violation_count')} "
                f"wall={record.get('wall_time_s')}s "
                f"rss={record.get('peak_rss_mb')}MB "
                f"native={record.get('native_backend')}",
                flush=True,
            )
    if args.resume:
        runs = []
        for path in sorted(out_dir.glob("run_*.json")):
            runs.append(json.loads(path.read_text(encoding="utf-8")))
    summary = {
        "protocol": "COVER ladder 2026-08-25",
        "solver_config": SOLVER_CONFIG,
        "seeds": list(seeds),
        "environment_file": "environment.json",
        "by_scale": aggregate(runs),
        "runs": runs,
    }
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_hashes(out_dir, sorted(out_dir.glob("*.json")))
    print(f"wrote {out_dir}", flush=True)
    if args.ci_gate:
        failures = _ci_gate_failures(runs, max_wall_s=float(args.max_wall_s))
        if failures:
            print("COVER CI gate failed:", flush=True)
            for item in failures:
                print(f"  {item}", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
