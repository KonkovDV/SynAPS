"""Unit tests for the RHC warm-start filter helper (Stage C1, Tasks 9.6 & 9.7).

Task 9.6: single-category rejection cases, mixed inputs, empty input.
Task 9.7: all warm-start assignments conflict → solver falls back to fresh
greedy initial generation and metadata records the reason breakdown.

Validates: Requirements 9.1, 9.2, 9.6, 9.7
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import AlnsSolver
from synaps.solvers.rhc._warm_start import (
    WarmStartSelection,
    filter_warm_start_assignments,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 3, 20, 0, tzinfo=UTC)


def _make_assignment(
    *,
    operation_id: UUID | None = None,
    work_center_id: UUID | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> Assignment:
    """Create a minimal Assignment with sensible defaults."""
    return Assignment(
        operation_id=operation_id or uuid4(),
        work_center_id=work_center_id or uuid4(),
        start_time=start_time or HORIZON_START,
        end_time=end_time or (HORIZON_START + timedelta(hours=1)),
        setup_minutes=0,
        aux_resource_ids=[],
        lane_id=None,
    )


def _make_small_feasible_problem(
    n_orders: int = 5,
    ops_per_order: int = 3,
    n_machines: int = 3,
    seed: int = 42,
) -> ScheduleProblem:
    """Build a small deterministic FJSP-SDST problem (~15 ops, 3 machines)."""
    rng = random.Random(seed)

    states = [State(id=uuid4(), code=f"S{i}", label=f"State {i}") for i in range(3)]
    state_ids = [s.id for s in states]

    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"M{i}",
            capability_group="grp",
            speed_factor=round(0.8 + rng.random() * 0.4, 2),
        )
        for i in range(n_machines)
    ]
    wc_ids = [wc.id for wc in work_centers]

    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if rng.random() < 0.7:
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=rng.randint(5, 25),
                        )
                    )

    orders: list[Order] = []
    operations: list[Operation] = []

    for i in range(n_orders):
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{i:04d}",
                due_date=HORIZON_START + timedelta(hours=8 + i * 4),
                priority=500 + i * 100,
            )
        )
        prev_op_id: UUID | None = None
        for j in range(ops_per_order):
            op_id = uuid4()
            n_eligible = rng.randint(2, n_machines)
            eligible = rng.sample(wc_ids, n_eligible)
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=rng.choice(state_ids),
                    base_duration_min=rng.randint(15, 60),
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Task 9.6: Unit tests for filter_warm_start_assignments
# ─────────────────────────────────────────────────────────────────────────────


class TestFilterWarmStartAssignments:
    """Task 9.6: filter helper unit tests."""

    def test_empty_input(self) -> None:
        """Empty candidates → zero counts, empty assignments."""
        result = filter_warm_start_assignments(
            candidates=[],
            active_window_op_ids=set(),
            frozen_committed_op_ids=set(),
            frozen_boundary_assignments=[],
        )

        assert result == WarmStartSelection(
            assignments=[],
            supplied_count=0,
            accepted_count=0,
            rejected_count=0,
            rejected_reason_counts={},
        )

    def test_all_accepted(self) -> None:
        """All candidates pass all filters → all accepted, zero rejections."""
        op_ids = [uuid4() for _ in range(3)]
        candidates = [_make_assignment(operation_id=oid) for oid in op_ids]

        result = filter_warm_start_assignments(
            candidates=candidates,
            active_window_op_ids=set(op_ids),
            frozen_committed_op_ids=set(),
            frozen_boundary_assignments=[],
        )

        assert result.supplied_count == 3
        assert result.accepted_count == 3
        assert result.rejected_count == 0
        assert result.rejected_reason_counts == {}
        assert len(result.assignments) == 3

    def test_single_rejection_not_in_active_window(self) -> None:
        """Candidate with operation_id not in active_window_op_ids → rejected."""
        active_op = uuid4()
        outside_op = uuid4()

        candidates = [
            _make_assignment(operation_id=active_op),
            _make_assignment(operation_id=outside_op),
        ]

        result = filter_warm_start_assignments(
            candidates=candidates,
            active_window_op_ids={active_op},
            frozen_committed_op_ids=set(),
            frozen_boundary_assignments=[],
        )

        assert result.supplied_count == 2
        assert result.accepted_count == 1
        assert result.rejected_count == 1
        assert result.rejected_reason_counts == {"not_in_active_window": 1}
        assert result.assignments[0].operation_id == active_op

    def test_single_rejection_frozen_committed(self) -> None:
        """Candidate with operation_id in frozen_committed_op_ids → rejected."""
        normal_op = uuid4()
        frozen_op = uuid4()

        candidates = [
            _make_assignment(operation_id=normal_op),
            _make_assignment(operation_id=frozen_op),
        ]

        result = filter_warm_start_assignments(
            candidates=candidates,
            active_window_op_ids={normal_op, frozen_op},
            frozen_committed_op_ids={frozen_op},
            frozen_boundary_assignments=[],
        )

        assert result.supplied_count == 2
        assert result.accepted_count == 1
        assert result.rejected_count == 1
        assert result.rejected_reason_counts == {"frozen_committed": 1}
        assert result.assignments[0].operation_id == normal_op

    def test_single_rejection_boundary_conflict(self) -> None:
        """Candidate overlapping a frozen boundary assignment on same work center → rejected."""
        op_id = uuid4()
        wc_id = uuid4()

        # Candidate: [08:00, 09:00)
        candidate = _make_assignment(
            operation_id=op_id,
            work_center_id=wc_id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(hours=1),
        )

        # Frozen boundary: [08:30, 09:30) — overlaps with candidate
        frozen_boundary = _make_assignment(
            work_center_id=wc_id,
            start_time=HORIZON_START + timedelta(minutes=30),
            end_time=HORIZON_START + timedelta(hours=1, minutes=30),
        )

        result = filter_warm_start_assignments(
            candidates=[candidate],
            active_window_op_ids={op_id},
            frozen_committed_op_ids=set(),
            frozen_boundary_assignments=[frozen_boundary],
        )

        assert result.supplied_count == 1
        assert result.accepted_count == 0
        assert result.rejected_count == 1
        assert result.rejected_reason_counts == {"boundary_conflict": 1}
        assert result.assignments == []

    def test_mixed_inputs(self) -> None:
        """5 candidates: 2 accepted, 1 not_in_active_window, 1 frozen_committed,
        1 boundary_conflict."""
        # IDs for the 5 candidates
        accepted_op_1 = uuid4()
        accepted_op_2 = uuid4()
        outside_op = uuid4()
        frozen_op = uuid4()
        conflict_op = uuid4()

        shared_wc = uuid4()
        other_wc = uuid4()

        # Frozen boundary on shared_wc: [10:00, 11:00)
        frozen_boundary = _make_assignment(
            work_center_id=shared_wc,
            start_time=HORIZON_START + timedelta(hours=2),
            end_time=HORIZON_START + timedelta(hours=3),
        )

        candidates = [
            # Accepted: in active window, not frozen, no boundary conflict
            _make_assignment(operation_id=accepted_op_1, work_center_id=other_wc),
            _make_assignment(operation_id=accepted_op_2, work_center_id=other_wc),
            # Rejected: not in active window
            _make_assignment(operation_id=outside_op, work_center_id=other_wc),
            # Rejected: frozen committed
            _make_assignment(operation_id=frozen_op, work_center_id=other_wc),
            # Rejected: boundary conflict (same wc, overlapping time [10:30, 11:30))
            _make_assignment(
                operation_id=conflict_op,
                work_center_id=shared_wc,
                start_time=HORIZON_START + timedelta(hours=2, minutes=30),
                end_time=HORIZON_START + timedelta(hours=3, minutes=30),
            ),
        ]

        active_ids = {accepted_op_1, accepted_op_2, frozen_op, conflict_op}
        # outside_op is NOT in active_ids → "not_in_active_window"

        result = filter_warm_start_assignments(
            candidates=candidates,
            active_window_op_ids=active_ids,
            frozen_committed_op_ids={frozen_op},
            frozen_boundary_assignments=[frozen_boundary],
        )

        assert result.supplied_count == 5
        assert result.accepted_count == 2
        assert result.rejected_count == 3
        assert result.rejected_reason_counts == {
            "not_in_active_window": 1,
            "frozen_committed": 1,
            "boundary_conflict": 1,
        }
        accepted_op_ids = {a.operation_id for a in result.assignments}
        assert accepted_op_ids == {accepted_op_1, accepted_op_2}

    def test_priority_ordering_not_in_active_window_wins_over_frozen(self) -> None:
        """A candidate matching BOTH not_in_active_window AND frozen_committed
        → only 'not_in_active_window' is recorded (first priority wins)."""
        dual_reject_op = uuid4()

        candidate = _make_assignment(operation_id=dual_reject_op)

        # The op is NOT in active_window AND is in frozen_committed.
        # Priority 1 (not_in_active_window) should fire first.
        result = filter_warm_start_assignments(
            candidates=[candidate],
            active_window_op_ids=set(),  # not in active window
            frozen_committed_op_ids={dual_reject_op},  # also frozen
            frozen_boundary_assignments=[],
        )

        assert result.supplied_count == 1
        assert result.accepted_count == 0
        assert result.rejected_count == 1
        # Only the first-priority reason is recorded
        assert result.rejected_reason_counts == {"not_in_active_window": 1}
        assert "frozen_committed" not in result.rejected_reason_counts


# ─────────────────────────────────────────────────────────────────────────────
# Task 9.7: All rejected → solver falls back to greedy
# ─────────────────────────────────────────────────────────────────────────────


class TestAllRejectedFallback:
    """Task 9.7: all warm-start assignments conflict → solver falls back to
    fresh greedy initial generation and metadata records the reason breakdown.
    """

    def test_filter_rejects_all_then_solver_uses_greedy(self) -> None:
        """When the RHC filter rejects ALL warm-start candidates (e.g., none
        are in the active window), the resulting empty list passed to ALNS
        causes the solver to fall back to fresh greedy initial generation.

        This test exercises the full pipeline:
        1. filter_warm_start_assignments rejects everything with reason counts
        2. ALNS receives an empty warm-start → falls back to greedy
        3. Metadata reflects the fallback path
        """
        problem = _make_small_feasible_problem(n_orders=5, ops_per_order=3, n_machines=3, seed=42)

        # Create candidates whose operation_ids are NOT in the problem's
        # active window (simulating total rejection at the RHC filter level).
        fake_op_ids = [uuid4() for _ in range(len(problem.operations))]
        fake_candidates = [_make_assignment(operation_id=oid) for oid in fake_op_ids]

        # Step 1: The filter rejects all candidates
        real_op_ids = {op.id for op in problem.operations}
        selection = filter_warm_start_assignments(
            candidates=fake_candidates,
            active_window_op_ids=real_op_ids,  # none of the fake IDs are here
            frozen_committed_op_ids=set(),
            frozen_boundary_assignments=[],
        )

        # All rejected as "not_in_active_window"
        assert selection.supplied_count == len(fake_candidates)
        assert selection.accepted_count == 0
        assert selection.rejected_count == len(fake_candidates)
        assert selection.rejected_reason_counts == {
            "not_in_active_window": len(fake_candidates),
        }
        assert selection.assignments == []

        # Step 2: ALNS receives the empty filtered list → greedy fallback
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=20,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=selection.assignments,  # empty list
        )

        # Solver must still produce a feasible schedule via greedy fallback
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
            f"Expected FEASIBLE/OPTIMAL after warm-start rejection fallback, got {result.status}"
        )

        md = result.metadata

        # Warm-start was not used (empty list after filtering)
        assert md["alns_warm_start_used"] is False, (
            "alns_warm_start_used must be False when filtered list is empty"
        )

        # The initial solver should NOT be warm_start
        assert md["initial_solver"] != "warm_start", (
            "initial_solver must not be 'warm_start' when warm-start was rejected"
        )

        # Coverage is 0 since nothing was supplied to ALNS after filtering
        assert md["alns_warm_start_coverage"] == pytest.approx(0.0, abs=1e-9)

    def test_all_warm_start_infeasible_solver_reports_rejection(self) -> None:
        """When warm-start assignments cover all operations but form an
        infeasible schedule (e.g., all on the same machine with overlapping
        times), the solver rejects the warm-start and falls back to greedy.
        Metadata records the rejection reason.
        """
        problem = _make_small_feasible_problem(n_orders=5, ops_per_order=3, n_machines=3, seed=42)

        # Create assignments that cover all problem operations but are
        # infeasible (all assigned to the same machine with overlapping times).
        single_wc = problem.work_centers[0].id
        infeasible_assignments = [
            Assignment(
                operation_id=op.id,
                work_center_id=single_wc,
                start_time=HORIZON_START,  # all start at same time → overlap
                end_time=HORIZON_START + timedelta(minutes=op.base_duration_min),
                setup_minutes=0,
                aux_resource_ids=[],
                lane_id=None,
            )
            for op in problem.operations
        ]

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=20,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=infeasible_assignments,
        )

        # Solver must still produce a feasible schedule via greedy fallback
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
            f"Expected FEASIBLE/OPTIMAL after infeasible warm-start fallback, got {result.status}"
        )

        md = result.metadata

        # Warm-start was not used (infeasible)
        assert md["alns_warm_start_used"] is False, (
            "alns_warm_start_used must be False when warm-start is infeasible"
        )

        # A rejection reason must be recorded for infeasible warm-start
        assert md["warm_start_rejected_reason"] is not None, (
            "warm_start_rejected_reason must be populated when warm-start is "
            "infeasible and rejected"
        )

        # The initial solver should NOT be warm_start
        assert md["initial_solver"] != "warm_start", (
            "initial_solver must not be 'warm_start' when warm-start was rejected"
        )
