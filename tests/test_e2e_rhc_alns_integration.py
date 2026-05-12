"""E2E integration test for the full RHC-ALNS stack with all Stage A–E features.

Validates: Task 13a — all new features work together on a synthetic 500-op instance.

Tests:
  13a.1: Synthetic 500-operation instance setup
  13a.2: Enable critical-path + due-pressure operators, warm-start, operator weight
         persistence (by name), gap metadata, convergence metadata
  13a.3: Assert result is feasible (zero FeasibilityChecker violations)
  13a.4: Assert metadata fields populated: warm_start_used,
         warm_start_completed_assignments, alns_final_operator_weights (dict),
         alns_gap_ratio, stagnation_detected, alns_operator_names
  13a.5: Assert cross-window telemetry flag toggle works
"""

from __future__ import annotations

import pytest

from synaps.model import SolverStatus
from synaps.validation import verify_schedule_result

try:
    from synaps.benchmarks.instance_generator import generate_large_instance
except ImportError:
    generate_large_instance = None  # type: ignore[assignment]

try:
    from synaps.solvers.rhc import RhcSolver
except ImportError:
    RhcSolver = None  # type: ignore[assignment, misc]


pytestmark = [pytest.mark.slow, pytest.mark.integration]

# Skip the entire module if core dependencies are unavailable.
if generate_large_instance is None:
    pytest.skip("Instance generator unavailable", allow_module_level=True)
if RhcSolver is None:
    pytest.skip("RhcSolver unavailable", allow_module_level=True)


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixture: 500-operation synthetic instance (Task 13a.1)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def problem_500():
    """Generate a deterministic 500-operation instance for E2E testing."""
    return generate_large_instance(
        n_operations=500,
        n_machines=10,
        n_states=5,
        setup_density=0.5,
        seed=42,
    )


def _solve_rhc(problem, *, cross_window_learning_enabled: bool = False, **extra_kwargs):
    """Run RHC-ALNS with the standard E2E configuration (Task 13a.2)."""
    kwargs = {
        "inner_solver": "alns",
        "window_minutes": 120,
        "overlap_minutes": 30,
        "time_limit_s": 120,
        "inner_kwargs": {
            "max_iterations": 30,
            "max_no_improve_iters": 15,
            "record_iteration_metrics": True,
            "max_iteration_records": 100,
        },
        "cross_window_learning_enabled": cross_window_learning_enabled,
        "random_seed": 42,
    }
    kwargs.update(extra_kwargs)
    solver = RhcSolver()
    return solver.solve(problem, **kwargs)


# Module-scoped solve results to avoid redundant solves across test classes.
_result_cache: dict[str, object] = {}


@pytest.fixture(scope="module")
def rhc_result_disabled(problem_500):
    """Solve with cross_window_learning_enabled=False (shared across tests)."""
    if "disabled" not in _result_cache:
        _result_cache["disabled"] = _solve_rhc(
            problem_500, cross_window_learning_enabled=False
        )
    return _result_cache["disabled"]


@pytest.fixture(scope="module")
def rhc_result_enabled(problem_500):
    """Solve with cross_window_learning_enabled=True (shared across tests)."""
    if "enabled" not in _result_cache:
        _result_cache["enabled"] = _solve_rhc(
            problem_500, cross_window_learning_enabled=True
        )
    return _result_cache["enabled"]


# ─────────────────────────────────────────────────────────────────────────────
# Task 13a.2 + 13a.3: Feasibility assertion
# ─────────────────────────────────────────────────────────────────────────────


