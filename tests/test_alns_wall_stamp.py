"""K3: ALNS/RHC wall-clock stamp matches the search stop, not a constant True."""

from __future__ import annotations

from synaps.solvers.alns_solver import AlnsSolver, _alns_wall_clock_honesty_meta
from synaps.solvers.rhc import RhcSolver
from tests.conftest import make_simple_problem


def test_alns_wall_stamp_matches_stop_reason() -> None:
    max_iter = _alns_wall_clock_honesty_meta(
        "strict", False, 12, 12, elapsed_s=0.5, time_limit_s=20.0
    )
    assert max_iter["search_stop_reason"] == "max_iterations"
    assert max_iter["wall_clock_path_dependent"] is False
    assert max_iter["determinism_violated"] is False

    wall = _alns_wall_clock_honesty_meta("strict", False, 3, 12, elapsed_s=20.0, time_limit_s=20.0)
    assert wall["search_stop_reason"] == "wall_clock"
    assert wall["wall_clock_path_dependent"] is True
    assert wall["determinism_violated"] is True

    before = _alns_wall_clock_honesty_meta("strict", True, 0, 12, elapsed_s=1.0, time_limit_s=0.5)
    assert before["search_stop_reason"] == "wall_clock_before_search"
    assert before["wall_clock_path_dependent"] is True

    fast = _alns_wall_clock_honesty_meta("fast", False, 3, 12, elapsed_s=20.0, time_limit_s=20.0)
    assert fast["wall_clock_path_dependent"] is True
    assert fast["determinism_violated"] is False

    # K3-RT: D3 remaining_s < 1 stop is a wall cut, not "completed".
    near_wall = _alns_wall_clock_honesty_meta(
        "strict", False, 317, 500, elapsed_s=299.2, time_limit_s=300.0
    )
    assert near_wall["search_stop_reason"] == "wall_clock"
    assert near_wall["wall_clock_path_dependent"] is True

    max_near_wall = _alns_wall_clock_honesty_meta(
        "strict", False, 500, 500, elapsed_s=299.2, time_limit_s=300.0
    )
    assert max_near_wall["search_stop_reason"] == "max_iterations"
    assert max_near_wall["wall_clock_path_dependent"] is False


def test_alns_zero_budget_stamps_wall_cut() -> None:
    """Wall timeout before search is a stamp, not a CI error."""

    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    result = AlnsSolver().solve(
        problem,
        max_iterations=10_000,
        time_limit_s=0.0,
        use_cpsat_repair=False,
        random_seed=1,
        determinism="strict",
    )
    reason = str(result.metadata["search_stop_reason"])
    assert reason.startswith("wall_clock")
    assert result.metadata["wall_clock_path_dependent"] is True
    assert result.metadata["determinism_violated"] is True
    assert result.metadata.get("time_limit_exhausted_before_search") is True
    if not result.assignments:
        assert result.status.value == "error"


def test_rhc_completed_run_is_not_wall_stamped() -> None:
    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    result = RhcSolver().solve(problem, time_limit_s=30, random_seed=1, inner_solver="greedy")
    reason = str(result.metadata["search_stop_reason"])
    assert result.metadata["wall_clock_path_dependent"] is (reason == "wall_clock")
    if reason == "completed":
        assert result.metadata["wall_clock_path_dependent"] is False
        assert result.metadata["determinism_violated"] is False
