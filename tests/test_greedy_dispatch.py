"""Tests for GreedyDispatch solver."""

from syn_aps.model import ScheduleProblem, SolverStatus
from syn_aps.solvers.greedy_dispatch import GreedyDispatch
from syn_aps.solvers.feasibility_checker import FeasibilityChecker


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
                assert cur.start_time >= pred.end_time, (
                    f"Op {op.id} starts before predecessor ends"
                )

    def test_makespan_is_positive(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)

        assert result.objective.makespan_minutes > 0
