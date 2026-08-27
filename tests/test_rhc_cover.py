"""Tests for RHC global greedy coverage placement."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    Assignment,
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
from synaps.solvers._dispatch_support import (
    APPEND_GAP_SCAN_MIN_OPS,
    MachineIndex,
    build_dispatch_context,
)
from synaps.solvers.rhc import RhcPolicy, RhcSolver
from synaps.solvers.rhc._cover import (
    _atcs_window_indices,
    _cover_gap_scan_for,
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
    assert should_use_global_greedy_cover(inner_solver_name="greedy", n_ops=10_000, min_ops=10_000)
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


def test_cover_gap_scan_appends_at_large_n_threshold() -> None:
    assert _cover_gap_scan_for(APPEND_GAP_SCAN_MIN_OPS - 1) == "all"
    assert _cover_gap_scan_for(APPEND_GAP_SCAN_MIN_OPS) == "append"


def test_residual_greedy_uses_append_scan_when_timeline_is_large(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fell before fix: leftover fill walked every gap on a 100k packed timeline."""

    import synaps.solvers.rhc._cover as cover

    seen: list[str] = []
    real_find = cover.find_earliest_feasible_slot

    def spy_find(*args: object, **kwargs: object) -> object:
        seen.append(str(kwargs.get("gap_scan")))
        return real_find(*args, **kwargs)

    monkeypatch.setattr(cover, "APPEND_GAP_SCAN_MIN_OPS", 1)
    monkeypatch.setattr(cover, "find_earliest_feasible_slot", spy_find)
    problem = _two_op_problem(duration=10, horizon_minutes=90)
    context = build_dispatch_context(problem)
    first = problem.operations[0]
    leftover = problem.operations[1]
    start = problem.planning_horizon_start
    packed = Assignment(
        operation_id=first.id,
        work_center_id=problem.work_centers[0].id,
        start_time=start,
        end_time=start + timedelta(minutes=10),
        setup_minutes=0,
    )
    assignments = [packed]
    by_op = {first.id: packed}
    scheduled = {first.id}
    machine_index = MachineIndex(context)
    machine_index.extend(assignments)
    place_operations_greedy(
        operations=[leftover],
        dispatch_context=context,
        assignments=assignments,
        assignment_by_op=by_op,
        scheduled_ids=scheduled,
        machine_index=machine_index,
        horizon_start=start,
        horizon_minutes=90.0,
        op_earliest={leftover.id: 0.0},
        default_wc_ids=[problem.work_centers[0].id],
    )
    assert "append" in seen


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


def test_list_schedule_respects_latest_finish() -> None:
    """G11: append-only cover must not park an op past Operation.latest_finish."""

    problem = _two_op_problem(duration=30, horizon_minutes=120)
    tight = problem.operations[1].model_copy(
        update={"latest_finish": HORIZON_START + timedelta(minutes=40)}
    )
    problem = problem.model_copy(update={"operations": [problem.operations[0], tight]})
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
        horizon_start=HORIZON_START,
        horizon_minutes=120.0,
        op_earliest={op.id: 0.0 for op in problem.operations},
        default_wc_ids=[problem.work_centers[0].id],
    )
    assert stats.placed == 1
    assert stats.clipped >= 1
    assert tight.id not in scheduled
    assert assignments[0].end_time <= HORIZON_START + timedelta(minutes=30)


