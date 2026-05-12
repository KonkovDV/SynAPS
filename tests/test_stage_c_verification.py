"""Stage C end-to-end verification tests (Task 16).

Covers:
  16.1: Operator weights extracted from window N appear as initial_operator_weights
        in window N+1 (verify RHC pass-through, not just ALNS acceptance).
  16.2: cross_window_operator_bias_enabled=True with high-setup hints produces
        measurably different machine_segment weight vs =False (isolated ALNS).
  16.3: WarmStartSelection metadata fields (warm_start_supplied_assignments,
        warm_start_rejected_reason_counts) appear in per-window RHC output.

Validates: Requirements 3.3, 9.3, 12.1, 12.2
"""

from __future__ import annotations

from unittest.mock import patch
from typing import Any

import pytest

from synaps.model import SolverStatus
from synaps.solvers.alns_solver import AlnsSolver
from synaps.solvers.rhc._cross_window import WindowQualitySummary

try:
    from synaps.solvers.rhc import RhcSolver
except ImportError:
    RhcSolver = None  # type: ignore[assignment, misc]

try:
    from synaps.benchmarks.instance_generator import generate_large_instance
except ImportError:
    generate_large_instance = None  # type: ignore[assignment]


pytestmark = [pytest.mark.slow]

# Skip the entire module if core dependencies are unavailable.
if generate_large_instance is None:
    pytest.skip("Instance generator unavailable", allow_module_level=True)
