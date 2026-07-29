"""P0-2: symmetry breaking must not cut the optimum.

A capacity-ordering symmetry cut is valid only when two machines are truly
interchangeable — same capability_group, speed_factor, max_parallel, identical
setup matrix, and the identical set of operations for which they are eligible.
The old cut grouped by (capability_group, speed_factor) and summed presences
over "shared" operations, which cut the optimum whenever one operation was
eligible on A but not B.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import Operation, Order, ScheduleProblem, SolverStatus, State, WorkCenter
from synaps.solvers.cpsat_solver import CpSatSolver

H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _asymmetric_eligibility_problem() -> ScheduleProblem:
    """M1==M2 by parameters, but X is eligible only on M1.

    X(100) on M1 only; Y(10), Z(10) on both. Optimum: X on M1, Y+Z on M2 =>
    makespan 100. A capacity cut sum(M1) >= sum(M2) over {Y,Z} forces at least
    one of Y/Z onto M1 (on top of X) => 110.
    """
    s1 = State(code="S1")
    m1 = WorkCenter(code="M1", capability_group="G", speed_factor=1.0)
    m2 = WorkCenter(code="M2", capability_group="G", speed_factor=1.0)
    ox, oy, oz = uuid4(), uuid4(), uuid4()
    x = Operation(
        order_id=ox, seq_in_order=0, state_id=s1.id, base_duration_min=100, eligible_wc_ids=[m1.id]
    )
    y = Operation(
        order_id=oy,
        seq_in_order=0,
        state_id=s1.id,
        base_duration_min=10,
        eligible_wc_ids=[m1.id, m2.id],
    )
    z = Operation(
        order_id=oz,
        seq_in_order=0,
        state_id=s1.id,
        base_duration_min=10,
        eligible_wc_ids=[m1.id, m2.id],
    )
    return ScheduleProblem(
        states=[s1],
        orders=[
            Order(id=ox, external_ref="X", due_date=H0 + timedelta(minutes=1000)),
            Order(id=oy, external_ref="Y", due_date=H0 + timedelta(minutes=1000)),
            Order(id=oz, external_ref="Z", due_date=H0 + timedelta(minutes=1000)),
        ],
        operations=[x, y, z],
        work_centers=[m1, m2],
        setup_matrix=[],
        planning_horizon_start=H0,
        planning_horizon_end=H0 + timedelta(minutes=1000),
    )


def test_symmetry_breaking_preserves_optimum() -> None:
    problem = _asymmetric_eligibility_problem()
    off = CpSatSolver().solve(
        problem, time_limit_s=20, auto_greedy_warm_start=False, enable_symmetry_breaking=False
    )
    on = CpSatSolver().solve(
        problem, time_limit_s=20, auto_greedy_warm_start=False, enable_symmetry_breaking=True
    )
    assert off.objective.makespan_minutes == 100.0
    # Pre-fix the cut forced 110; interchangeability now requires identical
    # eligible-op sets, which M1/M2 do not have (X is M1-only).
    assert on.objective.makespan_minutes == 100.0


def _random_small_problem(seed: int) -> ScheduleProblem:
    rng = random.Random(seed)
    n_states = rng.randint(1, 3)
    states = [State(code=f"S{i}") for i in range(n_states)]
    n_machines = rng.randint(2, 4)
    machines = [
        WorkCenter(code=f"M{i}", capability_group=rng.choice(["G", "H"]), speed_factor=1.0)
        for i in range(n_machines)
    ]
    n_ops = rng.randint(3, 12)
    operations: list[Operation] = []
    orders: list[Order] = []
    for _ in range(n_ops):
        order_id = uuid4()
        orders.append(Order(id=order_id, external_ref="O", due_date=H0 + timedelta(minutes=5000)))
        k = rng.randint(1, n_machines)
        eligible = rng.sample([m.id for m in machines], k)
        operations.append(
            Operation(
                order_id=order_id,
                seq_in_order=0,
                state_id=rng.choice(states).id,
                base_duration_min=rng.randint(5, 40),
                eligible_wc_ids=eligible,
            )
        )
    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=machines,
        setup_matrix=[],
        planning_horizon_start=H0,
        planning_horizon_end=H0 + timedelta(minutes=5000),
    )


@pytest.mark.slow
def test_symmetry_breaking_property_200_random_instances() -> None:
    """On 200 random small instances, makespan must match with SB on and off."""
    for seed in range(200):
        problem = _random_small_problem(seed)
        off = CpSatSolver().solve(
            problem, time_limit_s=10, auto_greedy_warm_start=False, enable_symmetry_breaking=False
        )
        on = CpSatSolver().solve(
            problem, time_limit_s=10, auto_greedy_warm_start=False, enable_symmetry_breaking=True
        )
        # Both must be proven optimal, else an equality of two non-optima (or a
        # timeout incumbent) would make the invariant vacuous or spuriously fail.
        assert on.status is SolverStatus.OPTIMAL and off.status is SolverStatus.OPTIMAL, (
            f"seed={seed}: expected OPTIMAL both, got off={off.status} on={on.status}"
        )
        assert on.objective.makespan_minutes == off.objective.makespan_minutes, (
            f"seed={seed}: SB changed optimum {off.objective.makespan_minutes} -> "
            f"{on.objective.makespan_minutes}"
        )
