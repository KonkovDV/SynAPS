"""Test that GreedyDispatch honours time_limit_s and returns TIMEOUT + partial schedule."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

from synaps.model import ScheduleProblem, SolverStatus


def build_medium_problem(*, n_ops: int = 300) -> ScheduleProblem:
    """Build a deterministic medium-sized scheduling problem for testing."""
    from benchmark.generate_instances import (
        GenerationSpec,
        generate_problem,
    )

    spec = GenerationSpec(
        n_jobs=n_ops // 5,
        n_machines=20,
        operations_per_job=(3, 5),
        state_count=6,
        flexibility=0.50,
        sdst_density=0.60,
        sdst_range=(6, 18),
        proc_time_range=(12, 30),
        due_date_tightness=0.50,
        aux_resource_probability=0.05,
        aux_resource_types=1,
        seed=42,
        preset_name="medium",
    )
    return generate_problem(spec)


def test_greedy_dispatch_returns_timeout_when_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GreedyDispatch must honour time_limit_s and return TIMEOUT + partial."""
    problem = build_medium_problem(n_ops=300)

    # Force-slow find_earliest_feasible_slot to guarantee we exceed the budget.
    import synaps.solvers.greedy_dispatch as gd

    original = gd.find_earliest_feasible_slot

    def slow(*args: object, **kwargs: object) -> object:
        time.sleep(0.01)
        return original(*args, **kwargs)

    monkeypatch.setattr(gd, "find_earliest_feasible_slot", slow)

    result = gd.GreedyDispatch().solve(problem, time_limit_s=0.5)

    assert result.status == SolverStatus.TIMEOUT
    assert result.metadata["partial_schedule"] is True
    assert result.metadata["remaining_ops"] > 0
    assert len(result.assignments) < 300
    assert result.duration_ms >= 400


def test_greedy_dispatch_no_time_limit_behaviour_unchanged() -> None:
    """When time_limit_s is not set, behaviour must be identical to original."""
    from synaps.solvers.greedy_dispatch import GreedyDispatch

    problem = build_medium_problem(n_ops=300)

    result = GreedyDispatch().solve(problem)

    assert result.status == SolverStatus.FEASIBLE
    assert len(result.assignments) == len(problem.operations)
    assert "partial_schedule" not in (result.metadata or {})
