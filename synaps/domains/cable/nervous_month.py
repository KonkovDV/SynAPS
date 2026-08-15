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
from synaps.domains.cable.instance import add_rush_orders, generate_cable_instance
from synaps.domains.cable.kpis import assignment_hamming, cable_kpis
from synaps.domains.cable.weights import CABLE_PVC_WEIGHTS
from synaps.model import Assignment, ScheduleProblem
from synaps.objective import DEFAULT_WEIGHTS, evaluate, scalarize
from synaps.solvers.feasibility_checker import FeasibilityChecker, proven_hard_violations
from synaps.solvers.incremental_repair import IncrementalRepair
from synaps.solvers.registry import create_solver
from synaps.solvers.router import SolveRegime

# Bounded ATCS delay for the nervous month. Window 0 is non-delay
# (Kolisch parallel SGS). One colour SMED (240) on *any* ready job
# collapsed 16-stage coverage (2026-08-15). Exhaust is continuation-only
# (Mahmoodi/Dooley 1991; Pfund ATCSR). Registry stays at 0.
_NERVOUS_ATCS_FLOOR_WINDOW = 0.0
_NERVOUS_ATCS_EXHAUST_WINDOW = 240.0


def _resolve_tight_shop_levers(
    machines_per_stage: int,
    *,
    family_dedicated_lines: bool | None,
    colour_dedicated_lines: bool | None,
    colour_phase: bool | None,
    cover_atcs_exhaust_window: float | None,
) -> tuple[bool, bool, bool, float]:
    """8-machine shop: family cells + colour wheel + continuation stay.

    Colour-dedicated lines fragment the 8-machine shop (coverage 0.85).
    The FEASIBLE mix is mix-sized family flex, a 6-colour campaign wheel,
    and exhaustive stay (ready-queue continuations + hot-machine preference).
    Colour cells stay opt-in. 16-stage stays ATCS-only (tardiness 1 922).
    """

    tight = machines_per_stage <= 8
    family = (
        tight and machines_per_stage >= 3
        if family_dedicated_lines is None
        else family_dedicated_lines
    )
    colour = False if colour_dedicated_lines is None else colour_dedicated_lines
    phase = (not colour) if colour_phase is None else colour_phase
    if cover_atcs_exhaust_window is None:
        exhaust = _NERVOUS_ATCS_EXHAUST_WINDOW if tight else 0.0
    else:
        exhaust = max(0.0, float(cover_atcs_exhaust_window))
    return family, colour, phase, exhaust
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
    family_dedicated_lines: bool = False,
    colour_phase: bool = True,
    colour_dedicated_lines: bool = False,
) -> ScheduleProblem:
    """30-day high-mix make-to-order month. Default ~2×10⁴ ops after reel split.

    16 machines/stage is the measured COVER-feasible shop for this mix
    with ATCS, no family/colour split (tardiness 1 922). At ≤8/stage,
    ``run_nervous_month`` turns on mix-sized family cells, the 6-colour
    wheel, and continuation-only ATCS exhaust with hot-machine stay.
    Colour-dedicated lines stay opt-in (they drop 8-stage coverage).
    Direct calls here keep the flags as passed.
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
        family_dedicated_lines=family_dedicated_lines,
        colour_phase=colour_phase,
        colour_dedicated_lines=colour_dedicated_lines,
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


def _select_steal_targets(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    freeze_end: Any,
    limit: int,
) -> list[UUID]:
    """High-priority ops that already start inside the freeze window."""

    orders = {order.id: order for order in problem.orders}
    ops_by_id = {operation.id: operation for operation in problem.operations}
    ranked: list[tuple[int, UUID]] = []
    for assignment in assignments:
        if assignment.start_time >= freeze_end:
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


def _notary_hits(problem: ScheduleProblem, assignments: list[Assignment]) -> list[Any]:
    return proven_hard_violations(
        FeasibilityChecker().check(problem, assignments, exhaustive=True)
    )


def _notary_count(problem: ScheduleProblem, assignments: list[Assignment]) -> int:
    return len(_notary_hits(problem, assignments))


def _solve_month(
    problem: ScheduleProblem,
    *,
    cover_ready_rule: str = "atcs",
    cover_atcs_floor_window: float = _NERVOUS_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float = 0.0,
) -> tuple[Any, str, float]:
    solver_name = _cover_solver_name(len(problem.operations))
    solver, kwargs = create_solver(solver_name)
    if solver_name == "RHC-GREEDY-COVER":
        kwargs = {
            **kwargs,
            "cover_ready_rule": cover_ready_rule,
            "cover_atcs_floor_window": cover_atcs_floor_window,
            "cover_atcs_exhaust_window": cover_atcs_exhaust_window,
        }
    _log(f"cover {solver_name} starting ops={len(problem.operations)}")
    started = time.perf_counter()
    result = solver.solve(problem, **kwargs)
    return result, solver_name, time.perf_counter() - started


def _wave_meta(repaired: Any) -> dict[str, Any]:
    meta = repaired.metadata or {}
    return {
        "neighbourhood_size": int(meta.get("neighbourhood_size", 0)),
        "frozen_count": int(meta.get("frozen_count", 0)),
        "unrepaired_count": int(meta.get("unrepaired_count", 0)),
        "used_cpsat_fallback": bool(meta.get("used_cpsat_fallback", False)),
    }


def _stabilization_report(solver_name: str, result: Any) -> dict[str, Any]:
    if solver_name == "GREED":
        return {
            "temporal_stabilization_converged": None,
            "temporal_stabilization_note": "n/a (GREED)",
        }
    return {
        "temporal_stabilization_converged": bool(
            (result.metadata or {}).get("temporal_stabilization_converged")
        )
    }


def _run_wave(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    *,
    wave_index: int,
    disruptions: int,
    compare_full_resolve: bool,
    cover_ready_rule: str,
    cover_atcs_floor_window: float,
    cover_atcs_exhaust_window: float,
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
    hard = _notary_hits(problem, repaired.assignments)
    row: dict[str, Any] = {
        "wave": wave_index,
        "skipped": False,
        "freeze_end": freeze_end.isoformat(),
        "disrupted": len(targets),
        "repair_s": round(repair_s, 3),
        "status": repaired.status.value,
        "notary_hard_violations": len(hard),
        "notary_kinds": sorted({item.kind for item in hard}),
        "notary_sample": (hard[0].message[:240] if hard else None),
        "stability_hamming": assignment_hamming(assignments, repaired.assignments),
        "kpis": cable_kpis(problem, repaired.assignments, baseline=assignments),
        **_wave_meta(repaired),
    }
    if compare_full_resolve:
        _full, _name, full_s = _solve_month(
            problem,
            cover_ready_rule=cover_ready_rule,
            cover_atcs_floor_window=cover_atcs_floor_window,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        )
        row["full_resolve_s"] = round(full_s, 3)
        row["full_resolve_status"] = _full.status.value
        if repair_s > 0:
            row["repair_vs_full_speedup"] = round(full_s / repair_s, 2)
    return repaired, row


def _new_rush_wave(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    *,
    n_orders: int,
    seed: int,
    family_dedicated: bool,
    colour_dedicated: bool,
    cover_ready_rule: str,
    cover_atcs_floor_window: float,
    cover_atcs_exhaust_window: float,
) -> dict[str, Any]:
    """Insert new parent reels after cover; repair vs full re-solve on the mutant."""

    release = problem.planning_horizon_start + timedelta(days=3)
    mutated = add_rush_orders(
        problem,
        n_orders=n_orders,
        release=release,
        due=release + timedelta(hours=48),
        seed=seed,
        family_dedicated=family_dedicated,
        colour_dedicated=colour_dedicated,
    )
    known = {operation.id for operation in problem.operations}
    new_ids = [operation.id for operation in mutated.operations if operation.id not in known]
    started = time.perf_counter()
    repaired = IncrementalRepair().solve(
        mutated,
        base_assignments=assignments,
        disrupted_op_ids=new_ids,
        radius=4,
        freeze_horizon_end=release,
        allow_freeze_break=False,
        regime=SolveRegime.RUSH_ORDER,
    )
    repair_s = time.perf_counter() - started
    hard = _notary_hits(mutated, repaired.assignments)
    full, solver_name, full_s = _solve_month(
        mutated,
        cover_ready_rule=cover_ready_rule,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    row: dict[str, Any] = {
        "kind": "new_parent_insert",
        "n_new_parents": n_orders,
        "n_new_ops": len(new_ids),
        "repair_s": round(repair_s, 3),
        "repair_status": repaired.status.value,
        "full_resolve_s": round(full_s, 3),
        "full_resolve_status": full.status.value,
        "stability_hamming": assignment_hamming(assignments, repaired.assignments),
        "notary_hard_violations": len(hard),
        "notary_kinds": sorted({item.kind for item in hard}),
        "solver_config": solver_name,
    }
    if repair_s > 0:
        row["repair_vs_full_speedup"] = round(full_s / repair_s, 2)
    return row


def _run_reshuffle_waves(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    *,
    waves: int,
    disruptions_per_wave: int,
    cover_ready_rule: str,
    cover_atcs_floor_window: float,
    cover_atcs_exhaust_window: float,
) -> list[dict[str, Any]]:
    wave_rows: list[dict[str, Any]] = []
    current = list(assignments)
    compared = False
    for wave_index in range(waves):
        repaired, row = _run_wave(
            problem,
            current,
            wave_index=wave_index,
            disruptions=disruptions_per_wave,
            compare_full_resolve=not compared,
            cover_ready_rule=cover_ready_rule,
            cover_atcs_floor_window=cover_atcs_floor_window,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        )
        wave_rows.append(row)
        compared = compared or not row.get("skipped", False)
        _log(
            f"wave {wave_index} skipped={row.get('skipped')} "
            f"status={row.get('status')} notary={row.get('notary_hard_violations')} "
            f"ham={row.get('stability_hamming')} repair_s={row.get('repair_s')}"
        )
        if repaired is None:
            break
        if row.get("status") != "feasible" or int(row.get("notary_hard_violations", 1)) != 0:
            _log(f"wave {wave_index} stop: dirty repair, later weeks not chained")
            break
        current = list(repaired.assignments)
    return wave_rows


def _post_cover_waves(
    problem: ScheduleProblem,
    result: Any,
    *,
    feasible: bool,
    new_rush_orders: int,
    seed: int,
    family_dedicated: bool,
    colour_dedicated: bool,
    cover_ready_rule: str,
    cover_atcs_floor_window: float,
    cover_atcs_exhaust_window: float,
    waves: int,
    disruptions_per_wave: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not feasible:
        _log("skipping waves: cover is not FEASIBLE")
        return [], None
    new_rush = None
    if new_rush_orders > 0:
        new_rush = _new_rush_wave(
            problem,
            result.assignments,
            n_orders=new_rush_orders,
            seed=seed + 99,
            family_dedicated=family_dedicated,
            colour_dedicated=colour_dedicated,
            cover_ready_rule=cover_ready_rule,
            cover_atcs_floor_window=cover_atcs_floor_window,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        )
    return _run_reshuffle_waves(
        problem,
        result.assignments,
        waves=waves,
        disruptions_per_wave=disruptions_per_wave,
        cover_ready_rule=cover_ready_rule,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    ), new_rush


def _cover_nervous_shop(
    *,
    n_orders: int,
    seed: int,
    machines_per_stage: int,
    drum_pool_size: int,
    family_dedicated_lines: bool | None,
    colour_phase: bool | None,
    colour_dedicated_lines: bool | None,
    cover_ready_rule: str,
    cover_atcs_floor_window: float,
    cover_atcs_exhaust_window: float | None,
) -> dict[str, Any]:
    family, colour, phase, exhaust = _resolve_tight_shop_levers(
        machines_per_stage,
        family_dedicated_lines=family_dedicated_lines,
        colour_dedicated_lines=colour_dedicated_lines,
        colour_phase=colour_phase,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    gen_started = time.perf_counter()
    problem = generate_nervous_month(
        n_orders=n_orders,
        seed=seed,
        machines_per_stage=machines_per_stage,
        drum_pool_size=drum_pool_size,
        family_dedicated_lines=family,
        colour_phase=phase,
        colour_dedicated_lines=colour,
    )
    generate_s = time.perf_counter() - gen_started
    _log(
        f"generated ops={len(problem.operations)} reels={len(problem.orders)} "
        f"setups={len(problem.setup_matrix)} in {generate_s:.2f}s"
    )
    result, solver_name, solve_s = _solve_month(
        problem,
        cover_ready_rule=cover_ready_rule,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=exhaust,
    )
    _log(f"cover {solver_name} status={result.status.value} in {solve_s:.2f}s")
    notary_started = time.perf_counter()
    hard = _notary_count(problem, result.assignments)
    notary_s = time.perf_counter() - notary_started
    _log(f"notary hard={hard} in {notary_s:.2f}s")
    return {
        "problem": problem,
        "result": result,
        "solver_name": solver_name,
        "family": family,
        "colour": colour,
        "colour_phase": phase,
        "exhaust": exhaust,
        "generate_s": generate_s,
        "solve_s": solve_s,
        "notary_s": notary_s,
        "hard": hard,
        "cover_ready_rule": cover_ready_rule,
        "cover_atcs_floor_window": cover_atcs_floor_window,
    }


def run_nervous_month(
    *,
    n_orders: int = 1600,
    seed: int = 1,
    waves: int = 4,
    disruptions_per_wave: int = 20,
    machines_per_stage: int = 16,
    drum_pool_size: int = 96,
    family_dedicated_lines: bool | None = None,
    colour_phase: bool | None = None,
    colour_dedicated_lines: bool | None = None,
    cover_ready_rule: str = "atcs",
    cover_atcs_floor_window: float = _NERVOUS_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float | None = None,
    new_rush_orders: int = 2,
) -> dict[str, Any]:
    """Generate, cover-solve, then weekly freeze+rush repair. Returns JSON report."""

    shop = _cover_nervous_shop(
        n_orders=n_orders,
        seed=seed,
        machines_per_stage=machines_per_stage,
        drum_pool_size=drum_pool_size,
        family_dedicated_lines=family_dedicated_lines,
        colour_phase=colour_phase,
        colour_dedicated_lines=colour_dedicated_lines,
        cover_ready_rule=cover_ready_rule,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    wave_rows, new_rush = _post_cover_waves(
        shop["problem"],
        shop["result"],
        feasible=shop["result"].status.value == "feasible" and not shop["hard"],
        new_rush_orders=new_rush_orders,
        seed=seed,
        family_dedicated=shop["family"],
        colour_dedicated=shop["colour"],
        cover_ready_rule=shop["cover_ready_rule"],
        cover_atcs_floor_window=shop["cover_atcs_floor_window"],
        cover_atcs_exhaust_window=shop["exhaust"],
        waves=waves,
        disruptions_per_wave=disruptions_per_wave,
    )
    return _month_report(
        shop["problem"], shop["result"], solver_name=shop["solver_name"],
        cover_ready_rule=shop["cover_ready_rule"],
        cover_atcs_floor_window=shop["cover_atcs_floor_window"],
        cover_atcs_exhaust_window=shop["exhaust"],
        family_dedicated_lines=shop["family"],
        colour_phase=shop["colour_phase"], colour_dedicated_lines=shop["colour"],
        n_orders=n_orders, seed=seed, generate_s=shop["generate_s"],
        solve_s=shop["solve_s"], notary_s=shop["notary_s"], hard=shop["hard"],
        wave_rows=wave_rows, new_rush=new_rush,
    )


def _arm_kpis(
    problem: ScheduleProblem,
    result: Any,
    wall_s: float,
    baseline: list[Assignment] | None = None,
) -> dict[str, Any]:
    return {
        "status": result.status.value,
        "wall_s": round(wall_s, 3),
        "notary_hard_violations": _notary_count(problem, result.assignments),
        "kpis": cable_kpis(problem, result.assignments, baseline=baseline),
    }


def _repair_disrupted(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    disrupted: list[UUID],
    freeze_end: Any,
    allow_break: bool,
) -> tuple[Any, float]:
    started = time.perf_counter()
    repaired = IncrementalRepair().solve(
        problem,
        base_assignments=assignments,
        disrupted_op_ids=disrupted,
        radius=4,
        freeze_horizon_end=freeze_end,
        allow_freeze_break=allow_break,
        regime=SolveRegime.RUSH_ORDER,
    )
    return repaired, time.perf_counter() - started


def _wip_delta(left: dict[str, Any], right: dict[str, Any]) -> int:
    return int(left["kpis"]["peak_wip_drums"]) - int(right["kpis"]["peak_wip_drums"])


def _c6b_rush_arms(shop: dict[str, Any], n_rush: int, seed: int) -> dict[str, Any]:
    problem = shop["problem"]
    result = shop["result"]
    freeze_end = problem.planning_horizon_start + timedelta(days=3)
    mutated = add_rush_orders(
        problem,
        n_orders=n_rush,
        release=freeze_end,
        due=freeze_end + timedelta(hours=48),
        seed=seed + 99,
        family_dedicated=shop["family"],
        colour_dedicated=shop["colour"],
    )
    known = {operation.id for operation in problem.operations}
    new_ids = [op.id for op in mutated.operations if op.id not in known]
    frozen_rep, freeze_s = _repair_disrupted(
        mutated, result.assignments, new_ids, freeze_end, False
    )
    insert, _name, insert_s = _solve_month(
        mutated,
        cover_ready_rule=shop["cover_ready_rule"],
        cover_atcs_floor_window=shop["cover_atcs_floor_window"],
        cover_atcs_exhaust_window=shop["exhaust"],
    )
    freeze_row = _arm_kpis(mutated, frozen_rep, freeze_s, result.assignments)
    insert_row = _arm_kpis(mutated, insert, insert_s)
    return {
        "n_new_ops": len(new_ids),
        "freeze_repair": freeze_row,
        "insert_cover": insert_row,
        "wip_delta": _wip_delta(freeze_row, insert_row),
    }


def _c6b_steal_arms(shop: dict[str, Any], n_steal: int) -> dict[str, Any]:
    problem = shop["problem"]
    result = shop["result"]
    freeze_end = problem.planning_horizon_start + timedelta(days=3)
    steal_ids = _select_steal_targets(problem, result.assignments, freeze_end, n_steal)
    steal_f, steal_f_s = _repair_disrupted(
        problem, result.assignments, steal_ids, freeze_end, False
    )
    steal_o, steal_o_s = _repair_disrupted(
        problem, result.assignments, steal_ids, freeze_end, True
    )
    freeze_row = _arm_kpis(problem, steal_f, steal_f_s, result.assignments)
    open_row = _arm_kpis(problem, steal_o, steal_o_s, result.assignments)
    return {
        "n_targets": len(steal_ids),
        "freeze": freeze_row,
        "open": open_row,
        "wip_delta": _wip_delta(freeze_row, open_row),
    }


def run_freeze_insert_pair(
    *,
    n_orders: int = 1600,
    seed: int = 1,
    machines_per_stage: int = 8,
    drum_pool_size: int = 48,
    family_dedicated_lines: bool | None = None,
    colour_phase: bool | None = None,
    colour_dedicated_lines: bool | None = None,
    cover_ready_rule: str = "atcs",
    cover_atcs_floor_window: float = _NERVOUS_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float | None = None,
    n_rush: int = 2,
    n_steal: int = 20,
) -> dict[str, Any]:
    """C6b: freeze+repair vs full re-cover insert, plus steal-window pair."""

    shop = _cover_nervous_shop(
        n_orders=n_orders,
        seed=seed,
        machines_per_stage=machines_per_stage,
        drum_pool_size=drum_pool_size,
        family_dedicated_lines=family_dedicated_lines,
        colour_phase=colour_phase,
        colour_dedicated_lines=colour_dedicated_lines,
        cover_ready_rule=cover_ready_rule,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    result = shop["result"]
    rush = _c6b_rush_arms(shop, n_rush, seed)
    steal = _c6b_steal_arms(shop, n_steal)
    freeze_ok = (
        result.status.value == "feasible"
        and shop["hard"] == 0
        and rush["freeze_repair"]["status"] == "feasible"
        and rush["freeze_repair"]["notary_hard_violations"] == 0
        and steal["freeze"]["status"] == "feasible"
        and steal["freeze"]["notary_hard_violations"] == 0
    )
    return {
        "claim": "synthetic C6b freeze vs insert; not Moskabelmet MES; not -24% drums",
        "seed": seed,
        "n_rush_parents": n_rush,
        "n_new_ops": rush["n_new_ops"],
        "n_steal_targets": steal["n_targets"],
        "cover": {
            "status": result.status.value,
            "kpis": cable_kpis(shop["problem"], result.assignments),
            "generate_s": shop["generate_s"],
            "solve_s": shop["solve_s"],
            "notary_s": shop["notary_s"],
            "hard": shop["hard"],
        },
        "rush": rush,
        "steal": steal,
        "all_feasible": freeze_ok,
    }


def _residual_destroy_kwargs(n_ops: int, use_cpsat_repair: bool) -> dict[str, Any]:
    """Destroy size the repair can iterate. 300-op destroy ate a 60 s 20k box."""

    if not use_cpsat_repair:
        return {
            "min_destroy": 2,
            "max_destroy": 8,
            "destroy_fraction": 0.15,
            "repair_time_limit_s": 1,
        }
    if n_ops >= 10_000:
        return {
            "min_destroy": 8,
            "max_destroy": 24,
            "destroy_fraction": 0.001,
            "repair_time_limit_s": 2,
            "cpsat_max_destroy_ops": 16,
        }
    return {}


def _residual_alns_kwargs(
    cover: list[Assignment],
    weights: dict[str, float],
    *,
    time_limit_s: float,
    max_iterations: int,
    use_cpsat_repair: bool,
    seed: int,
) -> dict[str, Any]:
    """ALNS residual kwargs. Construction COVER is not in this dict."""

    kwargs: dict[str, Any] = {
        "warm_start_assignments": [row.model_copy() for row in cover],
        "objective_weights": dict(weights),
        "time_limit_s": time_limit_s,
        "max_iterations": max_iterations,
        "use_cpsat_repair": use_cpsat_repair,
        "random_seed": seed,
        "repair_num_workers": 1,
    }
    kwargs.update(_residual_destroy_kwargs(len(cover), use_cpsat_repair))
    return kwargs


def _residual_arm(
    problem: ScheduleProblem,
    cover: list[Assignment],
    weights: dict[str, float],
    *,
    time_limit_s: float,
    max_iterations: int,
    use_cpsat_repair: bool,
    seed: int,
) -> dict[str, Any]:
    """One ALNS residual from the cover seed. Scores with canonical scalarize."""

    from synaps.solvers.alns_solver import AlnsSolver

    _log(
        f"ALNS residual seed={seed} time={time_limit_s}s "
        f"iters={max_iterations} cpsat={use_cpsat_repair} "
        f"tardiness_w={weights.get('tardiness', 0)}"
    )

    started = time.perf_counter()
    result = AlnsSolver().solve(
        problem,
        **_residual_alns_kwargs(
            cover,
            weights,
            time_limit_s=time_limit_s,
            max_iterations=max_iterations,
            use_cpsat_repair=use_cpsat_repair,
            seed=seed,
        ),
    )
    wall_s = time.perf_counter() - started
    row = _arm_kpis(problem, result, wall_s, cover)
    objective = evaluate(problem, result.assignments)
    meta = result.metadata or {}
    row["scalar_cable_pvc"] = scalarize(objective, CABLE_PVC_WEIGHTS)
    row["coverage"] = objective.coverage
    row["warm_start_used"] = bool(meta.get("alns_warm_start_used", meta.get("warm_start_used")))
    row["alns_warm_start_coverage"] = meta.get("alns_warm_start_coverage")
    row["wall_clock_path_dependent"] = bool(meta.get("wall_clock_path_dependent"))
    row["search_stop_reason"] = meta.get("search_stop_reason")
    row["iterations_completed"] = int(meta.get("iterations_completed", 0))
    row["max_destroy"] = int(
        _residual_destroy_kwargs(len(cover), use_cpsat_repair).get("max_destroy", 0)
    )
    _log(
        f"residual done wall={wall_s:.1f}s status={result.status.value} "
        f"scalar={row['scalar_cable_pvc']:.1f} "
        f"tard={row['kpis']['total_tardiness_minutes']}"
    )
    return row


def _cover_scalar_row(shop: dict[str, Any]) -> dict[str, Any]:
    problem = shop["problem"]
    result = shop["result"]
    objective = evaluate(problem, result.assignments)
    return {
        "status": result.status.value,
        "notary_hard_violations": shop["hard"],
        "kpis": cable_kpis(problem, result.assignments),
        "scalar_cable_pvc": scalarize(objective, CABLE_PVC_WEIGHTS),
        "coverage": objective.coverage,
        "generate_s": shop["generate_s"],
        "solve_s": shop["solve_s"],
        "notary_s": shop["notary_s"],
        "solver_config": shop["solver_name"],
    }


def run_weighted_residual_pair(
    *,
    n_orders: int = 400,
    seed: int = 1,
    machines_per_stage: int = 8,
    drum_pool_size: int = 48,
    family_dedicated_lines: bool | None = None,
    colour_phase: bool | None = None,
    colour_dedicated_lines: bool | None = None,
    cover_ready_rule: str = "atcs",
    cover_atcs_floor_window: float = _NERVOUS_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float | None = None,
    residual_time_limit_s: float = 120.0,
    residual_max_iterations: int = 300,
    residual_use_cpsat_repair: bool = True,
) -> dict[str, Any]:
    """C6c: COVER then two ALNS residuals. Weights never enter list-schedule."""

    shop = _cover_nervous_shop(
        n_orders=n_orders,
        seed=seed,
        machines_per_stage=machines_per_stage,
        drum_pool_size=drum_pool_size,
        family_dedicated_lines=family_dedicated_lines,
        colour_phase=colour_phase,
        colour_dedicated_lines=colour_dedicated_lines,
        cover_ready_rule=cover_ready_rule,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    cover = list(shop["result"].assignments)
    arm_kw = {
        "time_limit_s": residual_time_limit_s,
        "max_iterations": residual_max_iterations,
        "use_cpsat_repair": residual_use_cpsat_repair,
        "seed": seed,
    }
    makespan = _residual_arm(shop["problem"], cover, DEFAULT_WEIGHTS, **arm_kw)
    pvc = _residual_arm(shop["problem"], cover, CABLE_PVC_WEIGHTS, **arm_kw)
    cover_row = _cover_scalar_row(shop)
    improved = pvc["scalar_cable_pvc"] < makespan["scalar_cable_pvc"]
    feasible = (
        cover_row["status"] == "feasible"
        and cover_row["notary_hard_violations"] == 0
        and makespan["status"] == "feasible"
        and makespan["notary_hard_violations"] == 0
        and pvc["status"] == "feasible"
        and pvc["notary_hard_violations"] == 0
        and float(cover_row["coverage"]) == 1.0
        and float(makespan["coverage"]) == 1.0
        and float(pvc["coverage"]) == 1.0
    )
    return {
        "claim": (
            "synthetic C6c cover-then-ALNS residual; not Moskabelmet MES; "
            "not OPTIMAL; not INFIMUM"
        ),
        "seed": seed,
        "residual_time_limit_s": residual_time_limit_s,
        "residual_max_iterations": residual_max_iterations,
        "residual_use_cpsat_repair": residual_use_cpsat_repair,
        "cover": cover_row,
        "makespan_residual": makespan,
        "pvc_residual": pvc,
        "scalar_improved": improved,
        "tardiness_delta": (
            int(pvc["kpis"]["total_tardiness_minutes"])
            - int(cover_row["kpis"]["total_tardiness_minutes"])
        ),
        "all_feasible": feasible,
    }


def run_weighted_residual_multiseed(
    seeds: tuple[int, ...], **kwargs: Any
) -> dict[str, Any]:
    """Independent C6c pairs. Not a confidence interval."""

    kwargs.pop("seed", None)
    runs = [run_weighted_residual_pair(seed=item, **kwargs) for item in seeds]
    improved = [bool(run["scalar_improved"]) for run in runs]
    tardiness = [
        int(run["pvc_residual"]["kpis"]["total_tardiness_minutes"]) for run in runs
    ]
    return {
        "claim": runs[0]["claim"] if runs else "synthetic C6c; empty seeds",
        "seeds": list(seeds),
        "n_runs": len(runs),
        "all_feasible": all(run["all_feasible"] for run in runs),
        "n_scalar_improved": sum(improved),
        "tardiness_minutes_pvc": tardiness,
        "runs": runs,
    }


def parse_nervous_seeds(raw: str | None, seed: int) -> tuple[int, ...]:
    """CLI `--seeds a,b` overrides `--seed`. Empty tokens are ignored."""

    if raw is None or not str(raw).strip():
        return (int(seed),)
    seeds = tuple(int(part.strip()) for part in str(raw).split(",") if part.strip())
    if not seeds:
        raise ValueError("empty --seeds")
    return seeds


def _wave_rows_feasible(waves: list[dict[str, Any]]) -> bool:
    """Skipped is not infeasible. A skipped month is not freeze-quality proof."""

    for row in waves:
        if row.get("skipped"):
            continue
        if row.get("status") != "feasible":
            return False
        if int(row.get("notary_hard_violations", 1)) != 0:
            return False
    return True


def nervous_report_ok(report: dict[str, Any]) -> bool:
    """Cover + wave notary. Multiseed uses the aggregator's all_feasible."""

    if "runs" in report:
        return bool(report.get("all_feasible"))
    return (
        report.get("status") == "feasible"
        and int(report.get("notary_hard_violations", 1)) == 0
        and _wave_rows_feasible(report.get("waves") or [])
    )


