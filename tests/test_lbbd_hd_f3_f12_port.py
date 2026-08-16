"""HD port of F3/F12/F10 (audit v4 follow-up).

Standard LBBD was fixed in Wave 1-2; LBBD-HD initially kept serial null-lane
post-assembly, master None→INFEASIBLE, and completion=0.0 tardiness. These
tests pin the ports.
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
from synaps.objective import evaluate
from synaps.solvers._lbbd_assembly import stamp_parallel_lane_ids
from synaps.solvers.lbbd_hd_solver import (
    _compute_objective,
    _topological_post_assembly,
)

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _parallel_no_setup_problem() -> tuple[ScheduleProblem, list[Assignment]]:
    """Two concurrent ops on max_parallel=2 with no SDST (lane_id absent)."""
    st = State(code="S")
    wc = WorkCenter(code="M", capability_group="G", speed_factor=1.0, max_parallel=2)
    o1 = Order(external_ref="O1", due_date=_H0 + timedelta(hours=2))
    o2 = Order(external_ref="O2", due_date=_H0 + timedelta(hours=2))
    # Unscheduled third order — F10: must charge horizon tardiness.
    o3 = Order(external_ref="O3", due_date=_H0 + timedelta(minutes=30))
    op1 = Operation(
        order_id=o1.id,
        seq_in_order=1,
        state_id=st.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    op2 = Operation(
        order_id=o2.id,
        seq_in_order=1,
        state_id=st.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[st],
        orders=[o1, o2, o3],
        operations=[op1, op2],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(hours=4),
    )
    assignments = [
        Assignment(
            operation_id=op1.id,
            work_center_id=wc.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=10),
            lane_id=None,
        ),
        Assignment(
            operation_id=op2.id,
            work_center_id=wc.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=10),
            lane_id=None,
        ),
    ]
    return problem, assignments


def test_hd_stamp_lanes_keeps_concurrent_ops_parallel() -> None:
    problem, assignments = _parallel_no_setup_problem()
    ops_by_id = {op.id: op for op in problem.operations}
    stamp_parallel_lane_ids(problem, assignments, ops_by_id, lane_tag_prefix="test")
    assert all(a.lane_id is not None for a in assignments)
    assert assignments[0].lane_id != assignments[1].lane_id


def test_hd_topological_assembly_does_not_serialize_parallel() -> None:
    problem, assignments = _parallel_no_setup_problem()
    ops_by_id = {op.id: op for op in problem.operations}
    assembled, horizon_ok = _topological_post_assembly(problem, assignments, ops_by_id)
    assert horizon_ok
    assert assembled is not None
    starts = sorted(a.start_time for a in assembled)
    # Both still start at horizon — not shifted into a serial queue.
    assert starts[0] == _H0
    assert starts[1] == _H0


def test_hd_compute_objective_uses_canonical_evaluate() -> None:
    problem, assignments = _parallel_no_setup_problem()
    got = _compute_objective(problem, assignments)
    expect = evaluate(problem, assignments)
    assert got.total_tardiness_minutes == expect.total_tardiness_minutes
    # Unscheduled o3: due at +30min, horizon 4h → tardiness 210.
    assert got.total_tardiness_minutes >= 210.0 - 1e-6
