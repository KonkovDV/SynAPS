"""F3-consistency (audit v4): canonical evaluate() infers lanes for parallel
machines without lane metadata instead of charging phantom cross-lane setups.

Two ops overlapping in time on a 2-lane machine with different states can
physically run on separate lanes — NO changeover exists. Pre-fix, evaluate()
grouped by (work_center_id, None) and charged a setup between them, diverging
from the FeasibilityChecker's lane-aware semantics. evaluate() now runs the
same exact lane inference as the checker.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.objective import evaluate

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _problem(setup_minutes: int) -> tuple[ScheduleProblem, list[Assignment]]:
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G", max_parallel=2)
    orders = [Order(external_ref=f"O{i}", due_date=_H0 + timedelta(days=1)) for i in (1, 2)]
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
                setup_minutes=setup_minutes,
                material_loss=2.0,
            ),
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=1),
    )
    # Fully concurrent: physically separate lanes, no setup exists.
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
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=10),
        ),
    ]
    return problem, assignments


def test_concurrent_parallel_ops_incur_no_phantom_setup() -> None:
    problem, assignments = _problem(setup_minutes=30)
    obj = evaluate(problem, assignments)
    assert obj.total_setup_minutes == 0.0, (
        f"phantom cross-lane setup charged: {obj.total_setup_minutes}"
    )
    assert obj.total_material_loss == 0.0


def test_sequential_ops_still_charge_setup() -> None:
    """Control: forced onto one lane by time order, the setup IS charged."""
    problem, assignments = _problem(setup_minutes=30)
    assignments[1].start_time = _H0 + timedelta(minutes=40)
    assignments[1].end_time = _H0 + timedelta(minutes=50)
    obj = evaluate(problem, assignments)
    assert obj.total_setup_minutes == 30.0
    assert obj.total_material_loss == 2.0
