"""Tests for GreedyDispatch solver."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch


class TestGreedyDispatch:
    def test_produces_feasible_result(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)

        assert result.status == SolverStatus.FEASIBLE
        assert result.solver_name == "greedy_dispatch"
        assert result.metadata["acceleration"]["atcs_log_score_backend"] in {"python", "native"}

    def test_all_operations_assigned(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)

        assigned_ops = {a.operation_id for a in result.assignments}
        expected_ops = {op.id for op in simple_problem.operations}
        assert assigned_ops == expected_ops

    def test_assignments_pass_feasibility(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)
        checker = FeasibilityChecker()

        violations = checker.check(simple_problem, result.assignments)
        assert violations == [], f"Violations found: {violations}"

    def test_runs_under_200ms(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)

        assert result.duration_ms < 200, f"Took {result.duration_ms}ms, budget is 200ms"

    def test_respects_precedence(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)

        assignment_map = {a.operation_id: a for a in result.assignments}
        for op in simple_problem.operations:
            if op.predecessor_op_id:
                pred = assignment_map[op.predecessor_op_id]
                cur = assignment_map[op.id]
                assert cur.start_time >= pred.end_time, f"Op {op.id} starts before predecessor ends"

    def test_makespan_is_positive(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)

        assert result.objective.makespan_minutes > 0

    def test_respects_auxiliary_resource_pool(self) -> None:
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=4)
        state = State(id=uuid4(), code="STATE-A")
        work_center_1 = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
        work_center_2 = WorkCenter(id=uuid4(), code="WC-2", capability_group="machining")
        resource = AuxiliaryResource(
            id=uuid4(),
            code="TOOL-1",
            resource_type="tool",
            pool_size=1,
        )

        order_a = Order(
            id=uuid4(),
            external_ref="ORD-A",
            due_date=horizon_start + timedelta(hours=2),
            priority=700,
        )
        order_b = Order(
            id=uuid4(),
            external_ref="ORD-B",
            due_date=horizon_start + timedelta(hours=2),
            priority=500,
        )
        operation_a = Operation(
            id=uuid4(),
            order_id=order_a.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center_1.id],
        )
        operation_b = Operation(
            id=uuid4(),
            order_id=order_b.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center_2.id],
        )
        problem = ScheduleProblem(
            states=[state],
            orders=[order_a, order_b],
            operations=[operation_a, operation_b],
            work_centers=[work_center_1, work_center_2],
            setup_matrix=[],
            auxiliary_resources=[resource],
            aux_requirements=[
                OperationAuxRequirement(operation_id=operation_a.id, aux_resource_id=resource.id),
                OperationAuxRequirement(operation_id=operation_b.id, aux_resource_id=resource.id),
            ],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        solver = GreedyDispatch()
        result = solver.solve(problem)

        assert result.status == SolverStatus.FEASIBLE
        assignment_a = next(a for a in result.assignments if a.operation_id == operation_a.id)
        assignment_b = next(a for a in result.assignments if a.operation_id == operation_b.id)
        assert assignment_b.start_time >= assignment_a.end_time

        checker = FeasibilityChecker()
        violations = checker.check(problem, result.assignments)
        assert violations == [], f"Violations found: {violations}"

    def test_prefers_lower_material_loss_when_setup_and_due_terms_tie(self) -> None:
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=6)

        state_a = State(id=uuid4(), code="STATE-A")
        state_b = State(id=uuid4(), code="STATE-B")
        work_center_1 = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
        work_center_2 = WorkCenter(id=uuid4(), code="WC-2", capability_group="machining")

        order_a = Order(
            id=uuid4(),
            external_ref="ORD-A",
            due_date=horizon_start + timedelta(hours=1),
            priority=1000,
        )
        order_b = Order(
            id=uuid4(),
            external_ref="ORD-B",
            due_date=horizon_start + timedelta(hours=1),
            priority=900,
        )
        order_c = Order(
            id=uuid4(),
            external_ref="ORD-C",
            due_date=horizon_start + timedelta(hours=4),
            priority=500,
        )

        operation_a = Operation(
            id=uuid4(),
            order_id=order_a.id,
            seq_in_order=0,
            state_id=state_a.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center_1.id],
        )
        operation_b = Operation(
            id=uuid4(),
            order_id=order_b.id,
            seq_in_order=0,
            state_id=state_a.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center_2.id],
        )
        operation_c = Operation(
            id=uuid4(),
            order_id=order_c.id,
            seq_in_order=0,
            state_id=state_b.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center_1.id, work_center_2.id],
        )

        problem = ScheduleProblem(
            states=[state_a, state_b],
            orders=[order_a, order_b, order_c],
            operations=[operation_a, operation_b, operation_c],
            work_centers=[work_center_1, work_center_2],
            setup_matrix=[
                SetupEntry(
                    work_center_id=work_center_1.id,
                    from_state_id=state_a.id,
                    to_state_id=state_b.id,
                    setup_minutes=5,
                    material_loss=9.0,
                ),
                SetupEntry(
                    work_center_id=work_center_2.id,
                    from_state_id=state_a.id,
                    to_state_id=state_b.id,
                    setup_minutes=5,
                    material_loss=1.0,
                ),
            ],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        result = GreedyDispatch().solve(problem)

        assert result.status == SolverStatus.FEASIBLE
        material_sensitive_assignment = next(
            assignment
            for assignment in result.assignments
            if assignment.operation_id == operation_c.id
        )
        assert material_sensitive_assignment.work_center_id == work_center_2.id
        assert result.objective.total_material_loss == 1.0

    def test_respects_auxiliary_resource_setup_windows(self) -> None:
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=4)

        state_a = State(id=uuid4(), code="STATE-A")
        state_b = State(id=uuid4(), code="STATE-B")
        wc_1 = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
        wc_2 = WorkCenter(id=uuid4(), code="WC-2", capability_group="machining")
        tool = AuxiliaryResource(id=uuid4(), code="SETUP-TOOL", resource_type="crew", pool_size=1)

        order_a = Order(id=uuid4(), external_ref="ORD-A", due_date=horizon_end, priority=700)
        order_b = Order(id=uuid4(), external_ref="ORD-B", due_date=horizon_end, priority=600)

        op_a1 = Operation(
            id=uuid4(),
            order_id=order_a.id,
            seq_in_order=0,
            state_id=state_a.id,
            base_duration_min=30,
            eligible_wc_ids=[wc_1.id],
        )
        op_a2 = Operation(
            id=uuid4(),
            order_id=order_a.id,
            seq_in_order=1,
            state_id=state_b.id,
            base_duration_min=30,
            eligible_wc_ids=[wc_1.id],
            predecessor_op_id=op_a1.id,
        )
        op_b1 = Operation(
            id=uuid4(),
            order_id=order_b.id,
            seq_in_order=0,
            state_id=state_a.id,
            base_duration_min=30,
            eligible_wc_ids=[wc_2.id],
        )
        op_b2 = Operation(
            id=uuid4(),
            order_id=order_b.id,
            seq_in_order=1,
            state_id=state_b.id,
            base_duration_min=30,
            eligible_wc_ids=[wc_2.id],
            predecessor_op_id=op_b1.id,
        )

        problem = ScheduleProblem(
            states=[state_a, state_b],
            orders=[order_a, order_b],
            operations=[op_a1, op_a2, op_b1, op_b2],
            work_centers=[wc_1, wc_2],
            setup_matrix=[
                SetupEntry(
                    work_center_id=wc_1.id,
                    from_state_id=state_a.id,
                    to_state_id=state_b.id,
                    setup_minutes=10,
                ),
                SetupEntry(
                    work_center_id=wc_2.id,
                    from_state_id=state_a.id,
                    to_state_id=state_b.id,
                    setup_minutes=10,
                ),
            ],
            auxiliary_resources=[tool],
            aux_requirements=[
                OperationAuxRequirement(operation_id=op_a2.id, aux_resource_id=tool.id),
                OperationAuxRequirement(operation_id=op_b2.id, aux_resource_id=tool.id),
            ],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        result = GreedyDispatch().solve(problem)

        assert result.status == SolverStatus.FEASIBLE
        checker = FeasibilityChecker()
        violations = checker.check(problem, result.assignments)
        assert violations == [], f"Violations found: {violations}"

        follow_up_assignments = sorted(
            [
                assignment
                for assignment in result.assignments
                if assignment.operation_id in {op_a2.id, op_b2.id}
            ],
            key=lambda assignment: assignment.start_time,
        )
        assert len(follow_up_assignments) == 2
        assert follow_up_assignments[1].start_time >= follow_up_assignments[0].end_time + timedelta(
            minutes=10
        )

    def test_returns_error_when_precedence_graph_contains_cycle(self) -> None:
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=4)

        state = State(id=uuid4(), code="STATE-A")
        work_center = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
        order = Order(
            id=uuid4(),
            external_ref="ORD-CYCLE",
            due_date=horizon_start + timedelta(hours=2),
            priority=500,
        )

        operation_a_id = uuid4()
        operation_b_id = uuid4()
        operation_a = Operation(
            id=operation_a_id,
            order_id=order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=15,
            eligible_wc_ids=[work_center.id],
            predecessor_op_id=operation_b_id,
        )
        operation_b = Operation(
            id=operation_b_id,
            order_id=order.id,
            seq_in_order=1,
            state_id=state.id,
            base_duration_min=15,
            eligible_wc_ids=[work_center.id],
            predecessor_op_id=operation_a_id,
        )

        with pytest.raises(ValidationError) as exc_info:
            ScheduleProblem(
                states=[state],
                orders=[order],
                operations=[operation_a, operation_b],
                work_centers=[work_center],
                setup_matrix=[],
                planning_horizon_start=horizon_start,
                planning_horizon_end=horizon_end,
            )

        assert "first operation" in str(exc_info.value)


class TestBeamSearchDispatch:
    """Tests for BeamSearchDispatch — filtered beam search extension."""

    def test_produces_feasible_result(self, simple_problem: ScheduleProblem) -> None:
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch

        solver = BeamSearchDispatch(beam_width=3)
        result = solver.solve(simple_problem)

        assert result.status == SolverStatus.FEASIBLE
        assert result.solver_name == "beam_search"

    def test_all_operations_assigned(self, simple_problem: ScheduleProblem) -> None:
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch

        solver = BeamSearchDispatch(beam_width=3)
        result = solver.solve(simple_problem)

        assigned_ops = {a.operation_id for a in result.assignments}
        expected_ops = {op.id for op in simple_problem.operations}
        assert assigned_ops == expected_ops

    def test_passes_feasibility_checker(self, simple_problem: ScheduleProblem) -> None:
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch

        solver = BeamSearchDispatch(beam_width=3)
        result = solver.solve(simple_problem)

        checker = FeasibilityChecker()
        violations = checker.check(simple_problem, result.assignments)
        assert violations == [], f"Violations found: {violations}"

    def test_beam_width_in_metadata(self, simple_problem: ScheduleProblem) -> None:
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch

        solver = BeamSearchDispatch(beam_width=5)
        result = solver.solve(simple_problem)
        assert result.metadata["beam_width"] == 5

    def test_beam_width_1_equals_greedy(self, simple_problem: ScheduleProblem) -> None:
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch

        beam1 = BeamSearchDispatch(beam_width=1)
        result_beam = beam1.solve(simple_problem)

        greedy = GreedyDispatch()
        result_greedy = greedy.solve(simple_problem)

        # With width=1, beam search degenerates to greedy — makespan should be equal
        assert abs(result_beam.objective.makespan_minutes - result_greedy.objective.makespan_minutes) < 0.1

    def test_respects_precedence(self, simple_problem: ScheduleProblem) -> None:
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch

        solver = BeamSearchDispatch(beam_width=3)
        result = solver.solve(simple_problem)

        assignment_map = {a.operation_id: a for a in result.assignments}
        for op in simple_problem.operations:
            if op.predecessor_op_id and op.predecessor_op_id in assignment_map:
                pred = assignment_map[op.predecessor_op_id]
                cur = assignment_map[op.id]
                assert cur.start_time >= pred.end_time
