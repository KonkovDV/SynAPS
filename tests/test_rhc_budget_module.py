"""Unit tests for the R7 RHC `_budget` pure kernels.

Locks in the exact arithmetic of `resolve_inner_window_time_cap` and
`scale_alns_inner_budget` so the rest of the Wave 4 R7 decomposition
cannot drift the per-window budget contract that downstream telemetry
and the ALNS solver depend on.
"""
from __future__ import annotations

from synaps.solvers.rhc._budget import (
    AlnsBudgetPolicy,
    EmpiricalRepairCostEstimator,
    InnerWindowTimeCapPolicy,
    resolve_inner_window_time_cap,
    scale_alns_inner_budget,
)


def _default_cap_policy(
    *,
    inner_cap: float | None = None,
    alns_cap: float | None = None,
    scaled_s: float = 180.0,
    threshold: int = 4000,
) -> InnerWindowTimeCapPolicy:
    return InnerWindowTimeCapPolicy(
        inner_window_time_cap_s=inner_cap,
        alns_inner_window_time_cap_s=alns_cap,
        alns_inner_window_time_cap_scaled_s=scaled_s,
        alns_inner_window_time_cap_scale_threshold_ops=threshold,
    )


def _default_budget_policy(
    *,
    raw: float | None = None,
    min_s: float = 1.0,
    max_s: float = 5.0,
    slope: float = 0.1,
) -> AlnsBudgetPolicy:
    return AlnsBudgetPolicy(
        estimated_repair_s_per_destroyed_op_raw=raw,
        dynamic_repair_time_limit_min_s=min_s,
        dynamic_repair_time_limit_max_s=max_s,
        dynamic_repair_s_per_destroyed_op=slope,
    )


class TestResolveInnerWindowTimeCap:
    def test_alns_specific_cap_takes_priority(self) -> None:
        policy = _default_cap_policy(inner_cap=30.0, alns_cap=15.0)
        assert (
            resolve_inner_window_time_cap(
                selected_solver_name="alns",
                window_op_count=1000,
                policy=policy,
            )
            == 15.0
        )

    def test_alns_falls_back_to_global_cap_when_alns_cap_unset(self) -> None:
        policy = _default_cap_policy(inner_cap=30.0)
        assert (
            resolve_inner_window_time_cap(
                selected_solver_name="alns",
                window_op_count=1000,
                policy=policy,
            )
            == 30.0
        )

    def test_alns_uses_scaled_cap_above_threshold(self) -> None:
        policy = _default_cap_policy(scaled_s=180.0, threshold=4000)
        assert (
            resolve_inner_window_time_cap(
                selected_solver_name="alns",
                window_op_count=4500,
                policy=policy,
            )
            == 180.0
        )

    def test_alns_uses_default_60s_below_threshold_with_no_caps(self) -> None:
        policy = _default_cap_policy(scaled_s=180.0, threshold=4000)
        assert (
            resolve_inner_window_time_cap(
                selected_solver_name="alns",
                window_op_count=100,
                policy=policy,
            )
            == 60.0
        )

    def test_non_alns_uses_global_cap(self) -> None:
        policy = _default_cap_policy(inner_cap=42.0, alns_cap=15.0)
        assert (
            resolve_inner_window_time_cap(
                selected_solver_name="cpsat",
                window_op_count=10,
                policy=policy,
            )
            == 42.0
        )

    def test_non_alns_falls_back_to_default_when_no_cap(self) -> None:
        policy = _default_cap_policy()
        assert (
            resolve_inner_window_time_cap(
                selected_solver_name="cpsat",
                window_op_count=10,
                policy=policy,
            )
            == 60.0
        )


