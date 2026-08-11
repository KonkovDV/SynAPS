"""Wave 5: SetupEntry.energy_kwh flows into ObjectiveValues (T-35) + p_om helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.objective import DEFAULT_WEIGHTS, evaluate, scalarize
from synaps.timegrain import (
    duration_minutes,
    duration_minutes_for,
    physical_processing_minutes_for,
)

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def test_evaluate_aggregates_setup_energy_kwh() -> None:
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    orders = [Order(external_ref="O1", due_date=_HE), Order(external_ref="O2", due_date=_HE)]
    ops = [
        Operation(
            order_id=orders[0].id,
            seq_in_order=1,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        ),
        Operation(
            order_id=orders[1].id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        ),
    ]
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=orders,
        operations=ops,
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=5,
                energy_kwh=3.5,
            )
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    assignments = [
        Assignment(
            operation_id=ops[0].id,
            work_center_id=wc.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=10),
        ),
        Assignment(
            operation_id=ops[1].id,
            work_center_id=wc.id,
            start_time=_H0 + timedelta(minutes=15),
            end_time=_H0 + timedelta(minutes=25),
        ),
    ]
    obj = evaluate(problem, assignments)
    assert obj.total_energy_kwh == 3.5
    assert obj.total_setup_minutes == 5.0
    assert DEFAULT_WEIGHTS["energy"] == 0.0
    assert scalarize(obj) == obj.makespan_minutes


def test_duration_minutes_for_honors_override() -> None:
    wc_fast = WorkCenter(code="F", capability_group="G", speed_factor=2.0)
    wc_slow = WorkCenter(code="S", capability_group="G", speed_factor=1.0)
    order_id = uuid4()
    state_id = uuid4()
    op = Operation(
        order_id=order_id,
        seq_in_order=1,
        state_id=state_id,
        base_duration_min=10,
        eligible_wc_ids=[wc_fast.id, wc_slow.id],
        machine_duration_overrides={wc_fast.id: 7, wc_slow.id: 12},
    )
    assert duration_minutes_for(op, wc_fast) == 7
    assert duration_minutes_for(op, wc_slow) == 12
    assert physical_processing_minutes_for(op, wc_fast) == 7.0
    op2 = Operation(
        order_id=order_id,
        seq_in_order=2,
        state_id=state_id,
        base_duration_min=10,
        eligible_wc_ids=[wc_fast.id],
    )
    assert duration_minutes_for(op2, wc_fast) == duration_minutes(10, 2.0)


def test_solver_boundary_publishes_setup_energy() -> None:
    """C1 / T-35: BaseSolver must publish evaluate()'s total_energy_kwh."""
    from synaps.solvers.greedy_dispatch import GreedyDispatch

    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    orders = [Order(external_ref="O1", due_date=_HE), Order(external_ref="O2", due_date=_HE)]
    ops = [
        Operation(
            order_id=orders[0].id,
            seq_in_order=1,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        ),
        Operation(
            order_id=orders[1].id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        ),
    ]
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=orders,
        operations=ops,
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=5,
                energy_kwh=3.5,
            )
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    result = GreedyDispatch().solve(problem, time_limit_s=5)
    assert result.assignments
    canonical = evaluate(problem, list(result.assignments))
    assert canonical.total_energy_kwh == result.objective.total_energy_kwh
    # On this two-op serial chain the greedy schedule must charge the setup energy.
    if len(result.assignments) == 2:
        assert result.objective.total_energy_kwh == 3.5