def run_nervous_month_multiseed(seeds: tuple[int, ...], **kwargs: Any) -> dict[str, Any]:
    """Independent covers. Does not prove a confidence interval or freeze quality."""

    kwargs.pop("seed", None)
    runs = [run_nervous_month(seed=item, **kwargs) for item in seeds]
    kpis = [run["kpis"] for run in runs]
    feasible = all(
        run["status"] == "feasible"
        and run["notary_hard_violations"] == 0
        and _wave_rows_feasible(run.get("waves") or [])
        for run in runs
    )
    tardiness = [int(row["total_tardiness_minutes"]) for row in kpis]
    return {
        "claim": "synthetic nervous-month multiseed; not Moskabelmet MES; not INFIMUM",
        "seeds": list(seeds),
        "n_runs": len(runs),
        "all_feasible": feasible,
        "tardiness_minutes": tardiness,
        "setup_minutes": [int(row["total_setup_minutes"]) for row in kpis],
        "peak_wip_drums": [int(row["peak_wip_drums"]) for row in kpis],
        "solve_s": [run["solve_s"] for run in runs],
        "notary_hard_violations": [run["notary_hard_violations"] for run in runs],
        "waves_all_feasible": [
            _wave_rows_feasible(run.get("waves") or []) for run in runs
        ],
        "runs": runs,
    }


