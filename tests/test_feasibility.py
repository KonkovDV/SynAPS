"""Tests for FeasibilityChecker."""

from datetime import timedelta
from uuid import uuid4

from synaps.model import (
    Assignment,
    AuxiliaryResource,
    OperationAuxRequirement,
    ScheduleProblem,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
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
        assert op.predecessor_op_id is not None
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

    def test_detects_missing_setup_gap_between_machine_operations(
        self, simple_problem: ScheduleProblem
    ) -> None:
        checker = FeasibilityChecker()
        op_a, op_b, op_c, op_d = simple_problem.operations
        wc_1 = simple_problem.work_centers[0].id
        wc_2 = simple_problem.work_centers[1].id

        assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc_1,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc_1,
                start_time=HORIZON_START + timedelta(minutes=30),
                end_time=HORIZON_START + timedelta(minutes=70),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc_2,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=wc_2,
                start_time=HORIZON_START + timedelta(minutes=38),
                end_time=HORIZON_START + timedelta(minutes=78),
            ),
        ]

        violations = checker.check(simple_problem, assignments)

        setup_violations = [v for v in violations if v.kind == "SETUP_GAP_VIOLATION"]
        assert len(setup_violations) == 1
        assert setup_violations[0].work_center_id == wc_1

    def test_detects_auxiliary_resource_pool_violation(
        self, simple_problem: ScheduleProblem
    ) -> None:
        checker = FeasibilityChecker()
        op_a, op_b, op_c, op_d = simple_problem.operations
        wc_1 = simple_problem.work_centers[0].id
        wc_2 = simple_problem.work_centers[1].id
        tool_id = uuid4()
        tool = AuxiliaryResource(
            id=tool_id,
            code="TOOL-1",
            resource_type="tool",
            pool_size=1,
        )
        problem = simple_problem.model_copy(
            update={
                "auxiliary_resources": [tool],
                "aux_requirements": [
                    OperationAuxRequirement(
                        operation_id=op_a.id, aux_resource_id=tool_id, quantity_needed=1
                    ),
                    OperationAuxRequirement(
                        operation_id=op_c.id, aux_resource_id=tool_id, quantity_needed=1
                    ),
                ],
            }
        )

        assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc_1,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc_1,
                start_time=HORIZON_START + timedelta(minutes=40),
                end_time=HORIZON_START + timedelta(minutes=80),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc_2,
                start_time=HORIZON_START + timedelta(minutes=5),
                end_time=HORIZON_START + timedelta(minutes=35),
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=wc_2,
                start_time=HORIZON_START + timedelta(minutes=43),
                end_time=HORIZON_START + timedelta(minutes=83),
            ),
        ]

        violations = checker.check(problem, assignments)

        resource_violations = [v for v in violations if v.kind == "AUX_RESOURCE_CAPACITY_VIOLATION"]
        assert len(resource_violations) == 1
        assert resource_violations[0].operation_id in {op_a.id, op_c.id}

    def test_detects_assignment_before_horizon_start(
        self, simple_problem: ScheduleProblem
    ) -> None:
        """Assignment starting before planning_horizon_start must be flagged (D4)."""
        checker = FeasibilityChecker()
        op_a, op_b, op_c, op_d = simple_problem.operations
        wc_1 = simple_problem.work_centers[0].id
        wc_2 = simple_problem.work_centers[1].id

        assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc_1,
                start_time=HORIZON_START - timedelta(minutes=10),
                end_time=HORIZON_START + timedelta(minutes=20),
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc_1,
                start_time=HORIZON_START + timedelta(minutes=30),
                end_time=HORIZON_START + timedelta(minutes=70),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc_2,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=wc_2,
                start_time=HORIZON_START + timedelta(minutes=38),
                end_time=HORIZON_START + timedelta(minutes=78),
            ),
        ]

        violations = checker.check(simple_problem, assignments)
        horizon_violations = [v for v in violations if v.kind == "HORIZON_BOUND_VIOLATION"]
        assert len(horizon_violations) >= 1
        assert horizon_violations[0].operation_id == op_a.id

    def test_detects_assignment_after_horizon_end(
        self, simple_problem: ScheduleProblem
    ) -> None:
        """Assignment ending after planning_horizon_end must be flagged (D4)."""
        from tests.conftest import HORIZON_END

        checker = FeasibilityChecker()
        op_a, op_b, op_c, op_d = simple_problem.operations
        wc_1 = simple_problem.work_centers[0].id
        wc_2 = simple_problem.work_centers[1].id

        assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc_1,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc_1,
                start_time=HORIZON_START + timedelta(minutes=40),
                end_time=HORIZON_START + timedelta(minutes=80),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc_2,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=wc_2,
                start_time=HORIZON_END - timedelta(minutes=5),
                end_time=HORIZON_END + timedelta(minutes=30),
            ),
        ]

        violations = checker.check(simple_problem, assignments)
        horizon_violations = [v for v in violations if v.kind == "HORIZON_BOUND_VIOLATION"]
        assert len(horizon_violations) >= 1
        assert horizon_violations[0].operation_id == op_d.id
