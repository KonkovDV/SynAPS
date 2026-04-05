"""Tests for Pydantic domain model (model.py)."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from synaps.model import (
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
            due_date=datetime(2026, 1, 1, tzinfo=UTC),
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
            orders=[Order(external_ref="O1", due_date=datetime(2026, 6, 1, tzinfo=UTC))],
            operations=[],
            work_centers=[WorkCenter(code="WC1", capability_group="mill")],
            setup_matrix=[],
            planning_horizon_start=datetime(2026, 6, 1, tzinfo=UTC),
            planning_horizon_end=datetime(2026, 6, 2, tzinfo=UTC),
        )
        json_str = problem.model_dump_json()
        restored = ScheduleProblem.model_validate_json(json_str)
        assert len(restored.states) == 1
        assert restored.states[0].code == "A"

    def test_schedule_problem_rejects_invalid_cross_references(
        self, simple_problem: ScheduleProblem
    ) -> None:
        data = simple_problem.model_dump()
        data["operations"][0]["eligible_wc_ids"] = [uuid4()]
        data["setup_matrix"][0]["from_state_id"] = uuid4()
        data["aux_requirements"] = [
            {
                "operation_id": data["operations"][0]["id"],
                "aux_resource_id": uuid4(),
                "quantity_needed": 1,
            }
        ]

        with pytest.raises(ValidationError) as exc_info:
            ScheduleProblem.model_validate(data)

        message = str(exc_info.value)
        assert "unknown eligible_wc_ids" in message
        assert "unknown from_state_id" in message
        assert "unknown aux_resource_id" in message

    def test_schedule_problem_rejects_duplicate_setup_and_aux_links(
        self, simple_problem: ScheduleProblem
    ) -> None:
        data = simple_problem.model_dump()
        duplicated_setup = dict(data["setup_matrix"][0])
        data["setup_matrix"].append(duplicated_setup)

        resource_id = uuid4()
        data["auxiliary_resources"] = [
            {
                "id": resource_id,
                "code": "TOOL-1",
                "resource_type": "fixture",
                "pool_size": 1,
            }
        ]
        data["aux_requirements"] = [
            {
                "operation_id": data["operations"][0]["id"],
                "aux_resource_id": resource_id,
                "quantity_needed": 1,
            },
            {
                "operation_id": data["operations"][0]["id"],
                "aux_resource_id": resource_id,
                "quantity_needed": 1,
            },
        ]

        with pytest.raises(ValidationError) as exc_info:
            ScheduleProblem.model_validate(data)

        message = str(exc_info.value)
        assert "duplicate setup_matrix key" in message
        assert "duplicate aux_requirement key" in message

    def test_schedule_problem_autofills_predecessor_chain_from_seq_in_order(self) -> None:
        horizon_start = datetime(2026, 6, 1, tzinfo=UTC)
        order = Order(external_ref="ORD-CHAIN", due_date=datetime(2026, 6, 2, tzinfo=UTC))
        state = State(code="A")
        work_center = WorkCenter(code="WC-1", capability_group="mill")
        op_1 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        )
        op_2 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=1,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        )
        op_3 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=2,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        )

        problem = ScheduleProblem(
            states=[state],
            orders=[order],
            operations=[op_1, op_2, op_3],
            work_centers=[work_center],
            setup_matrix=[],
            planning_horizon_start=horizon_start,
            planning_horizon_end=datetime(2026, 6, 3, tzinfo=UTC),
        )

        assert problem.operations[0].predecessor_op_id is None
        assert problem.operations[1].predecessor_op_id == op_1.id
        assert problem.operations[2].predecessor_op_id == op_2.id

    def test_schedule_problem_rejects_conflicting_same_order_predecessor_chain(self) -> None:
        horizon_start = datetime(2026, 6, 1, tzinfo=UTC)
        order = Order(external_ref="ORD-BAD-CHAIN", due_date=datetime(2026, 6, 2, tzinfo=UTC))
        state = State(code="A")
        work_center = WorkCenter(code="WC-1", capability_group="mill")
        op_1 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        )
        op_2 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=1,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        )
        op_3 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=2,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
            predecessor_op_id=op_1.id,
        )

        with pytest.raises(ValidationError) as exc_info:
            ScheduleProblem(
                states=[state],
                orders=[order],
                operations=[op_1, op_2, op_3],
                work_centers=[work_center],
                setup_matrix=[],
                planning_horizon_start=horizon_start,
                planning_horizon_end=datetime(2026, 6, 3, tzinfo=UTC),
            )

        assert "must reference predecessor_op_id" in str(exc_info.value)

    def test_schedule_problem_rejects_cross_order_predecessor_reference(self) -> None:
        horizon_start = datetime(2026, 6, 1, tzinfo=UTC)
        state = State(code="A")
        work_center = WorkCenter(code="WC-1", capability_group="mill")
        order_a = Order(external_ref="ORD-A", due_date=datetime(2026, 6, 2, tzinfo=UTC))
        order_b = Order(external_ref="ORD-B", due_date=datetime(2026, 6, 2, tzinfo=UTC))
        foreign_op = Operation(
            id=uuid4(),
            order_id=order_b.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        )
        local_op_1 = Operation(
            id=uuid4(),
            order_id=order_a.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        )
        local_op_2 = Operation(
            id=uuid4(),
            order_id=order_a.id,
            seq_in_order=1,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
            predecessor_op_id=foreign_op.id,
        )

        with pytest.raises(ValidationError) as exc_info:
            ScheduleProblem(
                states=[state],
                orders=[order_a, order_b],
                operations=[local_op_1, local_op_2, foreign_op],
                work_centers=[work_center],
                setup_matrix=[],
                planning_horizon_start=horizon_start,
                planning_horizon_end=datetime(2026, 6, 3, tzinfo=UTC),
            )

        assert "different order" in str(exc_info.value)
