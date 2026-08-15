"""Operation-level time windows (Wave 15 / G11).

Order.release_date is the material floor for the whole job. Per-operation
``earliest_start`` / ``latest_finish`` are optional hard windows (outage
clearances). Ignoring them would let a chain share one Order interval and
mis-place later ops.
"""

from __future__ import annotations

import math
from typing import Any


def operation_earliest_offset_minutes(
    operation: Any,
    order: Any | None,
    horizon_start: Any,
) -> float:
    """Minutes from horizon start; max(order.release, op.earliest_start, 0).

    The return is ceiled onto the integer-minute grid (C7 / F8): a 90s release
    is offset 2, matching CP-SAT. Ingest also snaps the published datetimes.
    """

    floor = 0.0
    release = getattr(order, "release_date", None) if order is not None else None
    if release is not None:
        floor = max(floor, (release - horizon_start).total_seconds() / 60.0)
    earliest = getattr(operation, "earliest_start", None)
    if earliest is not None:
        floor = max(floor, (earliest - horizon_start).total_seconds() / 60.0)
    floor = max(0.0, floor)
    if floor <= 0.0:
        return 0.0
    return float(math.ceil(floor - 1e-12))


def operation_latest_finish_offset_minutes(operation: Any, horizon_start: Any) -> float | None:
    """Minutes from horizon start; floored onto the integer-minute grid (C7-R1).

    A 90s latest_finish is offset 1, matching CP-SAT. Ingest also snaps the
    published datetime. ``None`` means no per-op LFT.
    """
    latest = getattr(operation, "latest_finish", None)
    if latest is None:
        return None
    offset = (latest - horizon_start).total_seconds() / 60.0
    return float(math.floor(offset + 1e-12))
