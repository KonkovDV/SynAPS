"""Property-based tests for RHC budget kernels (R21).

Uses Hypothesis to check invariants that unit tests cannot exhaustively
sample: monotonicity, floor/ceiling clamping, and non-negativity across
the random-parameter surface.
"""

from __future__ import annotations

from hypothesis import given, settings, strategies as st

from synaps.solvers.rhc._budget import AlnsBudgetPolicy, scale_alns_inner_budget


class TestScaleAlnsInnerBudgetProperties:
    @given(
        per_window_limit=st.floats(min_value=1.0, max_value=600.0),
        destroy_fraction=st.floats(min_value=0.01, max_value=0.5),
        min_destroy=st.integers(min_value=1, max_value=100),
        max_destroy=st.integers(min_value=1, max_value=500),
        window_op_count=st.integers(min_value=1, max_value=10_000),
    )
    @settings(max_examples=200)
    def test_smaller_limit_reduces_or_keeps_caps(
        self,
        per_window_limit: float,
        destroy_fraction: float,
        min_destroy: int,
        max_destroy: int,
        window_op_count: int,
    ) -> None:
        """A tighter time limit must not increase either effective cap."""
        policy = AlnsBudgetPolicy(
            estimated_repair_s_per_destroyed_op_raw=0.1,
            dynamic_repair_time_limit_min_s=1.0,
            dynamic_repair_time_limit_max_s=5.0,
            dynamic_repair_s_per_destroyed_op=0.1,
        )
        kwargs = {
            "destroy_fraction": destroy_fraction,
            "min_destroy": min_destroy,
            "max_destroy": max_destroy,
        }
        result_lo = scale_alns_inner_budget(
            effective_kwargs=kwargs,
            per_window_limit=per_window_limit,
            window_op_count=window_op_count,
            policy=policy,
        )
        result_hi = scale_alns_inner_budget(
            effective_kwargs=kwargs,
            per_window_limit=per_window_limit * 2,
            window_op_count=window_op_count,
            policy=policy,
        )
        assert result_lo["effective_max_iterations"] <= result_hi["effective_max_iterations"]
        assert result_lo["effective_max_destroy"] <= result_hi["effective_max_destroy"]

    @given(
        per_window_limit=st.floats(min_value=1.0, max_value=600.0),
        window_op_count=st.integers(min_value=1, max_value=10_000),
    )
    @settings(max_examples=100)
    def test_outputs_are_non_negative(
        self,
        per_window_limit: float,
        window_op_count: int,
    ) -> None:
        """All scalar outputs must be >= 0."""
        result = scale_alns_inner_budget(
            effective_kwargs={
                "destroy_fraction": 0.05,
                "min_destroy": 20,
                "max_destroy": 300,
            },
            per_window_limit=per_window_limit,
            window_op_count=window_op_count,
            policy=AlnsBudgetPolicy(
                estimated_repair_s_per_destroyed_op_raw=0.1,
                dynamic_repair_time_limit_min_s=1.0,
                dynamic_repair_time_limit_max_s=5.0,
                dynamic_repair_s_per_destroyed_op=0.1,
            ),
        )
        assert result["effective_max_iterations"] >= 0
        assert result["effective_max_destroy"] >= 0
        assert result["effective_repair_time_limit_s"] >= 0.0

    @given(
        per_window_limit=st.floats(min_value=1.0, max_value=600.0),
        window_op_count=st.integers(min_value=1, max_value=10_000),
    )
    @settings(max_examples=100)
    def test_monotonic_in_iterations_vs_time(
        self,
        per_window_limit: float,
        window_op_count: int,
    ) -> None:
        """Doubling the time limit must not reduce max iterations."""
        policy = AlnsBudgetPolicy(
            estimated_repair_s_per_destroyed_op_raw=0.1,
            dynamic_repair_time_limit_min_s=1.0,
            dynamic_repair_time_limit_max_s=5.0,
            dynamic_repair_s_per_destroyed_op=0.1,
        )
        kwargs = {
            "destroy_fraction": 0.05,
            "min_destroy": 20,
            "max_destroy": 300,
        }
        result_lo = scale_alns_inner_budget(
            effective_kwargs=kwargs,
            per_window_limit=per_window_limit,
            window_op_count=window_op_count,
            policy=policy,
        )
        result_hi = scale_alns_inner_budget(
            effective_kwargs=kwargs,
            per_window_limit=per_window_limit * 2,
            window_op_count=window_op_count,
            policy=policy,
        )
        assert result_hi["effective_max_iterations"] >= result_lo["effective_max_iterations"]
