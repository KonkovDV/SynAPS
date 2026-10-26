"""Public makespan lower bounds honour execution modes (Rule 6).

``duration_minutes_for`` knows the base duration and T-30 overrides, not
modes. CP-SAT runs a moded operation for the SELECTED mode's ``duration_min``
on any eligible machine, so a bound built on the base duration over-claims
whenever a mode is shorter. The bounds use the shortest mode instead.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_DNS, uuid5

from synaps.model import (
    Operation,
    OperationMode,
    Order,
    ScheduleProblem,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers._lbbd_sound import compute_sound_master_lower_bound
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.lower_bounds import compute_relaxed_makespan_lower_bound
from synaps.timegrain import min_duration_minutes_for

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _moded_problem() -> ScheduleProblem:
    state = State(id=uuid5(NAMESPACE_DNS, "mlb-s"), code="S")
    machine = WorkCenter(id=uuid5(NAMESPACE_DNS, "mlb-m"), code="M", capability_group="g")
    order = Order(id=uuid5(NAMESPACE_DNS, "mlb-o"), external_ref="O", due_date=_H0)
    return ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[
            Operation(
                id=uuid5(NAMESPACE_DNS, f"mlb-op{i}"),
                order_id=order.id,
                seq_in_order=i,
                state_id=state.id,
                base_duration_min=100,
                modes=[
                    OperationMode(code="FAST", duration_min=10),
                    OperationMode(code="SLOW", duration_min=20),
                ],
            )
            for i in range(2)
        ],
        work_centers=[machine],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(hours=8),
    )


def test_min_duration_is_the_shortest_mode() -> None:
    problem = _moded_problem()
    assert min_duration_minutes_for(problem.operations[0], problem.work_centers[0]) == 10


def test_bounds_do_not_exceed_the_cpsat_optimum_with_modes() -> None:
    problem = _moded_problem()
    result = CpSatSolver().solve(problem, time_limit_s=10, random_seed=1)
    assert result.status is SolverStatus.OPTIMAL
    optimum = result.objective.makespan_minutes
    assert optimum == 20  # two chained FAST runs
    assert compute_relaxed_makespan_lower_bound(problem).value <= optimum
    assert compute_sound_master_lower_bound(problem).value <= optimum
