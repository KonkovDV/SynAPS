"""Tests for RHC global greedy coverage placement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers._dispatch_support import MachineIndex, build_dispatch_context
from synaps.solvers.rhc import RhcPolicy, RhcSolver
from synaps.solvers.rhc._cover import (
    place_operations_greedy,
    place_operations_list_schedule,
    should_use_global_greedy_cover,
)

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)


def _two_op_problem(*, duration: int, horizon_minutes: int) -> ScheduleProblem:
    state = State(id=uuid4(), code="S0", label="S0")
    wc = WorkCenter(id=uuid4(), code="M1", capability_group="g", speed_factor=1.0)
    order = Order(
        id=uuid4(),
        external_ref="O1",
        due_date=HORIZON_START + timedelta(days=30),
        priority=1,
    )
    first_id = uuid4()
    second_id = uuid4()
    operations = [
        Operation(
            id=first_id,
            order_id=order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=duration,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=None,
        ),
        Operation(
            id=second_id,
            order_id=order.id,
            seq_in_order=1,
            state_id=state.id,
            base_duration_min=duration,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=first_id,
        ),
    ]
    return ScheduleProblem(
        states=[state],
        orders=[order],
        operations=operations,
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(minutes=horizon_minutes),
    )


def test_should_use_global_greedy_cover_only_for_large_greedy() -> None:
    assert should_use_global_greedy_cover(
        inner_solver_name="greedy", n_ops=10_000, min_ops=10_000
    )
    assert not should_use_global_greedy_cover(
        inner_solver_name="greedy", n_ops=9_999, min_ops=10_000
    )
    assert not should_use_global_greedy_cover(
        inner_solver_name="alns", n_ops=50_000, min_ops=10_000
    )


def test_place_operations_greedy_clips_past_horizon() -> None:
    problem = _two_op_problem(duration=30, horizon_minutes=40)
    context = build_dispatch_context(problem)
    assignments: list[Assignment] = []
    by_op: dict = {}
    scheduled: set = set()
    stats = place_operations_greedy(
        operations=problem.operations,
        dispatch_context=context,
        assignments=assignments,
        assignment_by_op=by_op,
        scheduled_ids=scheduled,
        machine_index=MachineIndex(context),
        horizon_start=problem.planning_horizon_start,
        horizon_minutes=40.0,
        op_earliest={op.id: 0.0 for op in problem.operations},
        default_wc_ids=[problem.work_centers[0].id],
    )
    assert stats.placed == 1
    assert stats.clipped >= 1
    assert len(assignments) == 1
    assert assignments[0].operation_id == problem.operations[0].id


def test_place_operations_list_schedule_sequences_predecessor() -> None:
    problem = _two_op_problem(duration=30, horizon_minutes=90)
    context = build_dispatch_context(problem)
    assignments: list[Assignment] = []
    by_op: dict = {}
    scheduled: set = set()
    stats = place_operations_list_schedule(
        operations=problem.operations,
        dispatch_context=context,
        assignments=assignments,
        assignment_by_op=by_op,
        scheduled_ids=scheduled,
        horizon_start=problem.planning_horizon_start,
        horizon_minutes=90.0,
        op_earliest={op.id: 0.0 for op in problem.operations},
        default_wc_ids=[problem.work_centers[0].id],
    )
    assert stats.placed == 2
    assert stats.clipped == 0
    first, second = assignments
    assert first.end_time <= second.start_time
    assert second.end_time <= problem.planning_horizon_end


def test_list_schedule_runs_early_successor_before_late_release() -> None:
    """Ready-queue dispatch must not park a late first-op ahead of an early chain."""

    state = State(id=uuid4(), code="S0", label="S0")
    wc = WorkCenter(id=uuid4(), code="M1", capability_group="g", speed_factor=1.0)
    early_order = Order(
        id=uuid4(),
        external_ref="EARLY",
        due_date=HORIZON_START + timedelta(days=30),
        priority=1,
        domain_attributes={"release_offset_min": 0.0},
    )
    late_order = Order(
        id=uuid4(),
        external_ref="LATE",
        due_date=HORIZON_START + timedelta(days=30),
        priority=1,
        domain_attributes={"release_offset_min": 100.0},
    )
    early0 = uuid4()
    early1 = uuid4()
    late0 = uuid4()
    operations = [
        Operation(
            id=early0,
            order_id=early_order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        ),
        Operation(
            id=early1,
            order_id=early_order.id,
            seq_in_order=1,
            state_id=state.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=early0,
        ),
        Operation(
            id=late0,
            order_id=late_order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        ),
    ]
    problem = ScheduleProblem(
        states=[state],
        orders=[early_order, late_order],
        operations=operations,
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(minutes=200),
    )
    context = build_dispatch_context(problem)
    assignments: list[Assignment] = []
    by_op: dict = {}
    scheduled: set = set()
    place_operations_list_schedule(
        operations=problem.operations,
        dispatch_context=context,
        assignments=assignments,
        assignment_by_op=by_op,
        scheduled_ids=scheduled,
        horizon_start=HORIZON_START,
        horizon_minutes=200.0,
        op_earliest={early0: 0.0, early1: 0.0, late0: 100.0},
        default_wc_ids=[wc.id],
    )
    assert by_op[early1].end_time <= HORIZON_START + timedelta(minutes=20)
    assert by_op[late0].start_time >= HORIZON_START + timedelta(minutes=20)


def test_global_greedy_cover_claims_feasible_inside_declared_horizon() -> None:
    problem = _two_op_problem(duration=30, horizon_minutes=90)
    extra_ops = []
    prev = problem.operations[-1].id
    for seq in range(2, 12):
        op_id = uuid4()
        extra_ops.append(
            Operation(
                id=op_id,
                order_id=problem.orders[0].id,
                seq_in_order=seq,
                state_id=problem.states[0].id,
                base_duration_min=30,
                eligible_wc_ids=[problem.work_centers[0].id],
                predecessor_op_id=prev,
            )
        )
        prev = op_id
    operations = list(problem.operations) + extra_ops
    problem = problem.model_copy(
        update={
            "operations": operations,
            "planning_horizon_end": HORIZON_START + timedelta(days=30),
        }
    )
    result = RhcSolver(policy=RhcPolicy.GREEDY_COVER).solve(
        problem,
        time_limit_s=30,
        global_greedy_cover_min_ops=0,
        coverage_horizon_extension_factor=1.0,
    )
    assert result.metadata["global_greedy_cover"] is True
    assert result.metadata["windows_solved"] == 0
    assert len(result.assignments) == len(problem.operations)
    assert result.status == SolverStatus.FEASIBLE
    assert result.metadata.get("notary_hard_violation_kinds") == []
    assert result.metadata.get("temporal_stabilization_converged") is True
    for assignment in result.assignments:
        assert assignment.end_time <= problem.planning_horizon_end
