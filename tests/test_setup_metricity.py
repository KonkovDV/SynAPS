"""M3: the SDST setup matrix triangle inequality must be validated (not silent).

Measured before the fix (Red Team audit v2, tag M3): a setup matrix violating
the triangle inequality (``s1->s3 = 100`` while ``s1->s2->s3 = 2``) was accepted
by ``ScheduleProblem`` with no validation surface, so any bound or heuristic
that assumes metricity had no way to know. The policy is *flag, don't forbid*:
non-metric matrices remain legal, but the violations are enumerable and the
problem profile records ``sdst_metric``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import Operation, Order, ScheduleProblem, SetupEntry, State, WorkCenter
from synaps.problem_profile import build_problem_profile
from synaps.validation import is_setup_matrix_metric, validate_setup_matrix_metricity

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=10)


def _problem(pairs: list[tuple[int, int, int]]) -> ScheduleProblem:
    """Build a 3-state single-machine instance with the given setup pairs.

    ``pairs`` is a list of (from_index, to_index, minutes).
    """
    states = [State(code=f"s{i}") for i in range(3)]
    wc = WorkCenter(code="M", capability_group="G")
    orders: list[Order] = []
    ops: list[Operation] = []
    for i, st in enumerate(states):
        order = Order(external_ref=f"O{i}", due_date=H0 + timedelta(days=9))
        orders.append(order)
        ops.append(
            Operation(
                order_id=order.id,
                seq_in_order=1,
                state_id=st.id,
                base_duration_min=10,
                eligible_wc_ids=[wc.id],
            )
        )
    setup_matrix = [
        SetupEntry(
            work_center_id=wc.id,
            from_state_id=states[a].id,
            to_state_id=states[b].id,
            setup_minutes=v,
        )
        for a, b, v in pairs
    ]
    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=ops,
        work_centers=[wc],
        setup_matrix=setup_matrix,
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )


# s1->s3 = 100 but s1->s2 + s2->s3 = 2 → triangle violated on (s1, s2, s3).
_NON_METRIC = [(0, 1, 1), (1, 2, 1), (0, 2, 100), (2, 0, 1), (1, 0, 1), (2, 1, 1)]
_METRIC = [(0, 1, 1), (1, 2, 1), (0, 2, 2), (2, 0, 1), (1, 0, 1), (2, 1, 1)]


def test_validate_detects_triangle_violation() -> None:
    """M3: the non-metric matrix must yield an enumerated violation triple."""
    problem = _problem(_NON_METRIC)
    violations = validate_setup_matrix_metricity(problem)
    assert violations, "non-metric matrix reported no triangle violations"
    triples = {(v.from_state_id, v.via_state_id, v.to_state_id) for v in violations}
    s = problem.states
    assert (s[0].id, s[1].id, s[2].id) in triples
    assert not is_setup_matrix_metric(problem)


def test_validate_passes_metric_matrix() -> None:
    """M3: a matrix satisfying the triangle inequality has no violations."""
    problem = _problem(_METRIC)
    assert validate_setup_matrix_metricity(problem) == []
    assert is_setup_matrix_metric(problem)


def test_problem_profile_records_sdst_metric() -> None:
    """M3: the problem profile must expose the sdst_metric flag."""
    assert build_problem_profile(_problem(_METRIC)).as_dict()["sdst_metric"] is True
    assert build_problem_profile(_problem(_NON_METRIC)).as_dict()["sdst_metric"] is False
