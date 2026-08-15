"""Canonical operation-duration time grain (Red Team audit, tags P0-4).

Historically the processing time was computed with divergent formulas across
call sites: CP-SAT and LBBD used ``max(1, round(base/speed))`` while the
dispatch layer used the raw ``base/speed``, so the same operation was 3.0
minutes for CP-SAT and 3.333 for GREEDY. This module is the single source of
truth for that conversion.

The canonical grain is ``max(1, ceil(base_duration_min / speed_factor))`` —
integer minutes, matching the CP-SAT/LBBD integer model. **ceil, not round:**
rounding DOWN (``round(3.333) = 3``) reserves less than the physical processing
time, yielding a schedule that is not physically executable and a lower bound
that is too optimistic (final brief, P0-4). An operation always takes at least
one minute.

EST windows (order ``release_date``, operation ``earliest_start``) use the same
minute grid: :func:`ceil_datetime_to_minute` at ingest so the published model,
CP-SAT, greedy, and the checker share one lower bound (C7 / F8). Due dates
and ``latest_finish`` are not ceiled (LFT must floor).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any


def duration_minutes(base_duration_min: float, speed_factor: float) -> int:
    """Return the canonical integer processing time in minutes.

    ``max(1, ceil(base_duration_min / speed_factor))``. ``ceil`` never reserves
    less than the physical time. A non-positive speed factor is treated as 1.0
    (no speed-up) rather than dividing by zero.
    """
    speed = speed_factor if speed_factor > 0 else 1.0
    return max(1, math.ceil(base_duration_min / speed))


def physical_processing_minutes(base_duration_min: float, speed_factor: float) -> float:
    """Return the exact real-valued processing time ``base / speed`` (minutes).

    The FEASIBILITY floor (audit v4, F2): a schedule span shorter than this is
    physically impossible. Distinct from :func:`duration_minutes` — the integer
    RESERVATION grain (P0-4): solvers reserve the grain, the FeasibilityChecker
    certifies against this floor. A non-positive speed factor is treated as 1.0
    (no speed-up), matching :func:`duration_minutes`.
    """
    speed = speed_factor if speed_factor > 0 else 1.0
    return base_duration_min / speed


def duration_minutes_for(operation: Any, work_center: Any) -> int:
    """Integer reservation grain for ``(operation, work_center)`` (T-30 / p_{o,m}).

    Prefer ``operation.machine_duration_overrides[work_center.id]`` when present
    (already grain-aligned integer minutes). Otherwise fall back to
    :func:`duration_minutes` on ``base_duration_min`` / ``speed_factor``.
    """
    overrides = getattr(operation, "machine_duration_overrides", None) or {}
    wc_id = getattr(work_center, "id", None)
    if wc_id is not None and wc_id in overrides:
        return max(1, int(overrides[wc_id]))
    return duration_minutes(
        float(getattr(operation, "base_duration_min", 0)),
        float(getattr(work_center, "speed_factor", 1.0)),
    )


def physical_processing_minutes_for(operation: Any, work_center: Any) -> float:
    """Physical processing floor for ``(operation, work_center)`` (T-30 / F2).

    Override values are treated as exact integer minutes (already grain-aligned).
    """
    overrides = getattr(operation, "machine_duration_overrides", None) or {}
    wc_id = getattr(work_center, "id", None)
    if wc_id is not None and wc_id in overrides:
        return float(overrides[wc_id])
    return physical_processing_minutes(
        float(getattr(operation, "base_duration_min", 0)),
        float(getattr(work_center, "speed_factor", 1.0)),
    )


def ceil_datetime_to_minute(value: datetime, origin: datetime) -> datetime:
    """First minute-grid instant that is not before *value* (Baptiste EST ceil).

    Release / earliest_start are lower bounds: rounding down admits a start
    up to 59.999s early on the integer-minute CP-SAT grid (F8). Exact minute
    offsets are unchanged. Instants at or before *origin* stay put; solvers
    already clamp negative offsets to 0. Due dates and latest_finish are
    not ceiled here (LFT must floor; C7 does not retarget tardiness).
    """
    seconds = (value - origin).total_seconds()
    if seconds <= 0:
        return value
    minutes = math.ceil((seconds / 60.0) - 1e-12)
    return origin + timedelta(minutes=int(minutes))


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _copy_record(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        return dict(item)
    dump = getattr(item, "model_dump", None)
    if not callable(dump):
        return None
    dumped = dump(mode="python")
    return dict(dumped) if isinstance(dumped, dict) else None


def snap_schedule_windows_to_minute_grain(data: dict[str, Any]) -> dict[str, Any]:
    """Ceil order.release_date and operation.earliest_start onto the minute grid.

    Called from ScheduleProblem ingest so the published model, CP-SAT, greedy,
    and the checker share one EST. Does not touch due_date or latest_finish.
    """
    origin = _coerce_datetime(data.get("planning_horizon_start"))
    if origin is None:
        return data

    def _snap_field(record: dict[str, Any], field: str) -> bool:
        raw = _coerce_datetime(record.get(field))
        if raw is None:
            return False
        snapped = ceil_datetime_to_minute(raw, origin)
        if snapped == raw:
            return False
        record[field] = snapped
        return True

    changed = False
    out = dict(data)
    raw_orders = data.get("orders")
    if isinstance(raw_orders, list):
        orders: list[Any] = []
        orders_changed = False
        for item in raw_orders:
            record = _copy_record(item)
            if record is None:
                orders.append(item)
                continue
            if _snap_field(record, "release_date"):
                orders_changed = True
            orders.append(record)
        if orders_changed:
            out["orders"] = orders
            changed = True
    raw_operations = data.get("operations")
    if isinstance(raw_operations, list):
        operations: list[Any] = []
        ops_changed = False
        for item in raw_operations:
            record = _copy_record(item)
            if record is None:
                operations.append(item)
                continue
            if _snap_field(record, "earliest_start"):
                ops_changed = True
            operations.append(record)
        if ops_changed:
            out["operations"] = operations
            changed = True
    return out if changed else data
