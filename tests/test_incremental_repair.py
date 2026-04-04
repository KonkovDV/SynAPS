"""Tests for IncrementalRepair solver."""

from datetime import timedelta

from synaps.model import Assignment, ScheduleProblem, SolverStatus
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.incremental_repair import IncrementalRepair
from tests.conftest import HORIZON_START


class TestIncrementalRepair:
    def test_repair_maintains_feasibility(self, simple_problem: ScheduleProblem) -> None:
        # Build a base schedule
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        # Disrupt one operation
        disrupted_id = simple_problem.operations[0].id

        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[disrupted_id],
            radius=3,
        )

        assert result.status == SolverStatus.FEASIBLE
        checker = FeasibilityChecker()
        violations = checker.check(simple_problem, result.assignments)
        assert violations == [], f"Violations after repair: {violations}"

    def test_repair_returns_all_operations(self, simple_problem: ScheduleProblem) -> None:
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        disrupted_id = simple_problem.operations[0].id
        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[disrupted_id],
        )

        assigned_ops = {a.operation_id for a in result.assignments}
        expected_ops = {op.id for op in simple_problem.operations}
        assert assigned_ops == expected_ops

    def test_repair_runs_fast(self, simple_problem: ScheduleProblem) -> None:
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[simple_problem.operations[0].id],
        )

        assert result.duration_ms < 2000, f"Repair took {result.duration_ms}ms, budget is 2000ms"

    def test_error_without_base_assignments(self, simple_problem: ScheduleProblem) -> None:
        repair = IncrementalRepair()
        result = repair.solve(simple_problem)

        assert result.status == SolverStatus.ERROR

    def test_metadata_includes_counts(self, simple_problem: ScheduleProblem) -> None:
        greedy = GreedyDispatch()
        base_result = greedy.solve(simple_problem)

        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_result.assignments,
            disrupted_op_ids=[simple_problem.operations[0].id],
            radius=2,
        )

        assert "neighbourhood_size" in result.metadata
        assert "frozen_count" in result.metadata
        assert "repaired_count" in result.metadata

    def test_repair_respects_setup_from_last_frozen_state(
        self, simple_problem: ScheduleProblem
    ) -> None:
        op_a, op_b, op_c, op_d = simple_problem.operations
        wc_1 = simple_problem.work_centers[0].id
        wc_2 = simple_problem.work_centers[1].id
        base_assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc_1,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
                setup_minutes=0,
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc_1,
                start_time=HORIZON_START + timedelta(minutes=40),
                end_time=HORIZON_START + timedelta(minutes=80),
                setup_minutes=10,
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc_2,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
                setup_minutes=0,
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=wc_2,
                start_time=HORIZON_START + timedelta(minutes=38),
                end_time=HORIZON_START + timedelta(minutes=78),
                setup_minutes=8,
            ),
        ]

        repair = IncrementalRepair()
        result = repair.solve(
            simple_problem,
            base_assignments=base_assignments,
            disrupted_op_ids=[op_b.id],
            radius=0,
        )

        assert result.status == SolverStatus.FEASIBLE
        repaired_assignment = next(a for a in result.assignments if a.operation_id == op_b.id)
        assert repaired_assignment.start_time == HORIZON_START + timedelta(minutes=40)
        assert repaired_assignment.setup_minutes == 10

        checker = FeasibilityChecker()
        violations = checker.check(simple_problem, result.assignments)
        assert violations == [], f"Violations after repair: {violations}"

    def test_repair_inserts_into_gap_before_later_frozen_assignment(
        self, simple_problem: ScheduleProblem
    ) -> None:
        problem_data = simple_problem.model_dump()
        work_center_1 = simple_problem.work_centers[0].id
        problem_data["operations"][1]["eligible_wc_ids"] = [work_center_1]
        problem = ScheduleProblem.model_validate(problem_data)

        op_a, op_b, op_c, op_d = problem.operations
        work_center_2 = problem.work_centers[1].id
        base_assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=work_center_1,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
                setup_minutes=0,
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=work_center_2,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
                setup_minutes=0,
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=work_center_1,
                start_time=HORIZON_START + timedelta(minutes=80),
                end_time=HORIZON_START + timedelta(minutes=120),
                setup_minutes=0,
            ),
        ]

        repair = IncrementalRepair()
        result = repair.solve(
            problem,
            base_assignments=base_assignments,
            disrupted_op_ids=[op_b.id],
            radius=0,
        )

        assert result.status == SolverStatus.FEASIBLE
        repaired_assignment = next(a for a in result.assignments if a.operation_id == op_b.id)
        assert repaired_assignment.work_center_id == work_center_1
        assert repaired_assignment.start_time == HORIZON_START + timedelta(minutes=40)
        assert repaired_assignment.end_time == HORIZON_START + timedelta(minutes=80)

        checker = FeasibilityChecker()
        violations = checker.check(problem, result.assignments)
        assert violations == [], f"Violations after repair: {violations}"

    def test_repair_computes_nonzero_tardiness_for_tight_due_dates(self) -> None:
        """Repaired schedule where order finishes past its due date must
        report positive total_tardiness_minutes (D3 regression)."""
        from datetime import UTC, datetime
        from uuid import uuid4

        from synaps.model import Operation, Order, State, WorkCenter

        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=4)
        state = State(id=uuid4(), code="STATE-A", label="State A")
        wc = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")

        # Due date is 20 min from horizon start — but the single op is 60 min.
        order = Order(
            id=uuid4(),
            external_ref="ORD-TIGHT",
            due_date=horizon_start + timedelta(minutes=20),
        )
        op = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=60,
            eligible_wc_ids=[wc.id],
        )

        problem = ScheduleProblem(
            states=[state],
            orders=[order],
            operations=[op],
            work_centers=[wc],
            setup_matrix=[],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        base = [
            Assignment(
                operation_id=op.id,
                work_center_id=wc.id,
                start_time=horizon_start,
                end_time=horizon_start + timedelta(minutes=60),
            ),
        ]

        repair = IncrementalRepair()
        result = repair.solve(
            problem,
            base_assignments=base,
            disrupted_op_ids=[op.id],
            radius=0,
        )

        assert result.status == SolverStatus.FEASIBLE
        # Op finishes at +60 min; due at +20 min → tardiness = 40 min
        assert result.objective.total_tardiness_minutes >= 40.0