class TestE2EFeasibility:
    """Assert the RHC-ALNS result is feasible with zero violations (Task 13a.3)."""

    def test_result_status_is_feasible_or_optimal(self, rhc_result_disabled) -> None:
        """Solver must return FEASIBLE or OPTIMAL status."""
        assert rhc_result_disabled.status in {
            SolverStatus.FEASIBLE,
            SolverStatus.OPTIMAL,
        }, f"Unexpected status: {rhc_result_disabled.status}"

    def test_zero_feasibility_violations(
        self, problem_500, rhc_result_disabled
    ) -> None:
        """FeasibilityChecker must report zero violations."""
        verification = verify_schedule_result(problem_500, rhc_result_disabled)
        assert verification.feasible, (
            f"Schedule is infeasible: {verification.violation_count} violations "
            f"({verification.violation_kinds})"
        )
        assert verification.violation_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# Task 13a.4: Metadata fields populated
# ─────────────────────────────────────────────────────────────────────────────


class TestE2EMetadata:
    """Assert required metadata fields are populated (Task 13a.4).

    RHC metadata nests inner solver metadata inside `inner_window_summaries`.
    We check both top-level RHC metadata and per-window summaries.
    """

    def test_alns_operator_names_present(self, rhc_result_disabled) -> None:
        """alns_operator_names must be a list of strings in per-window metadata."""
        summaries = rhc_result_disabled.metadata.get("inner_window_summaries", [])
        assert len(summaries) > 0, "No inner_window_summaries in metadata"

        # Find at least one window with ALNS metadata
        found = False
        for summary in summaries:
            if "alns_operator_names" in summary:
                names = summary["alns_operator_names"]
                assert isinstance(names, list)
                assert len(names) > 0
                assert all(isinstance(n, str) for n in names)
                # Verify critical-path and due-pressure operators are present
                assert "critical_path" in names
                assert "due_pressure" in names
                found = True
                break

        if not found:
            top_names = rhc_result_disabled.metadata.get("alns_operator_names")
            if top_names is not None:
                assert isinstance(top_names, list)
                assert len(top_names) > 0
                assert "critical_path" in top_names
                assert "due_pressure" in top_names
            else:
                pytest.fail(
                    "alns_operator_names not found in inner_window_summaries "
                    "or top-level metadata"
                )

    def test_alns_final_operator_weights_is_dict(self, rhc_result_disabled) -> None:
        """alns_final_operator_weights must be a dict with string keys."""
        summaries = rhc_result_disabled.metadata.get("inner_window_summaries", [])

        found = False
        for summary in summaries:
            if "alns_final_operator_weights" in summary:
                weights = summary["alns_final_operator_weights"]
                assert isinstance(weights, dict), (
                    f"Expected dict, got {type(weights)}"
                )
                assert len(weights) > 0
                assert all(isinstance(k, str) for k in weights.keys())
                assert all(isinstance(v, (int, float)) for v in weights.values())
                found = True
                break

        if not found:
            top_weights = rhc_result_disabled.metadata.get(
                "alns_final_operator_weights"
            )
            if top_weights is not None:
                assert isinstance(top_weights, dict)
                assert len(top_weights) > 0
            else:
                pytest.fail(
                    "alns_final_operator_weights not found in inner_window_summaries "
                    "or top-level metadata"
                )

    def test_alns_gap_ratio_present(self, rhc_result_disabled) -> None:
        """alns_gap_ratio must be a non-negative float."""
        summaries = rhc_result_disabled.metadata.get("inner_window_summaries", [])

        found = False
        for summary in summaries:
            if "alns_gap_ratio" in summary:
                gap = summary["alns_gap_ratio"]
                assert isinstance(gap, (int, float))
                assert gap >= 0, f"Gap ratio should be >= 0, got {gap}"
                found = True
                break

        if not found:
            top_gap = rhc_result_disabled.metadata.get("alns_gap_ratio")
            if top_gap is not None:
                assert isinstance(top_gap, (int, float))
                assert top_gap >= 0
            else:
                pytest.fail(
                    "alns_gap_ratio not found in inner_window_summaries "
                    "or top-level metadata"
                )

    def test_stagnation_detected_present(self, rhc_result_disabled) -> None:
        """stagnation_detected must be a boolean in per-window metadata."""
        summaries = rhc_result_disabled.metadata.get("inner_window_summaries", [])

        found = False
        for summary in summaries:
            # Check both the new key and the legacy alias
            if "stagnation_detected" in summary:
                assert isinstance(summary["stagnation_detected"], bool)
                found = True
                break
            if "no_improve_early_stop" in summary:
                assert isinstance(summary["no_improve_early_stop"], bool)
                found = True
                break

        if not found:
            top_stag = rhc_result_disabled.metadata.get("stagnation_detected")
            if top_stag is not None:
                assert isinstance(top_stag, bool)
            else:
                pytest.fail(
                    "stagnation_detected not found in inner_window_summaries "
                    "or top-level metadata"
                )

    def test_warm_start_used_present(self, rhc_result_disabled) -> None:
        """warm_start_used must appear in per-window metadata."""
        summaries = rhc_result_disabled.metadata.get("inner_window_summaries", [])
        assert len(summaries) > 0, "No inner_window_summaries"

        warm_start_found = any("warm_start_used" in s for s in summaries)
        assert warm_start_found, (
            "warm_start_used not found in any inner_window_summary"
        )

    def test_warm_start_completed_assignments_present(
        self, rhc_result_disabled
    ) -> None:
        """warm_start_completed_assignments must appear in per-window metadata."""
        summaries = rhc_result_disabled.metadata.get("inner_window_summaries", [])
        assert len(summaries) > 0, "No inner_window_summaries"

        ws_completed_found = any(
            "warm_start_completed_assignments" in s for s in summaries
        )
        assert ws_completed_found, (
            "warm_start_completed_assignments not found in any inner_window_summary"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Task 13a.5: Cross-window telemetry flag toggle
# ─────────────────────────────────────────────────────────────────────────────


class TestE2ECrossWindowTelemetryToggle:
    """Assert cross-window telemetry flag toggle works (Task 13a.5).

    - disabled → no cross_window_hints kwarg propagated to inner solver
    - enabled → buffer summaries passed (evidence in metadata or no crash)
    """

    def test_disabled_no_hints_propagated(self, rhc_result_disabled) -> None:
        """With cross_window_learning_enabled=False, no hints should appear."""
        # The result should succeed
        assert rhc_result_disabled.status in {
            SolverStatus.FEASIBLE,
            SolverStatus.OPTIMAL,
        }

        # When disabled, the inner ALNS solver should not receive hints,
        # so cross_window_bias_applied should be False or absent.
        summaries = rhc_result_disabled.metadata.get("inner_window_summaries", [])
        for summary in summaries:
            bias_applied = summary.get("cross_window_bias_applied", False)
            assert not bias_applied or summary.get(
                "cross_window_bias_operator_deltas"
            ) == {}, (
                f"Window {summary.get('window')}: cross_window_bias_applied="
                f"{bias_applied} but learning was disabled"
            )

    def test_enabled_no_crash_and_evidence(self, rhc_result_enabled) -> None:
        """With cross_window_learning_enabled=True, solver completes and shows evidence."""
        # Must still produce a feasible result
        assert rhc_result_enabled.status in {
            SolverStatus.FEASIBLE,
            SolverStatus.OPTIMAL,
        }

        # Verify the solver completed without error
        assert rhc_result_enabled.assignments, (
            "No assignments produced with learning enabled"
        )

        # Evidence: the solver ran multiple windows and the feature was active.
        summaries = rhc_result_enabled.metadata.get("inner_window_summaries", [])
        assert len(summaries) > 0, "No windows solved with learning enabled"

        # After the first window, subsequent windows should have had the
        # opportunity to receive hints (buffer non-empty after first window).
        if len(summaries) > 1:
            later_windows = summaries[1:]
            has_bias_field = any(
                "cross_window_bias_applied" in s for s in later_windows
            )
            # The field should be present (True or False) when hints are passed
            assert has_bias_field, (
                "cross_window_bias_applied field not found in any window "
                "after the first when learning is enabled"
            )