def test_list_schedule_inserts_into_idle_gap_when_tail_blocked() -> None:
    """Insertion SGS: aux delay parks a tail and leaves a hole a later op must use."""

    state = State(id=uuid4(), code="S0", label="S0")
    m1 = WorkCenter(id=uuid4(), code="M1", capability_group="g", speed_factor=1.0)
    m2 = WorkCenter(id=uuid4(), code="M2", capability_group="g", speed_factor=1.0)
    aux = AuxiliaryResource(id=uuid4(), code="CRANE", resource_type="tool", pool_size=1)
    hold_order = Order(
        id=uuid4(),
        external_ref="HOLD",
        due_date=HORIZON_START + timedelta(days=1),
        priority=1,
    )
    park_order = Order(
        id=uuid4(),
        external_ref="PARK",
        due_date=HORIZON_START + timedelta(days=1),
        priority=1,
    )
    fit_order = Order(
        id=uuid4(),
        external_ref="FIT",
        due_date=HORIZON_START + timedelta(days=1),
        priority=1,
    )
    hold_id = uuid4()
    park_id = uuid4()
    fit_id = uuid4()
    operations = [
        Operation(
            id=hold_id,
            order_id=hold_order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=80,
            eligible_wc_ids=[m2.id],
        ),
        Operation(
            id=park_id,
            order_id=park_order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=10,
            eligible_wc_ids=[m1.id],
            earliest_start=HORIZON_START + timedelta(minutes=1),
        ),
        Operation(
            id=fit_id,
            order_id=fit_order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=20,
            eligible_wc_ids=[m1.id],
            earliest_start=HORIZON_START + timedelta(minutes=10),
            latest_finish=HORIZON_START + timedelta(minutes=40),
        ),
    ]
    problem = ScheduleProblem(
        states=[state],
        orders=[hold_order, park_order, fit_order],
        operations=operations,
        work_centers=[m1, m2],
        setup_matrix=[],
        auxiliary_resources=[aux],
        aux_requirements=[
            OperationAuxRequirement(
                operation_id=hold_id, aux_resource_id=aux.id, quantity_needed=1
            ),
            OperationAuxRequirement(
                operation_id=park_id, aux_resource_id=aux.id, quantity_needed=1
            ),
        ],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(minutes=200),
    )
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
        horizon_start=HORIZON_START,
        horizon_minutes=200.0,
        op_earliest={hold_id: 0.0, park_id: 1.0, fit_id: 10.0},
        default_wc_ids=[m1.id, m2.id],
    )
    assert stats.placed == 3
    assert stats.clipped == 0
    assert stats.gap_inserted >= 1
    assert by_op[fit_id].end_time <= HORIZON_START + timedelta(minutes=40)
    assert by_op[fit_id].start_time < by_op[park_id].start_time


def test_greedy_cover_does_not_claim_feasible_when_latest_finish_blocks() -> None:
    """Incomplete G11 cover must not stamp FEASIBLE."""

    problem = _two_op_problem(duration=30, horizon_minutes=120)
    tight = problem.operations[1].model_copy(
        update={"latest_finish": HORIZON_START + timedelta(minutes=40)}
    )
    problem = problem.model_copy(update={"operations": [problem.operations[0], tight]})
    result = RhcSolver(policy=RhcPolicy.GREEDY_COVER).solve(
        problem,
        time_limit_s=10,
        global_greedy_cover_min_ops=0,
        coverage_horizon_extension_factor=1.0,
    )
    assert result.status != SolverStatus.FEASIBLE
    assert len(result.assignments) < len(problem.operations)


def test_greedy_cover_generator_instance_claims_feasible() -> None:
    """Locks the cover path on a Brandimarte-style instance, not a toy chain."""

    from synaps.benchmarks.instance_generator import generate_large_instance

    problem = generate_large_instance(
        n_operations=400,
        n_machines=8,
        n_states=10,
        ops_per_order=5,
        machine_flexibility=0.25,
        setup_density=0.5,
        horizon_hours=720,
        seed=1,
    )
    result = RhcSolver(policy=RhcPolicy.GREEDY_COVER).solve(
        problem,
        time_limit_s=30,
        global_greedy_cover_min_ops=0,
        coverage_horizon_extension_factor=1.0,
    )
    assert result.status == SolverStatus.FEASIBLE
    assert len(result.assignments) == len(problem.operations)
    assert result.metadata.get("notary_hard_violation_kinds") == []
    assert result.metadata.get("global_greedy_cover") is True


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


def test_native_list_schedule_cover_solves_small_instance_when_forced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("synaps_native", reason="native module not built")
    from synaps.accelerators import _native_list_schedule_cover
    from synaps.solvers.rhc import _cover as cover_mod

    if _native_list_schedule_cover is None:
        pytest.skip("list_schedule_cover kernel is not in this wheel")
    monkeypatch.setattr(cover_mod, "_NATIVE_LIST_SCHEDULE_MIN_OPS", 0)
    problem = _two_op_problem(duration=30, horizon_minutes=90)
    result = RhcSolver(policy=RhcPolicy.GREEDY_COVER).solve(
        problem,
        time_limit_s=30,
        global_greedy_cover_min_ops=0,
        coverage_horizon_extension_factor=1.0,
    )
    assert len(result.assignments) == 2
    assert result.status == SolverStatus.FEASIBLE
    assert result.metadata.get("notary_hard_violation_kinds") == []


