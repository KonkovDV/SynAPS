"""Tests for R11 cross-window variable fixing (L-RHO)."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from synaps.model import Assignment
from synaps.solvers.rhc._window import detect_cross_window_stable_ops


def _make_assignment(op_id: object, wc_id: object, start_offset_min: float) -> Assignment:
    base = datetime(2024, 1, 1, 0, 0)
    return Assignment(
        operation_id=op_id,  # type: ignore[arg-type]
        work_center_id=wc_id,  # type: ignore[arg-type]
        start_time=base + timedelta(minutes=start_offset_min),
        end_time=base + timedelta(minutes=start_offset_min + 30),
    )


class TestDetectCrossWindowStableOps:
    def test_empty_both_returns_empty(self) -> None:
        assert (
            detect_cross_window_stable_ops(prev_committed_by_op={}, curr_committed_by_op={})
            == set()
        )

    def test_disjoint_sets_returns_empty(self) -> None:
        a, b = uuid4(), uuid4()
        prev = {a: _make_assignment(a, uuid4(), 10.0)}
        curr = {b: _make_assignment(b, uuid4(), 10.0)}
        assert (
            detect_cross_window_stable_ops(prev_committed_by_op=prev, curr_committed_by_op=curr)
            == set()
        )

    def test_same_signature_is_stable(self) -> None:
        a = uuid4()
        wc = uuid4()
        prev = {a: _make_assignment(a, wc, 10.0)}
        curr = {a: _make_assignment(a, wc, 10.0)}
        assert detect_cross_window_stable_ops(
            prev_committed_by_op=prev, curr_committed_by_op=curr
        ) == {a}

    def test_different_wc_not_stable(self) -> None:
        a = uuid4()
        prev = {a: _make_assignment(a, uuid4(), 10.0)}
        curr = {a: _make_assignment(a, uuid4(), 10.0)}
        assert (
            detect_cross_window_stable_ops(prev_committed_by_op=prev, curr_committed_by_op=curr)
            == set()
        )

    def test_different_offset_not_stable(self) -> None:
        a = uuid4()
        wc = uuid4()
        prev = {a: _make_assignment(a, wc, 10.0)}
        curr = {a: _make_assignment(a, wc, 15.0)}
        assert (
            detect_cross_window_stable_ops(prev_committed_by_op=prev, curr_committed_by_op=curr)
            == set()
        )

    def test_tolerance_boundary(self) -> None:
        a = uuid4()
        wc = uuid4()
        prev = {a: _make_assignment(a, wc, 10.0)}
        curr = {a: _make_assignment(a, wc, 11.0)}
        assert detect_cross_window_stable_ops(
            prev_committed_by_op=prev,
            curr_committed_by_op=curr,
            tolerance_minutes=1.0,
        ) == {a}

    def test_mixed_set(self) -> None:
        a, b, c = uuid4(), uuid4(), uuid4()
        wc = uuid4()
        prev = {
            a: _make_assignment(a, wc, 10.0),
            b: _make_assignment(b, wc, 20.0),
        }
        curr = {
            a: _make_assignment(a, wc, 10.0),
            c: _make_assignment(c, wc, 30.0),
        }
        assert detect_cross_window_stable_ops(
            prev_committed_by_op=prev, curr_committed_by_op=curr
        ) == {a}
