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


def duration_minutes(base_duration_min: float, speed_factor: float) -> int:
    """Return the canonical integer processing time in minutes.

    ``max(1, ceil(base_duration_min / speed_factor))``. ``ceil`` never reserves
    less than the physical time. A non-positive speed factor is treated as 1.0
    (no speed-up) rather than dividing by zero.
    """
    speed = speed_factor if speed_factor > 0 else 1.0
    return max(1, math.ceil(base_duration_min / speed))
