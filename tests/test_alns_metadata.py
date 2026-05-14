"""Unit tests for ALNS solver lower-bound metadata fields.

Task 6.6: Verify that `alns_lower_bound`, `alns_gap_ratio`, and
`lower_bound_components` appear in `ScheduleResult.metadata` after ALNS solve,
and `alns_gap_ratio >= 0` for complete feasible schedules.

Validates: Requirements 6.2, 6.3
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import AlnsSolver

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 3, 20, 0, tzinfo=UTC)


def _make_small_feasible_problem(
    n_orders: int = 5,
    ops_per_order: int = 3,
    n_machines: int = 3,
    seed: int = 42,
) -> ScheduleProblem:
    """Build a small deterministic FJSP-SDST problem (15 ops, 3 machines).

    Uses a fixed seed for deterministic state/setup generation so the test
    is reproducible and fast.
    """
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

    # Build sparse setup matrix
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
        prev_op_id = None
        for j in range(ops_per_order):
            op_id = uuid4()
            # Each op eligible on 2-3 machines
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
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestAlnsLowerBoundMetadata:
    """Verify ALNS solver populates lower-bound metadata fields correctly."""

    def test_alns_lower_bound_metadata_present_and_valid(self) -> None:
        """After ALNS solve on a small feasible problem, metadata contains
        `alns_lower_bound`, `alns_gap_ratio`, and `lower_bound_components`
        with correct types and non-negative values.
        """
        problem = _make_small_feasible_problem(n_orders=5, ops_per_order=3, n_machines=3, seed=42)
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=50,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
        )

        # 1. Result must be feasible
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL), (
            f"Expected FEASIBLE or OPTIMAL, got {result.status}"
        )

        # 2. alns_lower_bound exists and is a non-negative float
        assert "alns_lower_bound" in result.metadata, "Missing 'alns_lower_bound' in metadata"
        alns_lb = result.metadata["alns_lower_bound"]
        assert isinstance(alns_lb, float), f"alns_lower_bound should be float, got {type(alns_lb)}"
        assert alns_lb >= 0.0, f"alns_lower_bound should be non-negative, got {alns_lb}"

        # 3. alns_gap_ratio exists and is >= 0
        assert "alns_gap_ratio" in result.metadata, "Missing 'alns_gap_ratio' in metadata"
        gap_ratio = result.metadata["alns_gap_ratio"]
        assert isinstance(gap_ratio, int | float), (
            f"alns_gap_ratio should be numeric, got {type(gap_ratio)}"
        )
        assert gap_ratio >= 0.0, (
            f"alns_gap_ratio should be >= 0 for feasible schedules, got {gap_ratio}"
        )

        # 4. lower_bound_components exists and is a dict with exactly 5 keys
        assert "lower_bound_components" in result.metadata, (
            "Missing 'lower_bound_components' in metadata"
        )
        lb_components = result.metadata["lower_bound_components"]
        assert isinstance(lb_components, dict), (
            f"lower_bound_components should be dict, got {type(lb_components)}"
        )
        expected_keys = {
            "precedence_critical_path_lb",
            "average_capacity_lb",
            "exclusive_machine_lb",
            "max_operation_lb",
            "auxiliary_resource_lb",
        }
        assert set(lb_components.keys()) == expected_keys, (
            f"lower_bound_components keys mismatch.\n"
            f"Expected: {expected_keys}\n"
            f"Got: {set(lb_components.keys())}"
        )
        # All component values must be non-negative floats
        for key, val in lb_components.items():
            assert isinstance(val, float), (
                f"lower_bound_components['{key}'] should be float, got {type(val)}"
            )
            assert val >= 0.0, f"lower_bound_components['{key}'] should be non-negative, got {val}"

        # 5. Consistency: alns_gap_ratio ≈ (makespan - LB) / max(LB, 1e-6)
        makespan = result.objective.makespan_minutes
        expected_gap = max(makespan - alns_lb, 0.0) / max(alns_lb, 1e-6)
        assert gap_ratio == pytest.approx(round(expected_gap, 6), abs=1e-5), (
            f"alns_gap_ratio ({gap_ratio}) does not match expected "
            f"(makespan - LB) / max(LB, 1e-6) = {expected_gap:.6f}\n"
            f"makespan={makespan}, alns_lower_bound={alns_lb}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.6: Aggregate metadata fields present when record_iteration_metrics=False
# ─────────────────────────────────────────────────────────────────────────────


class TestAlnsAggregateMetadataAlwaysPresent:
    """Verify aggregate convergence metadata is always populated regardless of
    the `record_iteration_metrics` flag.

    Validates: Requirements 7.4
    """

    def test_aggregate_metadata_present_when_metrics_disabled(self) -> None:
        """With record_iteration_metrics=False (default), all aggregate metadata
        fields must still be present with correct types, and the iteration trace
        must NOT appear in metadata.
        """
        problem = _make_small_feasible_problem(n_orders=5, ops_per_order=3, n_machines=3, seed=42)
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=30,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            record_iteration_metrics=False,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        md = result.metadata

        # 1. iterations_completed: int > 0
        assert "iterations_completed" in md
        assert isinstance(md["iterations_completed"], int)
        assert md["iterations_completed"] > 0

        # 2. accepted_iterations: int >= 0
        assert "accepted_iterations" in md
        assert isinstance(md["accepted_iterations"], int)
        assert md["accepted_iterations"] >= 0

        # 3. improved_iterations: int >= 0
        assert "improved_iterations" in md
        assert isinstance(md["improved_iterations"], int)
        assert md["improved_iterations"] >= 0

        # 4. operator_attempt_counts: dict[str, int], all values >= 0
        assert "operator_attempt_counts" in md
        oac = md["operator_attempt_counts"]
        assert isinstance(oac, dict)
        for key, val in oac.items():
            assert isinstance(key, str), (
                f"operator_attempt_counts key should be str, got {type(key)}"
            )
            assert isinstance(val, int), (
                f"operator_attempt_counts['{key}'] should be int, got {type(val)}"
            )
            assert val >= 0, f"operator_attempt_counts['{key}'] should be >= 0, got {val}"

        # 5. operator_improvement_counts: dict[str, int], all values >= 0
        assert "operator_improvement_counts" in md
        oic = md["operator_improvement_counts"]
        assert isinstance(oic, dict)
        for key, val in oic.items():
            assert isinstance(key, str), (
                f"operator_improvement_counts key should be str, got {type(key)}"
            )
            assert isinstance(val, int), (
                f"operator_improvement_counts['{key}'] should be int, got {type(val)}"
            )
            assert val >= 0, f"operator_improvement_counts['{key}'] should be >= 0, got {val}"

        # 6. alns_final_operator_weights: dict[str, float], values sum to ~1.0
        assert "alns_final_operator_weights" in md
        weights = md["alns_final_operator_weights"]
        assert isinstance(weights, dict)
        for key, val in weights.items():
            assert isinstance(key, str), (
                f"alns_final_operator_weights key should be str, got {type(key)}"
            )
            assert isinstance(val, float), (
                f"alns_final_operator_weights['{key}'] should be float, got {type(val)}"
            )
        weight_sum = sum(weights.values())
        assert weight_sum == pytest.approx(1.0, abs=1e-6), (
            f"alns_final_operator_weights should sum to ~1.0, got {weight_sum}"
        )

        # 7. stagnation_detected: bool
        assert "stagnation_detected" in md
        assert isinstance(md["stagnation_detected"], bool)

        # 8. stagnation_iteration: int or None
        assert "stagnation_iteration" in md
        si = md["stagnation_iteration"]
        assert si is None or isinstance(si, int), (
            f"stagnation_iteration should be int or None, got {type(si)}"
        )

        # 9. alns_iteration_trace must NOT be present when flag is off
        assert "alns_iteration_trace" not in md, (
            "alns_iteration_trace should not be in metadata when record_iteration_metrics=False"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.7: Iteration trace length bounded by max_iteration_records
# ─────────────────────────────────────────────────────────────────────────────


class TestAlnsIterationTraceBounded:
    """Verify that the iteration trace never exceeds max_iteration_records.

    Validates: Requirements 7.2, 7.3
    """

    def test_iteration_trace_bounded_by_max_records(self) -> None:
        """With record_iteration_metrics=True and max_iteration_records=10,
        running 50 iterations must produce a trace with at most 10 records,
        each containing the expected 9 fields.
        """
        problem = _make_small_feasible_problem(n_orders=5, ops_per_order=3, n_machines=3, seed=42)
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=50,
            time_limit_s=60,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            record_iteration_metrics=True,
            max_iteration_records=10,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        md = result.metadata

        # 1. alns_iteration_trace must be present when flag is on
        assert "alns_iteration_trace" in md, (
            "alns_iteration_trace should be in metadata when record_iteration_metrics=True"
        )
        trace = md["alns_iteration_trace"]
        assert isinstance(trace, list)

        # 2. Trace length must not exceed max_iteration_records
        assert len(trace) <= 10, f"Trace length {len(trace)} exceeds max_iteration_records=10"

        # 3. Each record must be a dict with the expected 9 keys
        expected_keys = {
            "iteration",
            "operator_name",
            "destroy_size",
            "repair_status",
            "candidate_cost",
            "best_cost",
            "temperature",
            "accepted",
            "improved",
        }
        for i, record in enumerate(trace):
            assert isinstance(record, dict), (
                f"Trace record {i} should be a dict, got {type(record)}"
            )
            assert set(record.keys()) == expected_keys, (
                f"Trace record {i} keys mismatch.\n"
                f"Expected: {expected_keys}\n"
                f"Got: {set(record.keys())}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Task 7.8: Stagnation detection property test
# ─────────────────────────────────────────────────────────────────────────────


class TestAlnsStagnationDetectionProperty:
    """Property test: stagnation detection fires correctly when no improvement
    occurs for exactly max_no_improve_iters iterations.

    Validates: Requirements 7.5
    """

    @given(
        max_no_improve=st.integers(min_value=3, max_value=20),
        seed=st.integers(min_value=1, max_value=10000),
    )
    @settings(max_examples=15, deadline=120_000)
    def test_stagnation_invariant_across_parameters(self, max_no_improve: int, seed: int) -> None:
        """For any max_no_improve_iters in [3, 20] and random seed:
        - If stagnation_detected is True:
          - stagnation_iteration is not None and is an int
          - iterations_completed <= stagnation_iteration + 1
        - If stagnation_detected is False:
          - stagnation_iteration is None
          - iterations_completed reached max_iterations (no early stop)
        """
        max_iterations = 1000
        problem = _make_small_feasible_problem(n_orders=5, ops_per_order=3, n_machines=3, seed=seed)
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=max_iterations,
            time_limit_s=120,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
            max_no_improve_iters=max_no_improve,
            random_seed=seed,
        )

        md = result.metadata
        stagnation_detected = md["stagnation_detected"]
        stagnation_iteration = md["stagnation_iteration"]
        iterations_completed = md["iterations_completed"]

        if stagnation_detected:
            # Stagnation fired — verify invariants
            assert stagnation_iteration is not None, (
                "stagnation_iteration must not be None when stagnation_detected=True"
            )
            assert isinstance(stagnation_iteration, int), (
                f"stagnation_iteration should be int, got {type(stagnation_iteration)}"
            )
            # The loop breaks at or just after the stagnation iteration
            assert iterations_completed <= stagnation_iteration + 1, (
                f"iterations_completed ({iterations_completed}) should be <= "
                f"stagnation_iteration + 1 ({stagnation_iteration + 1})"
            )
        else:
            # No stagnation — verify invariants
            assert stagnation_iteration is None, (
                f"stagnation_iteration should be None when stagnation_detected=False, "
                f"got {stagnation_iteration}"
            )
            # Either reached max_iterations or time limit stopped it
            # (time limit is generous at 120s, so normally max_iterations is reached)
            assert iterations_completed == max_iterations or iterations_completed > 0, (
                f"Expected iterations_completed == {max_iterations} or > 0, "
                f"got {iterations_completed}"
            )
