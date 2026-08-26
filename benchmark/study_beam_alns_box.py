"""И5: BEAM-3/BEAM-5 120s box vs unbounded; ALNS-500 unconstrained search entry.

Does not retune registry defaults. Writes a new evidence folder (hashed
deadzone/COVER JSON is not rewritten). Night analog for BEAM matches the
GREED stall geometry. ALNS-500 uses unconstrained generate_large_instance.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from benchmark.evidence_common import REPO_ROOT, collect_environment, write_hashes
from benchmark.study_deadzone_5k import generate_deadzone_problem
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.solvers.registry import create_solver
from synaps.validation import verify_schedule_result

DEFAULT_OUT = REPO_ROOT / "benchmark" / "evidence" / "beam-alns-box-2026-08-26"


def _record(
    *,
    n_operations: int,
    n_machines: int,
    solver_config: str,
    seed: int,
    night_analog: bool,
    time_limit_s: float | None,
    result: Any,
    generate_s: float,
    wall_s: float,
    verification: Any,
) -> dict[str, Any]:
    meta = dict(result.metadata or {})
    scheduled = len(result.assignments)
    total = n_operations
    return {
        "n_operations_requested": n_operations,
        "ops_generated": total,
        "n_machines": n_machines,
        "solver_config": solver_config,
        "seed": seed,
        "night_analog": night_analog,
        "time_limit_s_kwarg": time_limit_s,
        "ops_scheduled": scheduled,
        "scheduled_ratio": scheduled / total if total else 0.0,
        "status": result.status.value,
        "verified_feasible": verification.feasible,
        "search_stop_reason": meta.get("search_stop_reason"),
        "time_limit_reached": meta.get("time_limit_reached"),
        "wall_clock_before_search": meta.get("search_stop_reason") == "wall_clock_before_search",
        "generate_s": round(generate_s, 3),
        "wall_time_s": round(wall_s, 3),
        "notary_hard_violation_kinds": meta.get("notary_hard_violation_kinds"),
    }


def run_one(
    *,
    n_operations: int,
    n_machines: int,
    solver_config: str,
    seed: int,
    night_analog: bool,
    boxed: bool,
) -> dict[str, Any]:
    gen_t0 = time.perf_counter()
    if night_analog:
        problem = generate_deadzone_problem(
            n_operations=n_operations, n_machines=n_machines, seed=seed
        )
    else:
        problem = generate_large_instance(
            n_operations=n_operations,
            n_machines=n_machines,
            n_states=8,
            ops_per_order=4,
            machine_flexibility=0.5,
            setup_density=0.85,
            setup_range=(10, 45),
            n_aux_resources=4,
            aux_pool_size=2,
            aux_requirement_prob=0.05,
            duration_range=(8, 24),
            horizon_hours=720,
            seed=seed,
        )
    generate_s = time.perf_counter() - gen_t0
    solver, kwargs = create_solver(solver_config)
    kwargs = {**kwargs, "random_seed": seed}
    time_limit_s: float | None = float(kwargs["time_limit_s"]) if boxed else None
    if not boxed:
        kwargs["time_limit_s"] = 10**9
    solve_t0 = time.perf_counter()
    result = solver.solve(problem, **kwargs)
    wall_s = time.perf_counter() - solve_t0
    verification = verify_schedule_result(problem, result)
    return _record(
        n_operations=len(problem.operations),
        n_machines=n_machines,
        solver_config=solver_config,
        seed=seed,
        night_analog=night_analog,
        time_limit_s=time_limit_s,
        result=result,
        generate_s=generate_s,
        wall_s=wall_s,
        verification=verification,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--mode",
        choices=("beam-boxed", "beam-unboxed", "alns-unconstrained"),
        required=True,
    )
    parser.add_argument("--seeds", default="1,42,999")
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = [int(tok) for tok in args.seeds.split(",") if tok.strip()]
    jobs: list[tuple[int, int, str, bool, bool]] = []
    if args.mode == "beam-boxed":
        for ops, machines in ((3000, 4), (5000, 8)):
            for name in ("BEAM-3", "BEAM-5"):
                jobs.append((ops, machines, name, True, True))
    elif args.mode == "beam-unboxed":
        for ops, machines in ((3000, 4), (5000, 8)):
            for name in ("BEAM-3", "BEAM-5"):
                jobs.append((ops, machines, name, True, False))
    else:
        jobs.append((5000, 8, "ALNS-500", False, True))
    env_path = out_dir / "environment.json"
    if not env_path.exists():
        env_path.write_text(
            json.dumps(collect_environment(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    for ops, machines, name, night, boxed in jobs:
        for seed in seeds:
            tag = "boxed" if boxed else "unboxed"
            geom = "night" if night else "free"
            path = (
                out_dir
                / f"run_{ops}ops_{machines}m_{name.replace('-', '_')}_{geom}_{tag}_seed{seed}.json"
            )
            if path.exists():
                print(f"skip {path.name}", flush=True)
                continue
            print(f"run {path.name}", flush=True)
            record = run_one(
                n_operations=ops,
                n_machines=machines,
                solver_config=name,
                seed=seed,
                night_analog=night,
                boxed=boxed,
            )
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(
                f"  ratio={record['scheduled_ratio']} "
                f"status={record['status']} wall={record['wall_time_s']} "
                f"stop={record['search_stop_reason']}",
                flush=True,
            )
    files = sorted(p for p in out_dir.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    write_hashes(out_dir, files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
