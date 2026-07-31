"""P0-3: FeasibilityChecker must validate operation durations.

Measured before the fix (Red Team audit v1, tag P0-3): an operation with
base_duration_min=10 on a speed_factor=3 machine (processing 10/3 = 3.33 min)
submitted with a 1-minute duration produced ZERO violations — the checker never
compared the assignment span against the processing time, so an arbitrarily
short operation passed as feasible.

Fix: a DURATION_MISMATCH check comparing the assignment span to the CANONICAL
integer grain ``timegrain.duration_minutes`` = ``ceil(base/speed)`` (P0-4), which
is the RESERVATION target. A 1-minute inter-solver tolerance is retained: the
real processing time is ``base/speed`` and a solver that reserved
``round(base/speed)`` (or the raw physical span) is at most ~1 min under ceil
and is still physically adequate, so only a MATERIAL underrun (>= 1 min below
ceil) is flagged. Removing the tolerance wrongly rejected valid round-based
schedules (e.g. ALNS' internal validity gate).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import Assignment, Operation, Order, ScheduleProblem, State, WorkCenter
from synaps.solvers.feasibility_checker import FeasibilityChecker

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=5)


def _speed3_problem() -> tuple[ScheduleProblem, Operation, WorkCenter]:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G", speed_factor=3.0)
    order = Order(external_ref="O1", due_date=HE)
    op = Operation(
        order_id=order.id, seq_in_order=1, state_id=state.id,
        base_duration_min=10, eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state], orders=[order], operations=[op], work_centers=[wc],
        setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
    )
    return problem, op, wc


def test_checker_flags_too_short_duration() -> None:
    """P0-3: a 1-min span for a 3.33-min operation must be a violation."""
    problem, op, wc = _speed3_problem()
    impossible = [
        Assignment(
            operation_id=op.id, work_center_id=wc.id,
            start_time=H0, end_time=H0 + timedelta(minutes=1),
        )
    ]
    violations = FeasibilityChecker().check(problem, impossible, exhaustive=True)
    assert any(v.kind == "DURATION_MISMATCH" for v in violations), (
        f"short duration not flagged: {[v.kind for v in violations]}"
    )


def test_checker_accepts_canonical_ceil_duration() -> None:
    """P0-3/P0-4: the canonical ceil(10/3)=4 span (and longer) must pass."""
    problem, op, wc = _speed3_problem()
    for minutes in (4.0, 5.0):
        ok = [
            Assignment(
                operation_id=op.id, work_center_id=wc.id,
                start_time=H0, end_time=H0 + timedelta(minutes=minutes),
            )
        ]
        violations = FeasibilityChecker().check(problem, ok, exhaustive=True)
        assert not any(v.kind == "DURATION_MISMATCH" for v in violations), (
            f"duration {minutes} wrongly flagged: {[v.kind for v in violations]}"
        )


def test_checker_flags_material_underrun_below_tolerance() -> None:
    """P0-3/P0-4: a span >= 1 min below the ceil(10/3)=4 grain (e.g. 2 min) is a
    MATERIAL underrun and is flagged, while a sub-minute divergence is not (see
    the tolerance test below)."""
    problem, op, wc = _speed3_problem()
    under = [
        Assignment(
            operation_id=op.id, work_center_id=wc.id,
            start_time=H0, end_time=H0 + timedelta(minutes=2.0),
        )
    ]
    violations = FeasibilityChecker().check(problem, under, exhaustive=True)
    assert any(v.kind == "DURATION_MISMATCH" for v in violations), (
        f"material underrun not flagged: {[v.kind for v in violations]}"
    )


def test_checker_tolerates_sub_minute_rounding_divergence() -> None:
    """P0-4: ceil(10/3)=4 is the reservation target, but a round-down (3) or raw
    physical (3.333) span is within 1 min of ceil and physically adequate, so it
    must be TOLERATED -- otherwise the checker rejects valid round-based solvers
    (the regression that broke ALNS' internal validity gate)."""
    problem, op, wc = _speed3_problem()
    for minutes in (3.0, 10.0 / 3.0):
        near = [
            Assignment(
                operation_id=op.id, work_center_id=wc.id,
                start_time=H0, end_time=H0 + timedelta(minutes=minutes),
            )
        ]
        violations = FeasibilityChecker().check(problem, near, exhaustive=True)
        assert not any(v.kind == "DURATION_MISMATCH" for v in violations), (
            f"sub-minute divergence {minutes} wrongly flagged: {[v.kind for v in violations]}"
        )
