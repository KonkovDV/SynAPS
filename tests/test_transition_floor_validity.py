"""Q2: the master per-transition setup floor is conservatively VALID, not dead.

compute_machine_transition_floor is applied by the master as ms*(n_k - 1). The
audit called it "almost always 0 / dead code" and proposed ms = min_{s != t}.
That is UNSAFE: with a repeated state the machine can place two same-state ops
adjacently (a free changeover), so ms*(n_k - 1) with ms = min_{s != t} would
over-claim -- exactly the S1/S2/S3 invalid-bound defect. The floor is therefore
0 whenever a same-state changeover is free (correct), and positive only when
EVERY transition (same-state included) is positive.
"""

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
from synaps.solvers._lbbd_cuts import compute_machine_transition_floor

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _problem_with_setups(
    setups: dict[tuple[int, int], float], *, n_states: int = 2
) -> tuple[ScheduleProblem, WorkCenter, dict[tuple, float]]:
    states = [State(code=f"s{i}") for i in range(n_states)]
    wc = WorkCenter(code="M", capability_group="G")
    orders: list[Order] = []
    ops: list[Operation] = []
    for i, st in enumerate(states):
        order = Order(external_ref=f"O{i}", due_date=_H0 + timedelta(days=1))
        orders.append(order)
        ops.append(
            Operation(order_id=order.id, seq_in_order=1, state_id=st.id,
                      base_duration_min=10, eligible_wc_ids=[wc.id])
        )
    setup_entries = [
        SetupEntry(work_center_id=wc.id, from_state_id=states[a].id, to_state_id=states[b].id,
                   setup_minutes=int(v))
        for (a, b), v in setups.items()
    ]
    problem = ScheduleProblem(
        states=states, orders=orders, operations=ops, work_centers=[wc],
        setup_matrix=setup_entries, planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=1),
    )
    lookup = {(e.work_center_id, e.from_state_id, e.to_state_id): float(e.setup_minutes)
              for e in setup_entries}
    return problem, wc, lookup


def test_floor_is_zero_when_same_state_changeover_is_free() -> None:
    """Distinct-state setups positive, same-state 0 -> floor must be 0 (valid)."""
    problem, wc, lookup = _problem_with_setups({
        (0, 1): 30.0, (1, 0): 30.0,  # distinct-state transitions positive
        (0, 0): 0.0, (1, 1): 0.0,    # same-state free
    })
    eligible = {op.id: [wc.id] for op in problem.operations}
    floor = compute_machine_transition_floor(problem, eligible, wc.id, lookup)
    assert floor == 0.0, "a free same-state changeover makes any positive floor unsafe"


def test_floor_positive_only_when_all_transitions_positive() -> None:
    """Every transition (same-state included) positive -> floor = min positive."""
    problem, wc, lookup = _problem_with_setups({
        (0, 1): 30.0, (1, 0): 20.0,
        (0, 0): 5.0, (1, 1): 7.0,  # even same-state reprocessing costs > 0
    })
    eligible = {op.id: [wc.id] for op in problem.operations}
    floor = compute_machine_transition_floor(problem, eligible, wc.id, lookup)
    assert floor == 5.0, "floor is the min over ALL transitions incl same-state"


def test_floor_zero_for_machine_with_no_eligible_ops() -> None:
    problem, wc, lookup = _problem_with_setups({(0, 1): 30.0})
    floor = compute_machine_transition_floor(problem, {}, wc.id, lookup)
    assert floor == 0.0
