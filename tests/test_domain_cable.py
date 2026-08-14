"""Cable domain adapter, KPIs, freeze policy, and GREEDY smoke (encode-first)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.domains.cable import (
    CABLE_PVC_WEIGHTS,
    CableSku,
    assignment_hamming,
    cable_kpis,
    duration_minutes_from_length,
    generate_cable_instance,
    peak_wip_drums,
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
from synaps.objective import scalarize
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
    assert kpis["stability_hamming"] == 0.0
    assert peak_wip_drums(problem, result.assignments) == kpis["peak_wip_drums"]


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
