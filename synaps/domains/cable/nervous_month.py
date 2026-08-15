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
from synaps.model import Assignment, ScheduleProblem
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


def _notary_count(problem: ScheduleProblem, assignments: list[Assignment]) -> int:
    return len(
        proven_hard_violations(
            FeasibilityChecker().check(problem, assignments, exhaustive=True)
        )
    )


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
            f"status={row.get('status')} repair_s={row.get('repair_s')}"
        )
        if repaired is None:
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

    family, colour, colour_phase, exhaust = _resolve_tight_shop_levers(
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
        colour_phase=colour_phase,
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
    wave_rows, new_rush = _post_cover_waves(
        problem,
        result,
        feasible=result.status.value == "feasible" and not hard,
        new_rush_orders=new_rush_orders,
        seed=seed,
        family_dedicated=family,
        colour_dedicated=colour,
        cover_ready_rule=cover_ready_rule,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=exhaust,
        waves=waves,
        disruptions_per_wave=disruptions_per_wave,
    )
    return _month_report(
        problem, result, solver_name=solver_name,
        cover_ready_rule=cover_ready_rule,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=exhaust,
        family_dedicated_lines=family,
        colour_phase=colour_phase, colour_dedicated_lines=colour,
        n_orders=n_orders, seed=seed, generate_s=generate_s, solve_s=solve_s,
        notary_s=notary_s, hard=hard, wave_rows=wave_rows, new_rush=new_rush,
    )


def parse_nervous_seeds(raw: str | None, seed: int) -> tuple[int, ...]:
    """CLI `--seeds a,b` overrides `--seed`. Empty tokens are ignored."""

    if raw is None or not str(raw).strip():
        return (int(seed),)
    seeds = tuple(int(part.strip()) for part in str(raw).split(",") if part.strip())
    if not seeds:
        raise ValueError("empty --seeds")
    return seeds


def run_nervous_month_multiseed(seeds: tuple[int, ...], **kwargs: Any) -> dict[str, Any]:
    """Independent covers. Does not prove a confidence interval or freeze quality."""

    kwargs.pop("seed", None)
    runs = [run_nervous_month(seed=item, **kwargs) for item in seeds]
    kpis = [run["kpis"] for run in runs]
    feasible = all(
        run["status"] == "feasible" and run["notary_hard_violations"] == 0 for run in runs
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
