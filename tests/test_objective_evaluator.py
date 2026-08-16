"""P0-6: a single canonical objective evaluator, consistent across solvers.

The objective vector was re-derived inline by seven solvers; ``weighted_sum``
was filled only by CP-SAT yet used as a sort key. ``synaps.objective.evaluate``
is now the one definition. This suite pins evaluate/scalarize and asserts every
representative solver's reported objective matches ``evaluate`` on its own final
assignments (the audit's rule: internal incremental evaluators are allowed, but
must agree with the canonical evaluator on the final solution).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.objective import DEFAULT_WEIGHTS, evaluate, scalarize
from synaps.solvers.registry import create_solver

_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"
_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _setup_problem() -> tuple[ScheduleProblem, list[Assignment]]:
    """One machine, two ops in different states: a 30-min changeover applies."""
    s1, s2 = State(code="s1"), State(code="s2")
    wc = WorkCenter(code="M", capability_group="G")
    o1, o2 = uuid4(), uuid4()
    op1 = Operation(
        order_id=o1, seq_in_order=1, state_id=s1.id, base_duration_min=60, eligible_wc_ids=[wc.id]
    )
    op2 = Operation(
        order_id=o2, seq_in_order=1, state_id=s2.id, base_duration_min=60, eligible_wc_ids=[wc.id]
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=[
            Order(id=o1, external_ref="O1", due_date=_H0 + timedelta(minutes=100)),
            Order(id=o2, external_ref="O2", due_date=_H0 + timedelta(minutes=100)),
        ],
        operations=[op1, op2],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=30,
                material_loss=4.0,
            ),
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=1),
    )
    assignments = [
        Assignment(
            operation_id=op1.id,
            work_center_id=wc.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=60),
        ),
        Assignment(
            operation_id=op2.id,
            work_center_id=wc.id,
            start_time=_H0 + timedelta(minutes=90),
            end_time=_H0 + timedelta(minutes=150),
        ),
    ]
    return problem, assignments


def test_evaluate_components() -> None:
    problem, assignments = _setup_problem()
    obj = evaluate(problem, assignments)
    assert obj.makespan_minutes == 150.0
    assert obj.total_setup_minutes == 30.0  # one s1->s2 changeover
    assert obj.total_material_loss == 4.0
    # O2 completes at 150, due at 100 -> 50 tardy; O1 completes at 60, due 100 -> 0.
    assert obj.total_tardiness_minutes == 50.0
    assert obj.coverage == 1.0


def test_scalarize_default_is_makespan() -> None:
    problem, assignments = _setup_problem()
    obj = evaluate(problem, assignments)
    assert scalarize(obj) == obj.makespan_minutes
    combined = scalarize(obj, {**DEFAULT_WEIGHTS, "setup": 1.0, "tardiness": 1.0})
    assert combined == obj.makespan_minutes + obj.total_setup_minutes + obj.total_tardiness_minutes


def test_parallel_lanes_incur_no_phantom_setup() -> None:
    """M2: two concurrent lanes of one machine must not charge a changeover."""
    s1, s2 = State(code="s1"), State(code="s2")
    wc = WorkCenter(code="M2", capability_group="G", max_parallel=2)
    o1, o2 = uuid4(), uuid4()
    op1 = Operation(
        order_id=o1, seq_in_order=1, state_id=s1.id, base_duration_min=60, eligible_wc_ids=[wc.id]
    )
    op2 = Operation(
        order_id=o2, seq_in_order=1, state_id=s2.id, base_duration_min=60, eligible_wc_ids=[wc.id]
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=[
            Order(id=o1, external_ref="O1", due_date=_H0 + timedelta(days=1)),
            Order(id=o2, external_ref="O2", due_date=_H0 + timedelta(days=1)),
        ],
        operations=[op1, op2],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=600
            )
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=1),
    )
    lane_a, lane_b = uuid4(), uuid4()
    concurrent = [
        Assignment(
            operation_id=op1.id,
            work_center_id=wc.id,
            lane_id=lane_a,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=60),
        ),
        Assignment(
            operation_id=op2.id,
            work_center_id=wc.id,
            lane_id=lane_b,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=60),
        ),
    ]
    obj = evaluate(problem, concurrent)
    assert obj.total_setup_minutes == 0.0, "parallel lanes must not incur a changeover"
    assert obj.makespan_minutes == 60.0


@pytest.mark.parametrize("config", ["GREED", "BEAM-3", "CPSAT-10", "LBBD-5", "ALNS-300"])
def test_solver_objective_matches_canonical_evaluator(config: str) -> None:
    """Every solver's reported objective must match evaluate() on its schedule."""
    problem = ScheduleProblem.model_validate(json.loads((_INSTANCES / "tiny_3x3.json").read_text()))
    solver, kwargs = create_solver(config)
    kwargs.update(
        {
            "CPSAT-10": {"time_limit_s": 5, "num_workers": 1},
            "LBBD-5": {"time_limit_s": 5, "max_iterations": 3},
            "ALNS-300": {"time_limit_s": 5, "max_iterations": 40},
        }.get(config, {})
    )
    result = solver.solve(problem, **kwargs)
    canonical = evaluate(problem, result.assignments)
    assert result.objective.makespan_minutes == pytest.approx(canonical.makespan_minutes, abs=1e-6)
    assert result.objective.total_setup_minutes == pytest.approx(
        canonical.total_setup_minutes, abs=1e-6
    )
    assert result.objective.total_material_loss == pytest.approx(
        canonical.total_material_loss, abs=1e-6
    )
    assert result.objective.total_tardiness_minutes == pytest.approx(
        canonical.total_tardiness_minutes, abs=1e-6
    )
