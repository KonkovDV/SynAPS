"""T-25: cross-layer setup-semantics glue (dispatch / CP-SAT / checker).

For small random instances, every FEASIBLE schedule returned by GreedyDispatch
or CpSatSolver must pass FeasibilityChecker (exhaustive) with no capacity,
setup-gap, or aux-resource violations. After F1 the checker charges setup
occupancy on parallel machines the same way aux windows already did — this
property keeps the three layers from drifting apart again.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_BLOCKING = {
    "MACHINE_CAPACITY_VIOLATION",
    "SETUP_GAP_VIOLATION",
    "MACHINE_OVERLAP",
    "AUX_CAPACITY_VIOLATION",
    "DURATION_MISMATCH",
    "PRECEDENCE_VIOLATION",
    "HORIZON_VIOLATION",
    "RELEASE_DATE_VIOLATION",
}


def _small_problem(seed: int, n_ops: int, n_wc: int, max_parallel: int) -> ScheduleProblem:
    rng = __import__("random").Random(seed)
    states = [State(code=f"S{i}") for i in range(max(2, n_ops // 2 + 1))]
    wcs = [
        WorkCenter(
            code=f"M{i}",
            capability_group="G",
            speed_factor=1.0,
            max_parallel=max_parallel if i == 0 else 1,
        )
        for i in range(n_wc)
    ]
    orders: list[Order] = []
    ops: list[Operation] = []
    for i in range(n_ops):
        order = Order(external_ref=f"O{i}", due_date=_H0 + timedelta(hours=8))
        orders.append(order)
        st = states[i % len(states)]
        ops.append(
            Operation(
                order_id=order.id,
                seq_in_order=1,
                state_id=st.id,
                base_duration_min=float(rng.randint(5, 20)),
                eligible_wc_ids=[wc.id for wc in wcs],
            )
        )
    setups: list[SetupEntry] = []
    for wc in wcs:
        for a in states:
            for b in states:
                if a.id == b.id:
                    continue
                setups.append(
                    SetupEntry(
                        work_center_id=wc.id,
                        from_state_id=a.id,
                        to_state_id=b.id,
                        setup_minutes=int(rng.choice([0, 2, 5, 10])),
                    )
                )
    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=ops,
        work_centers=wcs,
        setup_matrix=setups,
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=2),
    )


@given(
    seed=st.integers(min_value=0, max_value=5_000),
    n_ops=st.integers(min_value=3, max_value=8),
    n_wc=st.integers(min_value=1, max_value=3),
    max_parallel=st.sampled_from([1, 2]),
)
@settings(max_examples=40, deadline=None)
def test_feasible_solver_schedules_pass_checker(
    seed: int, n_ops: int, n_wc: int, max_parallel: int
) -> None:
    problem = _small_problem(seed, n_ops, n_wc, max_parallel)
    checker = FeasibilityChecker()
    for solver in (GreedyDispatch(), CpSatSolver()):
        kwargs = {"time_limit_s": 5, "num_workers": 1} if isinstance(solver, CpSatSolver) else {}
        result = solver.solve(problem, **kwargs)
        if result.status.name not in {"FEASIBLE", "OPTIMAL"} or not result.assignments:
            continue
        violations = checker.check(problem, result.assignments, exhaustive=True)
        blocking = [v for v in violations if v.kind in _BLOCKING]
        assert not blocking, (
            f"{solver.name} returned a schedule the checker rejects: "
            + "; ".join(f"{v.kind}: {v.message}" for v in blocking[:3])
        )
