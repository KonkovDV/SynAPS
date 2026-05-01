"""Regression tests for Phase 2 LBBD upgrades."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    Assignment,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.lbbd_solver import LbbdSolver
from synaps.solvers.lbbd_solver import (
    _compute_machine_transition_floor as _compute_machine_transition_floor_plain,
)
from synaps.solvers.lbbd_solver import (
    _compute_sequence_independent_setup_lower_bound as _compute_setup_lb_plain,
)
from synaps.solvers.lbbd_hd_solver import (
    _compute_machine_transition_floor as _compute_machine_transition_floor_hd,
)
from synaps.solvers.lbbd_hd_solver import (
    _compute_sequence_independent_setup_lower_bound as _compute_setup_lb_hd,
)

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)


def _make_setup_dense_problem() -> ScheduleProblem:
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    work_center = WorkCenter(
        id=uuid4(),
        code="WC-SETUP",
        capability_group="machining",
        speed_factor=1.0,
    )

    orders: list[Order] = []
    operations: list[Operation] = []
    for index in range(4):
        order = Order(
            id=uuid4(),
            external_ref=f"ORD-{index}",
            due_date=HORIZON_START + timedelta(hours=8),
        )
        orders.append(order)
        operations.append(
            Operation(
                id=uuid4(),
                order_id=order.id,
                seq_in_order=0,
                state_id=state_a.id if index % 2 == 0 else state_b.id,
                base_duration_min=20,
                eligible_wc_ids=[work_center.id],
            )
        )

    setup_matrix = [
        SetupEntry(
            work_center_id=work_center.id,
            from_state_id=state_a.id,
            to_state_id=state_b.id,
            setup_minutes=5,
        ),
        SetupEntry(
            work_center_id=work_center.id,
            from_state_id=state_b.id,
            to_state_id=state_a.id,
            setup_minutes=5,
        ),
    ]

    return ScheduleProblem(
        states=[state_a, state_b],
        orders=orders,
        operations=operations,
        work_centers=[work_center],
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


def test_setup_cost_cuts_are_exposed_in_metadata() -> None:
    problem = _make_setup_dense_problem()

    result = LbbdSolver().solve(
        problem,
        max_iterations=4,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )

    assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    assert result.metadata["cut_pool"]["kinds"].get("setup_cost", 0) >= 1
    assert result.metadata["cut_pool"]["kinds"].get("critical_path", 0) >= 1


def test_lbbd_reports_master_warm_start_iterations() -> None:
    problem = _make_setup_dense_problem()

    result = LbbdSolver().solve(
        problem,
        max_iterations=4,
        time_limit_s=20,
        random_seed=42,
        setup_relaxation=False,
    )

    assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    assert result.metadata["master_warm_start_iterations"] >= 1


def test_gap_threshold_is_configurable(simple_problem: ScheduleProblem) -> None:
    solver = LbbdSolver()

    loose = solver.solve(
        simple_problem,
        max_iterations=6,
        time_limit_s=20,
        random_seed=42,
        gap_threshold=0.50,
    )
    tight = solver.solve(
        simple_problem,
        max_iterations=6,
        time_limit_s=20,
        random_seed=42,
        gap_threshold=0.01,
    )

    assert loose.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    assert tight.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.TIMEOUT}
    assert loose.metadata["gap_threshold"] == 0.50
    assert tight.metadata["gap_threshold"] == 0.01
    assert loose.metadata["iterations"] <= tight.metadata["iterations"]


def test_setup_relaxation_floor_drops_to_zero_when_zero_transition_exists() -> None:
    problem = _make_setup_dense_problem()
    work_center = problem.work_centers[0]
    eligible_by_op = {operation.id: list(operation.eligible_wc_ids) for operation in problem.operations}
    setup_lookup = {
        (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
        for entry in problem.setup_matrix
    }

    assert _compute_machine_transition_floor_plain(problem, eligible_by_op, work_center.id, setup_lookup) == 0.0
    assert _compute_machine_transition_floor_hd(problem, eligible_by_op, work_center.id, setup_lookup) == 0.0


def test_setup_cost_lower_bound_uses_state_mix_not_realized_sequence_cost() -> None:
    problem = _make_setup_dense_problem()
    work_center = problem.work_centers[0]
    assignments = [
        Assignment(
            operation_id=operation.id,
            work_center_id=work_center.id,
            start_time=HORIZON_START + timedelta(minutes=index * 25),
            end_time=HORIZON_START + timedelta(minutes=index * 25 + 20),
        )
        for index, operation in enumerate(problem.operations)
    ]
    ops_by_id = {operation.id: operation for operation in problem.operations}
    setup_lookup = {
        (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
        for entry in problem.setup_matrix
    }

    assert (
        _compute_setup_lb_plain(assignments, work_center.id, ops_by_id, setup_lookup) == 5.0
    )
    assert _compute_setup_lb_hd(assignments, work_center.id, ops_by_id, setup_lookup) == 5.0