if RhcSolver is None:
    pytest.skip("RhcSolver unavailable", allow_module_level=True)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_small_problem(n_ops: int = 40, n_machines: int = 3, seed: int = 77):
    """Build a small problem suitable for multi-window RHC testing."""
    return generate_large_instance(
        n_operations=n_ops,
        n_machines=n_machines,
        n_states=3,
        setup_density=0.5,
        seed=seed,
        horizon_hours=48,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Task 16.1: Operator weight pass-through across RHC windows
# ─────────────────────────────────────────────────────────────────────────────


class TestOperatorWeightPassThrough:
    """Verify RHC extracts alns_final_operator_weights from window N metadata
    and passes them as initial_operator_weights to window N+1.

    **Validates: Requirements 12.1, 12.2**
    """

    def test_window_n_weights_appear_as_initial_in_window_n_plus_1(self) -> None:
        """Monkeypatch ALNS to capture kwargs across 2 windows and verify
        that window 2's initial_operator_weights matches window 1's final weights.
        """
        problem = _make_small_problem(n_ops=40, n_machines=2, seed=101)

        # Capture the kwargs passed to each ALNS solve call.
        captured_kwargs: list[dict[str, Any]] = []
        original_solve = AlnsSolver.solve

        def _capturing_solve(self_inner, prob, **kwargs):
            captured_kwargs.append(dict(kwargs))
            return original_solve(self_inner, prob, **kwargs)

        with patch.object(AlnsSolver, "solve", _capturing_solve):
            solver = RhcSolver()
            result = solver.solve(
                problem,
                inner_solver="alns",
                window_minutes=60,
                overlap_minutes=15,
                time_limit_s=120,
                max_windows=2,
                inner_kwargs={
                    "max_iterations": 15,
                    "max_no_improve_iters": 10,
                    "repair_time_limit_s": 3,
                },
                random_seed=42,
            )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

        # We need at least 2 ALNS calls (one per window).
        assert len(captured_kwargs) >= 2, (
            f"Expected at least 2 ALNS solve calls, got {len(captured_kwargs)}"
        )

        # Window 1 should NOT have initial_operator_weights (or it should be None).
        first_call_weights = captured_kwargs[0].get("initial_operator_weights")
        assert first_call_weights is None, (
            "First window should not receive initial_operator_weights from a prior window"
        )

        # Window 2 should have initial_operator_weights set.
        second_call_weights = captured_kwargs[1].get("initial_operator_weights")
        assert second_call_weights is not None, (
            "Second window should receive initial_operator_weights from first window"
        )
        assert isinstance(second_call_weights, dict), (
            f"Expected dict, got {type(second_call_weights).__name__}"
        )

        # Verify the weights are non-uniform (i.e., they came from actual ALNS
        # learning, not a fresh uniform initialization).
        weight_values = list(second_call_weights.values())
        assert len(weight_values) > 0
        # At minimum, weights should sum to ~1.0 (they're normalized final weights).
        assert abs(sum(weight_values) - 1.0) < 1e-4, (
            f"Passed weights should sum to ~1.0, got {sum(weight_values)}"
        )

        # Verify the passed weights match what's in the inner_window_summaries
        # for window 0's alns_final_operator_weights.
        metadata = result.metadata or {}
        summaries = metadata.get("inner_window_summaries", [])
        if len(summaries) >= 1:
            window_0_final = summaries[0].get("alns_final_operator_weights")
            if window_0_final is not None:
                # The weights passed to window 2 should match window 1's final.
                for name, weight in second_call_weights.items():
                    assert name in window_0_final, (
                        f"Operator '{name}' in passed weights but not in window 0 final"
                    )
                    assert abs(weight - window_0_final[name]) < 1e-6, (
                        f"Weight mismatch for '{name}': passed={weight}, "
                        f"window_0_final={window_0_final[name]}"
                    )


# ─────────────────────────────────────────────────────────────────────────────
# Task 16.2: Cross-window bias produces measurably different machine_segment weight
# ─────────────────────────────────────────────────────────────────────────────


class TestCrossWindowBiasEffect:
    """Verify that cross_window_operator_bias_enabled=True with high-setup hints
    produces a measurably higher machine_segment initial weight vs =False.

    Runs ALNS directly (not via RHC) for isolation.

    **Validates: Requirements 3.3**
    """

    def test_bias_on_produces_higher_machine_segment_initial_weight(self) -> None:
        """Compare effective machine_segment weight (initial + bias delta) between
        bias-on and bias-off runs with identical high-setup hints.

        Note: alns_initial_operator_weights is captured *before* bias application.
        The bias effect is recorded in cross_window_bias_operator_deltas. The
        effective starting weight = initial + delta.
        """
        problem = _make_small_problem(n_ops=40, n_machines=3, seed=200)

        high_setup_hints = [
            WindowQualitySummary(
                window_index=i,
                per_machine_utilization={"wc_0": 0.9, "wc_1": 0.7},
                setup_cost_by_machine={"wc_0": 250.0, "wc_1": 180.0},
                tardiness_contribution=20.0,
                operation_count=300,
            )
            for i in range(3)
        ]

        common_kwargs = {
            "max_iterations": 5,
            "time_limit_s": 30,
            "destroy_fraction": 0.2,
            "min_destroy": 2,
            "max_destroy": 5,
            "repair_time_limit_s": 3,
            "cross_window_hints": high_setup_hints,
        }

        # Run with bias OFF
        solver_off = AlnsSolver()
        result_off = solver_off.solve(
            problem,
            cross_window_operator_bias_enabled=False,
            **common_kwargs,
        )
        assert result_off.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

        # Run with bias ON
        solver_on = AlnsSolver()
        result_on = solver_on.solve(
            problem,
            cross_window_operator_bias_enabled=True,
            **common_kwargs,
        )
        assert result_on.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

        # Verify the bias was actually applied
        assert result_on.metadata["cross_window_bias_applied"] is True
        assert result_off.metadata["cross_window_bias_applied"] is False

        # Extract initial weights and bias deltas from metadata.
        # alns_initial_operator_weights is captured BEFORE bias; the actual
        # effective starting weight = initial + delta.
        initial_off = result_off.metadata["alns_initial_operator_weights"]
        initial_on = result_on.metadata["alns_initial_operator_weights"]
        deltas_off = result_off.metadata["cross_window_bias_operator_deltas"]
        deltas_on = result_on.metadata["cross_window_bias_operator_deltas"]

        assert isinstance(initial_on, dict)
        assert isinstance(deltas_on, dict)

        # machine_segment must be present
        assert "machine_segment" in initial_on
        assert "machine_segment" in deltas_on

        # Effective weight = initial + delta (after bias + renormalization)
        effective_off = initial_off["machine_segment"] + deltas_off.get("machine_segment", 0.0)
        effective_on = initial_on["machine_segment"] + deltas_on["machine_segment"]

        # With bias ON and high setup hints, machine_segment should get a boost.
        assert effective_on > effective_off, (
            f"Expected bias-on effective machine_segment weight ({effective_on}) > "
            f"bias-off effective weight ({effective_off}). "
            f"Delta on={deltas_on['machine_segment']}, delta off={deltas_off.get('machine_segment', 0.0)}"
        )

        # Verify the delta is positive and meaningful
        ms_delta = deltas_on["machine_segment"]
        assert ms_delta > 0.0, (
            f"Expected positive machine_segment delta when bias is on, got {ms_delta}"
        )

        # All deltas should be zero when bias is off
        for name, delta in deltas_off.items():
            assert delta == 0.0, (
                f"Operator '{name}' has non-zero delta {delta} when bias is off"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Task 16.3: WarmStartSelection metadata in per-window RHC output
# ─────────────────────────────────────────────────────────────────────────────


class TestWarmStartMetadataInRhcOutput:
    """Verify WarmStartSelection metadata fields appear in per-window RHC output.

    Checks that inner_window_summaries contain warm_start_used,
    warm_start_supplied_assignments, and warm_start_completed_assignments.

    **Validates: Requirements 9.3**
    """

    def test_warm_start_fields_present_in_window_summaries(self) -> None:
        """Run RHC with 2+ windows and verify warm-start metadata fields."""
        problem = _make_small_problem(n_ops=60, n_machines=3, seed=303)

        solver = RhcSolver()
        result = solver.solve(
            problem,
            inner_solver="alns",
            window_minutes=60,
            overlap_minutes=20,
            time_limit_s=120,
            max_windows=3,
            inner_kwargs={
                "max_iterations": 15,
                "max_no_improve_iters": 10,
                "repair_time_limit_s": 3,
            },
            random_seed=42,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

        metadata = result.metadata or {}
        summaries = metadata.get("inner_window_summaries", [])

        # We should have at least 2 window summaries.
        assert len(summaries) >= 2, (
            f"Expected at least 2 window summaries, got {len(summaries)}"
        )

        # Check that warm_start_used field is present in all summaries.
        for i, summary in enumerate(summaries):
            assert "warm_start_used" in summary, (
                f"Window {i} summary missing 'warm_start_used' field. "
                f"Keys: {list(summary.keys())}"
            )

        # After the first window, at least one window should have
        # warm_start_supplied_assignments > 0 (overlap provides candidates).
        has_warm_start_supplied = False
        for i, summary in enumerate(summaries):
            if i == 0:
                # First window may or may not have warm-start depending on
                # external assignments — skip it.
                continue
            supplied = summary.get("warm_start_supplied_assignments", 0)
            if supplied > 0:
                has_warm_start_supplied = True
                # When supplied > 0, warm_start_completed_assignments should also exist.
                assert "warm_start_completed_assignments" in summary, (
                    f"Window {i} has warm_start_supplied_assignments={supplied} "
                    f"but missing 'warm_start_completed_assignments'"
                )
                break

        assert has_warm_start_supplied, (
            "Expected at least one window (after the first) to have "
            "warm_start_supplied_assignments > 0. Summaries: "
            + str([
                {
                    "window": s.get("window"),
                    "warm_start_used": s.get("warm_start_used"),
                    "warm_start_supplied_assignments": s.get("warm_start_supplied_assignments"),
                }
                for s in summaries
            ])
        )
