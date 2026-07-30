"""P0-3: FeasibilityChecker must validate operation durations.

Measured before the fix (Red Team audit v1, tag P0-3): an operation with
base_duration_min=10 on a speed_factor=3 machine (processing 10/3 = 3.33 min)
submitted with a 1-minute duration produced ZERO violations — the checker never
compared the assignment span against base/speed, so an arbitrarily short (or
long) operation passed as feasible.

Fix: a DURATION_MISMATCH check comparing the assignment span to base/speed with
a 1-minute tolerance. The tolerance absorbs the round/ceil/floor divergence
between solvers (P0-4, a separate defect) so a correct CP-SAT (round) or greedy
(exact) duration passes, while a grossly wrong span (1 vs 3.33) is caught.
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


def test_checker_accepts_rounded_duration() -> None:
    """P0-3: the round (3) and exact (3.333) durations must both pass."""
    problem, op, wc = _speed3_problem()
    for minutes in (3.0, 10.0 / 3.0, 4.0):
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
