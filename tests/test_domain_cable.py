"""Cable domain adapter, KPIs, freeze policy, and GREEDY smoke (encode-first)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.domains.cable import (
    CABLE_PVC_CPSAT_WEIGHTS,
    CABLE_PVC_WEIGHTS,
    NERVOUS_STAGES,
    CableSku,
    add_rush_orders,
    apply_campaign_windows,
    assignment_hamming,
    cable_kpis,
    duration_minutes_from_length,
    generate_cable_instance,
    generate_nervous_month,
    nervous_report_ok,
    nervous_sku_catalog,
    parse_nervous_seeds,
    peak_processing_drums,
    peak_wip_drums,
    run_freeze_insert_pair,
    run_nervous_month,
    run_nervous_month_multiseed,
    run_weighted_residual_pair,
    setup_transition,
    split_length_into_reels,
    state_code,
)
from synaps.model import (
    Assignment,
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.objective import evaluate, scalarize
from synaps.portfolio import solve_schedule
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityChecker, proven_hard_violations
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.incremental_repair import IncrementalRepair
from synaps.solvers.router import SolveRegime

_H0 = datetime(2026, 8, 1, tzinfo=UTC)


def test_length_duration_and_reel_split() -> None:
    assert duration_minutes_from_length(100.0, 25.0) == 4
    assert duration_minutes_from_length(0.0, 25.0) == 1
    assert split_length_into_reels(2200.0, 1000.0) == [1000.0, 1000.0, 200.0]
    assert state_code(CableSku("Cu", "PVC", "BK", 16)) == "Cu-PVC-BK-16"
    minutes, loss, _energy = setup_transition(
        CableSku("Cu", "PVC", "BK", 16),
        CableSku("Cu", "PVC", "RD", 16),
    )
    assert minutes == 240
    assert loss == 15.0
    assert setup_transition(
        CableSku("Cu", "PVC", "BK", 16),
        CableSku("Cu", "PVC", "BK", 16),
    ) == (0, 0.0, 0.0)


def test_generate_cable_instance_greedy_feasible() -> None:
    problem = generate_cable_instance(n_orders=3, seed=1, horizon_hours=240)
    assert problem.orders
    assert all(order.unit == "m" for order in problem.orders)
    assert any(op.domain_attributes.get("reel_id") for op in problem.operations)
    result = GreedyDispatch().solve(problem)
    assert result.status is SolverStatus.FEASIBLE
    hard = proven_hard_violations(
        FeasibilityChecker().check(problem, result.assignments, exhaustive=True)
    )
    assert hard == []
    kpis = cable_kpis(problem, result.assignments, baseline=result.assignments)
    assert kpis["coverage"] == 1.0
    assert int(kpis["peak_wip_drums"]) >= 1
    assert int(kpis["peak_processing_drums"]) >= 1
    assert int(kpis["peak_processing_drums"]) <= int(kpis["peak_wip_drums"])
    assert kpis["stability_hamming"] == 0.0
    assert peak_wip_drums(problem, result.assignments) == kpis["peak_wip_drums"]
    assert peak_processing_drums(problem, result.assignments) == kpis["peak_processing_drums"]


def test_parent_order_splits_into_reels() -> None:
    problem = generate_cable_instance(
        n_orders=1,
        seed=1,
        length_range_m=(2200.0, 2200.0),
        reel_capacity_m=1000.0,
        campaign_slot_hours=8,
    )
    assert len(problem.orders) == 3
    parents = {order.domain_attributes["parent_order_ref"] for order in problem.orders}
    assert parents == {"ORD-0001"}
    first_ops = [op for op in problem.operations if op.seq_in_order == 1]
    assert all(op.earliest_start is not None for op in first_ops)


def test_campaign_gate_is_release_not_due() -> None:
    problem = generate_cable_instance(
        n_orders=12,
        seed=1,
        horizon_hours=720,
        rush_fraction=0.15,
        scatter_releases=True,
        shuffle_skus=True,
    )
    orders = {order.id: order for order in problem.orders}
    for operation in problem.operations:
        if operation.seq_in_order != 1 or operation.earliest_start is None:
            continue
        order = orders[operation.order_id]
        assert operation.earliest_start < order.due_date
        assert operation.earliest_start >= problem.planning_horizon_start


def test_cable_pvc_weights_prefer_lower_material() -> None:
    dirty = ObjectiveValues(makespan_minutes=100.0, total_material_loss=50.0)
    clean = ObjectiveValues(makespan_minutes=110.0, total_material_loss=5.0)
    assert scalarize(dirty) < scalarize(clean)
    assert scalarize(clean, CABLE_PVC_WEIGHTS) < scalarize(dirty, CABLE_PVC_WEIGHTS)


def test_assignment_hamming_detects_move() -> None:
    op_id, wc = uuid4(), uuid4()
    base = [
        Assignment(
            operation_id=op_id,
            work_center_id=wc,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=10),
        )
    ]
    moved = [
        Assignment(
            operation_id=op_id,
            work_center_id=wc,
            start_time=_H0 + timedelta(minutes=5),
            end_time=_H0 + timedelta(minutes=15),
        )
    ]
    assert assignment_hamming(base, base) == 0.0
    assert assignment_hamming(base, moved) == 1.0


def _rush_pair_problem() -> tuple[ScheduleProblem, list[Assignment], Operation, Operation]:
    state = State(code="Cu-PVC-BK-16")
    work_center = WorkCenter(code="extrude-01", capability_group="extrusion")
    low = Order(
        id=uuid4(),
        external_ref="LOW",
        due_date=_H0 + timedelta(hours=10),
        priority=100,
    )
    rush = Order(
        id=uuid4(),
        external_ref="RUSH",
        due_date=_H0 + timedelta(hours=10),
        priority=900,
    )
    first = Operation(
        id=uuid4(),
        order_id=low.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=60,
        eligible_wc_ids=[work_center.id],
    )
    second = Operation(
        id=uuid4(),
        order_id=rush.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=10,
        eligible_wc_ids=[work_center.id],
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[low, rush],
        operations=[first, second],
        work_centers=[work_center],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(hours=12),
    )
    base = [
        Assignment(
            operation_id=first.id,
            work_center_id=work_center.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=60),
        ),
        Assignment(
            operation_id=second.id,
            work_center_id=work_center.id,
            start_time=_H0 + timedelta(minutes=60),
            end_time=_H0 + timedelta(minutes=70),
        ),
    ]
    return problem, base, first, second


def test_freeze_blocks_rush_from_stealing_issued_slot() -> None:
    problem, base, first, second = _rush_pair_problem()
    freeze_end = _H0 + timedelta(hours=3)
    repaired = IncrementalRepair().solve(
        problem,
        base_assignments=base,
        disrupted_op_ids=[first.id, second.id],
        radius=5,
        freeze_horizon_end=freeze_end,
        allow_freeze_break=False,
        regime=SolveRegime.RUSH_ORDER,
    )
    by_op = {row.operation_id: row for row in repaired.assignments}
    assert by_op[first.id].start_time == _H0
    unconstrained = IncrementalRepair().solve(
        problem,
        base_assignments=base,
        disrupted_op_ids=[first.id, second.id],
        radius=5,
        regime=SolveRegime.RUSH_ORDER,
    )
    unconstrained_by_op = {row.operation_id: row for row in unconstrained.assignments}
    assert unconstrained_by_op[second.id].start_time <= unconstrained_by_op[first.id].start_time


def test_family_dedicated_lines_split_pvc_xlpe() -> None:
    problem = generate_cable_instance(
        n_orders=4,
        seed=1,
        machines_per_stage=2,
        family_dedicated_lines=True,
        skus=(
            CableSku("Cu", "PVC", "BK", 16),
            CableSku("Cu", "XLPE", "BK", 16),
        ),
    )
    pvc_ids: set = set()
    xlpe_ids: set = set()
    states = {state.id: state for state in problem.states}
    for operation in problem.operations:
        insulation = str(states[operation.state_id].domain_attributes.get("insulation"))
        if insulation == "PVC":
            pvc_ids.update(operation.eligible_wc_ids)
        else:
            xlpe_ids.update(operation.eligible_wc_ids)
    assert pvc_ids
    assert xlpe_ids
    assert pvc_ids.isdisjoint(xlpe_ids)


def test_family_lines_follow_sku_mix_not_half() -> None:
    problem = generate_cable_instance(
        n_orders=6,
        seed=1,
        machines_per_stage=3,
        family_dedicated_lines=True,
        skus=(
            CableSku("Cu", "PVC", "BK", 16),
            CableSku("Cu", "XLPE", "BK", 16),
            CableSku("Al", "XLPE", "BK", 16),
        ),
    )
    pvc_ids: set = set()
    xlpe_ids: set = set()
    states = {state.id: state for state in problem.states}
    for operation in problem.operations:
        insulation = str(states[operation.state_id].domain_attributes.get("insulation"))
        if insulation == "PVC":
            pvc_ids.update(operation.eligible_wc_ids)
        else:
            xlpe_ids.update(operation.eligible_wc_ids)
    assert pvc_ids
    assert xlpe_ids
    by_group: dict[str, list] = {}
    for center in problem.work_centers:
        by_group.setdefault(center.capability_group, []).append(center.id)
    for ids in by_group.values():
        pvc_in = pvc_ids.intersection(ids)
        xlpe_in = xlpe_ids.intersection(ids)
        assert len(pvc_in) == 2
        assert len(xlpe_in) == 2
        assert len(pvc_in & xlpe_in) == 1


def test_colour_wheel_staggers_colours_not_past_due() -> None:
    """Colour wheel staggers colours; rush due skips a wait that would pass due."""

    horizon = _H0
    state_bk = State(
        id=uuid4(),
        code="Cu-PVC-BK-16",
        domain_attributes={"insulation": "PVC", "color": "BK", "section_mm2": 16},
    )
    state_rd = State(
        id=uuid4(),
        code="Cu-PVC-RD-16",
        domain_attributes={"insulation": "PVC", "color": "RD", "section_mm2": 16},
    )
    wc = WorkCenter(code="draw-01", capability_group="drawing")
    bk_order = Order(
        id=uuid4(),
        external_ref="BK",
        release_date=horizon,
        due_date=horizon + timedelta(hours=72),
    )
    rd_order = Order(
        id=uuid4(),
        external_ref="RD",
        release_date=horizon,
        due_date=horizon + timedelta(hours=72),
    )
    rush = Order(
        id=uuid4(),
        external_ref="RUSH-GY",
        release_date=horizon,
        due_date=horizon + timedelta(hours=4),
    )
    state_gy = State(
        id=uuid4(),
        code="Cu-PVC-GY-16",
        domain_attributes={"insulation": "PVC", "color": "GY", "section_mm2": 16},
    )
    op_bk = Operation(
        id=uuid4(),
        order_id=bk_order.id,
        seq_in_order=1,
        state_id=state_bk.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    op_rd = Operation(
        id=uuid4(),
        order_id=rd_order.id,
        seq_in_order=1,
        state_id=state_rd.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    op_rush = Operation(
        id=uuid4(),
        order_id=rush.id,
        seq_in_order=1,
        state_id=state_gy.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state_bk, state_rd, state_gy],
        orders=[bk_order, rd_order, rush],
        operations=[op_bk, op_rd, op_rush],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=horizon,
        planning_horizon_end=horizon + timedelta(hours=168),
    )
    apply_campaign_windows(problem, slot_hours=8, colour_phase=True, colour_cycle=6)
    assert op_bk.earliest_start == horizon
    assert op_rd.earliest_start == horizon + timedelta(hours=8)
    assert op_rush.earliest_start == horizon


def test_colour_lines_one_machine_per_colour() -> None:
    from synaps.domains.cable.adapter import CABLE_COLORS

    skus = tuple(CableSku("Cu", "PVC", color, 16) for color in CABLE_COLORS)
    problem = generate_cable_instance(
        n_orders=6,
        seed=1,
        machines_per_stage=6,
        colour_dedicated_lines=True,
        skus=skus,
    )
    states = {state.id: state for state in problem.states}
    by_group: dict[str, list] = {}
    for center in problem.work_centers:
        by_group.setdefault(center.capability_group, []).append(center.id)
    colour_wcs: dict[str, set] = {color: set() for color in CABLE_COLORS}
    for operation in problem.operations:
        color = str(states[operation.state_id].domain_attributes.get("color"))
        colour_wcs[color].update(operation.eligible_wc_ids)
    for ids in by_group.values():
        id_set = set(ids)
        parts = [colour_wcs[color] & id_set for color in CABLE_COLORS]
        assert all(len(part) == 1 for part in parts)
        assert len(set().union(*parts)) == 6


def test_family_and_colour_lines_colour_split_inside_family() -> None:
    from synaps.domains.cable.adapter import CABLE_COLORS

    problem = generate_cable_instance(
        n_orders=36,
        seed=1,
        machines_per_stage=8,
        family_dedicated_lines=True,
        colour_dedicated_lines=True,
        skus=nervous_sku_catalog(),
        stages=NERVOUS_STAGES,
    )
    states = {state.id: state for state in problem.states}
    by_group: dict[str, list] = {}
    for center in problem.work_centers:
        by_group.setdefault(center.capability_group, []).append(center.id)
    pvc_ids: set = set()
    xlpe_by_colour: dict[str, set] = {color: set() for color in CABLE_COLORS}
    for operation in problem.operations:
        attrs = states[operation.state_id].domain_attributes
        if str(attrs.get("insulation")) == "PVC":
            pvc_ids.update(operation.eligible_wc_ids)
        else:
            xlpe_by_colour[str(attrs.get("color"))].update(operation.eligible_wc_ids)
    for ids in by_group.values():
        id_set = set(ids)
        pvc_in = pvc_ids & id_set
        assert len(pvc_in) == 3
        xlpe_parts = [xlpe_by_colour[color] & id_set for color in CABLE_COLORS]
        assert all(len(part) == 1 for part in xlpe_parts)
        assert len(set().union(*xlpe_parts)) == 6
        assert len(pvc_in & set().union(*xlpe_parts)) == 1


def test_tight_shop_auto_family_colour_exhaust_not_wheel() -> None:
    from synaps.domains.cable.nervous_month import _resolve_tight_shop_levers

    family, colour, phase, exhaust = _resolve_tight_shop_levers(
        8,
        family_dedicated_lines=None,
        colour_dedicated_lines=None,
        colour_phase=None,
        cover_atcs_exhaust_window=None,
    )
    assert (family, colour, phase, exhaust) == (True, False, True, 240.0)
    family, colour, phase, exhaust = _resolve_tight_shop_levers(
        16,
        family_dedicated_lines=None,
        colour_dedicated_lines=None,
        colour_phase=None,
        cover_atcs_exhaust_window=None,
    )
    assert (family, colour, phase, exhaust) == (False, False, True, 0.0)
    family, colour, phase, exhaust = _resolve_tight_shop_levers(
        2,
        family_dedicated_lines=None,
        colour_dedicated_lines=None,
        colour_phase=None,
        cover_atcs_exhaust_window=None,
    )
    assert (family, colour, phase, exhaust) == (False, False, True, 240.0)


def test_colour_phase_does_not_pass_due() -> None:
    problem = generate_cable_instance(
        n_orders=12,
        seed=1,
        horizon_hours=720,
        rush_fraction=0.15,
        scatter_releases=True,
        shuffle_skus=True,
        colour_phase=True,
    )
    orders = {order.id: order for order in problem.orders}
    for operation in problem.operations:
        if operation.seq_in_order != 1 or operation.earliest_start is None:
            continue
        assert operation.earliest_start < orders[operation.order_id].due_date


def test_add_rush_orders_grows_and_repairs() -> None:
    problem = generate_cable_instance(n_orders=2, seed=1, horizon_hours=240)
    base = GreedyDispatch().solve(problem)
    assert base.status is SolverStatus.FEASIBLE
    release = problem.planning_horizon_start + timedelta(days=1)
    mutated = add_rush_orders(
        problem,
        n_orders=1,
        release=release,
        due=release + timedelta(hours=48),
        seed=7,
    )
    assert len(mutated.operations) > len(problem.operations)
    new_ids = {op.id for op in mutated.operations} - {op.id for op in problem.operations}
    repaired = IncrementalRepair().solve(
        mutated,
        base_assignments=base.assignments,
        disrupted_op_ids=list(new_ids),
        radius=4,
        freeze_horizon_end=release,
        allow_freeze_break=False,
        regime=SolveRegime.RUSH_ORDER,
    )
    assert repaired.status is SolverStatus.FEASIBLE
    hard = proven_hard_violations(
        FeasibilityChecker().check(mutated, repaired.assignments, exhaustive=True)
    )
    assert hard == []


def test_pin_issued_plan_blocks_rush_on_first_solve() -> None:
    problem, base, first, _second = _rush_pair_problem()
    freeze_end = _H0 + timedelta(hours=3)
    result = solve_schedule(
        problem,
        solver_config="GREED",
        solve_kwargs={
            "issued_assignments": base,
            "freeze_horizon_end": freeze_end,
        },
        verify_feasibility=True,
    )
    by_op = {row.operation_id: row for row in result.assignments}
    assert by_op[first.id].start_time == _H0
    assert by_op[first.id].work_center_id == base[0].work_center_id
    assert by_op[first.id].end_time <= freeze_end or by_op[first.id].start_time < freeze_end


def test_cpsat_cable_weights_do_not_increase_material() -> None:
    problem = generate_cable_instance(
        n_orders=3, seed=1, machines_per_stage=1, horizon_hours=240
    )
    makespan_only = CpSatSolver().solve(
        problem,
        time_limit_s=8,
        objective_weights={
            "makespan": 100,
            "setup": 0,
            "material": 0,
            "tardiness": 0,
            "energy": 0,
        },
    )
    weighted = CpSatSolver().solve(
        problem,
        time_limit_s=8,
        objective_weights=CABLE_PVC_CPSAT_WEIGHTS,
    )
    assert makespan_only.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
    assert weighted.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
    makespan_obj = evaluate(problem, makespan_only.assignments)
    weighted_obj = evaluate(problem, weighted.assignments)
    assert weighted_obj.total_material_loss <= makespan_obj.total_material_loss


def test_nervous_sku_catalog_and_tiny_month_feasible() -> None:
    assert len(nervous_sku_catalog()) == 36
    assert len(NERVOUS_STAGES) == 6
    problem = generate_nervous_month(
        n_orders=8,
        seed=1,
        machines_per_stage=2,
        drum_pool_size=24,
    )
    assert problem.planning_horizon_end - problem.planning_horizon_start == timedelta(hours=720)
    assert any(order.release_date is not None for order in problem.orders)
    assert {op.domain_attributes["stage"] for op in problem.operations} >= {"draw", "pack"}
    report = run_nervous_month(
        n_orders=8,
        seed=1,
        waves=1,
        disruptions_per_wave=2,
        machines_per_stage=2,
        drum_pool_size=24,
    )
    assert report["status"] == "feasible"
    assert report["notary_hard_violations"] == 0
    assert report["n_operations"] == len(problem.operations)
    assert report["solver_config"] == "GREED"
    assert report["temporal_stabilization_converged"] is None
    assert report["temporal_stabilization_note"] == "n/a (GREED)"
    assert report["waves"]
    assert report["waves"][0]["notary_hard_violations"] == 0
    assert report["waves"][0]["notary_kinds"] == []
    assert report["waves"][0]["notary_sample"] is None
    assert report["waves"][0]["unrepaired_count"] == 0
    assert report["waves"][0]["repair_notary_mode"] == "exhaustive"
    assert report["waves"][0]["repair_notary_mismatch"] is False
    assert report["new_rush"]["kind"] == "new_parent_insert"
    assert report["new_rush"]["n_new_parents"] == 2


def test_nervous_report_ok_rejects_dirty_wave() -> None:
    """C6-R1: an infeasible week must fail the CLI oracle. Skipped is not dirty."""

    cover = {
        "status": "feasible",
        "notary_hard_violations": 0,
        "waves": [
            {"skipped": False, "status": "feasible", "notary_hard_violations": 0},
            {"skipped": False, "status": "infeasible", "notary_hard_violations": 1},
        ],
    }
    assert nervous_report_ok(cover) is False
    skipped_only = {
        "status": "feasible",
        "notary_hard_violations": 0,
        "waves": [{"skipped": True}],
    }
    assert nervous_report_ok(skipped_only) is True


def test_parse_nervous_seeds_overrides_single_seed() -> None:
    assert parse_nervous_seeds(None, 7) == (7,)
    assert parse_nervous_seeds(" 1, 2,3 ", 9) == (1, 2, 3)
    with pytest.raises(ValueError):
        parse_nervous_seeds(" , , ", 1)


def test_nervous_multiseed_tiny_aggregates() -> None:
    report = run_nervous_month_multiseed(
        (1, 2),
        n_orders=6,
        waves=0,
        new_rush_orders=0,
        machines_per_stage=2,
        drum_pool_size=24,
    )
    assert report["n_runs"] == 2
    assert report["seeds"] == [1, 2]
    assert report["all_feasible"] is True
    assert report["notary_hard_violations"] == [0, 0]
    assert len(report["tardiness_minutes"]) == 2
    assert {run["seed"] for run in report["runs"]} == {1, 2}
    assert all(run["solver_config"] == "GREED" for run in report["runs"])


def test_freeze_insert_pair_tiny_keeps_freeze_feasible() -> None:
    report = run_freeze_insert_pair(
        n_orders=6,
        seed=1,
        machines_per_stage=2,
        drum_pool_size=24,
        n_rush=1,
        n_steal=2,
    )
    assert report["all_feasible"] is True
    assert report["n_new_ops"] >= 1
    assert report["rush"]["freeze_repair"]["status"] == "feasible"
    assert report["steal"]["freeze"]["status"] == "feasible"
    freeze_h = float(report["steal"]["freeze"]["kpis"]["stability_hamming"])
    open_h = float(report["steal"]["open"]["kpis"]["stability_hamming"])
    assert freeze_h <= open_h


def test_weighted_residual_pair_tiny_keeps_cover_and_notary() -> None:
    """C6c plumbing: COVER stays GREED; ALNS residuals stay feasible. Quality is the probe."""

    report = run_weighted_residual_pair(
        n_orders=6,
        seed=1,
        machines_per_stage=2,
        drum_pool_size=24,
        residual_time_limit_s=8.0,
        residual_max_iterations=2,
        residual_use_cpsat_repair=False,
    )
    assert report["all_feasible"] is True
    assert report["cover"]["solver_config"] == "GREED"
    assert report["cover"]["coverage"] == 1.0
    assert report["makespan_residual"]["coverage"] == 1.0
    assert report["pvc_residual"]["coverage"] == 1.0
    assert report["makespan_residual"]["notary_hard_violations"] == 0
    assert report["pvc_residual"]["notary_hard_violations"] == 0
    assert "scalar_cable_pvc" in report["cover"]
    assert isinstance(report["scalar_improved"], bool)
    assert isinstance(report["tardiness_delta"], int)


def test_residual_destroy_shrinks_on_large_cover() -> None:
    """300-op destroy on 20k ops completed one ALNS iteration in 90 s (0 improvements)."""

    from synaps.domains.cable.nervous_month import _residual_destroy_kwargs

    large = _residual_destroy_kwargs(20_316, True)
    assert large["max_destroy"] == 24
    assert large["min_destroy"] == 8
    tiny = _residual_destroy_kwargs(70, False)
    assert tiny["max_destroy"] == 8