def test_cover_atcs_prefers_zero_setup_same_state() -> None:
    """ATCS among ready ops should continue the loaded SKU; FIFO uses seq."""

    state_a = State(id=uuid4(), code="A", label="A")
    state_b = State(id=uuid4(), code="B", label="B")
    wc = WorkCenter(id=uuid4(), code="M1", capability_group="g", speed_factor=1.0)
    order_seed = Order(
        id=uuid4(),
        external_ref="SEED",
        due_date=HORIZON_START + timedelta(days=1),
        priority=1,
    )
    order_other = Order(
        id=uuid4(),
        external_ref="OTHER",
        due_date=HORIZON_START + timedelta(days=1),
        priority=1,
    )
    order_same = Order(
        id=uuid4(),
        external_ref="SAME",
        due_date=HORIZON_START + timedelta(days=1),
        priority=1,
    )
    seeded = Operation(
        id=uuid4(),
        order_id=order_seed.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    other = Operation(
        id=uuid4(),
        order_id=order_other.id,
        seq_in_order=1,
        state_id=state_b.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    same = Operation(
        id=uuid4(),
        order_id=order_same.id,
        seq_in_order=2,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order_seed, order_other, order_same],
        operations=[seeded, other, same],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=100,
            ),
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=100,
            ),
        ],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(hours=8),
    )
    seeded_asg = Assignment(
        operation_id=seeded.id,
        work_center_id=wc.id,
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(minutes=10),
    )

    def _run(rule: str) -> dict:
        context = build_dispatch_context(problem)
        assignments = [seeded_asg.model_copy()]
        by_op = {seeded.id: assignments[0]}
        scheduled = {seeded.id}
        place_operations_list_schedule(
            operations=problem.operations,
            dispatch_context=context,
            assignments=assignments,
            assignment_by_op=by_op,
            scheduled_ids=scheduled,
            horizon_start=HORIZON_START,
            horizon_minutes=480.0,
            op_earliest={op.id: 0.0 for op in problem.operations},
            default_wc_ids=[wc.id],
            cover_ready_rule=rule,
        )
        return {row.operation_id: row for row in assignments}

    fifo = _run("fifo")
    atcs = _run("atcs")
    assert fifo[other.id].start_time <= fifo[same.id].start_time
    assert atcs[same.id].start_time <= atcs[other.id].start_time
    assert atcs[same.id].setup_minutes == 0


def test_cover_atcs_does_not_jump_future_floor() -> None:
    """Non-delay ATCS must not skip an earlier-ready op for a later zero-setup."""

    state_a = State(id=uuid4(), code="A", label="A")
    state_b = State(id=uuid4(), code="B", label="B")
    wc = WorkCenter(id=uuid4(), code="M1", capability_group="g", speed_factor=1.0)
    order_seed = Order(id=uuid4(), external_ref="SEED", due_date=HORIZON_START + timedelta(days=1))
    order_early = Order(
        id=uuid4(), external_ref="EARLY", due_date=HORIZON_START + timedelta(days=1)
    )
    order_late = Order(id=uuid4(), external_ref="LATE", due_date=HORIZON_START + timedelta(days=1))
    seeded = Operation(
        id=uuid4(),
        order_id=order_seed.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    early = Operation(
        id=uuid4(),
        order_id=order_early.id,
        seq_in_order=1,
        state_id=state_b.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    late = Operation(
        id=uuid4(),
        order_id=order_late.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order_seed, order_early, order_late],
        operations=[seeded, early, late],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=100,
            ),
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=100,
            ),
        ],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(hours=8),
    )
    seeded_asg = Assignment(
        operation_id=seeded.id,
        work_center_id=wc.id,
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(minutes=10),
    )
    context = build_dispatch_context(problem)
    assignments = [seeded_asg.model_copy()]
    by_op = {seeded.id: assignments[0]}
    place_operations_list_schedule(
        operations=problem.operations,
        dispatch_context=context,
        assignments=assignments,
        assignment_by_op=by_op,
        scheduled_ids={seeded.id},
        horizon_start=HORIZON_START,
        horizon_minutes=480.0,
        op_earliest={seeded.id: 0.0, early.id: 0.0, late.id: 200.0},
        default_wc_ids=[wc.id],
        cover_ready_rule="atcs",
    )
    by_id = {row.operation_id: row for row in assignments}
    assert by_id[early.id].start_time <= by_id[late.id].start_time


