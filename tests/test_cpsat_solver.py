"""Tests for CP-SAT SDST handling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityChecker


def _make_setup_forced_problem() -> ScheduleProblem:
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    wc_id = uuid4()
    work_center = WorkCenter(id=wc_id, code="WC-1", capability_group="machining", speed_factor=1.0)
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)

    order_a = Order(
        id=uuid4(), external_ref="ORD-A", due_date=horizon_start + timedelta(hours=6), priority=500
    )
    order_b = Order(
        id=uuid4(), external_ref="ORD-B", due_date=horizon_start + timedelta(hours=6), priority=500
    )
    operation_a = Operation(
        id=uuid4(),
        order_id=order_a.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=30,
        eligible_wc_ids=[wc_id],
    )
    operation_b = Operation(
        id=uuid4(),
        order_id=order_b.id,
        seq_in_order=0,
        state_id=state_b.id,
        base_duration_min=30,
        eligible_wc_ids=[wc_id],
    )

    return ScheduleProblem(
        states=[state_a, state_b],
        orders=[order_a, order_b],
        operations=[operation_a, operation_b],
        work_centers=[work_center],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc_id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=10,
            ),
            SetupEntry(
                work_center_id=wc_id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=15,
            ),
        ],
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


def test_cpsat_respects_sequence_dependent_setups() -> None:
    problem = _make_setup_forced_problem()
    solver = CpSatSolver()

    result = solver.solve(problem, time_limit_s=5, random_seed=7)

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert len(result.assignments) == 2
    assert result.objective.makespan_minutes == 70

    checker = FeasibilityChecker()
    violations = checker.check(problem, result.assignments)
    assert violations == []


def _make_adjacent_setup_chain_problem() -> ScheduleProblem:
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    state_c = State(id=uuid4(), code="STATE-C", label="State C")
    work_center = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)

    order = Order(
        id=uuid4(),
        external_ref="ORD-CHAIN",
        due_date=horizon_start + timedelta(hours=10),
        priority=500,
    )
    operation_a = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=30,
        eligible_wc_ids=[work_center.id],
    )
    operation_b = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=1,
        state_id=state_b.id,
        base_duration_min=30,
        eligible_wc_ids=[work_center.id],
        predecessor_op_id=operation_a.id,
    )
    operation_c = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=2,
        state_id=state_c.id,
        base_duration_min=30,
        eligible_wc_ids=[work_center.id],
        predecessor_op_id=operation_b.id,
    )

    return ScheduleProblem(
        states=[state_a, state_b, state_c],
        orders=[order],
        operations=[operation_a, operation_b, operation_c],
        work_centers=[work_center],
        setup_matrix=[
            SetupEntry(
                work_center_id=work_center.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=5,
            ),
            SetupEntry(
                work_center_id=work_center.id,
                from_state_id=state_b.id,
                to_state_id=state_c.id,
                setup_minutes=7,
            ),
            SetupEntry(
                work_center_id=work_center.id,
                from_state_id=state_a.id,
                to_state_id=state_c.id,
                setup_minutes=100,
            ),
        ],
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


def _make_aux_resource_problem() -> ScheduleProblem:
    state = State(id=uuid4(), code="STATE-A", label="State A")
    work_center_a = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
    work_center_b = WorkCenter(id=uuid4(), code="WC-2", capability_group="machining")
    resource = AuxiliaryResource(
        id=uuid4(),
        code="TOOL-1",
        resource_type="fixture",
        pool_size=1,
    )
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)

    order_a = Order(
        id=uuid4(),
        external_ref="ORD-A",
        due_date=horizon_start + timedelta(hours=8),
        priority=500,
    )
    order_b = Order(
        id=uuid4(),
        external_ref="ORD-B",
        due_date=horizon_start + timedelta(hours=8),
        priority=500,
    )
    operation_a = Operation(
        id=uuid4(),
        order_id=order_a.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=30,
        eligible_wc_ids=[work_center_a.id],
    )
    operation_b = Operation(
        id=uuid4(),
        order_id=order_b.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=30,
        eligible_wc_ids=[work_center_b.id],
    )

    return ScheduleProblem(
        states=[state],
        orders=[order_a, order_b],
        operations=[operation_a, operation_b],
        work_centers=[work_center_a, work_center_b],
        setup_matrix=[],
        auxiliary_resources=[resource],
        aux_requirements=[
            OperationAuxRequirement(operation_id=operation_a.id, aux_resource_id=resource.id),
            OperationAuxRequirement(operation_id=operation_b.id, aux_resource_id=resource.id),
        ],
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


def _make_material_tiebreak_problem() -> tuple[ScheduleProblem, Operation, Operation]:
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    work_center = WorkCenter(id=uuid4(), code="WC-1", capability_group="machining")
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)

    order_a = Order(
        id=uuid4(),
        external_ref="ORD-A",
        due_date=horizon_start + timedelta(hours=6),
        priority=500,
    )
    order_b = Order(
        id=uuid4(),
        external_ref="ORD-B",
        due_date=horizon_start + timedelta(hours=6),
        priority=500,
    )
    operation_a = Operation(
        id=uuid4(),
        order_id=order_a.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=30,
        eligible_wc_ids=[work_center.id],
    )
    operation_b = Operation(
        id=uuid4(),
        order_id=order_b.id,
        seq_in_order=0,
        state_id=state_b.id,
        base_duration_min=30,
        eligible_wc_ids=[work_center.id],
    )

    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order_a, order_b],
        operations=[operation_a, operation_b],
        work_centers=[work_center],
        setup_matrix=[
            SetupEntry(
                work_center_id=work_center.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=10,
                material_loss=0.5,
            ),
            SetupEntry(
                work_center_id=work_center.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=10,
                material_loss=5.0,
            ),
        ],
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )
    return problem, operation_a, operation_b


def test_cpsat_counts_only_adjacent_setup_transitions() -> None:
    problem = _make_adjacent_setup_chain_problem()
    solver = CpSatSolver()

    result = solver.solve(problem, time_limit_s=10, random_seed=11)

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.objective.makespan_minutes == 102
    assert result.objective.total_setup_minutes == 12

    checker = FeasibilityChecker()
    violations = checker.check(problem, result.assignments)
    assert violations == []


def test_cpsat_respects_auxiliary_resource_capacity() -> None:
    problem = _make_aux_resource_problem()
    solver = CpSatSolver()

    result = solver.solve(problem, time_limit_s=10, random_seed=5)

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.objective.makespan_minutes == 60

    checker = FeasibilityChecker()
    violations = checker.check(problem, result.assignments)
    assert violations == []


def test_cpsat_breaks_makespan_tie_by_material_loss() -> None:
    problem, operation_a, operation_b = _make_material_tiebreak_problem()
    solver = CpSatSolver()

    result = solver.solve(problem, time_limit_s=10, random_seed=9)

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    ordered_assignments = sorted(result.assignments, key=lambda assignment: assignment.start_time)
    assert [assignment.operation_id for assignment in ordered_assignments] == [
        operation_a.id,
        operation_b.id,
    ]
    assert result.objective.makespan_minutes == 70
    assert result.objective.total_material_loss == 0.5


def _make_setup_tradeoff_problem() -> ScheduleProblem:
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    fast_wc = WorkCenter(
        id=uuid4(),
        code="WC-FAST",
        capability_group="machining",
        speed_factor=1.0,
    )
    slow_wc = WorkCenter(
        id=uuid4(),
        code="WC-SLOW",
        capability_group="machining",
        speed_factor=0.5,
    )
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = datetime(2026, 4, 1, 18, 0, tzinfo=UTC)

    order = Order(
        id=uuid4(),
        external_ref="ORD-TRADEOFF",
        due_date=horizon_start + timedelta(hours=8),
        priority=500,
    )

    operation_1 = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=20,
        eligible_wc_ids=[fast_wc.id, slow_wc.id],
    )
    operation_2 = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=1,
        state_id=state_b.id,
        base_duration_min=20,
        eligible_wc_ids=[fast_wc.id, slow_wc.id],
        predecessor_op_id=operation_1.id,
    )
    operation_3 = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=2,
        state_id=state_a.id,
        base_duration_min=20,
        eligible_wc_ids=[fast_wc.id, slow_wc.id],
        predecessor_op_id=operation_2.id,
    )
    operation_4 = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=3,
        state_id=state_b.id,
        base_duration_min=20,
        eligible_wc_ids=[fast_wc.id, slow_wc.id],
        predecessor_op_id=operation_3.id,
    )

    return ScheduleProblem(
        states=[state_a, state_b],
        orders=[order],
        operations=[operation_1, operation_2, operation_3, operation_4],
        work_centers=[fast_wc, slow_wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=fast_wc.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=10,
            ),
            SetupEntry(
                work_center_id=fast_wc.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=10,
            ),
            SetupEntry(
                work_center_id=slow_wc.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=10,
            ),
            SetupEntry(
                work_center_id=slow_wc.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=10,
            ),
        ],
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


def test_cpsat_can_minimise_setup_under_makespan_epsilon() -> None:
    problem = _make_setup_tradeoff_problem()
    solver = CpSatSolver()

    baseline = solver.solve(problem, time_limit_s=10, random_seed=17)
    epsilon_result = solver.solve(
        problem,
        time_limit_s=10,
        random_seed=17,
        objective_mode="epsilon_primary",
        primary_objective="setup",
        epsilon_constraints={"max_makespan_minutes": 121},
    )

    assert baseline.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert baseline.objective.makespan_minutes == 110
    assert baseline.objective.total_setup_minutes == 10

    assert epsilon_result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert epsilon_result.objective.makespan_minutes == 120
    assert epsilon_result.objective.total_setup_minutes == 0

    checker = FeasibilityChecker()
    assert checker.check(problem, epsilon_result.assignments) == []


def test_cpsat_virtualizes_parallel_work_centers_for_material_only_transitions() -> None:
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    work_center = WorkCenter(
        id=uuid4(),
        code="WC-PAR",
        capability_group="machining",
        max_parallel=2,
    )
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = datetime(2026, 4, 1, 18, 0, tzinfo=UTC)

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
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        ),
        Operation(
            id=uuid4(),
            order_id=orders[1].id,
            seq_in_order=0,
            state_id=state_b.id,
            base_duration_min=30,
            eligible_wc_ids=[work_center.id],
        ),
        Operation(
            id=uuid4(),
            order_id=orders[2].id,
            seq_in_order=0,
            state_id=state_a.id,
            base_duration_min=30,
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
                setup_minutes=0,
                material_loss=3.0,
            ),
            SetupEntry(
                work_center_id=work_center.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=0,
                material_loss=4.0,
            ),
        ],
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )

    result = CpSatSolver().solve(problem, time_limit_s=10, random_seed=13)

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.metadata["parallel_virtualization"]["enabled"] is True
    assert result.metadata["parallel_virtualization"]["original_parallel_work_centers"] == 1
    assert result.metadata["parallel_virtualization"]["virtual_lane_count"] == 2

    checker = FeasibilityChecker()
    assert checker.check(problem, result.assignments) == []
