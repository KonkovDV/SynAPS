"""P0-1: the setup interval must not weld end_i to start_j (forbidding idle)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.cpsat_solver import CpSatSolver

H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _idle_forcing_problem() -> ScheduleProblem:
    """Construction where forbidding machine idle cuts the optimum.

    Order 1: A (M1, dur 10, state S1) -> C (M2, dur 60), precedence A -> C.
    Order 2: B0 (M3, dur 100, state S1) -> B (M1, dur 10, state S2).
    setup (M1, S1 -> S2) = 10, so on M1 the sequence A then B needs a 10-min gap.

    True optimum: A[0,10], C[10,70], B0[0,100], B[100,110] -> makespan 110.
    B cannot start before 100 (waits on B0), so M1 is idle 10..100. The weld
    bug forces start_B == end_A + 10 -> end_A = 90 -> C[90,150] -> makespan 150.
    """
    s1, s2 = State(code="S1"), State(code="S2")
    m1 = WorkCenter(code="M1", capability_group="g1")
    m2 = WorkCenter(code="M2", capability_group="g2")
    m3 = WorkCenter(code="M3", capability_group="g3")
    o1, o2 = uuid4(), uuid4()
    a = Operation(
        order_id=o1, seq_in_order=0, state_id=s1.id, base_duration_min=10, eligible_wc_ids=[m1.id]
    )
    c = Operation(
        order_id=o1,
        seq_in_order=1,
        state_id=s1.id,
        base_duration_min=60,
        eligible_wc_ids=[m2.id],
        predecessor_op_id=a.id,
    )
    b0 = Operation(
        order_id=o2, seq_in_order=0, state_id=s1.id, base_duration_min=100, eligible_wc_ids=[m3.id]
    )
    b = Operation(
        order_id=o2,
        seq_in_order=1,
        state_id=s2.id,
        base_duration_min=10,
        eligible_wc_ids=[m1.id],
        predecessor_op_id=b0.id,
    )
    return ScheduleProblem(
        states=[s1, s2],
        orders=[
            Order(id=o1, external_ref="O1", due_date=H0 + timedelta(minutes=500)),
            Order(id=o2, external_ref="O2", due_date=H0 + timedelta(minutes=500)),
        ],
        operations=[a, c, b0, b],
        work_centers=[m1, m2, m3],
        setup_matrix=[
            SetupEntry(
                work_center_id=m1.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=10
            ),
            SetupEntry(
                work_center_id=m1.id, from_state_id=s2.id, to_state_id=s1.id, setup_minutes=10
            ),
        ],
        planning_horizon_start=H0,
        planning_horizon_end=H0 + timedelta(minutes=500),
    )


def test_setup_interval_does_not_forbid_machine_idle() -> None:
    """P0-1: idle on M1 (10..100) must be allowed; optimum is 110, not 150."""
    problem = _idle_forcing_problem()
    result = CpSatSolver().solve(
        problem, time_limit_s=30, auto_greedy_warm_start=False, enable_symmetry_breaking=False
    )
    assert result.status is SolverStatus.OPTIMAL
    # Pre-fix the weld yields 150.0; the correct optimum with machine idle is 110.
    assert result.objective.makespan_minutes == 110.0
