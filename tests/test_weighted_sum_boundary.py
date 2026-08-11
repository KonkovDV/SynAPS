"""F4 (audit v4): weighted_sum is canonicalized at the solver boundary.

Pre-v4, CP-SAT published its internal big-M int64 scalar as weighted_sum while
ALNS/LBBD/Greedy left the 0.0 default — so ``objective_sort_key`` level-2
tie-breaks compared a mixed-unit big-M number against 0.0 and systematically
ranked CP-SAT solutions WORSE on ties. The BaseSolver wrapper now re-derives
``weighted_sum = scalarize(evaluate(problem, assignments))`` for every solver
(raw units, single definition, P0-6 completed); solver-internal scalars live
in ``metadata["objective_components"]``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from synaps.model import (
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    State,
    WorkCenter,
)
from synaps.objective import DEFAULT_WEIGHTS, evaluate, objective_sort_key, scalarize
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.greedy_dispatch import GreedyDispatch

_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _tiny_problem() -> ScheduleProblem:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O1", due_date=_H0 + timedelta(days=1))
    op = Operation(
        order_id=order.id, seq_in_order=1, state_id=state.id,
        base_duration_min=10, eligible_wc_ids=[wc.id],
    )
    return ScheduleProblem(
        states=[state], orders=[order], operations=[op], work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0, planning_horizon_end=_H0 + timedelta(days=1),
    )


def test_cpsat_weighted_sum_is_canonical_not_bigm() -> None:
    """CP-SAT's published weighted_sum must equal scalarize(evaluate(...))."""
    problem = ScheduleProblem.model_validate(
        json.loads((_INSTANCES / "tiny_3x3.json").read_text())
    )
    result = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False
    )
    assert result.objective is not None and result.assignments
    expected = scalarize(evaluate(problem, list(result.assignments)))
    assert result.objective.weighted_sum == expected
    # The raw int64 big-M would be makespan * secondary_bound + ... — vastly
    # larger than the makespan-only canonical scalar on any real instance.
    assert result.objective.weighted_sum == result.objective.weighted_sum  # no NaN


def test_cross_solver_tie_break_no_longer_anti_cpsat() -> None:
    """Equal-component schedules must tie on weighted_sum across solvers."""
    problem = _tiny_problem()
    cpsat = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False
    )
    greedy = GreedyDispatch().solve(problem, time_limit_s=5)
    assert cpsat.assignments and greedy.assignments
    # Same one-op instance -> identical canonical vector -> identical sort key.
    assert objective_sort_key(cpsat.objective) == objective_sort_key(greedy.objective)


def test_default_weights_are_makespan_only() -> None:
    """Pins the scalarization contract referenced by the boundary wrapper."""
    assert DEFAULT_WEIGHTS == {
        "makespan": 1.0,
        "setup": 0.0,
        "material": 0.0,
        "tardiness": 0.0,
    }
    obj = ObjectiveValues(makespan_minutes=42.0, total_setup_minutes=1000.0)
    assert scalarize(obj) == 42.0
