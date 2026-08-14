"""Nervous-month cable benchmark: high-mix, rushes, freeze/repair waves.

Synthetic. Not a live Moskabelmet month. INFIMUM 39k/40 min is not a target.
"""

from __future__ import annotations

import sys
import time
from datetime import timedelta
from typing import Any
from uuid import UUID

from synaps.domains.cable.adapter import STAGES, CableSku
from synaps.domains.cable.instance import generate_cable_instance
from synaps.domains.cable.kpis import assignment_hamming, cable_kpis
from synaps.model import Assignment, ScheduleProblem
from synaps.solvers.feasibility_checker import FeasibilityChecker, proven_hard_violations
from synaps.solvers.incremental_repair import IncrementalRepair
from synaps.solvers.registry import create_solver
from synaps.solvers.router import SolveRegime

# 6 stages (plant public range is 4–25). Extra test/pack lengthens chains and WIP.
NERVOUS_STAGES: tuple[tuple[str, str, float], ...] = STAGES + (
    ("test", "testing", 50.0),
    ("pack", "packing", 70.0),
)

_COLORS = ("BK", "RD", "WH", "BL", "GN", "GY")
_SECTIONS = (16, 35)
_FAMILIES = (("Cu", "PVC"), ("Cu", "XLPE"), ("Al", "XLPE"))


def nervous_sku_catalog() -> tuple[CableSku, ...]:
    """36 SKUs: 3 families × 6 colours × 2 sections."""

    return tuple(
        CableSku(conductor, insulation, color, section)
        for conductor, insulation in _FAMILIES
        for color in _COLORS
        for section in _SECTIONS
    )


def generate_nervous_month(
    *,
    n_orders: int = 1600,
    seed: int = 1,
    machines_per_stage: int = 16,
    drum_pool_size: int = 96,
) -> ScheduleProblem:
    """30-day high-mix make-to-order month. Default ~2×10⁴ ops after reel split.

    16 machines/stage is the measured COVER-feasible shop for this mix
    (8/stage overflows the 720 h horizon under list-schedule + SMED-scale SDST).
    """

    return generate_cable_instance(
        n_orders=n_orders,
        machines_per_stage=machines_per_stage,
        reel_capacity_m=900.0,
        drum_pool_size=drum_pool_size,
        length_range_m=(500.0, 2400.0),
        horizon_hours=720,
        campaign_slot_hours=8,
        seed=seed,
        skus=nervous_sku_catalog(),
        stages=NERVOUS_STAGES,
        rush_fraction=0.15,
        scatter_releases=True,
        shuffle_skus=True,
    )


def _cover_solver_name(operation_count: int) -> str:
    return "RHC-GREEDY-COVER" if operation_count >= 10_000 else "GREED"


def _log(message: str) -> None:
    print(f"[nervous-month] {message}", file=sys.stderr, flush=True)


def _select_rush_targets(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    freeze_end: Any,
    limit: int,
) -> list[UUID]:
    orders = {order.id: order for order in problem.orders}
    ops_by_id = {operation.id: operation for operation in problem.operations}
    ranked: list[tuple[int, UUID]] = []
    for assignment in assignments:
        if assignment.start_time < freeze_end:
            continue
        operation = ops_by_id.get(assignment.operation_id)
        if operation is None:
            continue
        ranked.append((orders[operation.order_id].priority, assignment.operation_id))
    ranked.sort(reverse=True)
    picked: list[UUID] = []
    seen: set[UUID] = set()
    for _priority, operation_id in ranked:
        if operation_id in seen:
            continue
        seen.add(operation_id)
        picked.append(operation_id)
        if len(picked) >= limit:
            break
    return picked


def _notary_count(problem: ScheduleProblem, assignments: list[Assignment]) -> int:
    return len(
        proven_hard_violations(
            FeasibilityChecker().check(problem, assignments, exhaustive=True)
        )
    )


def _solve_month(problem: ScheduleProblem) -> tuple[Any, str, float]:
    solver_name = _cover_solver_name(len(problem.operations))
    solver, kwargs = create_solver(solver_name)
    started = time.perf_counter()
    result = solver.solve(problem, **kwargs)
    return result, solver_name, time.perf_counter() - started


def _wave_meta(repaired: Any) -> dict[str, Any]:
    meta = repaired.metadata or {}
    return {
        "neighbourhood_size": int(meta.get("neighbourhood_size", 0)),
        "frozen_count": int(meta.get("frozen_count", 0)),
        "used_cpsat_fallback": bool(meta.get("used_cpsat_fallback", False)),
    }


