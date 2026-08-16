"""F9 (audit v4): strict determinism must not be bypassable via sat_parameters.

Strict mode is reproducible BECAUSE it is single-threaded (N1, ADR-0001). Before
this fix, ``sat_parameters={"num_workers": 8}`` was applied AFTER the strict
setup and silently re-enabled the multi-threaded portfolio race, while metadata
still claimed ``determinism="strict"``. Worker-count overrides are now rejected
in strict mode (same policy as the N3 timebox keys); ``determinism="fast"``
remains the explicit opt-out.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from synaps.model import Operation, Order, ScheduleProblem, State, WorkCenter
from synaps.solvers.cpsat_solver import CpSatSolver

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _tiny_problem() -> ScheduleProblem:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O1", due_date=_H0 + timedelta(days=1))
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    return ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=1),
    )


@pytest.mark.parametrize("worker_key", ["num_workers", "num_search_workers"])
def test_worker_override_rejected_in_strict_mode(worker_key: str) -> None:
    problem = _tiny_problem()
    with pytest.raises(ValueError, match="determinism='fast'"):
        CpSatSolver().solve(
            problem,
            time_limit_s=5,
            determinism="strict",
            auto_greedy_warm_start=False,
            sat_parameters={worker_key: 8},
        )


def test_worker_override_allowed_in_fast_mode() -> None:
    """The fast lane keeps full override freedom (it never claimed reproducibility)."""
    problem = _tiny_problem()
    result = CpSatSolver().solve(
        problem,
        time_limit_s=5,
        determinism="fast",
        auto_greedy_warm_start=False,
        sat_parameters={"num_workers": 2},
    )
    assert result.assignments
    assert result.metadata["determinism"] == "fast"


def test_random_seed_override_rejected_in_strict_mode() -> None:
    """C7: sat_parameters must not swap the solve() seed under strict."""
    problem = _tiny_problem()
    with pytest.raises(ValueError, match="random_seed"):
        CpSatSolver().solve(
            problem,
            time_limit_s=5,
            determinism="strict",
            random_seed=42,
            auto_greedy_warm_start=False,
            sat_parameters={"random_seed": 99},
        )


def test_random_seed_override_allowed_in_fast_mode() -> None:
    """Fast mode may still override the seed; the published seed must follow."""
    problem = _tiny_problem()
    result = CpSatSolver().solve(
        problem,
        time_limit_s=5,
        determinism="fast",
        random_seed=42,
        auto_greedy_warm_start=False,
        sat_parameters={"random_seed": 99},
    )
    assert result.assignments
    assert result.random_seed == 99
    assert result.metadata["sat_parameters"]["random_seed"] == 99
