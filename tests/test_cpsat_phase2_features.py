"""Regression tests for Phase 2 CP-SAT upgrades.

Covers:
    - explicit warm-start hints
    - symmetry-breaking toggle on identical machines
    - max_parallel via cumulative constraints when no SDST exists
    - exact virtual-lane handling when max_parallel and SDST coexist
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)


def _make_parallel_no_setup_problem(
    max_parallel: int = 3, operation_count: int = 6
) -> ScheduleProblem:
    state = State(id=uuid4(), code="STATE-A", label="State A")
    work_center = WorkCenter(
        id=uuid4(),
        code="WC-PAR",
        capability_group="machining",
        speed_factor=1.0,
        max_parallel=max_parallel,
    )

    orders: list[Order] = []
    operations: list[Operation] = []
    for index in range(operation_count):
        order = Order(
            id=uuid4(),
            external_ref=f"ORD-{index}",
            due_date=HORIZON_START + timedelta(hours=6),
        )
        orders.append(order)
        operations.append(
            Operation(
                id=uuid4(),
                order_id=order.id,
                seq_in_order=0,
                state_id=state.id,
                base_duration_min=20,
                eligible_wc_ids=[work_center.id],
            )
        )

    return ScheduleProblem(
        states=[state],
        orders=orders,
        operations=operations,
        work_centers=[work_center],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


def _make_parallel_setup_problem(max_parallel: int = 2) -> tuple[ScheduleProblem, WorkCenter]:
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    work_center = WorkCenter(
        id=uuid4(),
        code="WC-SDST-PAR",
        capability_group="machining",
        speed_factor=1.0,
        max_parallel=max_parallel,
    )

    orders: list[Order] = []
    operations: list[Operation] = []
    for index in range(4):
        order = Order(
            id=uuid4(),
            external_ref=f"ORD-SDST-{index}",
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

    return (
        ScheduleProblem(
            states=[state_a, state_b],
            orders=orders,
            operations=operations,
            work_centers=[work_center],
            setup_matrix=setup_matrix,
            planning_horizon_start=HORIZON_START,
            planning_horizon_end=HORIZON_END,
        ),
        work_center,
    )


def _make_identical_machine_problem() -> ScheduleProblem:
    state = State(id=uuid4(), code="STATE-A", label="State A")
    work_center_a = WorkCenter(
        id=uuid4(),
        code="WC-1",
        capability_group="machining",
        speed_factor=1.0,
    )
    work_center_b = WorkCenter(
        id=uuid4(),
        code="WC-2",
        capability_group="machining",
        speed_factor=1.0,
    )

    orders: list[Order] = []
    operations: list[Operation] = []
    for index in range(4):
        order = Order(
            id=uuid4(),
            external_ref=f"ORD-ID-{index}",
            due_date=HORIZON_START + timedelta(hours=6),
        )
        orders.append(order)
        operations.append(
            Operation(
                id=uuid4(),
                order_id=order.id,
                seq_in_order=0,
                state_id=state.id,
                base_duration_min=20,
                eligible_wc_ids=[work_center_a.id, work_center_b.id],
            )
        )

    return ScheduleProblem(
        states=[state],
        orders=orders,
        operations=operations,
        work_centers=[work_center_a, work_center_b],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


def test_parallel_machine_allows_concurrency_without_sdst() -> None:
    problem = _make_parallel_no_setup_problem(max_parallel=3, operation_count=6)

    result = CpSatSolver().solve(problem, time_limit_s=10, random_seed=42)

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.objective.makespan_minutes == 40

    violations = FeasibilityChecker().check(problem, result.assignments)
    assert violations == []


def test_parallel_machine_with_sdst_uses_virtualization_and_maps_back() -> None:
    problem, original_work_center = _make_parallel_setup_problem(max_parallel=2)

    result = CpSatSolver().solve(problem, time_limit_s=10, random_seed=42)

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.metadata["parallel_virtualization"]["enabled"] is True
    assert result.metadata["parallel_virtualization"]["virtual_lane_count"] == 2
    assert {assignment.work_center_id for assignment in result.assignments} == {
        original_work_center.id
    }
    assert all(assignment.lane_id is not None for assignment in result.assignments)

    violations = FeasibilityChecker().check(problem, result.assignments)
    assert violations == []


def test_explicit_warm_start_assignments_reported_in_metadata(
    simple_problem: ScheduleProblem,
) -> None:
    warm_start = GreedyDispatch().solve(simple_problem).assignments

    result = CpSatSolver().solve(
        simple_problem,
        time_limit_s=10,
        random_seed=42,
        warm_start_assignments=warm_start,
    )

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.metadata["warm_started"] is True
    assert result.metadata["hint_count"] > 0


def test_symmetry_breaking_toggle_preserves_feasible_solution() -> None:
    problem = _make_identical_machine_problem()
    solver = CpSatSolver()

    with_symmetry = solver.solve(
        problem, time_limit_s=10, random_seed=42, enable_symmetry_breaking=True
    )
    without_symmetry = solver.solve(
        problem, time_limit_s=10, random_seed=42, enable_symmetry_breaking=False
    )

    assert with_symmetry.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert without_symmetry.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert (
        with_symmetry.objective.makespan_minutes
        == without_symmetry.objective.makespan_minutes
        == 40
    )
    assert with_symmetry.metadata["symmetry_breaking"] is True
    assert without_symmetry.metadata["symmetry_breaking"] is False
