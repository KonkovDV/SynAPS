"""Tests for Pydantic domain model (model.py)."""

from datetime import datetime, timezone
from uuid import UUID

from syn_aps.model import (
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
    State,
    WorkCenter,
)


class TestDomainModel:
    def test_state_defaults(self) -> None:
        s = State(code="TEST")
        assert isinstance(s.id, UUID)
        assert s.domain_attributes == {}

    def test_order_defaults(self) -> None:
        o = Order(
            external_ref="ORD-001",
            due_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert o.priority == 500
        assert o.quantity == 1.0
        assert o.unit == "pcs"

    def test_operation_fields(self) -> None:
        order_id = State(code="X").id  # just get a UUID
        state_id = State(code="Y").id
        op = Operation(
            order_id=order_id,
            seq_in_order=0,
            state_id=state_id,
            base_duration_min=60,
        )
        assert op.predecessor_op_id is None
        assert op.eligible_wc_ids == []

    def test_schedule_result_serialization(self) -> None:
        result = ScheduleResult(
            solver_name="test",
            status=SolverStatus.OPTIMAL,
            objective=ObjectiveValues(makespan_minutes=120.0),
        )
        data = result.model_dump()
        assert data["solver_name"] == "test"
        assert data["status"] == "optimal"
        assert data["objective"]["makespan_minutes"] == 120.0

    def test_schedule_problem_roundtrip(self) -> None:
        problem = ScheduleProblem(
            states=[State(code="A")],
            orders=[Order(external_ref="O1", due_date=datetime(2026, 6, 1, tzinfo=timezone.utc))],
            operations=[],
            work_centers=[WorkCenter(code="WC1", capability_group="mill")],
            setup_matrix=[],
            planning_horizon_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            planning_horizon_end=datetime(2026, 6, 2, tzinfo=timezone.utc),
        )
        json_str = problem.model_dump_json()
        restored = ScheduleProblem.model_validate_json(json_str)
        assert len(restored.states) == 1
        assert restored.states[0].code == "A"
