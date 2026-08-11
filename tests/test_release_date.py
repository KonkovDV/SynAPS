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

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=10)


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
