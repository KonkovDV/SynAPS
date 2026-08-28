"""3000@8 machine-calendar coverage (K2.1). Not the per-op night analog.

Geometry: ``generate_large_instance`` with empty per-op windows, then a
night shift calendar (22:00-06:00) on every work center. Solver: RHC-GREEDY.
Do not cite 0.7702 from the dead-zone study — that number is per-op windows
on a 24/7 machine.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchmark.evidence_common import REPO_ROOT, collect_environment, write_hashes
from synaps.accelerators import get_acceleration_status
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.calendar import delay_start_to_open_shift
from synaps.model import (
    ScheduleProblem,
    ScheduleResult,
    ShiftInterval,
    WorkCenter,
)
from synaps.solvers.registry import create_solver
from synaps.timegrain import duration_minutes_for
from synaps.validation import verify_schedule_result

if TYPE_CHECKING:
    from uuid import UUID

DEFAULT_OUT = REPO_ROOT / "benchmark" / "evidence" / "calendar-3000-8m-2026-08-27"
NIGHT_START_HOUR = 22
NIGHT_HOURS = 8
N_OPERATIONS = 3000
N_MACHINES = 8
SOLVER_CONFIG = "RHC-GREEDY"

WINDOW_CLOSED = "WINDOW_CLOSED"
NO_CREW_CAPACITY = "NO_CREW_CAPACITY"
IMPOSSIBLE_BY_CONSTRUCTION = "IMPOSSIBLE_BY_CONSTRUCTION"
GOST_PRIORITY_PREEMPTED = "GOST_PRIORITY_PREEMPTED"
REASON_CODES = (
    WINDOW_CLOSED,
    NO_CREW_CAPACITY,
    IMPOSSIBLE_BY_CONSTRUCTION,
    GOST_PRIORITY_PREEMPTED,
)


def night_shift_intervals(horizon_start: Any, horizon_end: Any) -> list[ShiftInterval]:
    """One 22:00-06:00 interval per calendar day, clipped to the horizon."""

    intervals: list[ShiftInterval] = []
    day = horizon_start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= horizon_end:
        start = day + timedelta(hours=NIGHT_START_HOUR)
        end = start + timedelta(hours=NIGHT_HOURS)
        if start >= horizon_end:
            break
        if start < horizon_start:
            start = horizon_start
        if end > horizon_end:
            end = horizon_end
        if end > start:
            intervals.append(ShiftInterval(start=start, end=end))
        day += timedelta(days=1)
    return intervals


def apply_night_machine_calendar(problem: ScheduleProblem) -> ScheduleProblem:
    """Stamp every work center with the night shift list. Ops stay window-free."""

    intervals = night_shift_intervals(problem.planning_horizon_start, problem.planning_horizon_end)
    stamped: list[WorkCenter] = [
        wc.model_copy(update={"calendar": list(intervals)}) for wc in problem.work_centers
    ]
    return problem.model_copy(update={"work_centers": stamped})


def generate_calendar_problem(*, seed: int) -> ScheduleProblem:
    raw = generate_large_instance(
        n_operations=N_OPERATIONS,
        n_machines=N_MACHINES,
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
    return apply_night_machine_calendar(raw)


def _worst_incoming_setup(problem: ScheduleProblem, work_center_id: UUID, to_state: UUID) -> int:
    setups = [
        entry.setup_minutes
        for entry in problem.setup_matrix
        if entry.work_center_id == work_center_id and entry.to_state_id == to_state
    ]
    return max(setups, default=0)


def _max_shift_minutes(calendar: list[ShiftInterval]) -> float:
    if not calendar:
        return float("inf")
    return max((iv.end - iv.start).total_seconds() / 60.0 for iv in calendar)


def classify_unplaced_operation(
    problem: ScheduleProblem,
    operation: Any,
) -> dict[str, Any]:
    """Attribute one leftover op. GOST is a domain code; kernel study yields 0."""

    wc_by_id = {wc.id: wc for wc in problem.work_centers}
    eligible = operation.eligible_wc_ids or list(wc_by_id)
    horizon_start = problem.planning_horizon_start
    earliest = 0.0
    if operation.earliest_start is not None:
        earliest = max(
            0.0,
            (operation.earliest_start - horizon_start).total_seconds() / 60.0,
        )
    latest: float | None = None
    if operation.latest_finish is not None:
        latest = (operation.latest_finish - horizon_start).total_seconds() / 60.0

    min_occupancy = float("inf")
    max_shift = 0.0
    fits_empty_machine = False
    for wc_id in eligible:
        wc = wc_by_id.get(wc_id)
        if wc is None:
            continue
        calendar = list(wc.calendar or [])
        max_shift = max(max_shift, _max_shift_minutes(calendar))
        duration = float(duration_minutes_for(operation, wc))
        occupancy = duration + float(_worst_incoming_setup(problem, wc.id, operation.state_id))
        min_occupancy = min(min_occupancy, occupancy)
        slot = delay_start_to_open_shift(earliest, occupancy, calendar, horizon_start)
        if slot is None:
            continue
        if latest is not None and slot + occupancy > latest + 1e-9:
            continue
        fits_empty_machine = True

    if min_occupancy == float("inf"):
        min_occupancy = 0.0
    if min_occupancy > max_shift + 1e-9:
        reason = IMPOSSIBLE_BY_CONSTRUCTION
    elif not fits_empty_machine:
        reason = WINDOW_CLOSED
    else:
        reason = NO_CREW_CAPACITY
    return {
        "operation_id": str(operation.id),
        "order_id": str(operation.order_id),
        "seq_in_order": operation.seq_in_order,
        "reason": reason,
        "occupancy_min": round(min_occupancy, 3),
        "max_shift_min": round(max_shift, 3) if max_shift != float("inf") else None,
    }


def classify_unplaced(
    problem: ScheduleProblem, result: ScheduleResult
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    scheduled = {assignment.operation_id for assignment in result.assignments}
    rows = [
        classify_unplaced_operation(problem, operation)
        for operation in problem.operations
        if operation.id not in scheduled
    ]
    counts = Counter(row["reason"] for row in rows)
    tallies = {code: int(counts.get(code, 0)) for code in REASON_CODES}
    return rows, tallies


def run_one(*, seed: int) -> dict[str, Any]:
    gen_t0 = time.perf_counter()
    problem = generate_calendar_problem(seed=seed)
    generate_s = time.perf_counter() - gen_t0
    has_op_windows = any(
        op.earliest_start is not None or op.latest_finish is not None for op in problem.operations
    )
    solver, kwargs = create_solver(SOLVER_CONFIG)
    kwargs = {**kwargs, "random_seed": seed}
    solve_t0 = time.perf_counter()
    result = solver.solve(problem, **kwargs)
    wall_s = time.perf_counter() - solve_t0
    verification = verify_schedule_result(problem, result)
    unplaced, tallies = classify_unplaced(problem, result)
    scheduled = len(result.assignments)
    total = len(problem.operations)
    meta = dict(result.metadata or {})
    accel = get_acceleration_status()
    return {
        "protocol": "machine-calendar-3000-8-2026-08-27",
        "geometry": "work_center.calendar night 22:00-06:00; per-op windows empty",
        "not_the_deadzone_ratio": "0.7702 is per-op windows on 24/7 machines; do not reuse",
        "n_operations_requested": N_OPERATIONS,
        "ops_generated": total,
        "n_machines": N_MACHINES,
        "solver_config": SOLVER_CONFIG,
        "seed": seed,
        "ops_scheduled": scheduled,
        "scheduled_ratio": scheduled / total if total else 0.0,
        "unplaced_count": len(unplaced),
        "status": result.status.value,
        "verified_feasible": verification.feasible,
        "independent_violation_kinds": verification.violation_kinds,
        "notary_hard_violation_kinds": meta.get("notary_hard_violation_kinds"),
        "notary_hard_violation_count": meta.get("notary_hard_violation_count"),
        "search_stop_reason": meta.get("search_stop_reason"),
        "time_limit_reached": meta.get("time_limit_reached"),
        "generate_s": round(generate_s, 3),
        "wall_time_s": round(wall_s, 3),
        "has_per_op_windows": has_op_windows,
        "has_machine_calendar": True,
        "night_start_hour": NIGHT_START_HOUR,
        "night_hours": NIGHT_HOURS,
        "reason_counts": tallies,
        "unplaced": unplaced,
        "native_probe": False,
        "bypass_gate": False,
        "native_available": accel.get("native_available"),
        "native_backend": accel.get("list_schedule_cover_backend"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seeds", default="1,42,999")
    parser.add_argument(
        "--session-id",
        default="",
        help="Write under out_dir/sessions/<id>/ (does not replace hashed JSON)",
    )
    parser.add_argument(
        "--native-probe",
        action="store_true",
        help="Bypass n>=10000 native gate in this process only. Kernel default stays 10_000.",
    )
    args = parser.parse_args(argv)
    out_dir: Path = args.out_dir
    if str(args.session_id).strip():
        out_dir = out_dir / "sessions" / str(args.session_id).strip()
    out_dir.mkdir(parents=True, exist_ok=True)
    seeds = [int(tok) for tok in str(args.seeds).split(",") if tok.strip()]
    if args.native_probe:
        from synaps.solvers.rhc import _cover as rhc_cover

        rhc_cover._NATIVE_LIST_SCHEDULE_MIN_OPS = 0
    env_path = out_dir / "environment.json"
    env_path.write_text(
        json.dumps(collect_environment(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    runs: list[dict[str, Any]] = []
    for seed in seeds:
        path = out_dir / f"run_3000ops_8m_RHC_GREEDY_calendar_seed{seed}.json"
        print(f"run seed={seed}", flush=True)
        record = run_one(seed=seed)
        record["native_probe"] = bool(args.native_probe)
        record["bypass_gate"] = bool(args.native_probe)
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(
            f"  ratio={record['scheduled_ratio']:.4f} wall={record['wall_time_s']} "
            f"status={record['status']} reasons={record['reason_counts']}",
            flush=True,
        )
        runs.append(record)
    summary = {
        "protocol": "machine-calendar-3000-8-2026-08-27",
        "solver_config": SOLVER_CONFIG,
        "seeds": seeds,
        "scheduled_ratios": [row["scheduled_ratio"] for row in runs],
        "walls_s": [row["wall_time_s"] for row in runs],
        "reason_counts_by_seed": {str(row["seed"]): row["reason_counts"] for row in runs},
        "notary_kinds_by_seed": {
            str(row["seed"]): row["notary_hard_violation_kinds"] for row in runs
        },
        "native_probe": bool(args.native_probe),
        "bypass_gate": bool(args.native_probe),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    files = sorted(
        path for path in out_dir.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"
    )
    write_hashes(out_dir, files)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
