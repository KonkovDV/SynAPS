"""Tests for the W1 coverage pace guard (outer/inner objective alignment)."""

from __future__ import annotations

import pytest

from synaps.solvers.rhc import RhcSolver
from synaps.solvers.rhc._budget import CoveragePaceController
from synaps.solvers.rhc._policy import RhcPolicy, RhcPolicySpec, build_solve_kwargs_from_spec
from tests.conftest import make_simple_problem

# ---------------------------------------------------------------------------
# Pure controller unit tests
# ---------------------------------------------------------------------------


class TestCoveragePaceController:
    def test_no_intervention_before_min_windows(self) -> None:
        controller = CoveragePaceController(
            total_ops=1000, time_limit_s=100.0, threshold=1.0, min_windows=2
        )
        controller.observe_window(1)
        # One window observed, min is 2 — never intervene regardless of pace.
        assert controller.should_intervene(elapsed_s=50.0) is False

    def test_intervenes_when_projection_below_threshold(self) -> None:
        controller = CoveragePaceController(
            total_ops=1000, time_limit_s=100.0, threshold=1.0, min_windows=2
        )
        # 2 windows, 100 ops in 50s → rate 2 ops/s → projected 100 + 2*50 = 200 < 1000.
        controller.observe_window(50)
        controller.observe_window(50)
        ratio = controller.pace_ratio(elapsed_s=50.0)
        assert ratio == pytest.approx(0.2)
        assert controller.should_intervene(elapsed_s=50.0) is True

    def test_no_intervention_when_on_pace(self) -> None:
        controller = CoveragePaceController(
            total_ops=100, time_limit_s=100.0, threshold=1.0, min_windows=2
        )
        # 60 ops in 50s → rate 1.2 → projected 60 + 1.2*50 = 120 ≥ 100.
        controller.observe_window(30)
        controller.observe_window(30)
        assert controller.pace_ratio(elapsed_s=50.0) == pytest.approx(1.2)
        assert controller.should_intervene(elapsed_s=50.0) is False

    def test_pace_ratio_undefined_edges(self) -> None:
        controller = CoveragePaceController(total_ops=0, time_limit_s=100.0)
        assert controller.pace_ratio(elapsed_s=10.0) is None
        controller = CoveragePaceController(total_ops=10, time_limit_s=100.0)
        assert controller.pace_ratio(elapsed_s=0.0) is None
        assert controller.should_intervene(elapsed_s=0.0) is False

    def test_negative_commit_counts_clamped(self) -> None:
        controller = CoveragePaceController(total_ops=10, time_limit_s=100.0)
        controller.observe_window(-5)
        assert controller.ops_committed_total == 0
        assert controller.windows_observed == 1

    def test_elapsed_beyond_time_limit_projects_no_future_commits(self) -> None:
        controller = CoveragePaceController(
            total_ops=100, time_limit_s=10.0, threshold=1.0, min_windows=1
        )
        controller.observe_window(40)
        # elapsed > time_limit → remaining clamps to 0 → projection = committed.
        assert controller.pace_ratio(elapsed_s=20.0) == pytest.approx(0.4)
        assert controller.should_intervene(elapsed_s=20.0) is True


# ---------------------------------------------------------------------------
# RHC integration: opt-in default and metadata surface
# ---------------------------------------------------------------------------


class TestRhcCoveragePaceMetadata:
    def test_disabled_by_default_and_metadata_present(self) -> None:
        problem = make_simple_problem(n_orders=2, ops_per_order=2)
        result = RhcSolver().solve(
            problem,
            inner_solver="greedy",
            time_limit_s=30,
            window_minutes=240,
            overlap_minutes=60,
        )
        meta = result.metadata
        assert meta["coverage_pace_guard_enabled"] is False
        assert meta["coverage_pace_interventions"] == 0
        assert meta["coverage_pace_final_ratio"] is None

    def test_enabled_reports_final_ratio(self) -> None:
        problem = make_simple_problem(n_orders=2, ops_per_order=2)
        result = RhcSolver().solve(
            problem,
            inner_solver="greedy",
            time_limit_s=30,
            window_minutes=240,
            overlap_minutes=60,
            coverage_pace_guard_enabled=True,
            coverage_pace_threshold=1.0,
            coverage_pace_min_windows=1,
        )
        meta = result.metadata
        assert meta["coverage_pace_guard_enabled"] is True
        assert meta["coverage_pace_threshold"] == 1.0
        assert meta["coverage_pace_min_windows"] == 1
        # Greedy inner path never triggers the guard (it only reroutes
        # non-greedy windows), so interventions stay zero here.
        assert meta["coverage_pace_interventions"] == 0
        assert meta["coverage_pace_final_ratio"] is not None


# ---------------------------------------------------------------------------
# W2: SEARCH_COVER preset and registry config wiring
# ---------------------------------------------------------------------------


class TestSearchCoverPreset:
    def test_preset_flattens_pace_guard_kwargs(self) -> None:
        spec = RhcPolicySpec.from_preset(RhcPolicy.SEARCH_COVER)
        kwargs = build_solve_kwargs_from_spec(spec)
        assert kwargs["window_minutes"] == 360
        assert kwargs["overlap_minutes"] == 90
        assert kwargs["coverage_pace_guard_enabled"] is True
        assert kwargs["coverage_pace_threshold"] == 1.0
        assert kwargs["coverage_pace_min_windows"] == 2
        assert kwargs["coverage_time_reserve_fraction"] == 0.15
        assert kwargs["alns_presearch_max_window_ops"] == 2000
        assert kwargs["inner_solver"] == "alns"

    def test_registry_exposes_search_cover_config(self) -> None:
        from synaps.solvers.registry import available_solver_configs, create_solver

        assert "RHC-ALNS-SEARCH-COVER" in available_solver_configs()
        solver, solve_kwargs = create_solver("RHC-ALNS-SEARCH-COVER")
        assert solver.name == "rhc"
        assert solve_kwargs["coverage_pace_guard_enabled"] is True

    def test_default_presets_keep_guard_disabled(self) -> None:
        for policy in (RhcPolicy.BALANCED, RhcPolicy.GREEDY_COVER, RhcPolicy.FAST_50K):
            kwargs = build_solve_kwargs_from_spec(RhcPolicySpec.from_preset(policy))
            assert kwargs["coverage_pace_guard_enabled"] is False, policy