def test_cover_atcs_bounded_delay_waits_for_same_state() -> None:
    """A one-setup window may idle for a later zero-setup successor."""

    state_a = State(id=uuid4(), code="A", label="A")
    state_b = State(id=uuid4(), code="B", label="B")
    wc = WorkCenter(id=uuid4(), code="M1", capability_group="g", speed_factor=1.0)
    order_seed = Order(id=uuid4(), external_ref="SEED", due_date=HORIZON_START + timedelta(days=1))
    order_early = Order(
        id=uuid4(), external_ref="EARLY", due_date=HORIZON_START + timedelta(days=1)
    )
    order_late = Order(id=uuid4(), external_ref="LATE", due_date=HORIZON_START + timedelta(days=1))
    seeded = Operation(
        id=uuid4(),
        order_id=order_seed.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    early = Operation(
        id=uuid4(),
        order_id=order_early.id,
        seq_in_order=1,
        state_id=state_b.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    late = Operation(
        id=uuid4(),
        order_id=order_late.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order_seed, order_early, order_late],
        operations=[seeded, early, late],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=100,
            ),
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=100,
            ),
        ],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(hours=8),
    )
    seeded_asg = Assignment(
        operation_id=seeded.id,
        work_center_id=wc.id,
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(minutes=10),
    )
    context = build_dispatch_context(problem)
    assignments = [seeded_asg.model_copy()]
    by_op = {seeded.id: assignments[0]}
    place_operations_list_schedule(
        operations=problem.operations,
        dispatch_context=context,
        assignments=assignments,
        assignment_by_op=by_op,
        scheduled_ids={seeded.id},
        horizon_start=HORIZON_START,
        horizon_minutes=480.0,
        op_earliest={seeded.id: 0.0, early.id: 0.0, late.id: 200.0},
        default_wc_ids=[wc.id],
        cover_ready_rule="atcs",
        cover_atcs_floor_window=200.0,
    )
    by_id = {row.operation_id: row for row in assignments}
    assert by_id[late.id].start_time <= by_id[early.id].start_time
    assert by_id[late.id].setup_minutes == 0


def test_cover_atcs_exhaust_waits_only_for_zero_setup() -> None:
    """Exhaust is continuation-only; a general floor window is a different lever."""

    stats = [
        (0.0, 100.0, 10.0, 0.0),
        (150.0, 50.0, 10.0, 0.0),
        (200.0, 0.0, 10.0, 0.0),
    ]
    assert _atcs_window_indices(stats, 0.0, 0.0) == [0]
    assert _atcs_window_indices(stats, 0.0, 200.0) == [2]
    assert _atcs_window_indices(stats, 200.0, 0.0) == [0, 1, 2]


def test_cover_atcs_exhaust_window_waits_for_same_state() -> None:
    """Continuation exhaust (not a general ATCS floor window) keeps the family."""

    state_a = State(id=uuid4(), code="A", label="A")
    state_b = State(id=uuid4(), code="B", label="B")
    wc = WorkCenter(id=uuid4(), code="M1", capability_group="g", speed_factor=1.0)
    order_seed = Order(id=uuid4(), external_ref="SEED", due_date=HORIZON_START + timedelta(days=1))
    order_early = Order(
        id=uuid4(), external_ref="EARLY", due_date=HORIZON_START + timedelta(days=1)
    )
    order_late = Order(id=uuid4(), external_ref="LATE", due_date=HORIZON_START + timedelta(days=1))
    seeded = Operation(
        id=uuid4(),
        order_id=order_seed.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    early = Operation(
        id=uuid4(),
        order_id=order_early.id,
        seq_in_order=1,
        state_id=state_b.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    late = Operation(
        id=uuid4(),
        order_id=order_late.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order_seed, order_early, order_late],
        operations=[seeded, early, late],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=100,
            ),
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=100,
            ),
        ],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(hours=8),
    )
    seeded_asg = Assignment(
        operation_id=seeded.id,
        work_center_id=wc.id,
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(minutes=10),
    )
    context = build_dispatch_context(problem)
    assignments = [seeded_asg.model_copy()]
    by_op = {seeded.id: assignments[0]}
    place_operations_list_schedule(
        operations=problem.operations,
        dispatch_context=context,
        assignments=assignments,
        assignment_by_op=by_op,
        scheduled_ids={seeded.id},
        horizon_start=HORIZON_START,
        horizon_minutes=480.0,
        op_earliest={seeded.id: 0.0, early.id: 0.0, late.id: 200.0},
        default_wc_ids=[wc.id],
        cover_ready_rule="atcs",
        cover_atcs_exhaust_window=200.0,
    )
    by_id = {row.operation_id: row for row in assignments}
    assert by_id[late.id].start_time <= by_id[early.id].start_time
    assert by_id[late.id].setup_minutes == 0


