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
"""

from __future__ import annotations

import math
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
