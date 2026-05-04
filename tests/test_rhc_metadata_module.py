"""Unit tests for the R7 RHC `_metadata` module.

These tests lock in the wire-format contract of `build_inner_window_summary`
so the `inner_window_summaries` trail stays stable during the rest of the
Wave 4 R7 decomposition work.
"""
from __future__ import annotations

from synaps.model import (
    ObjectiveValues,
    ScheduleResult,
    SolverErrorCategory,
    SolverStatus,
)
from synaps.solvers.rhc._metadata import (
    INNER_SUMMARY_METADATA_KEYS,
    build_inner_window_summary,
)


def _make_inner_result(metadata: dict | None = None) -> ScheduleResult:
    return ScheduleResult(
        assignments=[],
        objective=ObjectiveValues(),
        status=SolverStatus.OPTIMAL,
        duration_ms=1234,
        solver_name="alns",
        error_category=SolverErrorCategory.NONE,
        metadata=metadata or {},
    )


class TestBuildInnerWindowSummary:
    def test_required_fields_always_present(self) -> None:
        summary = build_inner_window_summary(
            window=0,
            ops_in_window=10,
            ops_committed=5,
            resolution_mode="alns",
            inner_result=None,
        )
        assert summary["window"] == 0
        assert summary["ops_in_window"] == 10
        assert summary["ops_committed"] == 5
        assert summary["resolution_mode"] == "alns"
        assert summary["inner_status"] == "not_run"
        assert summary["inner_duration_ms"] == 0

    def test_optional_fields_elided_when_none(self) -> None:
        summary = build_inner_window_summary(
            window=1,
            ops_in_window=4,
            ops_committed=4,
            resolution_mode="greedy",
            inner_result=None,
        )
        for key in (
            "lower_bound",
            "inner_time_limit_s",
            "candidate_pressure",
            "due_pressure",
            "due_drift_minutes",
            "spillover_ops",
            "fallback_reason",
            "fallback_iterations",
            "inner_exception_message",
        ):
            assert key not in summary

    def test_inner_time_limit_exposes_budget_trio(self) -> None:
        summary = build_inner_window_summary(
            window=2,
            ops_in_window=8,
            ops_committed=8,
            resolution_mode="alns",
            inner_result=None,
            inner_time_limit_s=12.5,
        )
        assert summary["inner_time_limit_s"] == 12.5
        assert summary["inner_time_budget_s"] == 12.5
        assert summary["inner_time_budget_mode"] == "advisory_soft"
        assert summary["inner_time_budget_hard_enforced"] is False

    def test_fallback_reason_mirrored_into_reason_code(self) -> None:
        summary = build_inner_window_summary(
            window=3,
            ops_in_window=2,
            ops_committed=0,
            resolution_mode="greedy",
            inner_result=None,
            fallback_reason="inner_time_limit_exhausted",
        )
        assert summary["fallback_reason"] == "inner_time_limit_exhausted"
        assert summary["fallback_reason_code"] == "inner_time_limit_exhausted"

    def test_inner_result_status_override_wins(self) -> None:
        inner = _make_inner_result(metadata={"inner_status_override": "greedy_fallback"})
        summary = build_inner_window_summary(
            window=4,
            ops_in_window=6,
            ops_committed=6,
            resolution_mode="alns",
            inner_result=inner,
        )
        assert summary["inner_status"] == "greedy_fallback"
        assert summary["inner_duration_ms"] == 1234

    def test_budget_overrun_exposed_when_duration_exceeds_limit(self) -> None:
        inner = _make_inner_result()
        summary = build_inner_window_summary(
            window=5,
            ops_in_window=3,
            ops_committed=3,
            resolution_mode="alns",
            inner_result=inner,
            inner_time_limit_s=1.0,  # 1000 ms, duration_ms=1234 → overrun 234
        )
        assert summary["inner_time_budget_overrun_ms"] == 234

    def test_no_overrun_when_within_budget(self) -> None:
        inner = _make_inner_result()
        summary = build_inner_window_summary(
            window=6,
            ops_in_window=3,
            ops_committed=3,
            resolution_mode="alns",
            inner_result=inner,
            inner_time_limit_s=10.0,
        )
        assert "inner_time_budget_overrun_ms" not in summary

    def test_inner_metadata_keys_copied_verbatim(self) -> None:
        inner = _make_inner_result(
            metadata={
                "lower_bound": 42.0,
                "iterations_completed": 7,
                "warm_start_used": True,
                "not_in_contract": "should_not_copy",
            }
        )
        summary = build_inner_window_summary(
            window=7,
            ops_in_window=3,
            ops_committed=3,
            resolution_mode="alns",
            inner_result=inner,
        )
        assert summary["lower_bound"] == 42.0
        assert summary["iterations_completed"] == 7
        assert summary["warm_start_used"] is True
        assert "not_in_contract" not in summary

    def test_inner_error_category_value_emitted(self) -> None:
        inner = _make_inner_result()
        summary = build_inner_window_summary(
            window=8,
            ops_in_window=3,
            ops_committed=3,
            resolution_mode="alns",
            inner_result=inner,
        )
        assert summary["inner_error_category"] == SolverErrorCategory.NONE.value


class TestInnerSummaryMetadataKeysContract:
    def test_all_keys_are_strings(self) -> None:
        assert all(isinstance(k, str) for k in INNER_SUMMARY_METADATA_KEYS)

    def test_no_duplicates(self) -> None:
        assert len(set(INNER_SUMMARY_METADATA_KEYS)) == len(INNER_SUMMARY_METADATA_KEYS)

    def test_required_telemetry_keys_present(self) -> None:
        # Minimal contract surface expected by LBBD / ALNS telemetry consumers.
        required = {
            "lower_bound",
            "upper_bound",
            "gap",
            "iterations_completed",
            "improvements",
            "warm_start_used",
            "inner_status_override",
        }
        assert required.issubset(set(INNER_SUMMARY_METADATA_KEYS))
