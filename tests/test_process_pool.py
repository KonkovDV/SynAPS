"""KI-R3 / T-04: the solve-scoped LBBD subproblem pool (``synaps.solvers._process_pool``)."""

from __future__ import annotations

import os
import sys
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool

import pytest

from synaps.solvers._process_pool import SubproblemPool, solve_clusters, subproblem_mp_context


def _dies_outside_the_parent(parent_pid: int, payload: dict[str, float]) -> dict[str, float]:
    """Kill any worker process; succeed in the process that submitted the job."""
    if os.getpid() != parent_pid:
        os._exit(1)
    return dict(payload)


def test_start_method_is_never_fork_from_a_threaded_parent() -> None:
    method = subproblem_mp_context().get_start_method()
    assert method == ("spawn" if sys.platform == "win32" else "forkserver")


def test_results_are_keyed_by_cluster_index_and_the_pool_is_reused() -> None:
    # ``dict`` copies its argument and pickles under any start method.
    jobs = [({"assignments": [], "makespan": float(index)},) for index in range(5)]
    with SubproblemPool(2) as pool:
        first, infeasible = solve_clusters(pool, dict, jobs)
        executor = pool._executor
        second, _ = solve_clusters(pool, dict, jobs)
        assert pool._executor is executor, "one executor per solve, not per round"
    assert pool._executor is None
    assert infeasible is False
    assert first == second
    assert first is not None
    assert [first[index]["makespan"] for index in sorted(first)] == [0.0, 1.0, 2.0, 3.0, 4.0]


@pytest.mark.parametrize("proven", [True, False])
def test_a_failed_cluster_ends_the_round_with_its_infeasibility_flag(proven: bool) -> None:
    jobs = [({"makespan": 1.0},), ({"failed": True, "infeasible_proven": proven},)]
    with SubproblemPool(2) as pool:
        results, infeasible = solve_clusters(pool, dict, jobs)
        # The pool stays usable for the next Benders iteration.
        again, _ = solve_clusters(pool, dict, jobs[:1])
    assert results is None
    assert infeasible is proven
    assert again == {0: {"makespan": 1.0}}


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc thread count")
def test_the_fork_server_itself_stays_single_threaded() -> None:
    """Workers are forked from the server, so the server must not hold threads.

    A preloading server would import NumPy, whose OpenBLAS pool already makes
    the process multi-threaded; the pool therefore preloads nothing.
    """
    import os
    from multiprocessing import forkserver

    with SubproblemPool(2) as pool:
        results, _ = solve_clusters(pool, dict, [({"x": 1},), ({"x": 2},)])
        server_pid = forkserver._forkserver._forkserver_pid  # type: ignore[attr-defined]
        assert server_pid is not None
        threads = len(os.listdir(f"/proc/{server_pid}/task"))
    assert results == {0: {"x": 1}, 1: {"x": 2}}
    assert threads == 1


def test_broken_pool_during_submit_falls_back_and_settles() -> None:
    """A later submit raising BrokenProcessPool must not leak the earlier futures."""

    class _DiesOnSecondSubmit:
        def __init__(self) -> None:
            self.calls = 0

        def submit(self, fn: object, /, *args: object) -> Future[object]:
            self.calls += 1
            if self.calls > 1:
                raise BrokenProcessPool("submit failed")
            future: Future[object] = Future()
            assert callable(fn)
            future.set_result(fn(*args))
            return future

    pool = SubproblemPool(2)
    pool._executor = _DiesOnSecondSubmit()  # type: ignore[assignment]
    jobs = [({"makespan": 1.0},), ({"makespan": 2.0},)]
    with pytest.warns(RuntimeWarning, match="solving clusters in-process"):
        results, infeasible = solve_clusters(pool, dict, jobs)
    assert pool.broken is True
    assert infeasible is False
    assert results == {0: {"makespan": 1.0}, 1: {"makespan": 2.0}}


def test_a_broken_pool_degrades_to_in_process_solving_with_one_warning() -> None:
    jobs = [(os.getpid(), {"makespan": 1.0}), (os.getpid(), {"makespan": 2.0})]
    with SubproblemPool(2) as pool:
        with pytest.warns(RuntimeWarning, match="solving clusters in-process"):
            results, infeasible = solve_clusters(pool, _dies_outside_the_parent, jobs)
        assert pool.broken
        # Later rounds of the same solve skip the dead pool silently.
        again, _ = solve_clusters(pool, _dies_outside_the_parent, jobs[:1])
    assert infeasible is False
    assert results == {0: {"makespan": 1.0}, 1: {"makespan": 2.0}}
    assert again == {0: {"makespan": 1.0}}
