"""F10 (audit v4): an unscheduled order is maximally late, not free.

Pre-fix, ``objective.evaluate`` used completion=0.0 for orders with no
assignments, UNDERSTATING tardiness — and ALNS' internal evaluator did the
same, which let the search "improve" its scalar cost by dropping late orders.
An order with no scheduled operations now completes at the planning horizon
end for tardiness purposes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import Operation, Order, ScheduleProblem, State, WorkCenter
from synaps.objective import evaluate
from synaps.solvers.alns_solver import _evaluate_objective
from synaps.solvers.sdst_matrix import SdstMatrix

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HORIZON_MIN = 24 * 60  # 1 day


def _problem_with_unscheduled() -> tuple[ScheduleProblem, float]:
    """One order scheduled nowhere; due 60 min into a 1-day horizon."""
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O1", due_date=_H0 + timedelta(minutes=60))
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(minutes=_HORIZON_MIN),
    )
    expected = float(_HORIZON_MIN - 60)  # horizon-end completion minus due
    return problem, expected


def test_canonical_evaluate_charges_unscheduled_order() -> None:
    problem, expected = _problem_with_unscheduled()
    obj = evaluate(problem, [])
    assert obj.total_tardiness_minutes == expected, (
        f"unscheduled order must be tardy by horizon_end - due: "
        f"{obj.total_tardiness_minutes} != {expected}"
    )
    assert obj.coverage == 0.0
    assert obj.unscheduled_operations == 1


def test_alns_internal_evaluator_agrees() -> None:
    """The ALNS search objective must not reward dropping a late order (F10)."""
    problem, expected = _problem_with_unscheduled()
    obj = _evaluate_objective(problem, [], SdstMatrix.from_problem(problem))
    assert obj.total_tardiness_minutes == expected
