"""P1-1: the big-M objective must not overflow int64 at the model's stated scale.

The default hierarchical objective is ``makespan * secondary_bound +
secondary_terms``. At MAX_SCHEDULE_OPERATIONS the coefficient product
``(horizon + 1) * secondary_bound`` can exceed the CP-SAT int64 objective
domain and corrupt the solve. The solver now detects that and degrades to a
pure lexicographic objective (makespan only) instead of overflowing, recording
``metadata["objective_bigm_overflow_degraded"]``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.cpsat_solver import (
    _SAFE_OBJECTIVE_MAX,
    CpSatSolver,
    _bigm_objective_overflows,
    _objective_product_overflows,
)

_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_overflow_predicate_boundary() -> None:
    # Well within the safe ceiling.
    assert _bigm_objective_overflows(horizon=10_000, secondary_bound=10_000) is False
    # A product that exceeds the safe ceiling (2**62) overflows.
    assert _bigm_objective_overflows(horizon=10**10, secondary_bound=10**10) is True
    # Exactly at the ceiling is not an overflow; one above is.
    assert _bigm_objective_overflows(horizon=_SAFE_OBJECTIVE_MAX - 1, secondary_bound=1) is False
    assert _bigm_objective_overflows(horizon=_SAFE_OBJECTIVE_MAX, secondary_bound=1) is True


def test_normal_solve_is_not_degraded() -> None:
    """A normal small instance stays on the exact big-M objective (flag False)."""
    problem = ScheduleProblem.model_validate(
        json.loads((_INSTANCES / "tiny_3x3.json").read_text())
    )
    result = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False
    )
    assert result.metadata["objective_bigm_overflow_degraded"] is False


# --- F5 (audit v4): epsilon_primary must obey the same overflow guard --------


def test_objective_product_overflows_predicate() -> None:
    assert _objective_product_overflows(term_bound=10_000, multiplier_bound=10_000) is False
    assert _objective_product_overflows(term_bound=10**10, multiplier_bound=10**10) is True
    assert _objective_product_overflows(1, _SAFE_OBJECTIVE_MAX - 1) is False
    assert _objective_product_overflows(1, _SAFE_OBJECTIVE_MAX) is True
    # Backward-compatible big-M wrapper agrees with the general predicate.
    assert _bigm_objective_overflows(horizon=10**10, secondary_bound=10**10) is True


def _overflow_instance() -> ScheduleProblem:
    """Same-state ops (no setup is ever taken) + one astronomic matrix entry.

    ``setup_ub = max_setup * n_ops`` is derived from the matrix regardless of
    usage, so the epsilon_primary objective ``total_setup * (horizon + 1)``
    overflows while the schedule itself stays trivially feasible.
    """
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O1", due_date=_H0 + timedelta(days=7))
    ops = [
        Operation(
            order_id=order.id, seq_in_order=i, state_id=s1.id,
            base_duration_min=10, eligible_wc_ids=[wc.id],
        )
        for i in (1, 2)
    ]
    setup = SetupEntry(
        work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id,
        setup_minutes=10**15,
    )
    return ScheduleProblem(
        states=[s1, s2], orders=[order], operations=ops, work_centers=[wc],
        setup_matrix=[setup],
        planning_horizon_start=_H0, planning_horizon_end=_H0 + timedelta(days=7),
    )


def test_epsilon_primary_overflow_degrades_instead_of_corrupting() -> None:
    """F5: primary*(horizon+1) with an astronomic primary bound must degrade."""
    problem = _overflow_instance()
    result = CpSatSolver().solve(
        problem,
        time_limit_s=5,
        num_workers=1,
        auto_greedy_warm_start=False,
        objective_mode="epsilon_primary",
        primary_objective="setup",
    )
    assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
    assert result.metadata["objective_bigm_overflow_degraded"] is True


def test_epsilon_primary_normal_instance_not_degraded() -> None:
    problem = ScheduleProblem.model_validate(
        json.loads((_INSTANCES / "tiny_3x3.json").read_text())
    )
    result = CpSatSolver().solve(
        problem,
        time_limit_s=5,
        num_workers=1,
        auto_greedy_warm_start=False,
        objective_mode="epsilon_primary",
        primary_objective="setup",
    )
    assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
    assert result.metadata["objective_bigm_overflow_degraded"] is False
