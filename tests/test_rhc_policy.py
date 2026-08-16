"""Tests for the typed RhcPolicy layer."""

from __future__ import annotations

import warnings

import pytest

from synaps.solvers.rhc._policy import (
    RhcPolicy,
    RhcPolicySpec,
    build_solve_kwargs_from_spec,
    resolve_policy,
)


class TestPresets:
    def test_coverage_first_has_600_180(self) -> None:
        spec = RhcPolicySpec.from_preset(RhcPolicy.COVERAGE_FIRST)
        assert spec.admission.window_minutes == 600
        assert spec.admission.overlap_minutes == 180

    def test_search_entry_has_300_90(self) -> None:
        spec = RhcPolicySpec.from_preset(RhcPolicy.SEARCH_ENTRY)
        assert spec.admission.window_minutes == 300
        assert spec.admission.overlap_minutes == 90

    def test_balanced_roundtrips_kwargs(self) -> None:
        spec = RhcPolicySpec.from_preset(RhcPolicy.BALANCED)
        kwargs = build_solve_kwargs_from_spec(spec)
        assert kwargs["window_minutes"] == 480
        assert kwargs["overlap_minutes"] == 120
        assert kwargs["inner_solver"] == "alns"
        assert kwargs["inner_kwargs"]["max_iterations"] == 100


class TestOverrides:
    def test_flat_override_wins(self) -> None:
        spec = RhcPolicySpec.from_preset(RhcPolicy.BALANCED)
        kwargs = build_solve_kwargs_from_spec(spec, overrides={"window_minutes": 600})
        assert kwargs["window_minutes"] == 600
        assert kwargs["overlap_minutes"] == 120  # unchanged

    def test_dotted_override_wins(self) -> None:
        spec = RhcPolicySpec.from_preset(RhcPolicy.BALANCED)
        kwargs = build_solve_kwargs_from_spec(spec, overrides={"admission.window_minutes": 600})
        assert kwargs["window_minutes"] == 600

    def test_unknown_override_ignored(self) -> None:
        spec = RhcPolicySpec.from_preset(RhcPolicy.BALANCED)
        kwargs = build_solve_kwargs_from_spec(spec, overrides={"unknown_key": 42})
        assert "unknown_key" not in kwargs


class TestResolvePolicy:
    def test_defaults_to_balanced(self) -> None:
        spec, _kwargs = resolve_policy()
        assert spec.admission.window_minutes == 480

    def test_deprecated_kwargs_warns_once(self) -> None:
        with pytest.warns(DeprecationWarning, match="raw kwargs"):
            _spec, kwargs = resolve_policy(window_minutes=600)
        assert kwargs["window_minutes"] == 600

    def test_no_warning_when_policy_given(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            resolve_policy(policy=RhcPolicy.BALANCED)


class TestEveryPresetInRegistry:
    """Each preset must roundtrip into the kwargs used by registry.py."""

    @pytest.mark.parametrize(
        "policy",
        [
            RhcPolicy.COVERAGE_FIRST,
            RhcPolicy.BALANCED,
            RhcPolicy.SEARCH_ENTRY,
            RhcPolicy.BOUNDED_100K,
            RhcPolicy.FAST_50K,
            RhcPolicy.GREEDY_COVER,
        ],
    )
    def test_preset_yields_finite_kwargs(self, policy: RhcPolicy) -> None:
        spec = RhcPolicySpec.from_preset(policy)
        kwargs = build_solve_kwargs_from_spec(spec)
        assert isinstance(kwargs["window_minutes"], int)
        assert kwargs["window_minutes"] > 0
        assert isinstance(kwargs["overlap_minutes"], int)
        assert kwargs["overlap_minutes"] >= 0
        assert isinstance(kwargs["inner_solver"], str)

    def test_greedy_cover_reserves_coverage_budget(self) -> None:
        spec = RhcPolicySpec.from_preset(RhcPolicy.GREEDY_COVER)
        kwargs = build_solve_kwargs_from_spec(spec)
        assert kwargs["inner_solver"] == "greedy"
        assert kwargs["coverage_time_reserve_fraction"] == 0.20
        assert kwargs["fallback_repair_on_timeout"] is True
        assert kwargs["coverage_horizon_extension_factor"] == 1.0
        assert kwargs["backtracking_enabled"] is False
