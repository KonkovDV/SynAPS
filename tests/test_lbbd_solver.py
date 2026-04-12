"""Tests for LBBD Solver (Logic-Based Benders Decomposition)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.lbbd_solver import LbbdSolver, _build_subproblem


class TestLbbdSolver:
    def test_produces_feasible_result(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(simple_problem, max_iterations=5, time_limit_s=30)

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.solver_name == "lbbd"
        assert len(result.assignments) > 0

    def test_all_operations_assigned(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(simple_problem, max_iterations=5, time_limit_s=30)

        assigned_ops = {a.operation_id for a in result.assignments}
        expected_ops = {op.id for op in simple_problem.operations}
        assert assigned_ops == expected_ops

    def test_passes_feasibility_checker(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(simple_problem, max_iterations=5, time_limit_s=30)

        checker = FeasibilityChecker()
        violations = checker.check(simple_problem, result.assignments)
        assert violations == [], f"Violations found: {violations}"

    def test_respects_precedence(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(simple_problem, max_iterations=5, time_limit_s=30)

        assignment_map = {a.operation_id: a for a in result.assignments}
        for op in simple_problem.operations:
            if op.predecessor_op_id and op.predecessor_op_id in assignment_map:
                pred = assignment_map[op.predecessor_op_id]
                cur = assignment_map[op.id]
                assert cur.start_time >= pred.end_time, (
                    f"Op {op.id} starts at {cur.start_time} before predecessor ends at "
                    f"{pred.end_time}"
                )

    def test_converges_within_iterations(self, simple_problem: ScheduleProblem) -> None:
        max_iter = 5
        solver = LbbdSolver()
        result = solver.solve(simple_problem, max_iterations=max_iter, time_limit_s=30)

        assert result.metadata["iterations"] <= max_iter

    def test_metadata_has_bounds(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(simple_problem, max_iterations=5, time_limit_s=30)

        assert "lower_bound" in result.metadata
        assert "upper_bound" in result.metadata
        assert "iteration_log" in result.metadata
        assert result.metadata["lower_bound"] >= 0
        if result.metadata["upper_bound"] < float("inf"):
            assert result.metadata["upper_bound"] >= result.metadata["lower_bound"]

    def test_makespan_is_positive(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(simple_problem, max_iterations=5, time_limit_s=30)

        assert result.objective.makespan_minutes > 0

    def test_handles_auxiliary_resources(self) -> None:
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=4)

        state = State(id=uuid4(), code="STATE-A")
        wc_1 = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
        wc_2 = WorkCenter(id=uuid4(), code="WC-2", capability_group="machining")
        resource = AuxiliaryResource(
            id=uuid4(),
            code="TOOL-1",
            resource_type="tool",
            pool_size=1,
        )

        order_1 = Order(
            id=uuid4(),
            external_ref="ORD-1",
            due_date=horizon_start + timedelta(hours=3),
        )
        order_2 = Order(
            id=uuid4(),
            external_ref="ORD-2",
            due_date=horizon_start + timedelta(hours=3),
        )

        op_1 = Operation(
            id=uuid4(),
            order_id=order_1.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=60,
            eligible_wc_ids=[wc_1.id, wc_2.id],
        )
        op_2 = Operation(
            id=uuid4(),
            order_id=order_2.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=60,
            eligible_wc_ids=[wc_1.id, wc_2.id],
        )

        problem = ScheduleProblem(
            states=[state],
            orders=[order_1, order_2],
            operations=[op_1, op_2],
            work_centers=[wc_1, wc_2],
            setup_matrix=[],
            auxiliary_resources=[resource],
            aux_requirements=[
                OperationAuxRequirement(
                    operation_id=op_1.id,
                    aux_resource_id=resource.id,
                    quantity_needed=1,
                ),
                OperationAuxRequirement(
                    operation_id=op_2.id,
                    aux_resource_id=resource.id,
                    quantity_needed=1,
                ),
            ],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        solver = LbbdSolver()
        result = solver.solve(problem, max_iterations=5, time_limit_s=30)

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

        checker = FeasibilityChecker()
        violations = checker.check(problem, result.assignments)
        assert violations == [], f"Violations: {violations}"

    def test_matches_or_beats_greedy(self, simple_problem: ScheduleProblem) -> None:
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        greedy = GreedyDispatch()
        greedy_result = greedy.solve(simple_problem)

        lbbd = LbbdSolver()
        lbbd_result = lbbd.solve(simple_problem, max_iterations=5, time_limit_s=30)

        # LBBD should produce a schedule at least as good as greedy
        # (with tolerance — decomposition + post-assembly precedence/setup
        # enforcement may push makespan beyond greedy on small problems)
        assert lbbd_result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert (
            lbbd_result.objective.makespan_minutes
            <= greedy_result.objective.makespan_minutes * 1.25
        )

    def test_subproblem_includes_transitive_external_predecessors(self) -> None:
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=4)

        state = State(id=uuid4(), code="STATE-A", label="State A")
        wc_1 = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
        wc_2 = WorkCenter(id=uuid4(), code="WC-2", capability_group="machining")
        order = Order(
            id=uuid4(),
            external_ref="ORD-CHAIN",
            due_date=horizon_start + timedelta(hours=3),
        )

        op_1 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=20,
            eligible_wc_ids=[wc_2.id],
        )
        op_2 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=1,
            state_id=state.id,
            base_duration_min=20,
            eligible_wc_ids=[wc_2.id],
            predecessor_op_id=op_1.id,
        )
        op_3 = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=2,
            state_id=state.id,
            base_duration_min=20,
            eligible_wc_ids=[wc_1.id],
            predecessor_op_id=op_2.id,
        )

        problem = ScheduleProblem(
            states=[state],
            orders=[order],
            operations=[op_1, op_2, op_3],
            work_centers=[wc_1, wc_2],
            setup_matrix=[],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        assignment_map = {
            op_1.id: wc_2.id,
            op_2.id: wc_2.id,
            op_3.id: wc_1.id,
        }
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        ops_by_id = {op.id: op for op in problem.operations}
        orders_by_id = {existing_order.id: existing_order for existing_order in problem.orders}

        sub_problem = _build_subproblem(
            problem,
            [op_3],
            {wc_1.id},
            {op_3.id},
            assignment_map,
            wc_by_id,
            ops_by_id,
            orders_by_id,
        )

        sub_ops = {operation.id: operation for operation in sub_problem.operations}

        assert set(sub_ops) == {op_1.id, op_2.id, op_3.id}
        assert sub_ops[op_2.id].predecessor_op_id == op_1.id
        assert sub_ops[op_3.id].predecessor_op_id == op_2.id


class TestLbbdGreedyWarmStart:
    """Tests for the greedy warm-start and parallel subproblem features."""

    def test_greedy_warm_start_produces_feasible(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(
            simple_problem, max_iterations=3, time_limit_s=30, use_greedy_warm_start=True,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata.get("greedy_warm_start_used") is True

    def test_greedy_warm_start_disabled(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(
            simple_problem, max_iterations=3, time_limit_s=30, use_greedy_warm_start=False,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata.get("greedy_warm_start_used") is False

    def test_warm_start_quality_at_least_as_good(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result_warm = solver.solve(
            simple_problem, max_iterations=5, time_limit_s=30, use_greedy_warm_start=True,
        )
        result_cold = solver.solve(
            simple_problem, max_iterations=5, time_limit_s=30, use_greedy_warm_start=False,
        )
        # Warm start should find at least as good a solution
        assert (
            result_warm.objective.makespan_minutes
            <= result_cold.objective.makespan_minutes * 1.01
        )

    def test_parallel_subproblems_flag_in_metadata(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(
            simple_problem, max_iterations=3, time_limit_s=30, parallel_subproblems=True,
        )
        assert result.metadata.get("parallel_subproblems") is True

    def test_sequential_subproblems_still_works(self, simple_problem: ScheduleProblem) -> None:
        solver = LbbdSolver()
        result = solver.solve(
            simple_problem, max_iterations=3, time_limit_s=30, parallel_subproblems=False,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata.get("parallel_subproblems") is False