def test_cover_atcs_exhaust_stays_on_hot_machine() -> None:
    """Exhaustive stay: a zero-setup tail beats a colder earlier-end (Flynn)."""

    state_a = State(id=uuid4(), code="A", label="A")
    state_b = State(id=uuid4(), code="B", label="B")
    hot = WorkCenter(id=uuid4(), code="HOT", capability_group="g", speed_factor=1.0)
    cold = WorkCenter(id=uuid4(), code="COLD", capability_group="g", speed_factor=1.0)
    order_hot = Order(id=uuid4(), external_ref="HOT", due_date=HORIZON_START + timedelta(days=1))
    order_cold = Order(id=uuid4(), external_ref="COLD", due_date=HORIZON_START + timedelta(days=1))
    order_job = Order(id=uuid4(), external_ref="JOB", due_date=HORIZON_START + timedelta(days=1))
    seed_hot = Operation(
        id=uuid4(),
        order_id=order_hot.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=200,
        eligible_wc_ids=[hot.id],
    )
    seed_cold = Operation(
        id=uuid4(),
        order_id=order_cold.id,
        seq_in_order=1,
        state_id=state_b.id,
        base_duration_min=1,
        eligible_wc_ids=[cold.id],
    )
    job = Operation(
        id=uuid4(),
        order_id=order_job.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[hot.id, cold.id],
    )
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order_hot, order_cold, order_job],
        operations=[seed_hot, seed_cold, job],
        work_centers=[hot, cold],
        setup_matrix=[
            SetupEntry(
                work_center_id=cold.id,
                from_state_id=state_b.id,
                to_state_id=state_a.id,
                setup_minutes=100,
            ),
            SetupEntry(
                work_center_id=hot.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=100,
            ),
        ],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(hours=8),
    )
    context = build_dispatch_context(problem)

    def _place(*, exhaust: float) -> dict:
        seeded = [
            Assignment(
                operation_id=seed_hot.id,
                work_center_id=hot.id,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=200),
            ),
            Assignment(
                operation_id=seed_cold.id,
                work_center_id=cold.id,
                start_time=HORIZON_START,
                end_time=HORIZON_START + timedelta(minutes=1),
            ),
        ]
        by_op = {row.operation_id: row for row in seeded}
        assignments = list(seeded)
        place_operations_list_schedule(
            operations=problem.operations,
            dispatch_context=context,
            assignments=assignments,
            assignment_by_op=by_op,
            scheduled_ids={seed_hot.id, seed_cold.id},
            horizon_start=HORIZON_START,
            horizon_minutes=480.0,
            op_earliest={seed_hot.id: 0.0, seed_cold.id: 0.0, job.id: 0.0},
            default_wc_ids=[hot.id, cold.id],
            cover_ready_rule="atcs",
            cover_atcs_exhaust_window=exhaust,
        )
        return {row.operation_id: row for row in assignments}

    jumped = _place(exhaust=0.0)
    stayed = _place(exhaust=240.0)
    assert jumped[job.id].work_center_id == cold.id
    assert jumped[job.id].setup_minutes == 100
    assert stayed[job.id].work_center_id == hot.id
    assert stayed[job.id].setup_minutes == 0
