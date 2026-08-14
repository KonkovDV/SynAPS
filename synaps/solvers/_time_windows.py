"""Operation-level time windows (Wave 15 / G11).

Order.release_date is the material floor for the whole job. Per-operation
``earliest_start`` / ``latest_finish`` are optional hard windows (outage
clearances). Ignoring them would let a chain share one Order interval and
mis-place later ops.
"""

from __future__ import annotations

from typing import Any


def operation_earliest_offset_minutes(
    operation: Any,
    order: Any | None,
    horizon_start: Any,
) -> float:
    """Minutes from horizon start; max(order.release, op.earliest_start, 0)."""

    floor = 0.0
    release = getattr(order, "release_date", None) if order is not None else None
    if release is not None:
        floor = max(floor, (release - horizon_start).total_seconds() / 60.0)
    earliest = getattr(operation, "earliest_start", None)
    if earliest is not None:
        floor = max(floor, (earliest - horizon_start).total_seconds() / 60.0)
    return max(0.0, floor)


def operation_latest_finish_offset_minutes(operation: Any, horizon_start: Any) -> float | None:
    latest = getattr(operation, "latest_finish", None)
    if latest is None:
        return None
    return (latest - horizon_start).total_seconds() / 60.0
