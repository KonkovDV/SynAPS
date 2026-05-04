"""Unit tests for the R7 RHC `_admission` pure kernels.

Locks in algorithmic invariants of the four admission helpers extracted
from `synaps/solvers/rhc/_solver.py` so the rest of the Wave 4 R7
decomposition can proceed without breaking the candidate-frontier contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from synaps.solvers.rhc._admission import (
    advance_admission_frontier,
    advance_due_frontier,
    compute_precedence_closed_set,
    count_admitted_candidates,
)


@dataclass
class _OpStub:
    """Minimal Operation-like stub for kernel testing."""
    id: UUID
    order_id: UUID
    predecessor_op_id: UUID | None = None


def _new_id() -> UUID:
    return uuid4()


class TestAdvanceAdmissionFrontier:
    def test_no_advance_when_all_offsets_at_or_after_boundary(self) -> None:
        op_a = _OpStub(id=_new_id(), order_id=_new_id())
        op_b = _OpStub(id=_new_id(), order_id=_new_id())
        offsets = {op_a.id: 100.0, op_b.id: 150.0}
        new_ids, cursor = advance_admission_frontier(
            cursor=0,
            ops_sorted_by_admission=[op_a, op_b],
            op_admission_offset_by_id=offsets,
            op_earliest={},
            window_boundary=50.0,
        )
        assert new_ids == []
        assert cursor == 0

    def test_advances_through_admitted_ops_only(self) -> None:
        op_a = _OpStub(id=_new_id(), order_id=_new_id())
        op_b = _OpStub(id=_new_id(), order_id=_new_id())
        op_c = _OpStub(id=_new_id(), order_id=_new_id())
        offsets = {op_a.id: 10.0, op_b.id: 20.0, op_c.id: 100.0}
        new_ids, cursor = advance_admission_frontier(
            cursor=0,
            ops_sorted_by_admission=[op_a, op_b, op_c],
            op_admission_offset_by_id=offsets,
            op_earliest={},
            window_boundary=50.0,
        )
        assert new_ids == [op_a.id, op_b.id]
        assert cursor == 2

    def test_falls_back_to_op_earliest_when_admission_offset_missing(self) -> None:
        op = _OpStub(id=_new_id(), order_id=_new_id())
        new_ids, cursor = advance_admission_frontier(
            cursor=0,
            ops_sorted_by_admission=[op],
            op_admission_offset_by_id={},
            op_earliest={op.id: 5.0},
            window_boundary=10.0,
        )
        assert new_ids == [op.id]
        assert cursor == 1

    def test_resumes_from_existing_cursor_position(self) -> None:
        ops = [_OpStub(id=_new_id(), order_id=_new_id()) for _ in range(3)]
        offsets = {ops[0].id: 0.0, ops[1].id: 50.0, ops[2].id: 200.0}
        new_ids, cursor = advance_admission_frontier(
            cursor=1,
            ops_sorted_by_admission=ops,
            op_admission_offset_by_id=offsets,
            op_earliest={},
            window_boundary=100.0,
        )
        assert new_ids == [ops[1].id]
        assert cursor == 2


class TestAdvanceDueFrontier:
    def test_uses_horizon_minutes_as_default_due(self) -> None:
        op = _OpStub(id=_new_id(), order_id=_new_id())
        new_ids, cursor = advance_due_frontier(
            cursor=0,
            ops_sorted_by_due=[op],
            order_due_offsets={},
            horizon_minutes=999.0,
            window_boundary=100.0,
        )
        # Due falls back to horizon_minutes (999) >= boundary (100), so no advance.
        assert new_ids == []
        assert cursor == 0

    def test_advances_when_due_below_boundary(self) -> None:
        op = _OpStub(id=_new_id(), order_id=_new_id())
        new_ids, cursor = advance_due_frontier(
            cursor=0,
            ops_sorted_by_due=[op],
            order_due_offsets={op.order_id: 50.0},
            horizon_minutes=999.0,
            window_boundary=100.0,
        )
        assert new_ids == [op.id]
        assert cursor == 1


class TestComputePrecedenceClosedSet:
    def test_no_predecessor_keeps_all_candidates(self) -> None:
        op_a = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=None)
        op_b = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=None)
        ops_by_id = {op_a.id: op_a, op_b.id: op_b}
        closed = compute_precedence_closed_set(
            {op_a.id, op_b.id},
            ops_by_id=ops_by_id,
            resolved_predecessor_ids=set(),
        )
        assert closed == {op_a.id, op_b.id}

    def test_drops_op_with_unresolved_predecessor(self) -> None:
        pred = _new_id()  # not in candidate set, not resolved
        op = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=pred)
        closed = compute_precedence_closed_set(
            {op.id},
            ops_by_id={op.id: op},
            resolved_predecessor_ids=set(),
        )
        assert closed == set()

    def test_keeps_op_when_predecessor_already_resolved(self) -> None:
        pred = _new_id()
        op = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=pred)
        closed = compute_precedence_closed_set(
            {op.id},
            ops_by_id={op.id: op},
            resolved_predecessor_ids={pred},
        )
        assert closed == {op.id}

    def test_keeps_op_when_predecessor_in_same_closure(self) -> None:
        op_a = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=None)
        op_b = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=op_a.id)
        closed = compute_precedence_closed_set(
            {op_a.id, op_b.id},
            ops_by_id={op_a.id: op_a, op_b.id: op_b},
            resolved_predecessor_ids=set(),
        )
        assert closed == {op_a.id, op_b.id}

    def test_cascades_drop_through_chain(self) -> None:
        # A unresolved -> B depends on A -> C depends on B; only D has resolved pred.
        a = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=_new_id())
        b = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=a.id)
        c = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=b.id)
        d = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=None)
        ops_by_id = {a.id: a, b.id: b, c.id: c, d.id: d}
        closed = compute_precedence_closed_set(
            {a.id, b.id, c.id, d.id},
            ops_by_id=ops_by_id,
            resolved_predecessor_ids=set(),
        )
        # A drops because its pred is unresolved & not in set; cascades to B then C.
        assert closed == {d.id}

    def test_input_set_not_mutated(self) -> None:
        op = _OpStub(id=_new_id(), order_id=_new_id(), predecessor_op_id=_new_id())
        candidates = {op.id}
        compute_precedence_closed_set(
            candidates,
            ops_by_id={op.id: op},
            resolved_predecessor_ids=set(),
        )
        assert candidates == {op.id}


class TestCountAdmittedCandidates:
    def test_returns_admitted_count_when_some_pass(self) -> None:
        a, b, c = _new_id(), _new_id(), _new_id()
        offsets = {a: 10.0, b: 20.0, c: 200.0}
        n = count_admitted_candidates(
            {a, b, c},
            op_admission_offset_by_id=offsets,
            op_earliest={},
            window_boundary=50.0,
        )
        assert n == 2

    def test_falls_back_to_raw_count_when_none_admitted(self) -> None:
        a, b = _new_id(), _new_id()
        offsets = {a: 200.0, b: 300.0}
        n = count_admitted_candidates(
            {a, b},
            op_admission_offset_by_id=offsets,
            op_earliest={},
            window_boundary=50.0,
        )
        assert n == 2  # raw count, not zero

    def test_uses_op_earliest_when_admission_offset_missing(self) -> None:
        a = _new_id()
        n = count_admitted_candidates(
            {a},
            op_admission_offset_by_id={},
            op_earliest={a: 5.0},
            window_boundary=10.0,
        )
        assert n == 1

    def test_empty_candidates_returns_zero(self) -> None:
        n = count_admitted_candidates(
            set(),
            op_admission_offset_by_id={},
            op_earliest={},
            window_boundary=50.0,
        )
        assert n == 0
