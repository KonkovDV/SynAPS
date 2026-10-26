"""Lane virtualization keeps per-machine durations (found by the T-06 oracle).

``max_parallel > 1`` work centers are split into virtual single-lane work
centers by greedy dispatch (always) and by CP-SAT (when the machine has
setups). Both copies remapped ``eligible_wc_ids`` onto the lanes but left
``machine_duration_overrides`` keyed by the ORIGINAL work center, which the
transformed ``ScheduleProblem`` rejects ("overrides reference unknown work
centers"): every solve of such an instance died with a ``ValidationError``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_DNS, uuid5

import pytest

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
from synaps.solvers.feasibility_checker import FeasibilityChecker, hard_violations
from synaps.solvers.greedy_dispatch import GreedyDispatch

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _problem(*, with_setups: bool) -> ScheduleProblem:
    a, b = (
        State(id=uuid5(NAMESPACE_DNS, "vl-a"), code="A"),
        State(id=uuid5(NAMESPACE_DNS, "vl-b"), code="B"),
    )
    press = WorkCenter(
        id=uuid5(NAMESPACE_DNS, "vl-press"), code="PRESS", capability_group="g", max_parallel=2
    )
    orders = [
        Order(id=uuid5(NAMESPACE_DNS, f"vl-o{i}"), external_ref=f"O{i}", due_date=_H0)
        for i in range(2)
    ]
    operations = [
        Operation(
            id=uuid5(NAMESPACE_DNS, f"vl-op{i}"),
            order_id=orders[i].id,
            seq_in_order=0,
            state_id=(a, b)[i].id,
            base_duration_min=10,
            eligible_wc_ids=[press.id],
            # The true time on PRESS is 3 minutes, not base 10.
            machine_duration_overrides={press.id: 3},
        )
        for i in range(2)
    ]
    setup = (
        [
            SetupEntry(
                work_center_id=press.id, from_state_id=x.id, to_state_id=y.id, setup_minutes=5
            )
            for x, y in ((a, b), (b, a))
        ]
        if with_setups
        else []
    )
    return ScheduleProblem(
        states=[a, b],
        orders=orders,
        operations=operations,
        work_centers=[press],
        setup_matrix=setup,
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(hours=4),
    )


@pytest.mark.parametrize("with_setups", [False, True])
def test_greedy_keeps_overrides_on_virtual_lanes(with_setups: bool) -> None:
    problem = _problem(with_setups=with_setups)
    result = GreedyDispatch().solve(problem)
    assert result.status is SolverStatus.FEASIBLE
    assert result.objective.makespan_minutes == 3  # both lanes, 3 minutes each
    assert not hard_violations(FeasibilityChecker().check(problem, result.assignments))


@pytest.mark.parametrize("with_setups", [False, True])
def test_cpsat_keeps_overrides_on_virtual_lanes(with_setups: bool) -> None:
    problem = _problem(with_setups=with_setups)
    result = CpSatSolver().solve(problem, time_limit_s=10, random_seed=1)
    assert result.status is SolverStatus.OPTIMAL
    assert result.objective.makespan_minutes == 3
    assert not hard_violations(FeasibilityChecker().check(problem, result.assignments))
