"""5k dead-zone matrix: 3k/5k/8k ops x 4/8/12 machines, night-analog windows.

Does not retune COVER/router thresholds. Named configs run with registry
kwargs (including ALNS-500 time_limit_s=300). Writes hashed JSON under
benchmark/evidence/deadzone-5k-2026-08-25/.
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import timedelta
from pathlib import Path
from typing import Any

from benchmark.evidence_common import (
    REPO_ROOT,
    collect_environment,
    write_hashes,
)
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.model import Operation, ScheduleProblem  # noqa: TC001
from synaps.solvers.registry import create_solver
from synaps.validation import verify_schedule_result

DEFAULT_OUT = REPO_ROOT / "benchmark" / "evidence" / "deadzone-5k-2026-08-25"
SOLVERS = (
    "GREED",
    "ALNS-500",
    "RHC-GREEDY",
    "RHC-GREEDY-COVER",
    "RHC-ALNS-SEARCH-COVER",
)
OPS = (3000, 5000, 8000)
MACHINES = (4, 8, 12)
NIGHT_HOURS = 8
NIGHT_START_HOUR = 22


def apply_consecutive_night_windows(problem: ScheduleProblem) -> ScheduleProblem:
    """Encode night-work analog without a machine calendar.

    Kernel WorkCenter has no shift calendar. Each operation gets a single
    8-hour [earliest_start, latest_finish] on consecutive nights by
    seq_in_order. Orders are spread across the horizon by enumeration index.
    Daytime between nights is inside the interval of a multi-night chain only
    for different ops; a single op cannot straddle days.
    """
    horizon_start = problem.planning_horizon_start
    horizon_end = problem.planning_horizon_end
    horizon_days = max(1, int((horizon_end - horizon_start).total_seconds() // 86400))
    order_ids = [order.id for order in problem.orders]
    order_index = {oid: i for i, oid in enumerate(order_ids)}
    max_seq = dict.fromkeys(order_ids, 0)
    for operation in problem.operations:
        max_seq[operation.order_id] = max(max_seq[operation.order_id], operation.seq_in_order)

    stamped: list[Operation] = []
    for operation in problem.operations:
        spread = max(1, horizon_days - max_seq[operation.order_id] - 2)
        first_day = order_index[operation.order_id] % spread
        night_day = first_day + max(0, operation.seq_in_order)
        start = horizon_start + timedelta(days=night_day, hours=NIGHT_START_HOUR)
        finish = start + timedelta(hours=NIGHT_HOURS)
        if finish > horizon_end:
            finish = horizon_end
            start = max(horizon_start, finish - timedelta(hours=NIGHT_HOURS))
        stamped.append(
            operation.model_copy(update={"earliest_start": start, "latest_finish": finish})
        )
    return problem.model_copy(update={"operations": stamped})


def generate_deadzone_problem(*, n_operations: int, n_machines: int, seed: int) -> ScheduleProblem:
    raw = generate_large_instance(
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
    return apply_consecutive_night_windows(raw)


def _run_path(out_dir: Path, ops: int, machines: int, solver: str, seed: int) -> Path:
    safe = solver.replace("-", "_")
    return out_dir / f"run_{ops}ops_{machines}m_{safe}_seed{seed}.json"


def _watchdog_s(solver_config: str) -> float:
    """Study isolation only. Does not change registry kwargs.

    GREED/BEAM registry ``time_limit_s`` is 120 s. Isolation slack covers
    generate + independent notary. This watchdog is not a solver retune.
    """
    _, kwargs = create_solver(solver_config)
    limit = kwargs.get("time_limit_s")
    if limit is None:
        return 600.0
    return float(limit) + 90.0


def _stall_record(
    *,
    n_operations: int,
    n_machines: int,
    solver_config: str,
    seed: int,
    watchdog_s: float,
) -> dict[str, Any]:
    return {
        "n_operations_requested": n_operations,
        "ops_generated": None,
        "n_machines": n_machines,
        "solver_config": solver_config,
        "seed": seed,
        "ops_scheduled": None,
        "scheduled_ratio": None,
        "status": "stalled",
        "stalled": True,
        "verified_feasible": False,
        "independent_violation_count": None,
        "independent_violation_kinds": None,
        "notary_hard_violation_count": None,
        "notary_hard_violation_kinds": None,
        "makespan_minutes": None,
        "generate_s": None,
        "wall_time_s": watchdog_s,
        "global_greedy_cover": None,
        "determinism": None,
        "determinism_violated": None,
        "time_limit_reached": None,
        "search_stop_reason": "study_killed_stall",
        "night_window_hours": NIGHT_HOURS,
        "night_start_hour": NIGHT_START_HOUR,
        "stall_watchdog_s": watchdog_s,
        "stall_note": (
            "Worker killed after study watchdog. Registry kwargs unchanged. "
            "Isolation uses named time_limit_s + 90s slack (GREED/BEAM 120s → 210s)."
        ),
    }


def run_one(
    *,
    n_operations: int,
    n_machines: int,
    solver_config: str,
    seed: int,
) -> dict[str, Any]:
    gen_t0 = time.perf_counter()
    problem = generate_deadzone_problem(n_operations=n_operations, n_machines=n_machines, seed=seed)
    generate_s = time.perf_counter() - gen_t0
    print(
        f"    generated {len(problem.operations)} ops in {generate_s:.2f}s, solving...",
        flush=True,
    )
    solver, kwargs = create_solver(solver_config)
    kwargs = {**kwargs, "random_seed": seed}
    solve_t0 = time.perf_counter()
    result = solver.solve(problem, **kwargs)
    wall_s = time.perf_counter() - solve_t0
    verification = verify_schedule_result(problem, result)
    meta = dict(result.metadata or {})
    scheduled = len(result.assignments)
    total = len(problem.operations)
    return {
        "n_operations_requested": n_operations,
        "ops_generated": total,
        "n_machines": n_machines,
        "solver_config": solver_config,
        "seed": seed,
        "ops_scheduled": scheduled,
        "scheduled_ratio": scheduled / total if total else 0.0,
        "status": result.status.value,
        "verified_feasible": verification.feasible,
        "independent_violation_count": verification.violation_count,
        "independent_violation_kinds": verification.violation_kinds,
        "notary_hard_violation_count": meta.get("notary_hard_violation_count"),
        "notary_hard_violation_kinds": meta.get("notary_hard_violation_kinds"),
        "makespan_minutes": result.objective.makespan_minutes if result.objective else None,
        "generate_s": round(generate_s, 3),
        "wall_time_s": round(wall_s, 3),
        "global_greedy_cover": meta.get("global_greedy_cover"),
        "determinism": meta.get("determinism"),
        "determinism_violated": meta.get("determinism_violated"),
        "time_limit_reached": meta.get("time_limit_reached"),
        "search_stop_reason": meta.get("search_stop_reason"),
        "night_window_hours": NIGHT_HOURS,
        "night_start_hour": NIGHT_START_HOUR,
    }


def five_k_eight_answer(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """P2.3: any config with ratio=1 and verified_feasible on all three seeds at 5k@8."""
    target = [r for r in runs if r["n_operations_requested"] == 5000 and r["n_machines"] == 8]
    by_solver: dict[str, list[dict[str, Any]]] = {}
    for row in target:
        by_solver.setdefault(row["solver_config"], []).append(row)
    winners: list[str] = []
    detail = {}
    for name, group in by_solver.items():
        seeds = sorted(r["seed"] for r in group)
        ok = seeds == [1, 42, 999] and all(
            (not r.get("stalled"))
            and r.get("scheduled_ratio") == 1.0
            and r.get("verified_feasible")
            for r in group
        )
        detail[name] = {
            "seeds": seeds,
            "scheduled_ratios": [r.get("scheduled_ratio") for r in group],
            "verified_feasible": [r.get("verified_feasible") for r in group],
            "stalled": [bool(r.get("stalled")) for r in group],
            "all_three_seeds_full_feasible": ok,
        }
        if ok:
            winners.append(name)
    have_all_five = all(
        name in by_solver and sorted(r["seed"] for r in by_solver[name]) == [1, 42, 999]
        for name in SOLVERS
    )
    if winners:
        answer = "yes"
    elif have_all_five:
        answer = "no"
    else:
        answer = "incomplete"
    return {
        "question": (
            "Exists a config with scheduled_ratio=1.0 and verified_feasible=true "
            "on 5000 ops / 8 machines for seeds 1, 42, and 999?"
        ),
        "answer": answer,
        "winning_configs": winners,
        "five_named_configs_complete": have_all_five,
        "by_solver": detail,
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seeds", default="1,42,999")
    parser.add_argument("--solvers", default=",".join(SOLVERS))
    parser.add_argument("--ops", default="3000,5000,8000")
    parser.add_argument("--machines", default="4,8,12")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--session-id",
        default="",
        help="Write this run under out_dir/sessions/<id>/ (does not replace historical files)",
    )
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Solve in this process (no watchdog). Default isolates each cell.",
    )
    parser.add_argument(
        "--worker-job",
        type=Path,
        default=None,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def _run_worker_job(job_path: Path) -> int:
    faulthandler.enable()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    print(
        f"  generating {job['n_operations']}@{job['n_machines']} "
        f"{job['solver_config']} seed={job['seed']}",
        flush=True,
    )
    out = Path(job["out_path"])
    try:
        record = run_one(
            n_operations=int(job["n_operations"]),
            n_machines=int(job["n_machines"]),
            solver_config=str(job["solver_config"]),
            seed=int(job["seed"]),
        )
    except Exception as exc:
        record = _stall_record(
            n_operations=int(job["n_operations"]),
            n_machines=int(job["n_machines"]),
            solver_config=str(job["solver_config"]),
            seed=int(job["seed"]),
            watchdog_s=0.0,
        )
        record["status"] = "worker_error"
        record["stalled"] = False
        record["search_stop_reason"] = "worker_exception"
        record["stall_note"] = f"{type(exc).__name__}: {exc}"
        record["worker_traceback"] = traceback.format_exc()[-8000:]
        record["wall_time_s"] = None
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        import resource as _resource

        record["worker_peak_rss_raw"] = _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError):
        record["worker_peak_rss_raw"] = None
    out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(_format_ratio_line(record), flush=True)
    return 0


def _format_ratio_line(record: dict[str, Any]) -> str:
    ratio = record.get("scheduled_ratio")
    ratio_s = f"{ratio:.4f}" if isinstance(ratio, int | float) else str(ratio)
    return (
        f"  ratio={ratio_s} "
        f"feasible={record.get('verified_feasible')} "
        f"status={record.get('status')} wall={record.get('wall_time_s')}s"
    )


def _run_isolated_cell(
    *,
    n_ops: int,
    n_m: int,
    solver_config: str,
    seed: int,
    path: Path,
) -> dict[str, Any]:
    watchdog = _watchdog_s(solver_config)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="deadzone-job-",
        delete=False,
        encoding="utf-8",
    ) as job_file:
        job_path = Path(job_file.name)
        json.dump(
            {
                "n_operations": n_ops,
                "n_machines": n_m,
                "solver_config": solver_config,
                "seed": seed,
                "out_path": str(path),
            },
            job_file,
            indent=2,
            sort_keys=True,
        )
        job_file.write("\n")
    try:
        cmd = [sys.executable, "-m", "benchmark.study_deadzone_5k", "--worker-job", str(job_path)]
        print(f"  watchdog={watchdog:.0f}s isolate={solver_config}", flush=True)
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                timeout=watchdog,
                check=False,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired as exc:
            record = _stall_record(
                n_operations=n_ops,
                n_machines=n_m,
                solver_config=solver_config,
                seed=seed,
                watchdog_s=watchdog,
            )
            stderr_raw = exc.stderr
            stdout_raw = exc.stdout
            if isinstance(stderr_raw, bytes):
                stderr_raw = stderr_raw.decode("utf-8", errors="replace")
            if isinstance(stdout_raw, bytes):
                stdout_raw = stdout_raw.decode("utf-8", errors="replace")
            record["worker_stderr_tail"] = (stderr_raw or "")[-4000:]
            record["worker_stdout_tail"] = (stdout_raw or "")[-2000:]
            record["worker_returncode"] = None
            record["worker_signal"] = "timeout"
            stderr_path = path.with_name(path.name + ".stderr.txt")
            stderr_path.write_text(stderr_raw or "", encoding="utf-8")
            record["worker_stderr_file"] = stderr_path.name
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(
                f"  STALL watchdog={watchdog:.0f}s {solver_config} {n_ops}@{n_m} seed={seed}",
                flush=True,
            )
            return record
        if completed.returncode != 0 or not path.exists():
            record = _stall_record(
                n_operations=n_ops,
                n_machines=n_m,
                solver_config=solver_config,
                seed=seed,
                watchdog_s=watchdog,
            )
            record["status"] = "worker_error"
            record["search_stop_reason"] = "worker_exit_nonzero"
            stderr_tail = (completed.stderr or "")[-4000:]
            stdout_tail = (completed.stdout or "")[-2000:]
            record["stall_note"] = (
                f"Worker process exited {completed.returncode} before writing a result. "
                "Not a named-config timebox."
            )
            record["worker_returncode"] = completed.returncode
            if completed.returncode is not None and completed.returncode < 0:
                record["worker_signal"] = -completed.returncode
            record["worker_stderr_tail"] = stderr_tail
            record["worker_stdout_tail"] = stdout_tail
            stderr_path = path.with_name(path.name + ".stderr.txt")
            stderr_path.write_text(completed.stderr or "", encoding="utf-8")
            record["worker_stderr_file"] = stderr_path.name
            path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return record
        return json.loads(path.read_text(encoding="utf-8"))
    finally:
        job_path.unlink(missing_ok=True)


def load_all_run_records(out_dir: Path) -> list[dict[str, Any]]:
    """Every run_*.json in the evidence dir, not just this process's loop."""
    records: list[dict[str, Any]] = []
    for path in sorted(out_dir.glob("run_*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def write_summary_and_hashes(out_dir: Path, *, seeds: tuple[int, ...]) -> dict[str, Any]:
    disk_runs = load_all_run_records(out_dir)
    solvers = sorted({str(row["solver_config"]) for row in disk_runs if row.get("solver_config")})
    payload = {
        "protocol": "5k dead-zone 2026-08-25",
        "seeds": list(seeds),
        "solvers": solvers,
        "p2_3": five_k_eight_answer(disk_runs),
        "runs": disk_runs,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    hashed = sorted(path for path in out_dir.glob("*.json"))
    freeze_sums = out_dir / "SHA256SUMS_p2_3.txt"
    if freeze_sums.exists():
        hashed.append(freeze_sums)
    write_hashes(out_dir, hashed)
    return payload


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.worker_job is not None:
        return _run_worker_job(args.worker_job)
    out_dir: Path = args.out_dir
    if str(args.session_id).strip():
        out_dir = out_dir / "sessions" / str(args.session_id).strip()
    out_dir.mkdir(parents=True, exist_ok=True)
    env_path = out_dir / "environment.json"
    if not (args.resume and env_path.exists()):
        env = collect_environment()
        env_path.write_text(json.dumps(env, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seeds = tuple(int(x.strip()) for x in str(args.seeds).split(",") if x.strip())
    solvers = tuple(x.strip() for x in str(args.solvers).split(",") if x.strip())
    ops_list = tuple(int(x.strip()) for x in str(args.ops).split(",") if x.strip())
    machines = tuple(int(x.strip()) for x in str(args.machines).split(",") if x.strip())
    for n_ops in ops_list:
        for n_m in machines:
            for solver_config in solvers:
                for seed in seeds:
                    path = _run_path(out_dir, n_ops, n_m, solver_config, seed)
                    if args.resume and path.exists():
                        print(f"resume {path.name}", flush=True)
                        continue
                    print(f"run {n_ops}@{n_m} {solver_config} seed={seed}", flush=True)
                    if args.in_process:
                        record = run_one(
                            n_operations=n_ops,
                            n_machines=n_m,
                            solver_config=solver_config,
                            seed=seed,
                        )
                        path.write_text(
                            json.dumps(record, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        print(_format_ratio_line(record), flush=True)
                    else:
                        _run_isolated_cell(
                            n_ops=n_ops,
                            n_m=n_m,
                            solver_config=solver_config,
                            seed=seed,
                            path=path,
                        )
    payload = write_summary_and_hashes(out_dir, seeds=seeds)
    print(json.dumps(payload["p2_3"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
