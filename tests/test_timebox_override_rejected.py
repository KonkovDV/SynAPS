"""N3 (audit v3): the timebox must not be bypassable through sat_parameters.

Before the fix, ``_apply_sat_parameter_overrides`` applied caller overrides
AFTER setting the limits and its docstring explicitly allowed it ("Explicit
overrides still win"), so ``solve(p, time_limit_s=8,
sat_parameters={'max_time_in_seconds': 8000})`` ran ~24 s -- 3x the budget. The
budget must be settable only through ``time_limit_s``.
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
        order_id=order.id, seq_in_order=1, state_id=state.id,
        base_duration_min=10, eligible_wc_ids=[wc.id],
    )
    return ScheduleProblem(
        states=[state], orders=[order], operations=[op], work_centers=[wc], setup_matrix=[],
        planning_horizon_start=_H0, planning_horizon_end=_H0 + timedelta(days=1),
    )


@pytest.mark.parametrize("limit_key", ["max_time_in_seconds", "max_deterministic_time"])
def test_time_limit_override_via_sat_parameters_is_rejected(limit_key: str) -> None:
    problem = _tiny_problem()
    with pytest.raises(ValueError, match="time_limit_s"):
        CpSatSolver().solve(
            problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False,
            sat_parameters={limit_key: 8000.0},
        )


def test_benign_sat_parameter_override_still_allowed() -> None:
    """A non-timebox override must still be accepted."""
    problem = _tiny_problem()
    result = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False,
        sat_parameters={"log_search_progress": False},
    )
    assert result.assignments
