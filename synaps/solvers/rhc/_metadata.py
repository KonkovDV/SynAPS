"""Telemetry and metadata builders for the RHC solver.

This module extracts pure serialization/metadata-packaging helpers from the
RHC solve loop. Nothing here should mutate solver state; these builders take
snapshot data and produce plain-dict metadata used by `ScheduleResult` and
by the per-window inner-summary trail.

Decomposed from `synaps/solvers/rhc/_solver.py` as part of the R7 subpackage
split (see AGENTS.md Wave 4 / R7 roadmap).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from synaps.model import ScheduleResult


# Keys copied verbatim from inner-solver metadata into each window summary.
# Keeping this as a module-level constant avoids rebuilding the tuple on every
# RhcSolver.solve() invocation and lets tests assert against a stable contract.
INNER_SUMMARY_METADATA_KEYS: tuple[str, ...] = (
    "lower_bound",
    "upper_bound",
    "gap",
    "iterations_completed",
    "improvements",
    "cpsat_repair_skips_large_destroy",
    "cpsat_max_destroy_ops",
    "cpsat_repair_attempts",
    "cpsat_repairs",
    "cpsat_repair_timeouts",
    "greedy_repair_attempts",
    "greedy_repairs",
    "greedy_repair_timeouts",
    "cpsat_repair_ms_total",
    "greedy_repair_ms_total",
    "cpsat_repair_ms_mean",
    "greedy_repair_ms_mean",
    "repair_rejection_reasons",
    "feasibility_failures",
    "initial_solution_ms",
    "initial_solver",
    "time_limit_exhausted_before_search",
    "max_no_improve_iters",
    "no_improve_early_stop",
    "no_improve_streak_final",
    "final_violations",
    "final_violations_before_recovery",
    "final_violation_recovery_attempted",
    "final_violation_recovered",
    "final_violation_recovery_source",
    "warm_start_used",
    "warm_start_supplied_assignments",
    "warm_start_completed_assignments",
    "warm_start_rejected_reason",
    "budget_guard_skipped_initial_search",
    "inner_status_override",
    "inner_solver_executed",
)


def build_inner_window_summary(
    *,
    window: int,
    ops_in_window: int,
    ops_committed: int,
    resolution_mode: str,
    inner_result: ScheduleResult | None,
    lower_bound: float | None = None,
    inner_time_limit_s: float | None = None,
    candidate_pressure: float | None = None,
    due_pressure: float | None = None,
    due_drift_minutes: float | None = None,
    spillover_ops: int | None = None,
    fallback_reason: str | None = None,
    fallback_iterations: int | None = None,
    exception_message: str | None = None,
) -> dict[str, Any]:
    """Build the per-window telemetry dict appended to `inner_window_summaries`.

    Pure function: no side effects, no access to outer solver state.
    Mirrors the previous closure `append_inner_window_summary` behaviour
    exactly, so the serialized schema of `inner_window_summaries` is
    preserved byte-for-byte.
    """
    summary: dict[str, Any] = {
        "window": window,
        "ops_committed": ops_committed,
        "ops_in_window": ops_in_window,
        "resolution_mode": resolution_mode,
    }
    if lower_bound is not None:
        summary["lower_bound"] = round(lower_bound, 4)
    if inner_time_limit_s is not None:
        summary["inner_time_limit_s"] = round(inner_time_limit_s, 2)
        # RHC passes a budget target into the inner solver but does not
        # enforce a hard kill boundary at process level.
        summary["inner_time_budget_s"] = round(inner_time_limit_s, 2)
        summary["inner_time_budget_mode"] = "advisory_soft"
        summary["inner_time_budget_hard_enforced"] = False
    if candidate_pressure is not None:
        summary["candidate_pressure"] = round(candidate_pressure, 4)
    if due_pressure is not None:
        summary["due_pressure"] = round(due_pressure, 4)
    if due_drift_minutes is not None:
        summary["due_drift_minutes"] = round(due_drift_minutes, 2)
    if spillover_ops is not None:
        summary["spillover_ops"] = spillover_ops
    if fallback_reason is not None:
        summary["fallback_reason"] = fallback_reason
        summary["fallback_reason_code"] = fallback_reason
    if fallback_iterations is not None:
        summary["fallback_iterations"] = fallback_iterations
    if exception_message is not None:
        summary["inner_exception_message"] = exception_message

    if inner_result is None:
        summary["inner_status"] = "not_run"
        summary["inner_duration_ms"] = 0
        return summary

    computed_inner_status = (
        inner_result.status.value
        if hasattr(inner_result.status, "value")
        else str(inner_result.status)
    )
    override_status = (inner_result.metadata or {}).get("inner_status_override")
    if isinstance(override_status, str) and override_status:
        computed_inner_status = override_status
    summary["inner_status"] = computed_inner_status
    summary["inner_duration_ms"] = inner_result.duration_ms
    if inner_time_limit_s is not None:
        budget_ms = int(round(inner_time_limit_s * 1000.0))
        if inner_result.duration_ms > budget_ms:
            summary["inner_time_budget_overrun_ms"] = (
                inner_result.duration_ms - budget_ms
            )
    if hasattr(inner_result.error_category, "value"):
        summary["inner_error_category"] = inner_result.error_category.value
    for key in INNER_SUMMARY_METADATA_KEYS:
        if key in (inner_result.metadata or {}):
            summary[key] = inner_result.metadata[key]

    return summary
