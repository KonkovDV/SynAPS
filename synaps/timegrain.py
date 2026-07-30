"""Canonical operation-duration time grain (Red Team audit, tag P0-4).

Five call sites computed processing time with divergent formulas: CP-SAT and
LBBD used ``max(1, round(base/speed))`` while the dispatch layer used the raw
``base/speed``, so the same operation was 3.0 minutes for CP-SAT and 3.333 for
GREEDY. This module is the single source of truth for that conversion.

The canonical grain is ``max(1, round(base_duration_min / speed_factor))`` —
integer minutes, matching the CP-SAT/LBBD integer model (an earlier attempt to
switch to ``ceil`` regressed ALNS reanchoring and was reverted; ``round`` keeps
the established solver behavior while unifying the dispatch layer onto it).
An operation always takes at least one minute.
"""

from __future__ import annotations


def duration_minutes(base_duration_min: float, speed_factor: float) -> int:
    """Return the canonical integer processing time in minutes.

    ``max(1, round(base_duration_min / speed_factor))``. A non-positive speed
    factor is treated as 1.0 (no speed-up) rather than dividing by zero.
    """
    speed = speed_factor if speed_factor > 0 else 1.0
    return max(1, round(base_duration_min / speed))
