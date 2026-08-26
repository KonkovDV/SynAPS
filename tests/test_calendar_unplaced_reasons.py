"""K2.1 unplaced-reason codes: construction vs window vs crew vs GOST."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from benchmark.study_calendar_3000 import (
    GOST_PRIORITY_PREEMPTED,
    IMPOSSIBLE_BY_CONSTRUCTION,
    NO_CREW_CAPACITY,
    WINDOW_CLOSED,
    apply_night_machine_calendar,
    classify_unplaced,
    classify_unplaced_operation,
    night_shift_intervals,
)
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    ScheduleResult,
    ShiftInterval,
    SolverStatus,
    State,
    WorkCenter,
)

H0 = datetime(2026, 4, 1, tzinfo=UTC)
HE = H0 + timedelta(days=2)


def _problem(
    *, duration: int, calendar: list[ShiftInterval], latest_finish=None
) -> ScheduleProblem:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G", calendar=calendar)
    order = Order(external_ref="O", due_date=HE)
    op = Operation(
        order_id=order.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=duration,
        eligible_wc_ids=[wc.id],
        latest_finish=latest_finish,
    )
    return ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )


def test_impossible_when_occupancy_exceeds_every_shift() -> None:
    shift = ShiftInterval(start=H0 + timedelta(hours=22), end=H0 + timedelta(hours=30))
    problem = _problem(duration=9 * 60, calendar=[shift])
    row = classify_unplaced_operation(problem, problem.operations[0])
    assert row["reason"] == IMPOSSIBLE_BY_CONSTRUCTION


def test_window_closed_when_latest_finish_is_before_first_shift() -> None:
    shift = ShiftInterval(start=H0 + timedelta(hours=22), end=H0 + timedelta(hours=30))
    problem = _problem(
        duration=30,
        calendar=[shift],
        latest_finish=H0 + timedelta(hours=1),
    )
    row = classify_unplaced_operation(problem, problem.operations[0])
    assert row["reason"] == WINDOW_CLOSED


def test_no_crew_capacity_when_empty_machine_would_fit() -> None:
    shift = ShiftInterval(start=H0 + timedelta(hours=22), end=H0 + timedelta(hours=30))
    problem = _problem(duration=30, calendar=[shift])
    empty = ScheduleResult(solver_name="RHC-GREEDY", status=SolverStatus.ERROR)
    rows, tallies = classify_unplaced(problem, empty)
    assert rows[0]["reason"] == NO_CREW_CAPACITY
    assert tallies[NO_CREW_CAPACITY] == 1
    assert tallies[GOST_PRIORITY_PREEMPTED] == 0


def test_calendar_instance_has_no_per_op_windows() -> None:
    raw = generate_large_instance(
        n_operations=8,
        n_machines=2,
        n_states=4,
        ops_per_order=2,
        machine_flexibility=0.5,
        setup_density=0.5,
        setup_range=(10, 20),
        n_aux_resources=0,
        duration_range=(8, 12),
        horizon_hours=72,
        seed=1,
    )
    problem = apply_night_machine_calendar(raw)
    assert all(wc.calendar for wc in problem.work_centers)
    assert all(op.earliest_start is None and op.latest_finish is None for op in problem.operations)
    nights = night_shift_intervals(problem.planning_horizon_start, problem.planning_horizon_end)
    assert nights
    assert nights[0].start.hour == 22
