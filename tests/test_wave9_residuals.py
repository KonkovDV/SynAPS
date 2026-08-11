"""Wave 9 tests: LBBD assignment_setup_lb metadata."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers._lbbd_cuts import compute_assignment_setup_lb_total
from synaps.solvers.lbbd_solver import LbbdSolver

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def _toy_problem() -> ScheduleProblem:
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    orders = [
        Order(external_ref="O1", due_date=_HE),
        Order(external_ref="O2", due_date=_HE),
    ]
    ops = [
        Operation(
            order_id=orders[0].id,
            seq_in_order=1,
            state_id=s1.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
        ),
        Operation(
            order_id=orders[1].id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
        ),
    ]
    return ScheduleProblem(
        states=[s1, s2],
        orders=orders,
        operations=ops,
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=3,
            ),
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s2.id,
                to_state_id=s1.id,
                setup_minutes=4,
            ),
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )


def test_assignment_setup_lb_total_nonnegative() -> None:
    problem = _toy_problem()
    # Empty schedule → 0
    assert compute_assignment_setup_lb_total(problem, []) == 0.0


def test_lbbd_metadata_includes_assignment_setup_lb() -> None:
    problem = _toy_problem()
    result = LbbdSolver().solve(
        problem,
        time_limit_s=5,
        max_iterations=3,
        use_greedy_warm_start=True,
    )
    components = (result.metadata or {}).get("lower_bound_components") or {}
    assert "assignment_setup_lb" in components
    assert components["assignment_setup_lb"] >= 0.0
