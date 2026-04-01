"""Tests for FeasibilityChecker."""

from datetime import timedelta

from syn_aps.model import Assignment, ScheduleProblem
from syn_aps.solvers.feasibility_checker import FeasibilityChecker
from syn_aps.solvers.greedy_dispatch import GreedyDispatch
from tests.conftest import HORIZON_START


class TestFeasibilityChecker:
    def test_valid_schedule_has_no_violations(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)
        checker = FeasibilityChecker()

        violations = checker.check(simple_problem, result.assignments)
        assert violations == []

    def test_detects_missing_assignment(self, simple_problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)
        checker = FeasibilityChecker()

        # Remove one assignment
        partial = result.assignments[:-1]
        violations = checker.check(simple_problem, partial)

        missing = [v for v in violations if v.kind == "MISSING_ASSIGNMENT"]
        assert len(missing) == 1

    def test_detects_machine_overlap(self, simple_problem: ScheduleProblem) -> None:
        checker = FeasibilityChecker()
        op_ids = [op.id for op in simple_problem.operations]
        wc_id = simple_problem.work_centers[0].id

        # Create overlapping assignments on same machine
        assignments = [
            Assignment(
                operation_id=op_ids[i],
                work_center_id=wc_id,
                start_time=HORIZON_START + timedelta(minutes=i * 10),
                end_time=HORIZON_START + timedelta(minutes=i * 10 + 30),
            )
            for i in range(len(op_ids))
        ]

        violations = checker.check(simple_problem, assignments)
        overlaps = [v for v in violations if v.kind == "MACHINE_OVERLAP"]
        assert len(overlaps) > 0

    def test_detects_precedence_violation(self, simple_problem: ScheduleProblem) -> None:
        checker = FeasibilityChecker()
        ops_with_pred = [op for op in simple_problem.operations if op.predecessor_op_id is not None]
        if not ops_with_pred:
            return  # skip if no precedence in fixture

        # Build valid schedule then swap times for a predecessor pair
        solver = GreedyDispatch()
        result = solver.solve(simple_problem)
        assignments = list(result.assignments)
        amap = {a.operation_id: a for a in assignments}

        op = ops_with_pred[0]
        pred_a = amap[op.predecessor_op_id]
        cur_a = amap[op.id]

        # Swap: successor starts before predecessor
        idx_pred = assignments.index(pred_a)
        idx_cur = assignments.index(cur_a)
        assignments[idx_pred] = Assignment(
            operation_id=pred_a.operation_id,
            work_center_id=pred_a.work_center_id,
            start_time=cur_a.end_time,
            end_time=cur_a.end_time + timedelta(minutes=30),
        )
        assignments[idx_cur] = Assignment(
            operation_id=cur_a.operation_id,
            work_center_id=cur_a.work_center_id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=10),
        )

        violations = checker.check(simple_problem, assignments)
        prec_violations = [v for v in violations if v.kind == "PRECEDENCE_VIOLATION"]
        assert len(prec_violations) > 0
