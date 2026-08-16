"""F2 (audit v4): DURATION_MISMATCH is a hard physical floor, no tolerance.

The pre-v4 checker allowed ``actual < ceil(base/speed) - 1 min`` and its comment
claimed ``round(base/speed) >= base/speed`` — false whenever the fractional part
is < 0.5 (e.g. base=10, speed=3 -> p_real=3.33, round=3). It therefore
CERTIFIED physically impossible spans (up to 0.5 min under-reservation per op,
compounding along precedence chains). T-10 removed the solver-side divergence
at the source (ALNS native paths snap to the ceil grain), so the tolerance is
gone: the hard floor is the real processing time ``base/speed``.
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
from synaps.solvers.feasibility_checker import FeasibilityChecker

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _problem(base_min: int, speed: float) -> ScheduleProblem:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G", speed_factor=speed)
    order = Order(external_ref="O1", due_date=_H0 + timedelta(days=1))
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=base_min,
        eligible_wc_ids=[wc.id],
    )
    return ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=1),
    )


def _single_assignment(problem: ScheduleProblem, span_min: float) -> list[Assignment]:
    return [
        Assignment(
            operation_id=problem.operations[0].id,
            work_center_id=problem.work_centers[0].id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=span_min),
        )
    ]


def test_span_below_physical_floor_is_rejected() -> None:
    """base=10, speed=3 -> p_real=3.33min; a 3.0-min span is physically impossible.

    Pre-fix this passed: 3.0 < ceil(3.33)-1 = 3 is False, so no violation.
    """
    problem = _problem(base_min=10, speed=3.0)
    violations = FeasibilityChecker().check(problem, _single_assignment(problem, 3.0))
    assert any(v.kind == "DURATION_MISMATCH" for v in violations)


def test_physically_sufficient_sub_ceil_span_passes_default() -> None:
    """3.4 min >= 3.33 real processing: feasible, though below the ceil grain."""
    problem = _problem(base_min=10, speed=3.0)
    violations = FeasibilityChecker().check(problem, _single_assignment(problem, 3.4))
    assert not violations


def test_strict_grain_flags_sub_ceil_span() -> None:
    problem = _problem(base_min=10, speed=3.0)
    violations = FeasibilityChecker().check(
        problem, _single_assignment(problem, 3.4), strict_grain=True
    )
    assert [v.kind for v in violations] == ["DURATION_BELOW_GRAIN"]


def test_ceil_grain_span_is_clean_under_strict_grain() -> None:
    problem = _problem(base_min=10, speed=3.0)
    violations = FeasibilityChecker().check(
        problem, _single_assignment(problem, 4.0), strict_grain=True
    )
    assert not violations
