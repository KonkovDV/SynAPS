"""Tests for Phase 1 features: instrumentation, guards, contract versioning."""

from __future__ import annotations

import threading

import pytest

from synaps.contracts import (
    CONTRACT_VERSION,
    ContractVersionError,
    SUPPORTED_CONTRACT_VERSIONS,
    check_contract_version,
)
from synaps.guards import (
    ResourceLimits,
    SolverTimeoutError,
    guarded_solve,
    timeout_to_error_result,
)
from synaps.instrumentation import (
    MetricsCollector,
    MetricsStore,
    clear_collectors,
    get_metrics_store,
    record_feasibility_event,
    record_routing_event,
    record_solve_event,
    register_collector,
)
from synaps.model import SolverErrorCategory, SolverStatus
from tests.conftest import make_simple_problem


# ── Instrumentation tests ──


class TestMetricsStore:
    def test_record_solve_tracks_stats(self) -> None:
        store = MetricsStore()
        store.record_solve("CPSAT-30", "optimal", 500, 120)
        store.record_solve("CPSAT-30", "feasible", 300, 80)

        summary = store.summary()
        cpsat = summary["solvers"]["CPSAT-30"]
        assert cpsat["call_count"] == 2
        assert cpsat["total_duration_ms"] == 800
        assert cpsat["avg_duration_ms"] == 400.0
        assert cpsat["min_duration_ms"] == 300
        assert cpsat["max_duration_ms"] == 500
        assert cpsat["status_counts"]["optimal"] == 1
        assert cpsat["status_counts"]["feasible"] == 1

    def test_record_routing(self) -> None:
        store = MetricsStore()
        store.record_routing("CPSAT-30", "nominal")
        store.record_routing("CPSAT-30", "nominal")
        store.record_routing("GREED", "interactive")

        summary = store.summary()
        assert summary["routing_decisions"]["nominal:CPSAT-30"] == 2
        assert summary["routing_decisions"]["interactive:GREED"] == 1

    def test_record_feasibility(self) -> None:
        store = MetricsStore()
        store.record_feasibility(True)
        store.record_feasibility(False, ["overlap", "precedence"])
        store.record_feasibility(False, ["overlap"])

        summary = store.summary()
        assert summary["feasibility"]["pass"] == 1
        assert summary["feasibility"]["fail"] == 2
        assert summary["violation_kinds"]["overlap"] == 2
        assert summary["violation_kinds"]["precedence"] == 1

    def test_reset_clears_all(self) -> None:
        store = MetricsStore()
        store.record_solve("GREED", "feasible", 10, 5)
        store.reset()
        summary = store.summary()
        assert summary["solvers"] == {}

    def test_thread_safety(self) -> None:
        store = MetricsStore()
        errors: list[Exception] = []

        def _writer(offset: int) -> None:
            try:
                for i in range(100):
                    store.record_solve(f"SOLVER-{offset}", "ok", i, i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_writer, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        summary = store.summary()
        for i in range(4):
            assert summary["solvers"][f"SOLVER-{i}"]["call_count"] == 100


class TestCollectorIntegration:
    def setup_method(self) -> None:
        clear_collectors()
        get_metrics_store().reset()

    def teardown_method(self) -> None:
        clear_collectors()

    def test_custom_collector_receives_events(self) -> None:
        events: list[dict] = []

        class Spy:
            def on_solve_event(self, solver_config, **kw):
                events.append({"type": "solve", "solver": solver_config, **kw})

            def on_routing_event(self, solver_config, **kw):
                events.append({"type": "routing", "solver": solver_config, **kw})

            def on_feasibility_event(self, **kw):
                events.append({"type": "feasibility", **kw})

        register_collector(Spy())

        record_solve_event("CPSAT-30", status="optimal", duration_ms=100, op_count=10)
        record_routing_event("CPSAT-30", regime="nominal", reason="small instance")
        record_feasibility_event(feasible=True, violation_count=0, violation_kinds=[])

        assert len(events) == 3
        assert events[0]["type"] == "solve"
        assert events[1]["type"] == "routing"
        assert events[2]["type"] == "feasibility"


# ── Guards tests ──


class TestResourceLimits:
    def test_defaults(self) -> None:
        limits = ResourceLimits()
        assert limits.timeout_s is None
        assert limits.memory_limit_mb is None
        assert limits.fail_open is True

    def test_guarded_solve_without_limits_delegates(self) -> None:
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        problem = make_simple_problem()
        solver = GreedyDispatch()
        result = guarded_solve(solver, problem, limits=None)
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

    def test_guarded_solve_with_generous_timeout(self) -> None:
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        problem = make_simple_problem()
        solver = GreedyDispatch()
        limits = ResourceLimits(timeout_s=30)
        result = guarded_solve(solver, problem, limits=limits)
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

    def test_timeout_to_error_result(self) -> None:
        err = SolverTimeoutError("test timeout")
        result = timeout_to_error_result("CPSAT-30", err)
        assert result.status == SolverStatus.TIMEOUT
        assert result.error_category == SolverErrorCategory.TIMEOUT_NO_SOLUTION
        assert "test timeout" in str(result.metadata.get("guard_error"))


# ── Contract versioning tests ──


class TestContractVersioning:
    def test_current_version_is_supported(self) -> None:
        check_contract_version(CONTRACT_VERSION)

    def test_unsupported_version_raises(self) -> None:
        with pytest.raises(ContractVersionError, match="not supported"):
            check_contract_version("1999-01-01")

    def test_supported_versions_includes_current(self) -> None:
        assert CONTRACT_VERSION in SUPPORTED_CONTRACT_VERSIONS


# ── Industry benchmark presets ──


class TestIndustryPresets:
    @pytest.mark.parametrize("preset_name", ["pharma", "semiconductor", "food-beverage"])
    def test_industry_preset_generates_valid_problem(self, preset_name: str) -> None:
        from benchmark.generate_instances import generate_problem, preset_spec

        spec = preset_spec(preset_name, seed=42)
        problem = generate_problem(spec)

        assert len(problem.operations) > 0
        assert len(problem.work_centers) > 0
        assert len(problem.orders) > 0