class TestScaleAlnsInnerBudget:
    def test_returns_all_seven_contract_keys(self) -> None:
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 100, "max_destroy": 50, "min_destroy": 10},
            per_window_limit=60.0,
            window_op_count=200,
            policy=_default_budget_policy(),
        )
        expected_keys = {
            "requested_max_iterations",
            "requested_max_destroy",
            "effective_max_iterations",
            "effective_max_destroy",
            "effective_repair_time_limit_s",
            "estimated_repair_s_per_destroyed_op",
            "scaled",
        }
        assert set(result.keys()) == expected_keys

    def test_scaled_flag_false_when_caps_match_request(self) -> None:
        # Generous budget: should not need to scale anything.
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 10, "max_destroy": 20, "min_destroy": 10},
            per_window_limit=10000.0,
            window_op_count=100,
            policy=_default_budget_policy(raw=0.01),
        )
        assert result["effective_max_iterations"] == result["requested_max_iterations"]
        assert result["effective_max_destroy"] == result["requested_max_destroy"]
        assert result["scaled"] is False

    def test_scaled_flag_true_when_budget_forces_iter_reduction(self) -> None:
        # Tight budget should force effective_max_iterations < requested.
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 1000, "max_destroy": 50, "min_destroy": 10},
            per_window_limit=1.0,
            window_op_count=200,
            policy=_default_budget_policy(raw=0.5),
        )
        assert result["effective_max_iterations"] < result["requested_max_iterations"]
        assert result["scaled"] is True

    def test_estimated_repair_uses_policy_when_raw_provided(self) -> None:
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 100, "max_destroy": 50, "min_destroy": 10},
            per_window_limit=60.0,
            window_op_count=200,
            policy=_default_budget_policy(raw=0.25),
        )
        assert result["estimated_repair_s_per_destroyed_op"] == 0.25

    def test_estimated_repair_falls_back_to_repair_limit_over_destroy(self) -> None:
        result = scale_alns_inner_budget(
            effective_kwargs={
                "max_iterations": 100,
                "max_destroy": 50,
                "min_destroy": 10,
                "repair_time_limit_s": 10.0,
            },
            per_window_limit=60.0,
            window_op_count=200,
            policy=_default_budget_policy(raw=None),
        )
        # Fallback: repair_time_limit_s / max_destroy = 10.0 / 50 = 0.2.
        assert abs(result["estimated_repair_s_per_destroyed_op"] - 0.2) < 1e-9

    def test_repair_time_limit_clamped_to_policy_max(self) -> None:
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 100, "max_destroy": 1000, "min_destroy": 10},
            per_window_limit=10000.0,
            window_op_count=2000,
            policy=_default_budget_policy(raw=0.001, min_s=0.1, max_s=3.0, slope=10.0),
        )
        assert result["effective_repair_time_limit_s"] <= 3.0

    def test_repair_time_limit_floored_to_policy_min(self) -> None:
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 100, "max_destroy": 50, "min_destroy": 10},
            per_window_limit=60.0,
            window_op_count=20,
            policy=_default_budget_policy(min_s=2.5, max_s=5.0, slope=0.0001),
        )
        assert result["effective_repair_time_limit_s"] >= 2.5

    def test_min_destroy_respected_even_under_tight_budget(self) -> None:
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 1000, "max_destroy": 200, "min_destroy": 25},
            per_window_limit=0.5,
            window_op_count=500,
            policy=_default_budget_policy(raw=1.0),
        )
        assert result["effective_max_destroy"] >= 25

    def test_caller_kwargs_dict_not_mutated(self) -> None:
        kwargs = {"max_iterations": 50, "max_destroy": 30, "min_destroy": 5}
        original = dict(kwargs)
        scale_alns_inner_budget(
            effective_kwargs=kwargs,
            per_window_limit=10.0,
            window_op_count=100,
            policy=_default_budget_policy(raw=0.1),
        )
        assert kwargs == original

    def test_override_wins_over_policy_raw(self) -> None:
        # Policy raw says 0.1, override says 0.5 ⇒ kernel should use 0.5.
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 100, "max_destroy": 50, "min_destroy": 10},
            per_window_limit=60.0,
            window_op_count=200,
            policy=_default_budget_policy(raw=0.1),
            override_estimated_repair_s_per_destroyed_op=0.5,
        )
        assert result["estimated_repair_s_per_destroyed_op"] == 0.5

    def test_override_floored_at_001(self) -> None:
        result = scale_alns_inner_budget(
            effective_kwargs={"max_iterations": 100, "max_destroy": 50, "min_destroy": 10},
            per_window_limit=60.0,
            window_op_count=200,
            policy=_default_budget_policy(raw=0.5),
            override_estimated_repair_s_per_destroyed_op=0.0001,
        )
        assert result["estimated_repair_s_per_destroyed_op"] == 0.01


class TestEmpiricalRepairCostEstimator:
    def test_initial_state(self) -> None:
        e = EmpiricalRepairCostEstimator()
        assert e.current() is None
        assert e.observation_count == 0

    def test_first_observation_initializes_exactly(self) -> None:
        e = EmpiricalRepairCostEstimator(alpha=0.3)
        result = e.update(0.5)
        assert result == 0.5
        assert e.current() == 0.5
        assert e.observation_count == 1

    def test_second_observation_blends_with_alpha(self) -> None:
        # alpha=0.3, prior=0.5, observed=0.1 ⇒ 0.3*0.1 + 0.7*0.5 = 0.38
        e = EmpiricalRepairCostEstimator(alpha=0.3)
        e.update(0.5)
        result = e.update(0.1)
        assert abs(result - 0.38) < 1e-9
        assert e.observation_count == 2

    def test_none_observation_ignored(self) -> None:
        e = EmpiricalRepairCostEstimator()
        e.update(0.5)
        before = e.estimate
        result = e.update(None)
        assert result == before
        assert e.observation_count == 1  # not incremented

    def test_zero_or_negative_observation_ignored(self) -> None:
        e = EmpiricalRepairCostEstimator()
        e.update(0.5)
        e.update(0.0)
        e.update(-1.0)
        assert e.estimate == 0.5
        assert e.observation_count == 1

    def test_alpha_one_is_pure_replacement(self) -> None:
        e = EmpiricalRepairCostEstimator(alpha=1.0)
        e.update(0.5)
        e.update(0.1)
        assert e.estimate == 0.1

    def test_alpha_zero_is_pure_history(self) -> None:
        e = EmpiricalRepairCostEstimator(alpha=0.0)
        e.update(0.5)
        e.update(0.9)  # ignored by smoothing weight
        assert e.estimate == 0.5

    def test_long_run_converges_to_observation_mean(self) -> None:
        # Repeatedly feed the same value; EMA must converge to it.
        e = EmpiricalRepairCostEstimator(alpha=0.3)
        target = 0.42
        for _ in range(100):
            e.update(target)
        assert abs(e.estimate - target) < 1e-9
