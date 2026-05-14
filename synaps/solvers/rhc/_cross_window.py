"""Cross-window quality telemetry for the RHC solver.

Records per-window quality signals (machine utilization, setup costs,
tardiness contribution) in a bounded buffer. When the cross-window
learning feature flag is enabled, buffer contents are passed as hints
to the inner ALNS solver for subsequent windows.

Decomposed from the RHC solver as part of the C3 cross-window quality
telemetry feature (see tasks.md Stage C / Task 3a).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime

    from synaps.model import Assignment

__all__ = ["WindowQualitySummary", "compute_window_quality_summary"]

#: Maximum number of window summaries retained in the cross-window buffer.
QUALITY_BUFFER_MAXLEN = 5


@dataclass(frozen=True)
class WindowQualitySummary:
    """Quality telemetry snapshot for a single RHC window solve.

    Captures per-machine utilization, setup cost distribution, tardiness
    contribution, and operation count. Stored in a bounded deque and
    optionally forwarded to the inner ALNS solver as cross-window hints.
    """

    window_index: int
    per_machine_utilization: dict[Any, float]
    setup_cost_by_machine: dict[Any, float]
    tardiness_contribution: float
    operation_count: int


def compute_window_quality_summary(
    *,
    window_index: int,
    assignments: list[Assignment],
    window_span_minutes: float,
    order_due_offsets: dict[Any, float],
    ops_by_id: dict[Any, Any],
    horizon_start: datetime,
) -> WindowQualitySummary:
    """Compute a quality summary from the assignments produced by a window solve.

    Parameters
    ----------
    window_index:
        Zero-based index of the current RHC window.
    assignments:
        Assignments produced (or committed) by the inner solver for this window.
    window_span_minutes:
        Total span of the window in minutes (active + overlap).
    order_due_offsets:
        Mapping of order_id → due-date offset in minutes from horizon start.
    ops_by_id:
        Mapping of operation_id → Operation for operations in this window.
    horizon_start:
        Planning horizon start datetime (used to convert assignment times to offsets).

    Returns
    -------
    WindowQualitySummary with computed metrics.
    """
    if not assignments or window_span_minutes <= 0:
        return WindowQualitySummary(
            window_index=window_index,
            per_machine_utilization={},
            setup_cost_by_machine={},
            tardiness_contribution=0.0,
            operation_count=0,
        )

    # Per-machine utilization: sum of assignment durations / window span.
    machine_duration: dict[Any, float] = {}
    # Per-machine setup cost: sum of setup_minutes per machine.
    machine_setup: dict[Any, float] = {}
    # Track latest end-time per order for tardiness computation.
    order_latest_end: dict[Any, float] = {}

    for assignment in assignments:
        wc_id = assignment.work_center_id
        duration_minutes = (assignment.end_time - assignment.start_time).total_seconds() / 60.0
        machine_duration[wc_id] = machine_duration.get(wc_id, 0.0) + duration_minutes
        machine_setup[wc_id] = machine_setup.get(wc_id, 0.0) + float(assignment.setup_minutes)

        # Track order completion for tardiness.
        op = ops_by_id.get(assignment.operation_id)
        if op is not None:
            end_offset = (assignment.end_time - horizon_start).total_seconds() / 60.0
            order_id = op.order_id
            if end_offset > order_latest_end.get(order_id, 0.0):
                order_latest_end[order_id] = end_offset

    # Utilization: duration on machine / window span.
    per_machine_utilization = {
        wc_id: min(duration / window_span_minutes, 1.0)
        for wc_id, duration in machine_duration.items()
    }

    # Tardiness contribution: sum of max(0, completion - due) for orders
    # whose last operation was in this window.
    tardiness_contribution = 0.0
    for order_id, latest_end in order_latest_end.items():
        due_offset = order_due_offsets.get(order_id)
        if due_offset is not None:
            tardiness = max(0.0, latest_end - due_offset)
            tardiness_contribution += tardiness

    return WindowQualitySummary(
        window_index=window_index,
        per_machine_utilization=per_machine_utilization,
        setup_cost_by_machine=machine_setup,
        tardiness_contribution=tardiness_contribution,
        operation_count=len(assignments),
    )
