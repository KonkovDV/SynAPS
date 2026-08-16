"""F2/T-10 (audit v4): ALNS native paths must emit canonical-grain spans.

The Rust ``greedy_repair_batch`` kernel computes raw ``base/speed`` float
spans (10/3 = 3.333... min). The Python post-processing now snaps every span
to the canonical integer reservation ``ceil(base/speed)`` (P0-4), which is
what allowed the checker to drop its 1-minute tolerance: the hard
DURATION_MISMATCH floor is the real physical processing time.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from synaps.model import Operation, Order, ScheduleProblem, State, WorkCenter
from synaps.solvers.alns_solver import (
    _repair_greedy,
    _try_native_initial_seed,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.timegrain import duration_minutes

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _speed3_problem(n_ops: int = 3) -> ScheduleProblem:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G", speed_factor=3.0)
    orders = [Order(external_ref=f"O{i}", due_date=_H0 + timedelta(days=1)) for i in range(n_ops)]
    ops = [
        Operation(
            order_id=orders[i].id,
            seq_in_order=1,
            state_id=state.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        )
        for i in range(n_ops)
    ]
    return ScheduleProblem(
        states=[state],
        orders=orders,
        operations=ops,
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=1),
    )


def _assert_canonical_spans(problem: ScheduleProblem, assignments: list) -> None:
    wc_speed = problem.work_centers[0].speed_factor
    assert len(assignments) == len(problem.operations)
    for a in assignments:
        op = next(o for o in problem.operations if o.id == a.operation_id)
        span = (a.end_time - a.start_time).total_seconds() / 60.0
        assert span == pytest.approx(float(duration_minutes(op.base_duration_min, wc_speed))), (
            f"op {a.operation_id} span {span} is not the canonical ceil grain"
        )
    violations = FeasibilityChecker().check(problem, list(assignments), strict_grain=True)
    assert not violations, [f"{v.kind}: {v.message}" for v in violations]


def test_native_initial_seed_snaps_to_ceil_grain() -> None:
    pytest.importorskip("synaps_native", reason="native module not built")
    problem = _speed3_problem()
    seed = _try_native_initial_seed(
        problem,
        frozen_assignments=[],
        ops_by_id={op.id: op for op in problem.operations},
        frozen_assignments_by_op={},
    )
    assert seed is not None, "native seed unavailable in this environment"
    _assert_canonical_spans(problem, seed)


def test_native_greedy_repair_snaps_to_ceil_grain() -> None:
    pytest.importorskip("synaps_native", reason="native module not built")
    problem = _speed3_problem()
    destroyed = {op.id for op in problem.operations}
    repaired = _repair_greedy(problem, [], destroyed)
    assert repaired is not None, "native repair unavailable in this environment"
    _assert_canonical_spans(problem, repaired)
