"""Night-analog leftovers must insert into the 8 h window, not append after daytime."""

from __future__ import annotations

from benchmark.study_deadzone_5k import apply_consecutive_night_windows
from synaps.solvers.greedy_dispatch import GreedyDispatch
from tests.conftest import make_simple_problem


def test_greed_closes_tiny_night_stamped_instance() -> None:
    problem = apply_consecutive_night_windows(make_simple_problem(n_orders=3, ops_per_order=2))
    assert all(
        operation.earliest_start is not None and operation.latest_finish is not None
        for operation in problem.operations
    )
    result = GreedyDispatch().solve(problem, time_limit_s=30, random_seed=1)
    assert len(result.assignments) == len(problem.operations)