def _month_report(
    problem: ScheduleProblem,
    result: Any,
    *,
    solver_name: str,
    cover_ready_rule: str,
    cover_atcs_floor_window: float,
    cover_atcs_exhaust_window: float,
    family_dedicated_lines: bool,
    colour_phase: bool,
    colour_dedicated_lines: bool,
    n_orders: int,
    seed: int,
    generate_s: float,
    solve_s: float,
    notary_s: float,
    hard: int,
    wave_rows: list[dict[str, Any]],
    new_rush: dict[str, Any] | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
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
        "cover_ready_rule": cover_ready_rule if solver_name == "RHC-GREEDY-COVER" else "n/a",
        "cover_atcs_floor_window": (
            cover_atcs_floor_window if solver_name == "RHC-GREEDY-COVER" else None
        ),
        "cover_atcs_exhaust_window": (
            cover_atcs_exhaust_window if solver_name == "RHC-GREEDY-COVER" else None
        ),
        "family_dedicated_lines": family_dedicated_lines,
        "colour_phase": colour_phase,
        "colour_dedicated_lines": colour_dedicated_lines,
        "status": result.status.value,
        "generate_s": round(generate_s, 3),
        "solve_s": round(solve_s, 3),
        "notary_s": round(notary_s, 3),
        "notary_hard_violations": hard,
        "kpis": cable_kpis(problem, result.assignments),
        "waves": wave_rows,
        "seed": seed,
        **_stabilization_report(solver_name, result),
    }
    if new_rush is not None:
        payload["new_rush"] = new_rush
    return payload
