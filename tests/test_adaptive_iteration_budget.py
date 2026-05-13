"""Unit tests for Task 18: Adaptive Iteration Budget + Warm-Start Skip.

Validates:
  18.4: warm-start with gap < threshold → ALNS skipped, metadata records reason
  18.5: adaptive scaling reduces iterations proportionally to coverage
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
from synaps.solvers.greedy_dispatch import GreedyDispatch


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 3, 20, 0, tzinfo=UTC)


def _make_small_problem(
    n_orders: int = 5,
    ops_per_order: int = 3,
    n_machines: int = 3,
    seed: int = 42,
) -> ScheduleProblem:
    """Build a small deterministic FJSP-SDST problem."""
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


def _greedy_warm_start(problem: ScheduleProblem) -> list[Assignment]:
    """Produce a full, feasible warm-start set via greedy dispatch."""
    result = GreedyDispatch().solve(problem, time_limit_s=10.0)
    assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
        f"Greedy dispatch did not produce a feasible seed: status={result.status}"
    )
    assert len(result.assignments) == len(problem.operations), (
        "Greedy dispatch did not cover every operation."
    )
    return list(result.assignments)


# ─────────────────────────────────────────────────────────────────────────────
# Task 18.4: Warm-start skip when gap < threshold
# ─────────────────────────────────────────────────────────────────────────────


class TestWarmStartSkipThreshold:
    """Task 18.4: ALNS skipped when warm-start gap < threshold."""

    def test_warm_start_skip_when_gap_below_threshold(self) -> None:
        """Full warm-start + threshold=10.0 (very permissive) → ALNS skipped,
        metadata records `alns_skipped_warm_start_sufficient=True` and
        `iterations_completed=0`.

        Note: threshold=10.0 means any gap ≤ 1000% triggers skip. For small
        problems the relaxed LB is loose, so we use a generous threshold to
        guarantee the skip fires regardless of problem structure.
        """
        problem = _make_small_problem(n_orders=3, ops_per_order=2, seed=100)
        warm = _greedy_warm_start(problem)

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=100,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=warm,
            # threshold=10.0 means any gap ≤ 1000% triggers skip — always true
            # for small problems where the relaxed LB is loose
            warm_start_skip_threshold_gap=10.0,
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        assert meta["alns_skipped_warm_start_sufficient"] is True
        assert meta["iterations_completed"] == 0
        assert "alns_skip_gap" in meta
        assert isinstance(meta["alns_skip_gap"], float)
        assert meta["alns_skip_gap"] >= 0.0
        assert meta["warm_start_used"] is True

    def test_warm_start_skip_disabled_by_default(self) -> None:
        """Default threshold=0.0 → ALNS runs normally even with full warm-start."""
        problem = _make_small_problem(n_orders=3, ops_per_order=2, seed=101)
        warm = _greedy_warm_start(problem)

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=warm,
            # No warm_start_skip_threshold_gap → default 0.0 → disabled
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        assert meta["alns_skipped_warm_start_sufficient"] is False
        # ALNS should have run at least some iterations
        assert meta["iterations_completed"] > 0

    def test_warm_start_skip_not_triggered_without_warm_start(self) -> None:
        """Even with threshold=10.0, skip does not trigger without warm-start."""
        problem = _make_small_problem(n_orders=3, ops_per_order=2, seed=102)

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_skip_threshold_gap=10.0,
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        assert meta["alns_skipped_warm_start_sufficient"] is False
        assert meta["iterations_completed"] > 0


# ─────────────────────────────────────────────────────────────────────────────
# Task 18.5: Adaptive iteration scaling
# ─────────────────────────────────────────────────────────────────────────────


class TestAdaptiveIterationScaling:
    """Task 18.5: adaptive scaling reduces iterations proportionally to coverage."""

    def test_full_coverage_reduces_iterations(self) -> None:
        """Full warm-start (100% coverage) + adaptive_iteration_scaling=True
        → max_iterations reduced to ~10% of configured value (floor at 5).
        """
        problem = _make_small_problem(n_orders=3, ops_per_order=2, seed=200)
        warm = _greedy_warm_start(problem)
        configured_max_iterations = 100

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=configured_max_iterations,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=warm,
            adaptive_iteration_scaling=True,
            max_no_improve_iters=0,  # disable stagnation to let it run full budget
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        assert meta["adaptive_iteration_scaling"] is True
        assert meta["adaptive_iteration_scaling_applied"] is True
        assert meta["original_max_iterations"] == configured_max_iterations
        # Full coverage → scale_factor = max(0.1, 1.0 - 1.0) = 0.1
        # max_iterations = max(5, int(100 * 0.1)) = 10
        assert meta["max_iterations"] == 10

    def test_partial_coverage_scales_proportionally(self) -> None:
        """50% warm-start coverage + adaptive_iteration_scaling=True
        → max_iterations reduced to ~50% of configured value.
        """
        problem = _make_small_problem(n_orders=4, ops_per_order=3, seed=201)
        full_warm = _greedy_warm_start(problem)

        # Take only half the assignments to simulate 50% coverage
        n_ops = len(problem.operations)
        half_count = n_ops // 2
        partial_warm = full_warm[:half_count]

        configured_max_iterations = 100

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=configured_max_iterations,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=partial_warm,
            adaptive_iteration_scaling=True,
            max_no_improve_iters=0,  # disable stagnation
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        assert meta["adaptive_iteration_scaling"] is True
        assert meta["adaptive_iteration_scaling_applied"] is True
        assert meta["original_max_iterations"] == configured_max_iterations
        # ~50% coverage → scale_factor = max(0.1, 1.0 - 0.5) = 0.5
        # max_iterations = max(5, int(100 * 0.5)) = 50
        effective_max = meta["max_iterations"]
        # Allow some tolerance since coverage may not be exactly 50%
        assert 30 <= effective_max <= 60, (
            f"Expected ~50 iterations for ~50% coverage, got {effective_max}"
        )

    def test_adaptive_scaling_disabled_by_default(self) -> None:
        """Default adaptive_iteration_scaling=False → no scaling applied."""
        problem = _make_small_problem(n_orders=3, ops_per_order=2, seed=202)
        warm = _greedy_warm_start(problem)
        configured_max_iterations = 50

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=configured_max_iterations,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=warm,
            # adaptive_iteration_scaling not passed → default False
            max_no_improve_iters=0,
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        assert meta["adaptive_iteration_scaling"] is False
        assert meta["adaptive_iteration_scaling_applied"] is False
        assert meta["max_iterations"] == configured_max_iterations
        assert meta["original_max_iterations"] == configured_max_iterations

    def test_adaptive_scaling_not_applied_without_warm_start(self) -> None:
        """Even with adaptive_iteration_scaling=True, no scaling without warm-start."""
        problem = _make_small_problem(n_orders=3, ops_per_order=2, seed=203)
        configured_max_iterations = 50

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=configured_max_iterations,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            adaptive_iteration_scaling=True,
            max_no_improve_iters=0,
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        assert meta["adaptive_iteration_scaling"] is True
        assert meta["adaptive_iteration_scaling_applied"] is False
        assert meta["max_iterations"] == configured_max_iterations


# ─────────────────────────────────────────────────────────────────────────────
# Task 18.1: Reduced no-improve for high-coverage warm-starts
# ─────────────────────────────────────────────────────────────────────────────


class TestReducedNoImproveHighCoverage:
    """Task 18.1: max_no_improve_iters capped at 15 for coverage > 80%."""

    def test_high_coverage_caps_no_improve_at_15(self) -> None:
        """Full warm-start (100% coverage) with max_no_improve_iters=30
        → capped to 15 in metadata.
        """
        problem = _make_small_problem(n_orders=3, ops_per_order=2, seed=300)
        warm = _greedy_warm_start(problem)

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=100,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=warm,
            max_no_improve_iters=30,
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        # max_no_improve_iters should be capped at 15
        assert meta["max_no_improve_iters"] == 15

    def test_low_coverage_does_not_cap_no_improve(self) -> None:
        """Partial warm-start (< 80% coverage) → max_no_improve_iters unchanged."""
        problem = _make_small_problem(n_orders=5, ops_per_order=3, seed=301)
        full_warm = _greedy_warm_start(problem)

        # Take only 30% of assignments
        n_ops = len(problem.operations)
        partial_count = int(n_ops * 0.3)
        partial_warm = full_warm[:partial_count]

        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=50,
            time_limit_s=30.0,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            warm_start_assignments=partial_warm,
            max_no_improve_iters=30,
        )

        assert result.status == SolverStatus.FEASIBLE
        meta = result.metadata
        # Coverage < 80% → no cap applied, stays at 30
        assert meta["max_no_improve_iters"] == 30
