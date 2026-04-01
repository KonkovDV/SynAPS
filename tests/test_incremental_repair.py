"""Tests for IncrementalRepair solver."""

from syn_aps.model import ScheduleProblem, SolverStatus
from syn_aps.solvers.greedy_dispatch import GreedyDispatch
from syn_aps.solvers.incremental_repair import IncrementalRepair
from syn_aps.solvers.feasibility_checker import FeasibilityChecker


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
