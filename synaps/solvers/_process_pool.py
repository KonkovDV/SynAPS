"""One subproblem process pool per LBBD solve (audit 2026-10, KI-R3 / T-04).

Both LBBD solvers used to open a ``ProcessPoolExecutor`` per Benders iteration
with the platform default start method. On Linux that is ``fork``, called from
a process that already runs OR-Tools / NumPy threads: Python 3.12 warns that
the child may deadlock, and Python 3.14 switched the Linux default to
``forkserver`` for that reason. The pool is now:

* created lazily on the first parallel dispatch and reused by every later
  iteration of the same solve (no per-iteration process start-up);
* started with ``forkserver`` on POSIX and ``spawn`` on Windows. The fork
  server preloads NOTHING: importing NumPy already starts OpenBLAS threads
  (measured: 1 -> 4 native threads), so a preloading server would itself be a
  multi-threaded process that forks, and the default preload would import the
  caller's ``__main__``. Each worker imports the LBBD module once, on its first
  task, and the pool lives for the whole solve;
* shut down by its owner, cancelling queued work.

Like ``spawn``, a ``forkserver`` worker re-imports the caller's main module, so
a script without an ``if __name__ == "__main__":`` guard (or one read from
stdin) breaks the pool. Instead of failing the solve, :func:`solve_clusters`
then warns once and solves the clusters in-process for the rest of the solve.
"""

from __future__ import annotations

import multiprocessing
import sys
import warnings
from concurrent.futures import Future, ProcessPoolExecutor, as_completed, wait
from concurrent.futures.process import BrokenProcessPool
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable
    from multiprocessing.context import BaseContext


def subproblem_mp_context() -> BaseContext:
    """``forkserver`` where available on POSIX, ``spawn`` otherwise."""
    if sys.platform != "win32" and "forkserver" in multiprocessing.get_all_start_methods():
        context = multiprocessing.get_context("forkserver")
        # Keep the server single-threaded (no NumPy / OpenBLAS in it). Effective
        # only before the fork server starts; later calls are no-ops.
        context.set_forkserver_preload([])
        return context
    return multiprocessing.get_context("spawn")


class SubproblemPool:
    """Lazily created ``ProcessPoolExecutor`` owned by one solve."""

    def __init__(self, max_workers: int) -> None:
        self._max_workers = max(1, int(max_workers))
        self._executor: ProcessPoolExecutor | None = None
        self.broken = False

    def submit(self, fn: Any, /, *args: Any) -> Future[Any]:
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self._max_workers, mp_context=subproblem_mp_context()
            )
        return self._executor.submit(fn, *args)

    def close(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._executor = None

    def __enter__(self) -> SubproblemPool:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def solve_clusters(
    pool: SubproblemPool, fn: Any, jobs: list[tuple[Any, ...]]
) -> tuple[dict[int, dict[str, Any]] | None, bool]:
    """Run ``fn(*job)`` per cluster; ``(results_by_index, False)`` or ``(None, infeasible)``.

    D2: results are keyed by cluster index, so the caller's merge order does not
    depend on completion order. The first failed cluster ends the round: the
    rest is cancelled or awaited (:func:`settle`) and ``infeasible_proven``
    reports whether that cluster was proven INFEASIBLE.
    """
    if pool.broken:
        return _solve_in_process(fn, jobs)
    # Submit inside the try. A BrokenProcessPool raised on a later submit used
    # to escape before any future was settled and skipped the in-process
    # fallback (the dict comprehension never finished).
    futures: dict[Future[Any], int] = {}
    results: dict[int, dict[str, Any]] = {}
    try:
        for index, job in enumerate(jobs):
            futures[pool.submit(fn, *job)] = index
        for future in as_completed(futures):
            result = future.result()
            if result is None or result.get("failed"):
                return None, bool(result.get("infeasible_proven")) if result else False
            results[futures[future]] = result
    except BrokenProcessPool:
        pool.broken = True
        warnings.warn(
            "LBBD subproblem process pool broke (is the calling script missing an "
            '`if __name__ == "__main__":` guard?); solving clusters in-process',
            RuntimeWarning,
            stacklevel=3,
        )
        return _solve_in_process(fn, jobs)
    finally:
        settle(futures)
    return results, False


def _solve_in_process(
    fn: Any, jobs: list[tuple[Any, ...]]
) -> tuple[dict[int, dict[str, Any]] | None, bool]:
    """Sequential fallback with the same contract as :func:`solve_clusters`."""
    results: dict[int, dict[str, Any]] = {}
    for index, job in enumerate(jobs):
        result = fn(*job)
        if result is None or result.get("failed"):
            return None, bool(result.get("infeasible_proven")) if result else False
        results[index] = result
    return results, False


def settle(futures: Iterable[Future[Any]]) -> None:
    """Cancel queued futures and wait for running ones (early-exit cleanup).

    A persistent pool must not carry an abandoned iteration's work into the
    next one; the per-iteration ``with`` used to provide that by waiting.
    """
    pending = list(futures)
    for future in pending:
        future.cancel()
    wait(pending)
