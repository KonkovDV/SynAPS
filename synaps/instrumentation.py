"""Instrumentation hooks for the SynAPS solver portfolio.

Provides a lightweight metrics collection API that records solver execution
events without requiring a specific observability vendor.  Consumers can
register custom collectors (OpenTelemetry, Prometheus, or plain counters)
via :func:`register_collector`.

Default behaviour: metrics are accumulated in an in-process ``MetricsStore``
that the caller can inspect programmatically or dump as JSON.

Usage::

    from synaps.instrumentation import get_metrics_store, record_solve_event

    record_solve_event("CPSAT-30", status="optimal", duration_ms=1234, op_count=120)
    store = get_metrics_store()
    print(store.summary())
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MetricsCollector(Protocol):
    """Protocol for custom metrics backends (OTel, Prometheus, etc.)."""

    def on_solve_event(
        self,
        solver_config: str,
        status: str,
        duration_ms: int,
        op_count: int,
        **extra: Any,
    ) -> None: ...

    def on_routing_event(
        self,
        solver_config: str,
        regime: str,
        reason: str,
        **extra: Any,
    ) -> None: ...

    def on_feasibility_event(
        self,
        feasible: bool,
        violation_count: int,
        violation_kinds: list[str],
        **extra: Any,
    ) -> None: ...


@dataclass
class _SolverStats:
    """Accumulated stats for a single solver configuration."""

    call_count: int = 0
    total_duration_ms: int = 0
    min_duration_ms: int = 0
    max_duration_ms: int = 0
    status_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    total_op_count: int = 0

    def record(self, status: str, duration_ms: int, op_count: int) -> None:
        self.call_count += 1
        self.total_duration_ms += duration_ms
        self.total_op_count += op_count
        if self.call_count == 1:
            self.min_duration_ms = duration_ms
            self.max_duration_ms = duration_ms
        else:
            self.min_duration_ms = min(self.min_duration_ms, duration_ms)
            self.max_duration_ms = max(self.max_duration_ms, duration_ms)
        self.status_counts[status] += 1

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.call_count if self.call_count else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "call_count": self.call_count,
            "total_duration_ms": self.total_duration_ms,
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "min_duration_ms": self.min_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "status_counts": dict(self.status_counts),
            "total_op_count": self.total_op_count,
        }


class MetricsStore:
    """Thread-safe in-process metrics accumulator."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._solver_stats: dict[str, _SolverStats] = defaultdict(_SolverStats)
        self._routing_counts: dict[str, int] = defaultdict(int)
        self._feasibility_counts = {"pass": 0, "fail": 0}
        self._violation_kinds: dict[str, int] = defaultdict(int)
        self._start_time = time.monotonic()

    def record_solve(
        self, solver_config: str, status: str, duration_ms: int, op_count: int
    ) -> None:
        with self._lock:
            self._solver_stats[solver_config].record(status, duration_ms, op_count)

    def record_routing(self, solver_config: str, regime: str) -> None:
        with self._lock:
            key = f"{regime}:{solver_config}"
            self._routing_counts[key] += 1

    def record_feasibility(
        self, feasible: bool, violation_kinds: list[str] | None = None
    ) -> None:
        with self._lock:
            if feasible:
                self._feasibility_counts["pass"] += 1
            else:
                self._feasibility_counts["fail"] += 1
                for kind in violation_kinds or []:
                    self._violation_kinds[kind] += 1

    def summary(self) -> dict[str, Any]:
        with self._lock:
            uptime_s = round(time.monotonic() - self._start_time, 1)
            return {
                "uptime_s": uptime_s,
                "solvers": {k: v.as_dict() for k, v in self._solver_stats.items()},
                "routing_decisions": dict(self._routing_counts),
                "feasibility": dict(self._feasibility_counts),
                "violation_kinds": dict(self._violation_kinds),
            }

    def reset(self) -> None:
        with self._lock:
            self._solver_stats.clear()
            self._routing_counts.clear()
            self._feasibility_counts = {"pass": 0, "fail": 0}
            self._violation_kinds.clear()
            self._start_time = time.monotonic()


# Module-level singleton and collector registry
_store = MetricsStore()
_collectors: list[MetricsCollector] = []
_collectors_lock = threading.Lock()


def get_metrics_store() -> MetricsStore:
    """Return the global in-process metrics store."""
    return _store


def register_collector(collector: MetricsCollector) -> None:
    """Register a custom metrics collector (OTel, Prometheus, etc.)."""
    with _collectors_lock:
        _collectors.append(collector)


def clear_collectors() -> None:
    """Remove all registered collectors."""
    with _collectors_lock:
        _collectors.clear()


def record_solve_event(
    solver_config: str,
    *,
    status: str,
    duration_ms: int,
    op_count: int,
    **extra: Any,
) -> None:
    """Record a solve completion event."""
    _store.record_solve(solver_config, status, duration_ms, op_count)
    with _collectors_lock:
        for collector in _collectors:
            collector.on_solve_event(
                solver_config, status=status, duration_ms=duration_ms,
                op_count=op_count, **extra,
            )


def record_routing_event(
    solver_config: str,
    *,
    regime: str,
    reason: str,
    **extra: Any,
) -> None:
    """Record a solver routing decision."""
    _store.record_routing(solver_config, regime)
    with _collectors_lock:
        for collector in _collectors:
            collector.on_routing_event(
                solver_config, regime=regime, reason=reason, **extra,
            )


def record_feasibility_event(
    *,
    feasible: bool,
    violation_count: int,
    violation_kinds: list[str],
    **extra: Any,
) -> None:
    """Record a feasibility verification event."""
    _store.record_feasibility(feasible, violation_kinds)
    with _collectors_lock:
        for collector in _collectors:
            collector.on_feasibility_event(
                feasible=feasible, violation_count=violation_count,
                violation_kinds=violation_kinds, **extra,
            )


__all__ = [
    "MetricsCollector",
    "MetricsStore",
    "clear_collectors",
    "get_metrics_store",
    "record_feasibility_event",
    "record_routing_event",
    "record_solve_event",
    "register_collector",
]
