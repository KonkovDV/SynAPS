"""Pure warm-start filtering helper for the RHC solver.

This module provides a data structure and filter function for selecting
which warm-start assignment candidates should be passed to the inner
solver for the next RHC window.  Candidates come from three sources:

* External warm-start assignments supplied by the caller.
* Tail assignments from the previous window's committed region.
* Rewound assignments from bounded backtracking.

The filter rejects candidates that are incompatible with the next
window's constraints and records per-reason rejection telemetry for
inclusion in per-window RHC metadata.

Decomposed from `synaps/solvers/rhc/_solver.py` as part of the C1
warm-start formalization (see tasks.md Stage C / Task 9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from synaps.model import Assignment

__all__ = ["WarmStartSelection", "filter_warm_start_assignments"]


@dataclass(frozen=True)
class WarmStartSelection:
    """Result of filtering warm-start assignment candidates.

    Contains the accepted assignments plus rejection telemetry for
    per-window RHC metadata.
    """

    assignments: list[Assignment]
    supplied_count: int
    accepted_count: int
    rejected_count: int
    rejected_reason_counts: dict[str, int] = field(default_factory=dict)


def filter_warm_start_assignments(
    candidates: list[Assignment],
    *,
    active_window_op_ids: set[UUID],
    frozen_committed_op_ids: set[UUID],
    frozen_boundary_assignments: list[Assignment],
) -> WarmStartSelection:
    """Filter warm-start candidates against the next window's constraints.

    Rejection reasons (checked in priority order):
    - "not_in_active_window": operation not in the next window's active set
    - "frozen_committed": operation is already frozen/committed
    - "boundary_conflict": assignment conflicts with a frozen boundary assignment

    Returns a WarmStartSelection with accepted assignments and rejection telemetry.
    """
    if not candidates:
        return WarmStartSelection(
            assignments=[],
            supplied_count=0,
            accepted_count=0,
            rejected_count=0,
            rejected_reason_counts={},
        )

    # Pre-build boundary lookup: {work_center_id -> [Assignment]} for O(N+M) conflict checks
    boundary_by_wc: dict[UUID, list[Assignment]] = {}
    for ba in frozen_boundary_assignments:
        boundary_by_wc.setdefault(ba.work_center_id, []).append(ba)

    accepted: list[Assignment] = []
    rejected_reason_counts: dict[str, int] = {}

    for candidate in candidates:
        # Priority 1: not in active window
        if candidate.operation_id not in active_window_op_ids:
            rejected_reason_counts["not_in_active_window"] = (
                rejected_reason_counts.get("not_in_active_window", 0) + 1
            )
            continue

        # Priority 2: frozen committed
        if candidate.operation_id in frozen_committed_op_ids:
            rejected_reason_counts["frozen_committed"] = (
                rejected_reason_counts.get("frozen_committed", 0) + 1
            )
            continue

        # Priority 3: boundary conflict (same work center + overlapping time)
        boundary_conflict = False
        wc_boundaries = boundary_by_wc.get(candidate.work_center_id)
        if wc_boundaries:
            for ba in wc_boundaries:
                if candidate.start_time < ba.end_time and ba.start_time < candidate.end_time:
                    boundary_conflict = True
                    break

        if boundary_conflict:
            rejected_reason_counts["boundary_conflict"] = (
                rejected_reason_counts.get("boundary_conflict", 0) + 1
            )
            continue

        accepted.append(candidate)

    supplied_count = len(candidates)
    accepted_count = len(accepted)
    rejected_count = supplied_count - accepted_count

    return WarmStartSelection(
        assignments=accepted,
        supplied_count=supplied_count,
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        rejected_reason_counts=rejected_reason_counts,
    )
