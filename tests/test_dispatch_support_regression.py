"""Regression tests for dispatch support helpers used by ALNS/repair flows."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from synaps.model import Assignment, ScheduleProblem
from synaps.solvers._dispatch_support import (
    MachineIndex,
    build_dispatch_context,
    recompute_assignment_setups,
)
from tests.conftest import HORIZON_START


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
