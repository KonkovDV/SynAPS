"""Tests for bounded cross-window operator bias (Tasks 3b.5, 3b.6, 3b.7).

Covers:
  - 3b.5: Weights remain normalized (sum to 1.0) after bias application.
  - 3b.6: Bias is absent when feature flag is off (behavior identical to baseline).
  - 3b.7: No operator weight drops below floor under maximum hint pressure.

Validates: Requirements 3.3
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import AlnsSolver, DESTROY_OPERATORS
from synaps.solvers.rhc._cross_window import WindowQualitySummary


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 3, 20, 0, tzinfo=UTC)


def _make_small_problem(
    n_orders: int = 4,
    ops_per_order: int = 3,
    n_machines: int = 3,
    seed: int = 99,
) -> ScheduleProblem:
    """Build a small deterministic FJSP-SDST problem for bias testing."""
    rng = random.Random(seed)

    states = [
        State(id=uuid4(), code=f"S{i}", label=f"State {i}")
        for i in range(3)
    ]
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
                if rng.random() < 0.6:
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=rng.randint(5, 30),
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
        prev_op_id = None
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


def _make_high_setup_hints(n_hints: int = 3) -> list[WindowQualitySummary]:
    """Create hints with high setup cost concentration (saturated signal)."""
    return [
        WindowQualitySummary(
            window_index=i,
            per_machine_utilization={f"wc_0": 0.8, f"wc_1": 0.6},
            setup_cost_by_machine={f"wc_0": 200.0, f"wc_1": 150.0},
            tardiness_contribution=10.0,
            operation_count=500,
        )
        for i in range(n_hints)
    ]


def _make_low_setup_hints(n_hints: int = 3) -> list[WindowQualitySummary]:
    """Create hints with very low setup cost (near-zero signal)."""
    return [
        WindowQualitySummary(
            window_index=i,
            per_machine_utilization={f"wc_0": 0.3, f"wc_1": 0.2},
            setup_cost_by_machine={f"wc_0": 1.0, f"wc_1": 0.5},
            tardiness_contribution=0.0,
            operation_count=100,
        )
        for i in range(n_hints)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Task 3b.5: Weights remain normalized after bias
# ─────────────────────────────────────────────────────────────────────────────


class TestBiasWeightsNormalized:
    """Verify operator weights sum to 1.0 after cross-window bias application.

    **Validates: Requirements 3.3**
    """

    def test_weights_sum_to_one_after_bias_with_high_hints(self) -> None:
        """With high setup hints and bias enabled, weights still sum to 1.0."""
        problem = _make_small_problem()
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            cross_window_operator_bias_enabled=True,
            cross_window_hints=_make_high_setup_hints(),
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["cross_window_bias_applied"] is True

        # Final weights should still sum to ~1.0
        final_weights = result.metadata["alns_final_operator_weights"]
        assert isinstance(final_weights, dict)
        weight_sum = sum(final_weights.values())
        # Tolerance accounts for rounding to 6 decimal places in metadata
        assert abs(weight_sum - 1.0) < 1e-4, (
            f"Final operator weights should sum to ~1.0, got {weight_sum}"
        )

    def test_weights_sum_to_one_after_bias_with_low_hints(self) -> None:
        """With low setup hints and bias enabled, weights still sum to 1.0."""
        problem = _make_small_problem()
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            cross_window_operator_bias_enabled=True,
            cross_window_hints=_make_low_setup_hints(),
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

        final_weights = result.metadata["alns_final_operator_weights"]
        assert isinstance(final_weights, dict)
        weight_sum = sum(final_weights.values())
        # Tolerance accounts for rounding to 6 decimal places in metadata
        assert abs(weight_sum - 1.0) < 1e-4, (
            f"Final operator weights should sum to ~1.0, got {weight_sum}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Task 3b.6: Bias absent when feature flag is off
# ─────────────────────────────────────────────────────────────────────────────


class TestBiasAbsentWhenFlagOff:
    """Verify bias is not applied when cross_window_operator_bias_enabled=False.

    **Validates: Requirements 3.3**
    """

    def test_bias_not_applied_when_flag_off(self) -> None:
        """With flag off, cross_window_bias_applied=False and deltas are all 0."""
        problem = _make_small_problem()
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            cross_window_operator_bias_enabled=False,
            cross_window_hints=_make_high_setup_hints(),
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["cross_window_bias_applied"] is False

        deltas = result.metadata["cross_window_bias_operator_deltas"]
        assert isinstance(deltas, dict)
        for name, delta in deltas.items():
            assert delta == 0.0, (
                f"Operator '{name}' has non-zero delta {delta} when flag is off"
            )

    def test_bias_not_applied_when_no_hints(self) -> None:
        """With flag on but no hints, cross_window_bias_applied=False."""
        problem = _make_small_problem()
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            cross_window_operator_bias_enabled=True,
            # No cross_window_hints kwarg
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["cross_window_bias_applied"] is False

        deltas = result.metadata["cross_window_bias_operator_deltas"]
        for name, delta in deltas.items():
            assert delta == 0.0, (
                f"Operator '{name}' has non-zero delta {delta} when no hints"
            )

    def test_bias_not_applied_when_hints_empty_list(self) -> None:
        """With flag on but empty hints list, cross_window_bias_applied=False."""
        problem = _make_small_problem()
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            cross_window_operator_bias_enabled=True,
            cross_window_hints=[],
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["cross_window_bias_applied"] is False

    def test_baseline_behavior_identical_when_flag_off(self) -> None:
        """Initial weights are identical whether flag is off or hints are absent."""
        problem = _make_small_problem()
        solver = AlnsSolver()

        # Run with flag off + hints present
        result_off = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            random_seed=42,
            cross_window_operator_bias_enabled=False,
            cross_window_hints=_make_high_setup_hints(),
        )

        # Run without any bias kwargs (default behavior)
        result_default = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            random_seed=42,
        )

        # Initial weights should be identical
        assert result_off.metadata["alns_initial_operator_weights"] == (
            result_default.metadata["alns_initial_operator_weights"]
        )


# ─────────────────────────────────────────────────────────────────────────────
# Task 3b.7: No operator weight drops below floor
# ─────────────────────────────────────────────────────────────────────────────


class TestBiasFloorEnforced:
    """Verify no operator weight drops below the minimum floor under max pressure.

    **Validates: Requirements 3.3**
    """

    def test_no_weight_below_floor_with_max_pressure(self) -> None:
        """Under maximum hint pressure, all operator weights stay above floor."""
        problem = _make_small_problem()
        solver = AlnsSolver()

        # Use extreme hints to maximize the bias signal
        extreme_hints = [
            WindowQualitySummary(
                window_index=i,
                per_machine_utilization={f"wc_0": 1.0},
                setup_cost_by_machine={f"wc_0": 10000.0},  # Very high
                tardiness_contribution=100.0,
                operation_count=1000,
            )
            for i in range(5)
        ]

        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            cross_window_operator_bias_enabled=True,
            cross_window_hints=extreme_hints,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["cross_window_bias_applied"] is True

        # Check that bias deltas show machine_segment got a positive boost
        deltas = result.metadata["cross_window_bias_operator_deltas"]
        assert deltas["machine_segment"] > 0.0, (
            "machine_segment should get a positive boost under high setup pressure"
        )

        # The floor is 1/(n_operators * 10) = 10% of uniform weight.
        # After bias + normalization, no weight should be below this floor
        # (within floating-point tolerance).
        n_operators = len(DESTROY_OPERATORS)
        weight_floor = 1.0 / (n_operators * 10)

        # Check initial weights after bias (use deltas + initial to reconstruct)
        initial_weights = result.metadata["alns_initial_operator_weights"]
        biased_weights = {
            name: initial_weights[name] + deltas[name]
            for name in initial_weights
        }

        for name, weight in biased_weights.items():
            assert weight >= weight_floor - 1e-10, (
                f"Operator '{name}' weight {weight} is below floor {weight_floor}"
            )

    def test_floor_prevents_zero_weight_with_skewed_initial(self) -> None:
        """Even with heavily skewed initial weights, floor prevents zero."""
        problem = _make_small_problem()
        solver = AlnsSolver()

        # Start with heavily skewed weights (machine_segment dominates)
        n_operators = len(DESTROY_OPERATORS)
        operator_names = [name for name, _ in DESTROY_OPERATORS]
        skewed_weights = {name: 0.01 for name in operator_names}
        skewed_weights["machine_segment"] = 10.0  # Dominates

        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            cross_window_operator_bias_enabled=True,
            cross_window_hints=_make_high_setup_hints(),
            initial_operator_weights=skewed_weights,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

        # All final weights should be positive (no zeroed-out operators)
        final_weights = result.metadata["alns_final_operator_weights"]
        for name, weight in final_weights.items():
            assert weight > 0.0, (
                f"Operator '{name}' has zero weight — floor should prevent this"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Additional: Metadata fields always present
# ─────────────────────────────────────────────────────────────────────────────


class TestBiasMetadataAlwaysPresent:
    """Verify bias metadata fields are always present in solver output."""

    def test_metadata_present_when_bias_off(self) -> None:
        """cross_window_bias_applied and deltas present even when flag is off."""
        problem = _make_small_problem()
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
        )

        assert "cross_window_bias_applied" in result.metadata
        assert "cross_window_bias_operator_deltas" in result.metadata
        assert result.metadata["cross_window_bias_applied"] is False
        assert isinstance(result.metadata["cross_window_bias_operator_deltas"], dict)

    def test_metadata_present_when_bias_on(self) -> None:
        """cross_window_bias_applied and deltas present when flag is on."""
        problem = _make_small_problem()
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            cross_window_operator_bias_enabled=True,
            cross_window_hints=_make_high_setup_hints(),
        )

        assert "cross_window_bias_applied" in result.metadata
        assert "cross_window_bias_operator_deltas" in result.metadata
        assert result.metadata["cross_window_bias_applied"] is True
        deltas = result.metadata["cross_window_bias_operator_deltas"]
        assert isinstance(deltas, dict)
        # All operator names should be present in deltas
        operator_names = [name for name, _ in DESTROY_OPERATORS]
        assert set(deltas.keys()) == set(operator_names)
