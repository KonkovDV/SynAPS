"""Wave 8 tests: energy cost preference + canonical objective attach."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import (
    Assignment,
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    ScheduleResult,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers import _attach_canonical_objective
from synaps.solvers.alns_solver import _objective_cost

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def test_objective_cost_prefers_lower_energy_when_weighted() -> None:
    """RT17-M5: energy weight must change ranking when makespan is tied."""
    low = ObjectiveValues(makespan_minutes=10.0, total_energy_kwh=1.0)
    high = ObjectiveValues(makespan_minutes=10.0, total_energy_kwh=9.0)
    weights = {"makespan": 1.0, "energy": 2.0}
    assert _objective_cost(low, weights) < _objective_cost(high, weights)
    assert _objective_cost(low, {"makespan": 1.0}) == _objective_cost(
        high, {"makespan": 1.0}
    )


def test_attach_canonical_objective_replaces_full_vector() -> None:
    """RT17-M2: boundary assigns a fresh ObjectiveValues (no silent field drop)."""
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op1 = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s1.id,
        base_duration_min=5,
        eligible_wc_ids=[wc.id],
    )
    op2 = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=s2.id,
        base_duration_min=5,
        eligible_wc_ids=[wc.id],
        predecessor_op_id=op1.id,
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=[order],
        operations=[op1, op2],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=1,
                energy_kwh=3.5,
            )
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    assignments = [
        Assignment(
            operation_id=op1.id,
            work_center_id=wc.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=5),
        ),
        Assignment(
            operation_id=op2.id,
            work_center_id=wc.id,
            start_time=_H0 + timedelta(minutes=6),
            end_time=_H0 + timedelta(minutes=11),
            setup_minutes=1,
        ),
    ]
    stale = ObjectiveValues(makespan_minutes=999.0, total_energy_kwh=0.0)
    result = ScheduleResult(
        solver_name="probe",
        status=SolverStatus.FEASIBLE,
        assignments=assignments,
        objective=stale,
    )
    _attach_canonical_objective(result, problem)
    assert result.objective is not stale
    assert result.objective.makespan_minutes < 999.0
    assert result.objective.total_energy_kwh == 3.5
