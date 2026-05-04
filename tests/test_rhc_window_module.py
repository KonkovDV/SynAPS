"""Unit tests for the R7 RHC `_window` pure kernels.

Locks in the algorithmic invariants of the four window helpers extracted
from `synaps/solvers/rhc/_solver.py`. These cover the core scheduling
decisions of one rolling-horizon iteration, so regression coverage here
gates any further structural change to the RHC main loop.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from synaps.model import Assignment
from synaps.solvers.rhc._window import (
    collect_commit_candidates,
    select_backtracking_assignments,
    stabilize_temporal_consistency,
)


HORIZON_START = datetime(2026, 4, 1, 8, 0, 0, tzinfo=timezone.utc)


@dataclass
class _OpStub:
    id: UUID
    order_id: UUID = field(default_factory=uuid4)
    seq_in_order: int = 0
    state_id: UUID = field(default_factory=uuid4)
    predecessor_op_id: UUID | None = None


def _make_assignment(
    op_id: UUID,
    *,
    work_center_id: UUID | None = None,
    start_minutes: float = 0.0,
    end_minutes: float = 10.0,
    setup_minutes: int = 0,
) -> Assignment:
    return Assignment(
        operation_id=op_id,
        work_center_id=work_center_id or uuid4(),
        start_time=HORIZON_START + timedelta(minutes=start_minutes),
        end_time=HORIZON_START + timedelta(minutes=end_minutes),
        setup_minutes=setup_minutes,
        aux_resource_ids=[],
    )


# =============================================================================
# collect_commit_candidates
# =============================================================================


class TestCollectCommitCandidates:
    def test_keeps_assignments_inside_commit_boundary(self) -> None:
        op_a = _OpStub(id=uuid4())
        op_b = _OpStub(id=uuid4())
        a_assignment = _make_assignment(op_a.id, end_minutes=30.0)
        b_assignment = _make_assignment(op_b.id, end_minutes=80.0)
        candidates, clipped = collect_commit_candidates(
            [a_assignment, b_assignment],
            commit_boundary=60.0,
            commit_all=False,
            frozen_ids=set(),
            eligible_ids=None,
            horizon_start=HORIZON_START,
            horizon_minutes=240.0,
            ops_by_id={op_a.id: op_a, op_b.id: op_b},
        )
        assert op_a.id in candidates
        assert op_b.id not in candidates  # ends after commit boundary
        assert clipped == 0

    def test_horizon_clipped_count_reports_overhang(self) -> None:
        op = _OpStub(id=uuid4())
        a = _make_assignment(op.id, end_minutes=300.0)  # past horizon=240
        candidates, clipped = collect_commit_candidates(
            [a],
            commit_boundary=200.0,
            commit_all=False,
            frozen_ids=set(),
            eligible_ids=None,
            horizon_start=HORIZON_START,
            horizon_minutes=240.0,
            ops_by_id={op.id: op},
        )
        assert candidates == {}
        assert clipped == 1

    def test_drops_already_frozen_ops(self) -> None:
        op = _OpStub(id=uuid4())
        a = _make_assignment(op.id, end_minutes=30.0)
        candidates, clipped = collect_commit_candidates(
            [a],
            commit_boundary=60.0,
            commit_all=False,
            frozen_ids={op.id},
            eligible_ids=None,
            horizon_start=HORIZON_START,
            horizon_minutes=240.0,
            ops_by_id={op.id: op},
        )
        assert candidates == {}
        assert clipped == 0

    def test_eligible_ids_restricts_candidates(self) -> None:
        op_a = _OpStub(id=uuid4())
        op_b = _OpStub(id=uuid4())
        a = _make_assignment(op_a.id, end_minutes=30.0)
        b = _make_assignment(op_b.id, end_minutes=30.0)
        candidates, _ = collect_commit_candidates(
            [a, b],
            commit_boundary=60.0,
            commit_all=False,
            frozen_ids=set(),
            eligible_ids={op_a.id},
            horizon_start=HORIZON_START,
            horizon_minutes=240.0,
            ops_by_id={op_a.id: op_a, op_b.id: op_b},
        )
        assert set(candidates.keys()) == {op_a.id}

    def test_commit_all_overrides_boundary(self) -> None:
        op = _OpStub(id=uuid4())
        a = _make_assignment(op.id, end_minutes=200.0)
        candidates, _ = collect_commit_candidates(
            [a],
            commit_boundary=60.0,
            commit_all=True,
            frozen_ids=set(),
            eligible_ids=None,
            horizon_start=HORIZON_START,
            horizon_minutes=240.0,
            ops_by_id={op.id: op},
        )
        assert op.id in candidates

    def test_drops_op_when_predecessor_neither_frozen_nor_in_set(self) -> None:
        pred = _OpStub(id=uuid4())
        succ = _OpStub(id=uuid4(), predecessor_op_id=pred.id)
        succ_assignment = _make_assignment(succ.id, end_minutes=30.0)
        # Predecessor not present and not frozen → succ must be dropped.
        candidates, _ = collect_commit_candidates(
            [succ_assignment],
            commit_boundary=60.0,
            commit_all=False,
            frozen_ids=set(),
            eligible_ids=None,
            horizon_start=HORIZON_START,
            horizon_minutes=240.0,
            ops_by_id={pred.id: pred, succ.id: succ},
        )
        assert candidates == {}

    def test_keeps_op_when_predecessor_already_frozen(self) -> None:
        pred = _OpStub(id=uuid4())
        succ = _OpStub(id=uuid4(), predecessor_op_id=pred.id)
        succ_assignment = _make_assignment(succ.id, end_minutes=30.0)
        candidates, _ = collect_commit_candidates(
            [succ_assignment],
            commit_boundary=60.0,
            commit_all=False,
            frozen_ids={pred.id},
            eligible_ids=None,
            horizon_start=HORIZON_START,
            horizon_minutes=240.0,
            ops_by_id={pred.id: pred, succ.id: succ},
        )
        assert succ.id in candidates


# =============================================================================
# select_backtracking_assignments
# =============================================================================


class TestSelectBacktrackingAssignments:
    def test_disabled_returns_empty(self) -> None:
        op = _OpStub(id=uuid4())
        result = select_backtracking_assignments(
            window_start_offset=100.0,
            backtracking_enabled=False,
            backtracking_tail_minutes=30.0,
            backtracking_max_ops=10,
            committed_assignments=[_make_assignment(op.id, end_minutes=90.0)],
            committed_assignment_by_op={op.id: _make_assignment(op.id, end_minutes=90.0)},
            ops_by_id={op.id: op},
            horizon_start=HORIZON_START,
        )
        assert result == []

    def test_zero_tail_returns_empty(self) -> None:
        op = _OpStub(id=uuid4())
        result = select_backtracking_assignments(
            window_start_offset=100.0,
            backtracking_enabled=True,
            backtracking_tail_minutes=0.0,
            backtracking_max_ops=10,
            committed_assignments=[_make_assignment(op.id)],
            committed_assignment_by_op={op.id: _make_assignment(op.id)},
            ops_by_id={op.id: op},
            horizon_start=HORIZON_START,
        )
        assert result == []

    def test_no_commits_returns_empty(self) -> None:
        result = select_backtracking_assignments(
            window_start_offset=100.0,
            backtracking_enabled=True,
            backtracking_tail_minutes=30.0,
            backtracking_max_ops=10,
            committed_assignments=[],
            committed_assignment_by_op={},
            ops_by_id={},
            horizon_start=HORIZON_START,
        )
        assert result == []

    def test_rewinds_assignments_past_boundary(self) -> None:
        # window_start=100, tail=30 ⇒ rewind_boundary=70.
        # Op A ends at 60 (before boundary, kept).
        # Op B ends at 85 (after boundary, rewound).
        op_a = _OpStub(id=uuid4())
        op_b = _OpStub(id=uuid4())
        a = _make_assignment(op_a.id, end_minutes=60.0)
        b = _make_assignment(op_b.id, end_minutes=85.0)
        result = select_backtracking_assignments(
            window_start_offset=100.0,
            backtracking_enabled=True,
            backtracking_tail_minutes=30.0,
            backtracking_max_ops=10,
            committed_assignments=[a, b],
            committed_assignment_by_op={op_a.id: a, op_b.id: b},
            ops_by_id={op_a.id: op_a, op_b.id: op_b},
            horizon_start=HORIZON_START,
        )
        assert [r.operation_id for r in result] == [op_b.id]

    def test_aborts_when_rewound_set_exceeds_max_ops(self) -> None:
        op_a = _OpStub(id=uuid4())
        op_b = _OpStub(id=uuid4())
        a = _make_assignment(op_a.id, end_minutes=85.0)
        b = _make_assignment(op_b.id, end_minutes=90.0)
        result = select_backtracking_assignments(
            window_start_offset=100.0,
            backtracking_enabled=True,
            backtracking_tail_minutes=30.0,
            backtracking_max_ops=1,
            committed_assignments=[a, b],
            committed_assignment_by_op={op_a.id: a, op_b.id: b},
            ops_by_id={op_a.id: op_a, op_b.id: op_b},
            horizon_start=HORIZON_START,
        )
        assert result == []  # bail-out: too many to rewind

    def test_closes_under_successors(self) -> None:
        # A ends at 60 (before boundary). B is A's successor and ends at 85
        # (after boundary). When B is rewound, A must follow because B is
        # A's successor → no, the test is the other way around: when an op's
        # PREDECESSOR is rewound, the op itself must be rewound. So:
        # A predecessor of B; B ends past boundary so B is rewound; A is
        # NOT a successor of a rewound op, so A stays.
        # Reverse case: A is rewound, B (successor) joins.
        op_a = _OpStub(id=uuid4())
        op_b = _OpStub(id=uuid4(), predecessor_op_id=op_a.id)
        a = _make_assignment(op_a.id, end_minutes=85.0)  # past boundary
        b = _make_assignment(op_b.id, end_minutes=60.0)  # before boundary
        result = select_backtracking_assignments(
            window_start_offset=100.0,
            backtracking_enabled=True,
            backtracking_tail_minutes=30.0,
            backtracking_max_ops=10,
            committed_assignments=[a, b],
            committed_assignment_by_op={op_a.id: a, op_b.id: b},
            ops_by_id={op_a.id: op_a, op_b.id: op_b},
            horizon_start=HORIZON_START,
        )
        result_ids = {r.operation_id for r in result}
        assert result_ids == {op_a.id, op_b.id}


# =============================================================================
# stabilize_temporal_consistency
# =============================================================================


class TestStabilizeTemporalConsistency:
    def test_empty_assignments_returns_zero_stats(self) -> None:
        stats = stabilize_temporal_consistency(
            [],
            ops_by_id={},
            setup_minutes={},
        )
        assert stats == {"passes": 0, "precedence_shifts": 0, "machine_shifts": 0}

    def test_no_conflicts_converges_in_one_pass(self) -> None:
        op = _OpStub(id=uuid4())
        a = _make_assignment(op.id, start_minutes=0.0, end_minutes=10.0)
        stats = stabilize_temporal_consistency(
            [a],
            ops_by_id={op.id: op},
            setup_minutes={},
        )
        assert stats["passes"] == 1
        assert stats["precedence_shifts"] == 0
        assert stats["machine_shifts"] == 0

    def test_precedence_violation_is_repaired_forward(self) -> None:
        # Op A ends at 30. Op B is A's successor but starts at 10 (overlaps).
        # The stabilizer must shift B forward so it starts at 30.
        op_a = _OpStub(id=uuid4())
        op_b = _OpStub(id=uuid4(), seq_in_order=1, predecessor_op_id=op_a.id)
        a = _make_assignment(op_a.id, start_minutes=0.0, end_minutes=30.0)
        b = _make_assignment(op_b.id, start_minutes=10.0, end_minutes=20.0)
        stats = stabilize_temporal_consistency(
            [a, b],
            ops_by_id={op_a.id: op_a, op_b.id: op_b},
            setup_minutes={},
        )
        assert stats["precedence_shifts"] >= 1
        # B should now start at A's end (30 min).
        assert b.start_time == HORIZON_START + timedelta(minutes=30.0)
        # And its duration must be preserved (10 min original duration).
        assert b.end_time == HORIZON_START + timedelta(minutes=40.0)

    def test_machine_overlap_is_repaired_with_setup(self) -> None:
        # Two ops on the same work center, overlapping by 5 min, with a
        # required setup of 4 min between their states.
        wc_id = uuid4()
        state_a = uuid4()
        state_b = uuid4()
        op_a = _OpStub(id=uuid4(), state_id=state_a)
        op_b = _OpStub(id=uuid4(), seq_in_order=1, state_id=state_b)
        a = _make_assignment(op_a.id, work_center_id=wc_id, start_minutes=0.0, end_minutes=20.0)
        b = _make_assignment(op_b.id, work_center_id=wc_id, start_minutes=15.0, end_minutes=25.0)
        stats = stabilize_temporal_consistency(
            [a, b],
            ops_by_id={op_a.id: op_a, op_b.id: op_b},
            setup_minutes={(wc_id, state_a, state_b): 4},
        )
        assert stats["machine_shifts"] >= 1
        # B must now start no earlier than A.end + 4 = 24.
        assert b.start_time >= HORIZON_START + timedelta(minutes=24.0)

    def test_pass_count_bounded_by_max_passes(self) -> None:
        op = _OpStub(id=uuid4())
        a = _make_assignment(op.id)
        stats = stabilize_temporal_consistency(
            [a],
            ops_by_id={op.id: op},
            setup_minutes={},
            max_passes=3,
        )
        assert stats["passes"] <= 3


# =============================================================================
# reanchor_inner_assignments — smoke test only (full coverage in integration)
# =============================================================================


class TestReanchorInnerAssignmentsSmoke:
    def test_empty_assignments_returns_empty_zero(self) -> None:
        # With no inner assignments to reanchor, function must return
        # early with zero changed count.
        from synaps.solvers.rhc._window import reanchor_inner_assignments

        result, changed = reanchor_inner_assignments(
            [],
            frozen_assignments=[_make_assignment(uuid4())],
            frozen_assignment_by_op={},
            dispatch_context=None,  # type: ignore[arg-type]
            machine_index_factory=lambda ctx: None,  # type: ignore[arg-type]
            find_earliest_feasible_slot=lambda *a, **k: None,
            ops_by_id={},
            op_earliest={},
            op_positions={},
            horizon_start=HORIZON_START,
        )
        assert result == []
        assert changed == 0

    def test_empty_frozen_returns_passthrough(self) -> None:
        from synaps.solvers.rhc._window import reanchor_inner_assignments

        op = _OpStub(id=uuid4())
        a = _make_assignment(op.id)
        result, changed = reanchor_inner_assignments(
            [a],
            frozen_assignments=[],
            frozen_assignment_by_op={},
            dispatch_context=None,  # type: ignore[arg-type]
            machine_index_factory=lambda ctx: None,  # type: ignore[arg-type]
            find_earliest_feasible_slot=lambda *a, **k: None,
            ops_by_id={op.id: op},
            op_earliest={},
            op_positions={op.id: 0},
            horizon_start=HORIZON_START,
        )
        assert result == [a]
        assert changed == 0
