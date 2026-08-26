"""Work-center shift calendar.

Empty ``WorkCenter.calendar`` is 24/7 open — that is not a night shift. A
non-empty calendar is a hard constraint: processing ``[start, end]`` must sit
inside one interval (an operation cannot straddle a closed period). Setup
occupancy before ``start`` is not clipped here (KI-N7 follow-up).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime


def work_centers_have_calendar(work_centers: Sequence[Any]) -> bool:
    """True when any work center publishes a non-empty shift list."""

    return any(getattr(wc, "calendar", None) for wc in work_centers)


def processing_fits_calendar(
    start: datetime,
    end: datetime,
    calendar: Sequence[Any],
) -> bool:
    """True when processing sits in one published interval, or calendar is empty."""

    if not calendar:
        return True
    return any(interval.start <= start and end <= interval.end for interval in calendar)


def delay_start_to_open_shift(
    start: float,
    duration: float,
    calendar: Sequence[Any],
    horizon_start: datetime,
) -> float | None:
    """Earliest start ≥ ``start`` whose processing fits one interval, or None."""

    if not calendar:
        return start
    offsets: list[tuple[float, float]] = []
    for interval in calendar:
        open_m = (interval.start - horizon_start).total_seconds() / 60.0
        close_m = (interval.end - horizon_start).total_seconds() / 60.0
        if close_m > open_m:
            offsets.append((open_m, close_m))
    offsets.sort()
    for open_m, close_m in offsets:
        candidate = max(start, open_m)
        if candidate + duration <= close_m + 1e-9:
            return candidate
    return None
