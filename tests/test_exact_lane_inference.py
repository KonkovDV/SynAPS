"""F7 (audit v4): lane inference on parallel machines is EXACT, not greedy.

The pre-v4 greedy inferred lanes in (start, end) order, choosing the
latest-available lane — an online heuristic that cannot revise choices. The
repro below (latest-fit tie picks the wrong lane) made the checker emit a
SETUP_GAP_VIOLATION for a schedule that IS lane-feasible. The exact memoized
backtracking search explores all lane assignments, so a violation it confirms
is a proven infeasibility, and a feasible schedule is never false-flagged.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def _greedy_trap_problem() -> tuple[ScheduleProblem, list[Assignment]]:
    """Latest-fit greedy fails on this; an exact assignment exists.

    Lanes: 2. Setup s1->s2 = 100 (everything else 0).
      A [0,10) s2 | B [5,10) s1 | C [10,20) s1 | D [20,30) s2
    Greedy: A->lane0; B->lane1; C fits BOTH at t=10 — the first/latest tie
    picks lane0; D then needs s2->s2 (lane0 tail C is s1: 120 > 20) or
    s1->s2 on lane1 (110 > 20) -> FALSE SETUP_GAP_VIOLATION.
    Exact: lane0 A->D (10 <= 20), lane1 B->C (10 <= 10) — feasible.
    """
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G", max_parallel=2)
    specs = [("A", s2, 0, 10), ("B", s1, 5, 10), ("C", s1, 10, 20), ("D", s2, 20, 30)]
    # One order per op: ops of the same order auto-chain via seq_in_order.
    orders = [Order(external_ref=f"O{name}", due_date=_HE) for name, _s, _a, _b in specs]
    ops = [
        Operation(order_id=orders[i].id, seq_in_order=1, state_id=st.id,
                  base_duration_min=1, eligible_wc_ids=[wc.id])
        for i, (_name, st, _start, _end) in enumerate(specs)
    ]
    setup = [
        SetupEntry(work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id,
                   setup_minutes=100),
    ]
    problem = ScheduleProblem(
        states=[s1, s2], orders=orders, operations=ops, work_centers=[wc],
        setup_matrix=setup, planning_horizon_start=_H0, planning_horizon_end=_HE,
    )
    assignments = [
        Assignment(
            operation_id=op.id, work_center_id=wc.id,
            start_time=_H0 + timedelta(minutes=start),
            end_time=_H0 + timedelta(minutes=end),
        )
        for op, (_name, _st, start, end) in zip(ops, specs, strict=True)
    ]
    return problem, assignments


def test_exact_inference_accepts_greedy_trap() -> None:
    """The feasible schedule must not be false-flagged anymore (F7 repro)."""
    problem, assignments = _greedy_trap_problem()
    violations = FeasibilityChecker().check(problem, assignments, exhaustive=True)
    assert not violations, [f"{v.kind}: {v.message}" for v in violations]


def test_exact_inference_still_proves_real_infeasibility() -> None:
    """Three truly-concurrent ops on a 2-lane machine stay infeasible."""
    s1 = State(code="a")
    wc = WorkCenter(code="M", capability_group="G", max_parallel=2)
    orders = [Order(external_ref=f"O{i}", due_date=_HE) for i in (1, 2, 3)]
    ops = [
        Operation(order_id=orders[i].id, seq_in_order=1, state_id=s1.id,
                  base_duration_min=10, eligible_wc_ids=[wc.id])
        for i in (0, 1, 2)
    ]
    problem = ScheduleProblem(
        states=[s1], orders=orders, operations=ops, work_centers=[wc],
        setup_matrix=[], planning_horizon_start=_H0, planning_horizon_end=_HE,
    )
    assignments = [
        Assignment(operation_id=op.id, work_center_id=wc.id,
                   start_time=_H0, end_time=_H0 + timedelta(minutes=10))
        for op in ops
    ]
    violations = FeasibilityChecker().check(problem, assignments, exhaustive=True)
    assert violations, "3 concurrent ops on 2 lanes must be flagged"


def test_explicit_lane_metadata_path_unchanged() -> None:
    """Explicit lane_id metadata still drives lane grouping directly."""
    problem, assignments = _greedy_trap_problem()
    lane_by_seq = {1: "lane-0", 2: "lane-1", 3: "lane-1", 4: "lane-0"}
    for a in assignments:
        seq = next(
            i for i, op in enumerate(problem.operations, start=1)
            if op.id == a.operation_id
        )
        a.lane_id = lane_by_seq[seq]
    violations = FeasibilityChecker().check(problem, assignments, exhaustive=True)
    assert not violations, [f"{v.kind}: {v.message}" for v in violations]
