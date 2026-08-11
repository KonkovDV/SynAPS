"""F1 (audit v4): the parallel-machine capacity sweep charges PHYSICAL
occupancy — the right-justified setup window plus the processing span — not
just the processing interval.

Setup physically occupies the machine (the checker's own aux-resource sweep
already accounts for the same window, so the machine sweep must obey the same
physics). Note on reachability: when lane inference SUCCEEDS, per-lane windows
are disjoint by construction (start >= prev_end + setup), so concurrency never
exceeds the lane count — the physical sweep is then defense-in-depth. Its bite
is the direct semantics: with setup windows supplied, three overlapping
physical windows on a 2-lane machine must trip MACHINE_CAPACITY_VIOLATION even
when the processing spans alone would not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import Assignment
from synaps.solvers.feasibility_checker import FeasibilityChecker, FeasibilityViolation

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _op_at(op_idx: int, start: int, end: int) -> Assignment:
    from uuid import uuid5, NAMESPACE_DNS

    return Assignment(
        operation_id=uuid5(NAMESPACE_DNS, f"f1-op-{op_idx}"),
        work_center_id=uuid5(NAMESPACE_DNS, "f1-wc"),
        start_time=_H0 + timedelta(minutes=start),
        end_time=_H0 + timedelta(minutes=end),
    )


def _sweep(setup_windows: dict[object, object] | None) -> list[str]:
    """Run the capacity sweep alone with an explicit setup-window map."""
    checker = FeasibilityChecker()
    violations: list[FeasibilityViolation] = []
    assignments = [
        _op_at(1, 0, 10),   # processing [0,10)
        _op_at(2, 0, 10),   # processing [0,10)
        _op_at(3, 10, 20),  # processing [10,20); setup window may start at 0
    ]
    windows: dict[object, object] = {}
    for a in assignments:
        windows[a.operation_id] = a.start_time
    if setup_windows:
        windows.update(setup_windows)
    checker._check_parallel_capacity(
        wc_id=assignments[0].work_center_id,
        machine_assignments=assignments,
        max_parallel=2,
        violations=violations,
        exhaustive=True,
        setup_window_start_by_op=windows,
    )
    return [v.kind for v in violations]


def test_setup_occupancy_trips_capacity() -> None:
    """op3's setup occupies [0,10): three physical windows on 2 lanes."""
    op3 = _op_at(3, 10, 20)
    kinds = _sweep({op3.operation_id: _H0})
    assert "MACHINE_CAPACITY_VIOLATION" in kinds


def test_processing_only_windows_stay_clean() -> None:
    """Control: processing spans alone never exceed two concurrent — the
    pre-F1 sweep (which ignored setup) therefore stayed silent here."""
    assert _sweep(None) == []
