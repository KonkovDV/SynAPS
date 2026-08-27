"""Regression tests for dispatch support helpers used by ALNS/repair flows."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from synaps.model import Assignment, ScheduleProblem
from synaps.solvers._dispatch_support import (
    APPEND_GAP_SCAN_MIN_OPS,
    MachineIndex,
    build_dispatch_context,
    find_earliest_feasible_slot,
    recompute_assignment_setups,
)
from tests.conftest import HORIZON_START, make_simple_problem


def test_machine_index_setup_windows_tolerate_missing_predecessor_operation(
    simple_problem: ScheduleProblem,
) -> None:
    """Missing predecessor operation IDs must not crash setup window computation."""
    context = build_dispatch_context(simple_problem)
    machine_id = simple_problem.work_centers[0].id
    known_operation = simple_problem.operations[0]

    index = MachineIndex(context)
    index.add(
        Assignment(
            operation_id=uuid4(),
            work_center_id=machine_id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=20),
            setup_minutes=0,
        )
    )
    index.add(
        Assignment(
            operation_id=known_operation.id,
            work_center_id=machine_id,
            start_time=HORIZON_START + timedelta(minutes=30),
            end_time=HORIZON_START + timedelta(minutes=60),
            setup_minutes=0,
        )
    )

    setup_windows = index.get_setup_window_starts()
    assert known_operation.id in setup_windows
    assert setup_windows[known_operation.id] == 30.0


def test_machine_index_incremental_setup_windows_match_full_recompute(
    simple_problem: ScheduleProblem,
) -> None:
    """Adding after a cache hit must match a cold full recompute."""
    context = build_dispatch_context(simple_problem)
    machine_id = simple_problem.work_centers[0].id
    ops = simple_problem.operations[:3]
    incremental = MachineIndex(context)
    for index, operation in enumerate(ops):
        incremental.add(
            Assignment(
                operation_id=operation.id,
                work_center_id=machine_id,
                start_time=HORIZON_START + timedelta(minutes=index * 40),
                end_time=HORIZON_START + timedelta(minutes=index * 40 + 20),
                setup_minutes=0,
            )
        )
        incremental.get_setup_window_starts()

    cold = MachineIndex(context)
    for index, operation in enumerate(ops):
        cold.add(
            Assignment(
                operation_id=operation.id,
                work_center_id=machine_id,
                start_time=HORIZON_START + timedelta(minutes=index * 40),
                end_time=HORIZON_START + timedelta(minutes=index * 40 + 20),
                setup_minutes=0,
            )
        )
    assert incremental.get_setup_window_starts() == cold.get_setup_window_starts()


def test_machine_index_extend_matches_sequential_add(
    simple_problem: ScheduleProblem,
) -> None:
    context = build_dispatch_context(simple_problem)
    machine_id = simple_problem.work_centers[0].id
    assignments = [
        Assignment(
            operation_id=operation.id,
            work_center_id=machine_id,
            start_time=HORIZON_START + timedelta(minutes=index * 40),
            end_time=HORIZON_START + timedelta(minutes=index * 40 + 20),
            setup_minutes=0,
        )
        for index, operation in enumerate(simple_problem.operations[:3])
    ]
    bulk = MachineIndex(context)
    bulk.extend(assignments)
    sequential = MachineIndex(context)
    for assignment in assignments:
        sequential.add(assignment)
    assert bulk.get_setup_window_starts() == sequential.get_setup_window_starts()
    assert [a.operation_id for a in bulk.get_machine_assignments(machine_id)] == [
        a.operation_id for a in sequential.get_machine_assignments(machine_id)
    ]


def test_recompute_assignment_setups_tolerates_missing_previous_operation(
    simple_problem: ScheduleProblem,
) -> None:
    """Recompute must keep running when previous assignment op is outside problem graph."""
    context = build_dispatch_context(simple_problem)
    machine_id = simple_problem.work_centers[0].id
    known_operation = simple_problem.operations[1]

    assignments = [
        Assignment(
            operation_id=uuid4(),
            work_center_id=machine_id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=15),
            setup_minutes=0,
        ),
        Assignment(
            operation_id=known_operation.id,
            work_center_id=machine_id,
            start_time=HORIZON_START + timedelta(minutes=25),
            end_time=HORIZON_START + timedelta(minutes=55),
            setup_minutes=999,
        ),
    ]

    total_setup = recompute_assignment_setups(assignments, context)
    assert assignments[1].setup_minutes == 0
    assert total_setup == 0.0


def test_append_gap_scan_min_ops_threshold() -> None:
    from synaps.solvers.greedy_dispatch import _gap_scan_for

    assert APPEND_GAP_SCAN_MIN_OPS == 2000
    assert _gap_scan_for(APPEND_GAP_SCAN_MIN_OPS - 1) == "all"
    assert _gap_scan_for(APPEND_GAP_SCAN_MIN_OPS) == "append"


def test_append_gap_scan_does_not_fill_interior_hole() -> None:
    """K3.6: append scan only evaluates after the last job on the machine."""

    problem = make_simple_problem(n_orders=3, ops_per_order=1)
    context = build_dispatch_context(problem)
    wc_id = problem.work_centers[0].id
    first, second, third = problem.operations
    scheduled = [
        Assignment(
            operation_id=first.id,
            work_center_id=wc_id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=30),
            setup_minutes=0,
        ),
        Assignment(
            operation_id=second.id,
            work_center_id=wc_id,
            start_time=HORIZON_START + timedelta(minutes=200),
            end_time=HORIZON_START + timedelta(minutes=230),
            setup_minutes=0,
        ),
    ]
    slot_all = find_earliest_feasible_slot(context, scheduled, third, wc_id, 0.0, gap_scan="all")
    slot_append = find_earliest_feasible_slot(
        context, scheduled, third, wc_id, 0.0, gap_scan="append"
    )
    assert slot_all is not None
    assert slot_append is not None
    assert slot_all.start_offset < 100
    assert slot_append.start_offset >= 200