def _run_wave(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    *,
    wave_index: int,
    disruptions: int,
    compare_full_resolve: bool,
) -> tuple[Any, dict[str, Any]]:
    freeze_end = problem.planning_horizon_start + timedelta(days=3 + wave_index * 7)
    targets = _select_rush_targets(problem, assignments, freeze_end, disruptions)
    if not targets:
        return None, {
            "wave": wave_index,
            "skipped": True,
            "reason": "no assignments after freeze",
        }
    started = time.perf_counter()
    repaired = IncrementalRepair().solve(
        problem,
        base_assignments=assignments,
        disrupted_op_ids=targets,
        radius=4,
        freeze_horizon_end=freeze_end,
        allow_freeze_break=False,
        regime=SolveRegime.RUSH_ORDER,
    )
    repair_s = time.perf_counter() - started
    row: dict[str, Any] = {
        "wave": wave_index,
        "skipped": False,
        "freeze_end": freeze_end.isoformat(),
        "disrupted": len(targets),
        "repair_s": round(repair_s, 3),
        "status": repaired.status.value,
        "stability_hamming": assignment_hamming(assignments, repaired.assignments),
        "kpis": cable_kpis(problem, repaired.assignments, baseline=assignments),
        **_wave_meta(repaired),
    }
    if compare_full_resolve:
        _full, _name, full_s = _solve_month(problem)
        row["full_resolve_s"] = round(full_s, 3)
        row["full_resolve_status"] = _full.status.value
        if repair_s > 0:
            row["repair_vs_full_speedup"] = round(full_s / repair_s, 2)
    return repaired, row


def run_nervous_month(
    *,
    n_orders: int = 1600,
    seed: int = 1,
    waves: int = 4,
    disruptions_per_wave: int = 20,
    machines_per_stage: int = 16,
    drum_pool_size: int = 96,
) -> dict[str, Any]:
    """Generate, cover-solve, then weekly freeze+rush repair. Returns JSON report."""

    gen_started = time.perf_counter()
    problem = generate_nervous_month(
        n_orders=n_orders,
        seed=seed,
        machines_per_stage=machines_per_stage,
        drum_pool_size=drum_pool_size,
    )
    generate_s = time.perf_counter() - gen_started
    _log(
        f"generated ops={len(problem.operations)} reels={len(problem.orders)} "
        f"setups={len(problem.setup_matrix)} in {generate_s:.2f}s"
    )
    result, solver_name, solve_s = _solve_month(problem)
    _log(f"cover {solver_name} status={result.status.value} in {solve_s:.2f}s")
    notary_started = time.perf_counter()
    hard = _notary_count(problem, result.assignments)
    notary_s = time.perf_counter() - notary_started
    _log(f"notary hard={hard} in {notary_s:.2f}s")
    wave_rows: list[dict[str, Any]] = []
    current = list(result.assignments)
    compared = False
    if result.status.value != "feasible" or hard:
        _log("skipping waves: cover is not FEASIBLE")
    else:
        for wave_index in range(waves):
            repaired, row = _run_wave(
                problem,
                current,
                wave_index=wave_index,
                disruptions=disruptions_per_wave,
                compare_full_resolve=not compared,
            )
            wave_rows.append(row)
            compared = compared or not row.get("skipped", False)
            _log(
                f"wave {wave_index} skipped={row.get('skipped')} "
                f"status={row.get('status')} repair_s={row.get('repair_s')}"
            )
            if repaired is None:
                break
            current = list(repaired.assignments)
    return {
        "claim": "synthetic nervous month; not Moskabelmet MES; not INFIMUM",
        "n_parent_orders": n_orders,
        "n_reel_orders": len(problem.orders),
        "n_operations": len(problem.operations),
        "n_work_centers": len(problem.work_centers),
        "n_states": len(problem.states),
        "n_setup_entries": len(problem.setup_matrix),
        "drum_pool": problem.auxiliary_resources[0].pool_size if problem.auxiliary_resources else 0,
        "horizon_hours": 720,
        "solver_config": solver_name,
        "status": result.status.value,
        "generate_s": round(generate_s, 3),
        "solve_s": round(solve_s, 3),
        "notary_s": round(notary_s, 3),
        "notary_hard_violations": hard,
        "temporal_stabilization_converged": bool(
            (result.metadata or {}).get("temporal_stabilization_converged")
        ),
        "kpis": cable_kpis(problem, result.assignments),
        "waves": wave_rows,
        "seed": seed,
    }
