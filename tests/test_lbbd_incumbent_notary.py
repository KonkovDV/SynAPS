"""LBBD never adopts a merged schedule the notary refuses (FEASIBLE ⇒ ∅ proven violations).

Cluster subproblems are solved separately and merged; post-assembly then
right-shifts operations for cross-cluster precedence. Before this fix the
shift ignored machine calendars and nothing re-checked the merge, so on the
instance below LBBD returned FEASIBLE with makespan 15 and a
CALENDAR_VIOLATION: cluster M1 put C (earlier due date) before A, cluster M2
placed B right after its own copy of A, and the merge pushed B into M2's
closed period [10, 100).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_DNS, uuid5

import pytest

import synaps.solvers.lbbd_solver as lbbd_module
from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    ShiftInterval,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker, proven_hard_violations
from synaps.solvers.lbbd_hd_solver import LbbdHdSolver
from synaps.solvers.lbbd_solver import LbbdSolver

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _uid(tag: str) -> object:
    return uuid5(NAMESPACE_DNS, f"lbbd-notary-{tag}")


def _calendar_problem() -> ScheduleProblem:
    state = State(id=_uid("s"), code="S")
    m1 = WorkCenter(id=_uid("m1"), code="M1", capability_group="g")
    m2 = WorkCenter(
        id=_uid("m2"),
        code="M2",
        capability_group="g",
        calendar=[
            ShiftInterval(start=_H0, end=_H0 + timedelta(minutes=10)),
            ShiftInterval(start=_H0 + timedelta(minutes=100), end=_H0 + timedelta(minutes=200)),
        ],
    )
    j1 = Order(id=_uid("j1"), external_ref="J1", due_date=_H0 + timedelta(minutes=500))
    j2 = Order(id=_uid("j2"), external_ref="J2", due_date=_H0 + timedelta(minutes=5))
    a = Operation(
        id=_uid("a"),
        order_id=j1.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=5,
        eligible_wc_ids=[m1.id],
    )
    return ScheduleProblem(
        states=[state],
        orders=[j1, j2],
        operations=[
            a,
            Operation(
                id=_uid("b"),
                order_id=j1.id,
                seq_in_order=1,
                state_id=state.id,
                base_duration_min=5,
                eligible_wc_ids=[m2.id],
                predecessor_op_id=a.id,
            ),
            Operation(
                id=_uid("c"),
                order_id=j2.id,
                seq_in_order=0,
                state_id=state.id,
                base_duration_min=5,
                eligible_wc_ids=[m1.id],
            ),
        ],
        work_centers=[m1, m2],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(minutes=1000),
    )


def _proven(problem: ScheduleProblem, result: object) -> list[str]:
    assignments = result.assignments  # type: ignore[attr-defined]
    checks = FeasibilityChecker().check(problem, assignments, exhaustive=True)
    return [violation.kind for violation in proven_hard_violations(checks)]


@pytest.mark.parametrize("warm_start", [True, False])
def test_lbbd_merge_is_moved_into_an_open_shift(warm_start: bool) -> None:
    problem = _calendar_problem()
    result = LbbdSolver().solve(
        problem,
        time_limit_s=20,
        max_iterations=3,
        use_greedy_warm_start=warm_start,
        parallel_subproblems=False,
    )
    assert result.status is SolverStatus.FEASIBLE
    assert _proven(problem, result) == []
    b = next(a for a in result.assignments if a.operation_id == _uid("b"))
    assert (b.start_time - _H0) >= timedelta(minutes=100)  # second shift


def test_lbbd_refuses_a_notary_rejected_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without the shift snap the merge violates the calendar: it must not win."""
    monkeypatch.setattr(lbbd_module, "snap_into_shifts", lambda *args: (False, True))
    problem = _calendar_problem()
    result = LbbdSolver().solve(
        problem, time_limit_s=20, max_iterations=3, parallel_subproblems=False
    )
    assert _proven(problem, result) == []
    rejections = result.metadata["incumbent_rejections"]
    assert {"source": "merged_subproblems", "kinds": ["CALENDAR_VIOLATION"]} in rejections


def test_lbbd_hd_result_has_no_proven_violation() -> None:
    problem = _calendar_problem()
    result = LbbdHdSolver().solve(
        problem, time_limit_s=20, max_iterations=3, parallel_subproblems=False
    )
    assert result.status is SolverStatus.FEASIBLE
    assert _proven(problem, result) == []
