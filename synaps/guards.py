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
import sys
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
            Forwarded to the solver's native ``time_limit_s`` parameter
            so that solver-internal resources (e.g. CP-SAT C++ threads)
            are cleaned up correctly.  ``None`` means no timeout
            (solver's own ``time_limit_s`` applies).
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
    """Return current process RSS in MB, or ``None`` if unavailable.

    Platform detection uses ``sys.platform`` to distinguish macOS (bytes)
    from Linux (KB) for ``ru_maxrss`` units.  The previous heuristic based
    on value magnitude (> 1_000_000) was incorrect — on Linux a 1 GB process
    reports ~1_000_000 KB, which crossed the threshold and was erroneously
    treated as macOS bytes, causing a ~1000× underestimate.
    """
    try:
        if os.name == "nt":
            import ctypes
            import ctypes.wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):  # noqa: N801
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
            windll = getattr(ctypes, "windll", None)
            if windll is None:
                return None
            kernel32 = windll.kernel32
            psapi = windll.psapi
            handle = kernel32.GetCurrentProcess()
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                return int(pmc.WorkingSetSize) // (1024 * 1024)
            return None
        else:
            import resource as _resource

            getrusage = getattr(_resource, "getrusage", None)
            rusage_self = getattr(_resource, "RUSAGE_SELF", None)
            if getrusage is None or rusage_self is None:
                return None
            rusage = getrusage(rusage_self)
            maxrss = int(getattr(rusage, "ru_maxrss", 0))
            # macOS reports ru_maxrss in bytes; Linux reports in KB.
            # Use sys.platform for reliable detection instead of a
            # value-magnitude heuristic (which fails at ~1 GB on Linux).
            if sys.platform == "darwin":
                return maxrss // (1024 * 1024)
            # Linux and other POSIX: KB
            return maxrss // 1024
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

    When ``limits.timeout_s`` is set, it is forwarded to the solver's
    ``time_limit_s`` parameter so that the solver terminates cleanly via
    its own internal mechanisms (e.g. CP-SAT's ``max_time_in_seconds``).
    This avoids leaking C++ solver resources that occur with daemon-thread
    based timeout wrappers.

    Returns a :class:`ScheduleResult`. If a memory limit is hit,
    raises :class:`SolverMemoryError`.  The caller can catch this and
    produce a result with an appropriate :class:`SolverErrorCategory`.
    """
    if limits is None:
        return solver.solve(problem, **solve_kwargs)

    _check_memory_limit(limits)

    if limits.timeout_s is not None:
        # Forward the timeout to the solver's native time_limit_s parameter.
        # This ensures the solver (e.g. CP-SAT C++ backend) terminates
        # cleanly and releases all internal resources.  The previous
        # daemon-thread approach leaked C++ solver instances on timeout.
        effective_kwargs = dict(solve_kwargs)
        existing_limit = effective_kwargs.get("time_limit_s")
        if existing_limit is not None:
            # Use the stricter of the two limits
            effective_kwargs["time_limit_s"] = min(
                int(existing_limit), limits.timeout_s
            )
        else:
            effective_kwargs["time_limit_s"] = limits.timeout_s

        _log.info(
            "guarded_solve_timeout_forwarded",
            solver=solver.name,
            timeout_s=limits.timeout_s,
            effective_time_limit_s=effective_kwargs["time_limit_s"],
        )
        return solver.solve(problem, **effective_kwargs)

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
