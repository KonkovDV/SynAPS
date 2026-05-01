"""Tests for FeasibilityChecker."""

from datetime import timedelta
from uuid import uuid4

from synaps.model import (
    Assignment,
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
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

    def test_detects_parallel_setup_violation_without_explicit_lane_ids(self) -> None:
        checker = FeasibilityChecker()
        horizon_end = HORIZON_START + timedelta(hours=2)

        state_a = State(id=uuid4(), code="STATE-A")
        state_b = State(id=uuid4(), code="STATE-B")
        work_center = WorkCenter(
            id=uuid4(),
            code="WC-PAR-SDST",
            capability_group="machining",
            max_parallel=2,
        )

        orders = [
            Order(id=uuid4(), external_ref=f"ORD-{index}", due_date=horizon_end)
            for index in range(3)
        ]
        operations = [
            Operation(
                id=uuid4(),
                order_id=orders[0].id,
                seq_in_order=0,
                state_id=state_a.id,
                base_duration_min=10,
                eligible_wc_ids=[work_center.id],
            ),
            Operation(
                id=uuid4(),
                order_id=orders[1].id,
                seq_in_order=0,
                state_id=state_b.id,
                base_duration_min=10,
                eligible_wc_ids=[work_center.id],
            ),
            Operation(
                id=uuid4(),
                order_id=orders[2].id,
                seq_in_order=0,
                state_id=state_b.id,
                base_duration_min=10,
                eligible_wc_ids=[work_center.id],
            ),
        ]

        problem = ScheduleProblem(
            states=[state_a, state_b],
            orders=orders,
            operations=operations,
            work_centers=[work_center],
            setup_matrix=[
                SetupEntry(
                    work_center_id=work_center.id,
                    from_state_id=state_a.id,
                    to_state_id=state_b.id,
                    setup_minutes=5,
                )
            ],
            planning_horizon_start=HORIZON_START,
            planning_horizon_end=horizon_end,
        )

        assignments = [
            Assignment(
                operation_id=operations[0].id,
                work_center_id=work_center.id,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=10),
            ),
            Assignment(
                operation_id=operations[1].id,
                work_center_id=work_center.id,
                start_time=HORIZON_START + timedelta(minutes=10),
                end_time=HORIZON_START + timedelta(minutes=20),
            ),
            Assignment(
                operation_id=operations[2].id,
                work_center_id=work_center.id,
                start_time=HORIZON_START + timedelta(minutes=10),
                end_time=HORIZON_START + timedelta(minutes=20),
            ),
        ]

        violations = checker.check(problem, assignments)
        setup_violations = [v for v in violations if v.kind == "SETUP_GAP_VIOLATION"]
        assert len(setup_violations) == 1
        assert setup_violations[0].work_center_id == work_center.id

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

    def test_exhaustive_mode_reports_multiple_auxiliary_resource_overflows(self) -> None:
        checker = FeasibilityChecker()
        horizon_end = HORIZON_START + timedelta(hours=2)
        state = State(id=uuid4(), code="STATE-A")
        tool = AuxiliaryResource(id=uuid4(), code="TOOL-X", resource_type="tool", pool_size=1)
        work_centers = [
            WorkCenter(id=uuid4(), code=f"WC-{index}", capability_group="machining")
            for index in range(3)
        ]
        orders = [
            Order(id=uuid4(), external_ref=f"ORD-{index}", due_date=horizon_end)
            for index in range(3)
        ]
        operations = [
            Operation(
                id=uuid4(),
                order_id=orders[index].id,
                seq_in_order=0,
                state_id=state.id,
                base_duration_min=30,
                eligible_wc_ids=[work_centers[index].id],
            )
            for index in range(3)
        ]

        problem = ScheduleProblem(
            states=[state],
            orders=orders,
            operations=operations,
            work_centers=work_centers,
            setup_matrix=[],
            auxiliary_resources=[tool],
            aux_requirements=[
                OperationAuxRequirement(operation_id=operation.id, aux_resource_id=tool.id)
                for operation in operations
            ],
            planning_horizon_start=HORIZON_START,
            planning_horizon_end=horizon_end,
        )
        assignments = [
            Assignment(
                operation_id=operation.id,
                work_center_id=work_centers[index].id,
                start_time=HORIZON_START + timedelta(minutes=index),
                end_time=HORIZON_START + timedelta(minutes=30 + index),
            )
            for index, operation in enumerate(operations)
        ]

        default_violations = checker.check(problem, assignments)
        exhaustive_violations = checker.check(problem, assignments, exhaustive=True)

        default_resource_violations = [
            violation
            for violation in default_violations
            if violation.kind == "AUX_RESOURCE_CAPACITY_VIOLATION"
        ]
        exhaustive_resource_violations = [
            violation
            for violation in exhaustive_violations
            if violation.kind == "AUX_RESOURCE_CAPACITY_VIOLATION"
        ]

        assert len(default_resource_violations) == 1
        assert len(exhaustive_resource_violations) > len(default_resource_violations)
        assert len(exhaustive_resource_violations) >= 2

    def test_detects_auxiliary_resource_violation_during_setup_windows(self) -> None:
        checker = FeasibilityChecker()
        horizon_end = HORIZON_START + timedelta(hours=4)
        state_a = State(id=uuid4(), code="STATE-A")
        state_b = State(id=uuid4(), code="STATE-B")
        wc_1 = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
        wc_2 = WorkCenter(id=uuid4(), code="WC-2", capability_group="machining")
        tool = AuxiliaryResource(id=uuid4(), code="TOOL-SETUP", resource_type="crew", pool_size=1)
        order_a = Order(id=uuid4(), external_ref="ORD-A", due_date=horizon_end)
        order_b = Order(id=uuid4(), external_ref="ORD-B", due_date=horizon_end)

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
            planning_horizon_start=HORIZON_START,
            planning_horizon_end=horizon_end,
        )

        assignments = [
            Assignment(
                operation_id=op_a1.id,
                work_center_id=wc_1.id,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
            ),
            Assignment(
                operation_id=op_a2.id,
                work_center_id=wc_1.id,
                start_time=HORIZON_START + timedelta(minutes=40),
                end_time=HORIZON_START + timedelta(minutes=70),
            ),
            Assignment(
                operation_id=op_b1.id,
                work_center_id=wc_2.id,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=30),
            ),
            Assignment(
                operation_id=op_b2.id,
                work_center_id=wc_2.id,
                start_time=HORIZON_START + timedelta(minutes=60),
                end_time=HORIZON_START + timedelta(minutes=90),
            ),
        ]

        violations = checker.check(problem, assignments)
        resource_violations = [v for v in violations if v.kind == "AUX_RESOURCE_CAPACITY_VIOLATION"]
        assert len(resource_violations) == 1
        assert resource_violations[0].operation_id in {op_a2.id, op_b2.id}

    def test_detects_assignment_before_horizon_start(self, simple_problem: ScheduleProblem) -> None:
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

    def test_detects_assignment_after_horizon_end(self, simple_problem: ScheduleProblem) -> None:
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
