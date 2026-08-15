"""M1: order release_date must be honored by solvers and the checker.

Measured before the fix (Red Team audit v2, tag M1): a 60-minute operation on
an order with ``release_date = H0 + 500 min`` started at H0 in GREEDY, BEAM,
CP-SAT, ALNS and LBBD, and ``FeasibilityChecker`` reported the schedule CLEAN.
``release_date`` (production meaning: material not available before it) was
declared on the model but only the RHC layer honored it.

Fix: a hard CP-SAT start constraint ``start >= release_offset``, the dispatch
layer seeds ``earliest_start`` with the release offset, and the checker gains a
``RELEASE_DATE_VIOLATION`` category.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    State,
    WorkCenter,
)
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.timegrain import ceil_datetime_to_minute, floor_datetime_to_minute

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=10)


def test_ceil_datetime_to_minute_is_idempotent_on_grid() -> None:
    """Exact minutes stay put; 90s ceils to 2; pre-horizon instants stay put."""
    assert ceil_datetime_to_minute(H0 + timedelta(minutes=1), H0) == H0 + timedelta(minutes=1)
    assert ceil_datetime_to_minute(H0 + timedelta(seconds=90), H0) == H0 + timedelta(minutes=2)
    assert ceil_datetime_to_minute(H0 - timedelta(seconds=30), H0) == H0 - timedelta(seconds=30)


def test_floor_datetime_to_minute_is_idempotent_on_grid() -> None:
    """C7-R1: exact minutes stay put; 90s floors to 1, not 2 (ceil would relax LFT)."""
    assert floor_datetime_to_minute(H0 + timedelta(minutes=2), H0) == H0 + timedelta(minutes=2)
    assert floor_datetime_to_minute(H0 + timedelta(seconds=90), H0) == H0 + timedelta(minutes=1)
    assert floor_datetime_to_minute(H0 - timedelta(seconds=30), H0) == H0 - timedelta(seconds=30)


def _released_problem() -> ScheduleProblem:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(
        external_ref="O1",
        due_date=H0 + timedelta(days=9),
        release_date=H0 + timedelta(minutes=500),
    )
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=60,
        eligible_wc_ids=[wc.id],
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


def test_checker_flags_release_date_violation() -> None:
    """M1: a start before the order release_date must be a violation."""
    problem = _released_problem()
    assert problem.orders[0].release_date == H0 + timedelta(minutes=500)
    op = problem.operations[0]
    early = [
        Assignment(
            operation_id=op.id,
            work_center_id=problem.work_centers[0].id,
            start_time=H0,
            end_time=H0 + timedelta(minutes=60),
        )
    ]
    violations = FeasibilityChecker().check(problem, early, exhaustive=True)
    assert any(v.kind == "RELEASE_DATE_VIOLATION" for v in violations), (
        f"release-date violation not flagged: {[v.kind for v in violations]}"
    )


def test_cpsat_honors_subminute_release_date() -> None:
    """F8 (audit v4): a release at a sub-minute offset must not be truncated.

    Before the fix the release offset was computed with ``int(seconds/60)``
    (floor), so a release at H0+90s became offset 1 and the op could start at
    H0+1:00 — 30s before release, a RELEASE_DATE_VIOLATION the checker rightly
    flags. The offset must ceil to the first integer minute not before release.
    """
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    release = H0 + timedelta(seconds=90)
    order = Order(
        external_ref="O1",
        due_date=H0 + timedelta(days=9),
        release_date=release,
    )
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=60,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state], orders=[order], operations=[op], work_centers=[wc],
        setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
    )
    result = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False
    )
    assert result.assignments, "expected a feasible schedule"
    start = result.assignments[0].start_time
    assert start >= release, f"started at {start}, before release {release}"
    violations = FeasibilityChecker().check(problem, result.assignments, exhaustive=True)
    assert not violations, f"checker must stay clean: {[v.kind for v in violations]}"


def test_cpsat_honors_release_date() -> None:
    """M1: CP-SAT must not start an operation before its order release_date."""
    problem = _released_problem()
    orders = {o.id: o for o in problem.orders}
    ops = {o.id: o for o in problem.operations}
    result = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False
    )
    for a in result.assignments:
        release = orders[ops[a.operation_id].order_id].release_date
        assert release is not None
        assert a.start_time >= release, f"CP-SAT started {a.start_time} before release {release}"
    assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True)


def test_greedy_honors_release_date() -> None:
    """M1: greedy dispatch must not start an operation before its release_date."""
    problem = _released_problem()
    orders = {o.id: o for o in problem.orders}
    ops = {o.id: o for o in problem.operations}
    result = GreedyDispatch().solve(problem)
    for a in result.assignments:
        release = orders[ops[a.operation_id].order_id].release_date
        assert release is not None
        assert a.start_time >= release, f"greedy started {a.start_time} before release {release}"
    assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True)


def test_ingest_ceils_subminute_release_and_leaves_due_date() -> None:
    """C7: published EST ceils, LFT floors; due_date is not retimed."""
    due = H0 + timedelta(days=9, seconds=90)
    release = H0 + timedelta(seconds=90)
    earliest = H0 + timedelta(seconds=30)
    latest = H0 + timedelta(minutes=5, seconds=30)  # 5.5 min → floor 5; 90s would be 6.5
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O1", due_date=due, release_date=release)
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=60,
        eligible_wc_ids=[wc.id],
        earliest_start=earliest,
        latest_finish=latest,
    )
    problem = ScheduleProblem(
        states=[state], orders=[order], operations=[op], work_centers=[wc],
        setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
    )
    assert problem.orders[0].release_date == H0 + timedelta(minutes=2)
    assert problem.operations[0].earliest_start == H0 + timedelta(minutes=1)
    assert problem.operations[0].latest_finish == H0 + timedelta(minutes=5)
    assert problem.orders[0].due_date == due


def test_checker_rejects_start_inside_ceiled_release_gap() -> None:
    """C7: a start at the raw 90s instant is late vs the ingested 2-minute EST."""
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(
        external_ref="O1",
        due_date=H0 + timedelta(days=9),
        release_date=H0 + timedelta(seconds=90),
    )
    op = Operation(
        order_id=order.id, seq_in_order=1, state_id=state.id,
        base_duration_min=60, eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state], orders=[order], operations=[op], work_centers=[wc],
        setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
    )
    gap = [
        Assignment(
            operation_id=op.id,
            work_center_id=wc.id,
            start_time=H0 + timedelta(seconds=90),
            end_time=H0 + timedelta(seconds=90, minutes=60),
        )
    ]
    violations = FeasibilityChecker().check(problem, gap, exhaustive=True)
    assert any(v.kind == "RELEASE_DATE_VIOLATION" for v in violations), (
        f"90s start must miss the ingested 2-minute release: {[v.kind for v in violations]}"
    )


def test_greedy_honors_subminute_release_on_minute_grid() -> None:
    """C7: greedy places on the same ceiled EST as CP-SAT / the checker."""
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(
        external_ref="O1",
        due_date=H0 + timedelta(days=9),
        release_date=H0 + timedelta(seconds=90),
    )
    op = Operation(
        order_id=order.id, seq_in_order=1, state_id=state.id,
        base_duration_min=60, eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state], orders=[order], operations=[op], work_centers=[wc],
        setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
    )
    result = GreedyDispatch().solve(problem)
    assert result.assignments
    snapped = H0 + timedelta(minutes=2)
    assert result.assignments[0].start_time >= snapped
    assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True)


def _one_minute_lft_problem(*, latest: datetime) -> ScheduleProblem:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O1", due_date=H0 + timedelta(days=9))
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=1,
        eligible_wc_ids=[wc.id],
        latest_finish=latest,
    )
    return ScheduleProblem(
        states=[state], orders=[order], operations=[op], work_centers=[wc],
        setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
    )


def test_checker_rejects_finish_inside_floored_lft_gap() -> None:
    """C7-R1: a finish at the raw 90s instant is late vs the ingested 1-minute LFT."""
    problem = _one_minute_lft_problem(latest=H0 + timedelta(seconds=90))
    assert problem.operations[0].latest_finish == H0 + timedelta(minutes=1)
    op = problem.operations[0]
    gap = [
        Assignment(
            operation_id=op.id,
            work_center_id=problem.work_centers[0].id,
            start_time=H0,
            end_time=H0 + timedelta(seconds=90),
        )
    ]
    violations = FeasibilityChecker().check(problem, gap, exhaustive=True)
    assert any(v.kind == "HORIZON_BOUND_VIOLATION" for v in violations), (
        f"90s finish must miss the ingested 1-minute LFT: {[v.kind for v in violations]}"
    )


def test_greedy_and_cpsat_honor_floored_latest_finish() -> None:
    """C7-R1: solvers finish on the same floored LFT as the checker."""
    problem = _one_minute_lft_problem(latest=H0 + timedelta(seconds=90))
    snapped = H0 + timedelta(minutes=1)
    greedy = GreedyDispatch().solve(problem)
    assert greedy.assignments
    assert greedy.assignments[0].end_time <= snapped
    assert not FeasibilityChecker().check(problem, greedy.assignments, exhaustive=True)
    cpsat = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False
    )
    assert cpsat.assignments
    assert cpsat.assignments[0].end_time <= snapped
    assert not FeasibilityChecker().check(problem, cpsat.assignments, exhaustive=True)
