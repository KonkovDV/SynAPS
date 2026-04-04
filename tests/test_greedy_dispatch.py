"""Tests for GreedyDispatch solver."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    State,
    SolverStatus,
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
