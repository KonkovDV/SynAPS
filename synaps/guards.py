"""Resource guards for solver execution — timeout and memory limits.

Wraps solver execution with configurable timeout and optional memory checks
so that runaway solves don't block production scheduling loops.

Usage::

    from synaps.guards import ResourceLimits, guarded_solve

    limits = ResourceLimits(timeout_s=60, memory_limit_mb=2048)
    result = guarded_solve(solver, problem, limits=limits, **solve_kwargs)
"""

from __future__ import annotations

import os
import signal
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from synaps.logging import get_logger
from synaps.model import ScheduleResult, SolverErrorCategory, SolverStatus

if TYPE_CHECKING:
    from synaps.model import ScheduleProblem
    from synaps.solvers import BaseSolver

_log = get_logger("synaps.guards")


class SolverTimeoutError(RuntimeError):
    """Raised when a solver exceeds its allotted wall-clock time."""


class SolverMemoryError(RuntimeError):
    """Raised when the process approaches the memory limit before solving."""


@dataclass(frozen=True)
class ResourceLimits:
    """Configurable resource bounds for a single solver invocation.

    Attributes:
        timeout_s: Maximum wall-clock seconds for the solve call.
            ``None`` means no timeout (solver's own ``time_limit_s`` applies).
        memory_limit_mb: Optional memory ceiling in megabytes.
            If the process RSS already exceeds this before solving, the call
            is rejected immediately.
        fail_open: If ``True`` (default), guard failures (e.g., platform
            doesn't support RSS check) are logged but don't block the solve.
    """

    timeout_s: int | None = None
    memory_limit_mb: int | None = None
    fail_open: bool = True


def _get_rss_mb() -> int | None:
    """Return current process RSS in MB, or ``None`` if unavailable."""
    try:
        if os.name == "nt":
            import ctypes
            import ctypes.wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.wintypes.DWORD),
                    ("PageFaultCount", ctypes.wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            handle = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
            if ctypes.windll.psapi.GetProcessMemoryInfo(  # type: ignore[attr-defined]
                handle, ctypes.byref(pmc), pmc.cb
            ):
                return pmc.WorkingSetSize // (1024 * 1024)
            return None
        else:
            import resource as _resource

            rusage = _resource.getrusage(_resource.RUSAGE_SELF)
            # On Linux maxrss is in KB; on macOS it's in bytes.
            maxrss_kb = rusage.ru_maxrss
            if maxrss_kb > 1_000_000:
                return maxrss_kb // (1024 * 1024)
            return maxrss_kb // 1024
    except Exception:
        return None


def _check_memory_limit(limits: ResourceLimits) -> None:
    """Raise :class:`SolverMemoryError` if RSS exceeds the configured limit."""
    if limits.memory_limit_mb is None:
        return
    rss_mb = _get_rss_mb()
    if rss_mb is None:
        if limits.fail_open:
            _log.warning("memory_check_unavailable", platform=os.name)
            return
        raise SolverMemoryError("Cannot determine process RSS on this platform")
    if rss_mb > limits.memory_limit_mb:
        raise SolverMemoryError(
            f"Process RSS ({rss_mb} MB) exceeds limit ({limits.memory_limit_mb} MB)"
        )


def _solve_with_timeout(
    solver: BaseSolver,
    problem: ScheduleProblem,
    timeout_s: int,
    **kwargs: Any,
) -> ScheduleResult:
    """Run ``solver.solve()`` with a wall-clock timeout via a daemon thread."""
    result_box: list[ScheduleResult | BaseException] = []

    def _target() -> None:
        try:
            result_box.append(solver.solve(problem, **kwargs))
        except BaseException as exc:
            result_box.append(exc)

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=timeout_s)

    if thread.is_alive():
        _log.warning(
            "solve_timeout",
            solver=solver.name,
            timeout_s=timeout_s,
        )
        raise SolverTimeoutError(
            f"Solver {solver.name!r} exceeded {timeout_s}s wall-clock timeout"
        )

    if not result_box:
        raise SolverTimeoutError("Solver thread completed without producing a result")

    outcome = result_box[0]
    if isinstance(outcome, BaseException):
        raise outcome
    return outcome


def guarded_solve(
    solver: BaseSolver,
    problem: ScheduleProblem,
    *,
    limits: ResourceLimits | None = None,
    **solve_kwargs: Any,
) -> ScheduleResult:
    """Execute ``solver.solve()`` with resource guards.

    If *limits* is ``None``, the solver runs without additional guards
    (equivalent to calling ``solver.solve()`` directly).

    Returns a :class:`ScheduleResult`. If a timeout or memory limit is hit,
    raises :class:`SolverTimeoutError` or :class:`SolverMemoryError`.  The
    caller can catch these and produce a result with an appropriate
    :class:`SolverErrorCategory`.
    """
    if limits is None:
        return solver.solve(problem, **solve_kwargs)

    _check_memory_limit(limits)

    if limits.timeout_s is not None:
        return _solve_with_timeout(solver, problem, limits.timeout_s, **solve_kwargs)

    return solver.solve(problem, **solve_kwargs)


def timeout_to_error_result(
    solver_name: str,
    error: SolverTimeoutError,
) -> ScheduleResult:
    """Build a :class:`ScheduleResult` for a timeout failure."""
    return ScheduleResult(
        solver_name=solver_name,
        status=SolverStatus.TIMEOUT,
        error_category=SolverErrorCategory.TIMEOUT_NO_SOLUTION,
        metadata={"guard_error": str(error)},
    )


__all__ = [
    "ResourceLimits",
    "SolverMemoryError",
    "SolverTimeoutError",
    "guarded_solve",
    "timeout_to_error_result",
]
