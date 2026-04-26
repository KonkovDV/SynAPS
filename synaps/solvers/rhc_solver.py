"""Receding Horizon Control (RHC) — temporal decomposition for ultra-large instances.

Solves windows of the planning horizon sequentially, freezing committed
assignments from prior windows and only solving the "active" window
plus a look-ahead buffer.

Academic basis:
    - Rawlings & Mayne (2009, Springer): Model Predictive Control
    - Nair et al. (2020, NeurIPS): dual sub-solver RHC for large VRP
    - Hottung & Tierney (2020, AAAI): Neural RHC with iterated destroy
    - Pernas-Álvarez et al. (2025, IJPR): CP-based decomposition for shipbuilding

Scales gracefully to 100K+ operations by ensuring each window stays within
the CP-SAT / ALNS sweet spot (≤5000 ops per window).
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from heapq import heappop, heappush
from typing import TYPE_CHECKING, Any

from synaps.accelerators import (
    compute_rhc_candidate_metrics_batch_np,
    get_acceleration_status,
)
from synaps.model import (
    Assignment,
    ObjectiveValues,
    Operation,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from synaps.solvers import BaseSolver
from synaps.solvers._dispatch_support import (
    MachineIndex,
    build_dispatch_context,
    find_earliest_feasible_slot,
    recompute_assignment_setups,
)
from synaps.solvers.lower_bounds import compute_relaxed_makespan_lower_bound
from synaps.solvers.sdst_matrix import SdstMatrix

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


class RhcSolver(BaseSolver):
    """Receding Horizon Control wrapper over any inner solver.

    Decomposes the planning horizon into overlapping windows.
    Each window is solved independently (via ALNS, CP-SAT, or any BaseSolver),
    with frozen commitments from prior windows providing boundary conditions.

    Parameters:
        window_minutes: Width of the active scheduling window (default 480 = 8h)
        overlap_minutes: Look-ahead overlap between windows (default 120 = 2h)
        inner_solver: Which solver to use per window ("alns" or "cpsat", default "alns")
        inner_kwargs: Dict of kwargs to pass to the inner solver per window
        max_ops_per_window: Hard cap on operations per window (default 5000)
    """

    @property
    def name(self) -> str:
        return "rhc"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()
        time_budget_t0 = t0
        acceleration_status = get_acceleration_status()
        global_lower_bound = compute_relaxed_makespan_lower_bound(problem)

        # Parameters
        window_minutes: int = int(kwargs.get("window_minutes", 480))
        overlap_minutes: int = int(kwargs.get("overlap_minutes", 120))
        inner_solver_name: str = str(kwargs.get("inner_solver", "alns"))
        inner_kwargs: dict[str, Any] = dict(kwargs.get("inner_kwargs", {}))
        # Prevent double-passing time_limit_s to inner solver.
        # RHC computes its own per-window budget.
        inner_kwargs.pop("time_limit_s", None)
        time_limit_s: float = float(kwargs.get("time_limit_s", 600))
        fallback_repair_enabled: bool = bool(kwargs.get("fallback_repair_enabled", True))
        inner_solver_min_budget_s: float = float(kwargs.get("inner_solver_min_budget_s", 0.0))
        backtracking_enabled: bool = bool(kwargs.get("backtracking_enabled", False))
        backtracking_tail_minutes: float = max(
            0.0,
            float(kwargs.get("backtracking_tail_minutes", overlap_minutes)),
        )
        backtracking_max_ops: int = max(0, int(kwargs.get("backtracking_max_ops", 0)))
        inner_window_time_fraction: float = min(
            1.0,
            max(0.1, float(kwargs.get("inner_window_time_fraction", 0.8))),
        )
        inner_window_time_cap_raw = kwargs.get("inner_window_time_cap_s")
        inner_window_time_cap_s: float | None = (
            float(inner_window_time_cap_raw)
            if inner_window_time_cap_raw is not None
            else None
        )
        alns_inner_window_time_cap_raw = kwargs.get("alns_inner_window_time_cap_s")
        alns_inner_window_time_cap_s: float | None = (
            float(alns_inner_window_time_cap_raw)
            if alns_inner_window_time_cap_raw is not None
            else None
        )
        alns_inner_window_time_cap_scale_threshold_ops: int = int(
            kwargs.get("alns_inner_window_time_cap_scale_threshold_ops", 4000)
        )
        alns_inner_window_time_cap_scaled_s: float = float(
            kwargs.get("alns_inner_window_time_cap_scaled_s", 180.0)
        )
        alns_budget_auto_scaling_raw = kwargs.get("alns_budget_auto_scaling_enabled")
        alns_budget_estimated_repair_s_per_destroyed_op_raw = kwargs.get(
            "alns_budget_estimated_repair_s_per_destroyed_op"
        )
        alns_dynamic_repair_budget_enabled: bool = bool(
            kwargs.get("alns_dynamic_repair_budget_enabled", True)
        )
        alns_dynamic_repair_s_per_destroyed_op: float = max(
            0.01,
            float(kwargs.get("alns_dynamic_repair_s_per_destroyed_op", 0.1)),
        )
        alns_dynamic_repair_time_limit_min_s: float = max(
            0.1,
            float(kwargs.get("alns_dynamic_repair_time_limit_min_s", 1.0)),
        )
        alns_dynamic_repair_time_limit_max_s: float = max(
            alns_dynamic_repair_time_limit_min_s,
            float(kwargs.get("alns_dynamic_repair_time_limit_max_s", 5.0)),
        )
        alns_presearch_budget_guard_enabled: bool = bool(
            kwargs.get("alns_presearch_budget_guard_enabled", True)
        )
        alns_presearch_max_window_ops: int = int(
            kwargs.get("alns_presearch_max_window_ops", 1000)
        )
        alns_presearch_min_time_limit_s: float = float(
            kwargs.get("alns_presearch_min_time_limit_s", 240.0)
        )
        max_ops_per_window: int = int(kwargs.get("max_ops_per_window", 5000))
        window_load_factor: float = float(kwargs.get("window_load_factor", 1.25))
        max_windows_raw = kwargs.get("max_windows")
        max_windows: int | None = int(max_windows_raw) if max_windows_raw is not None else None
        dynamic_no_improve_enabled: bool = bool(
            kwargs.get("dynamic_no_improve_enabled", True)
        )
        no_improve_due_alpha: float = float(kwargs.get("no_improve_due_alpha", 0.6))
        no_improve_candidate_beta: float = float(
            kwargs.get("no_improve_candidate_beta", 0.4)
        )
        no_improve_min_iters_raw = kwargs.get("no_improve_min_iters")
        no_improve_min_iters: int | None = (
            int(no_improve_min_iters_raw) if no_improve_min_iters_raw is not None else None
        )
        no_improve_max_iters_raw = kwargs.get("no_improve_max_iters")
        no_improve_max_iters: int | None = (
            int(no_improve_max_iters_raw) if no_improve_max_iters_raw is not None else None
        )
        due_pressure_k1: float = float(kwargs.get("due_pressure_k1", 1.0))
        machine_coverage_boost: float = float(
            kwargs.get("machine_coverage_boost", 1.15)
        )
        due_pressure_overdue_boost: float = float(
            kwargs.get("due_pressure_overdue_boost", 1.25)
        )
        random_seed_raw = kwargs.get("random_seed")
        random_seed_base = int(random_seed_raw) if random_seed_raw is not None else 0
        candidate_admission_enabled: bool = bool(
            kwargs.get("candidate_admission_enabled", True)
        )
        candidate_pool_factor: float = max(
            1.0,
            float(kwargs.get("candidate_pool_factor", 3.0)),
        )
        due_admission_horizon_factor: float = max(
            0.0,
            float(kwargs.get("due_admission_horizon_factor", 1.0)),
        )
        admission_tail_weight: float = max(
            0.0,
            float(kwargs.get("admission_tail_weight", 0.5)),
        )
        adaptive_window_enabled: bool = bool(
            kwargs.get("adaptive_window_enabled", True)
        )
        adaptive_window_min_fill_ratio: float = min(
            1.0,
            max(0.0, float(kwargs.get("adaptive_window_min_fill_ratio", 0.5))),
        )
        adaptive_window_max_multiplier: float = max(
            1.0,
            float(kwargs.get("adaptive_window_max_multiplier", 2.0)),
        )
        progressive_admission_relaxation_enabled: bool = bool(
            kwargs.get("progressive_admission_relaxation_enabled", True)
        )
        precedence_ready_candidate_filter_enabled: bool = bool(
            kwargs.get("precedence_ready_candidate_filter_enabled", False)
        )
        admission_relaxation_min_fill_ratio: float = min(
            1.0,
            max(0.0, float(kwargs.get("admission_relaxation_min_fill_ratio", 0.3))),
        )
        admission_full_scan_enabled: bool = bool(
            kwargs.get("admission_full_scan_enabled", True)
        )
        admission_full_scan_min_fill_ratio: float = min(
            1.0,
            max(0.0, float(kwargs.get("admission_full_scan_min_fill_ratio", 0.3))),
        )
        hybrid_inner_routing_enabled: bool = bool(
            kwargs.get("hybrid_inner_routing_enabled", False)
        )
        hybrid_inner_solver_name: str = str(
            kwargs.get("hybrid_inner_solver", "cpsat")
        )
        hybrid_due_pressure_threshold: float = float(
            kwargs.get("hybrid_due_pressure_threshold", 0.35)
        )
        hybrid_candidate_pressure_threshold: float = float(
            kwargs.get("hybrid_candidate_pressure_threshold", 1.75)
        )
        hybrid_max_ops: int = int(kwargs.get("hybrid_max_ops", 1500))
        hybrid_inner_kwargs: dict[str, Any] = dict(kwargs.get("hybrid_inner_kwargs", {}))
        inner_fallback_kpi_threshold: float = float(
            kwargs.get("inner_fallback_kpi_threshold", 0.1)
        )
        max_candidate_pool_raw = kwargs.get("max_candidate_pool")
        external_warm_start_assignments = list(
            kwargs.get("warm_start_assignments", []) or []
        )

        ops_by_id = {op.id: op for op in problem.operations}
        orders_by_id = {o.id: o for o in problem.orders}
        external_warm_start_by_op = {
            assignment.operation_id: assignment
            for assignment in external_warm_start_assignments
            if assignment.operation_id in ops_by_id
        }
        sdst = SdstMatrix.from_problem(problem)
        dispatch_context = build_dispatch_context(problem)

        horizon_start = problem.planning_horizon_start
        horizon_end = problem.planning_horizon_end
        horizon_minutes = (horizon_end - horizon_start).total_seconds() / 60.0

        # Build inner solver
        inner_solver = self._make_inner_solver(inner_solver_name)
        hybrid_inner_solver = None
        if hybrid_inner_routing_enabled and inner_solver_name == "alns":
            hybrid_inner_solver = self._make_inner_solver(hybrid_inner_solver_name)

        preprocess_t0 = time.monotonic()
        preprocess_phase_ms: dict[str, int] = {}
        phase_t0 = preprocess_t0

        # Build due-date and release offsets for order prioritization
        order_due_offsets: dict[UUID, float] = {}
        order_release_offsets: dict[UUID, float] = {}
        for order in problem.orders:
            order_due_offsets[order.id] = (order.due_date - horizon_start).total_seconds() / 60.0
            order_release_offsets[order.id] = self._extract_order_release_offset_minutes(
                order,
                horizon_start=horizon_start,
                horizon_minutes=horizon_minutes,
            )
        phase_now = time.monotonic()
        preprocess_phase_ms["due_offsets"] = int((phase_now - phase_t0) * 1000)
        phase_t0 = phase_now

        # Compute precedence-constrained earliest offsets, then tighten them
        # with release-aware and machine-speed-aware lower bounds.
        op_earliest: dict[UUID, float] = {}
        self._compute_earliest_starts(problem, op_earliest)
        phase_now = time.monotonic()
        preprocess_phase_ms["earliest_starts"] = int((phase_now - phase_t0) * 1000)
        phase_t0 = phase_now

        op_positions = {op.id: index for index, op in enumerate(problem.operations)}
        all_work_center_ids = {work_center.id for work_center in problem.work_centers}
        wc_speed_by_id = {
            work_center.id: max(work_center.speed_factor, 1e-6)
            for work_center in problem.work_centers
        }
        op_eligible_wc_ids: dict[UUID, set[UUID]] = {
            op.id: (
                set(op.eligible_wc_ids)
                if op.eligible_wc_ids
                else set(all_work_center_ids)
            )
            for op in problem.operations
        }

        op_mean_duration_by_id: dict[UUID, float] = {}
        op_min_duration_by_id: dict[UUID, float] = {}
        for op in problem.operations:
            eligible_ids = op_eligible_wc_ids[op.id]
            effective_durations = [
                op.base_duration_min / wc_speed_by_id.get(wc_id, 1.0)
                for wc_id in eligible_ids
            ]
            if not effective_durations:
                effective_durations = [max(op.base_duration_min, 1.0)]
            op_mean_duration_by_id[op.id] = max(
                sum(effective_durations) / len(effective_durations),
                1e-6,
            )
            op_min_duration_by_id[op.id] = max(min(effective_durations), 1e-6)
        self._propagate_earliest_starts_with_release_and_duration(
            problem,
            op_earliest,
            op_duration_by_id=op_min_duration_by_id,
            order_release_offsets=order_release_offsets,
        )
        phase_now = time.monotonic()
        preprocess_phase_ms["operation_stats"] = int((phase_now - phase_t0) * 1000)
        phase_t0 = phase_now

        rms_processing = math.sqrt(
            sum(duration * duration for duration in op_mean_duration_by_id.values())
            / max(1, len(op_mean_duration_by_id))
        )
        avg_total_p = max(rms_processing, 1e-6)

        positive_setups = [
            setup_entry.setup_minutes
            for setup_entry in problem.setup_matrix
            if setup_entry.setup_minutes > 0
        ]
        expected_setup = (
            sum(positive_setups) / len(positive_setups)
            if positive_setups
            else 0.0
        )

        _ops_by_order: dict[UUID, list[Operation]] = {}
        for op in problem.operations:
            _ops_by_order.setdefault(op.order_id, []).append(op)
        order_ops_sorted: dict[UUID, list[Operation]] = {
            order_id: sorted(ops, key=lambda op: op.seq_in_order)
            for order_id, ops in _ops_by_order.items()
        }

        op_tail_rpt_by_id: dict[UUID, float] = {}
        for _order_id, order_ops in order_ops_sorted.items():
            suffix_sum = 0.0
            for reverse_index, op in enumerate(reversed(order_ops)):
                suffix_sum += op_min_duration_by_id.get(op.id, max(op.base_duration_min, 1.0))
                remaining_edges = reverse_index
                op_tail_rpt_by_id[op.id] = suffix_sum + remaining_edges * expected_setup
        admission_horizon_minutes = (
            window_minutes + overlap_minutes
        ) * due_admission_horizon_factor
        op_admission_offset_by_id: dict[UUID, float] = {}
        for op in problem.operations:
            due_offset = order_due_offsets.get(op.order_id, horizon_minutes)
            rpt_tail = op_tail_rpt_by_id.get(op.id, op_mean_duration_by_id.get(op.id, 1.0))
            due_release_offset = (
                due_offset
                - admission_horizon_minutes
                + admission_tail_weight * rpt_tail
            )
            op_admission_offset_by_id[op.id] = max(
                op_earliest.get(op.id, 0.0),
                due_release_offset,
            )
        phase_now = time.monotonic()
        preprocess_phase_ms["admission_offsets"] = int((phase_now - phase_t0) * 1000)
        phase_t0 = phase_now

        ops_sorted_by_admission = sorted(
            problem.operations,
            key=lambda op: (
                op_admission_offset_by_id.get(op.id, op_earliest.get(op.id, 0.0)),
                order_due_offsets.get(op.order_id, horizon_minutes),
                op.seq_in_order,
            ),
        )
        ops_sorted_by_due = sorted(
            problem.operations,
            key=lambda op: (
                order_due_offsets.get(op.order_id, horizon_minutes),
                op.seq_in_order,
                op_earliest.get(op.id, 0.0),
            ),
        )
        ops_sorted_by_earliest = sorted(
            problem.operations,
            key=lambda op: (
                op_earliest.get(op.id, 0.0),
                order_due_offsets.get(op.order_id, horizon_minutes),
                op.seq_in_order,
                op_positions[op.id],
            ),
        )
        phase_now = time.monotonic()
        preprocess_phase_ms["candidate_orderings"] = int((phase_now - phase_t0) * 1000)
        preprocessing_ms = int((time.monotonic() - preprocess_t0) * 1000)
        # Start the global budget after static preprocessing so short smoke
        # limits reflect window scheduling behavior instead of setup overhead.
        time_budget_t0 = time.monotonic()
        effective_window_op_cap = max_ops_per_window
        if len(problem.operations) > max_ops_per_window:
            effective_window_op_cap = min(
                max_ops_per_window,
                self._estimate_window_operation_cap(
                    problem,
                    window_span_minutes=window_minutes + overlap_minutes,
                    window_load_factor=window_load_factor,
                ),
            )
        candidate_pool_limit = max(
            effective_window_op_cap,
            (
                int(max_candidate_pool_raw)
                if max_candidate_pool_raw is not None
                else int(math.ceil(effective_window_op_cap * candidate_pool_factor))
            ),
        )
        candidate_admission_active = (
            candidate_admission_enabled
            and len(problem.operations) > effective_window_op_cap
        )
        if not candidate_admission_active:
            op_admission_offset_by_id = {
                op.id: op_earliest.get(op.id, 0.0)
                for op in problem.operations
            }
            ops_sorted_by_admission = sorted(
                problem.operations,
                key=lambda op: (
                    op_admission_offset_by_id.get(op.id, op_earliest.get(op.id, 0.0)),
                    order_due_offsets.get(op.order_id, horizon_minutes),
                    op.seq_in_order,
                ),
            )
        alns_budget_auto_scaling_enabled = (
            bool(alns_budget_auto_scaling_raw)
            if alns_budget_auto_scaling_raw is not None
            else len(problem.operations) > effective_window_op_cap
        )

        # Sliding windows
        committed_assignments: list[Assignment] = []
        committed_assignment_by_op: dict[UUID, Assignment] = {}
        committed_op_ids: set[UUID] = set()
        window_start_offset = 0.0
        window_count = 0
        admission_cursor = 0
        due_cursor = 0
        admission_candidate_ids: set[UUID] = set()
        due_candidate_ids: set[UUID] = set()
        peak_window_candidate_count = 0
        peak_raw_window_candidate_count = 0
        candidate_pool_clamped_windows = 0
        candidate_pool_filtered_ops = 0
        precedence_ready_filtered_ops = 0
        precedence_ready_candidate_ops_total = 0
        precedence_ready_candidate_ready_total = 0
        precedence_blocked_by_precedence_count = 0
        due_pressure_selected_ids: set[UUID] = set()
        admission_frontier_advances = 0
        admission_starvation_count = 0
        admission_relaxation_windows = 0
        admission_relaxation_recovered_ops = 0
        admission_full_scan_windows = 0
        admission_full_scan_triggered_windows = 0
        admission_full_scan_added_ops = 0
        admission_full_scan_final_pool_peak = 0
        admission_full_scan_recovered_ops = 0
        due_frontier_advances = 0
        candidate_pressure_values: list[float] = []
        due_pressure_values: list[float] = []
        due_drift_minutes_values: list[float] = []
        spillover_count = 0
        hybrid_route_attempts = 0
        hybrid_route_activations = 0
        inner_fallback_windows = 0
        inner_fallback_reason_counts: dict[str, int] = defaultdict(int)
        inner_status_counts: dict[str, int] = defaultdict(int)
        inner_exception_windows = 0
        inner_exception_messages_sample: list[str] = []
        inner_exception_logs_emitted = 0
        max_inner_exception_logs = 3
        max_inner_exception_message_samples = 5
        backtracking_windows = 0
        backtracking_ops_total = 0
        horizon_clipped_assignments = 0
        time_limit_reached = False
        fallback_repair_attempted = False
        fallback_repair_skipped = False
        fallback_repair_time_limited = False
        adaptive_window_expansions = 0
        adaptive_window_expansion_factors: list[float] = []
        alns_budget_scaled_windows = 0
        alns_presearch_budget_guard_skipped_windows = 0
        alns_effective_max_iterations_values: list[int] = []
        alns_effective_max_destroy_values: list[int] = []
        alns_effective_repair_time_limit_values: list[float] = []
        boundary_reanchor_windows = 0
        boundary_reanchor_ops_total = 0
        boundary_reanchor_changed_ops_total = 0
        external_warm_start_used_windows = 0
        base_window_span_minutes = max(float(window_minutes + overlap_minutes), 1.0)
        inner_window_summaries: list[dict[str, Any]] = []
        previous_window_tail_assignments: list[Assignment] = []

        inner_summary_metadata_keys = (
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

        def append_inner_window_summary(
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
        ) -> None:
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
            else:
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
                for key in inner_summary_metadata_keys:
                    if key in (inner_result.metadata or {}):
                        summary[key] = inner_result.metadata[key]

            inner_window_summaries.append(summary)

        def global_time_exceeded() -> bool:
            return (time.monotonic() - time_budget_t0) > time_limit_s

        def extend_candidate_frontiers(window_boundary: float) -> None:
            nonlocal admission_cursor
            nonlocal due_cursor
            nonlocal admission_frontier_advances
            nonlocal due_frontier_advances

            while admission_cursor < len(ops_sorted_by_admission):
                op = ops_sorted_by_admission[admission_cursor]
                if (
                    op_admission_offset_by_id.get(op.id, op_earliest.get(op.id, 0.0))
                    >= window_boundary
                ):
                    break
                admission_candidate_ids.add(op.id)
                admission_cursor += 1
                admission_frontier_advances += 1

            while due_cursor < len(ops_sorted_by_due):
                op = ops_sorted_by_due[due_cursor]
                if order_due_offsets.get(op.order_id, horizon_minutes) >= window_boundary:
                    break
                due_candidate_ids.add(op.id)
                due_cursor += 1
                due_frontier_advances += 1

        def collect_raw_window_candidate_ids() -> set[UUID]:
            admission_candidate_ids.difference_update(committed_op_ids)
            due_candidate_ids.difference_update(committed_op_ids)
            return {
                op_id
                for op_id in (admission_candidate_ids | due_candidate_ids)
                if op_id not in committed_op_ids
            }

        def filter_precedence_ready_candidate_ids(
            candidate_ids: set[UUID],
            *,
            window_boundary: float,
            resolved_predecessor_ids: set[UUID],
        ) -> set[UUID]:
            nonlocal precedence_ready_filtered_ops
            nonlocal precedence_ready_candidate_ops_total
            nonlocal precedence_ready_candidate_ready_total
            nonlocal precedence_blocked_by_precedence_count

            if not precedence_ready_candidate_filter_enabled or not candidate_ids:
                return candidate_ids

            precedence_ready_candidate_ops_total += len(candidate_ids)
            filtered_ids = {
                op_id
                for op_id in candidate_ids
                if op_earliest.get(op_id, 0.0) < window_boundary
            }
            if not filtered_ids:
                precedence_ready_filtered_ops += len(candidate_ids)
                return filtered_ids

            # Keep only operations whose unresolved predecessors are reachable in
            # the same candidate set (or already resolved by commits/tail carry-over).
            predecessor_closed_ids = set(filtered_ids)
            changed = True
            while changed:
                changed = False
                for op_id in tuple(predecessor_closed_ids):
                    operation = ops_by_id.get(op_id)
                    predecessor_id = (
                        operation.predecessor_op_id
                        if operation is not None
                        else None
                    )
                    if predecessor_id is None:
                        continue
                    if (
                        predecessor_id in predecessor_closed_ids
                        or predecessor_id in resolved_predecessor_ids
                    ):
                        continue
                    predecessor_closed_ids.remove(op_id)
                    changed = True

            blocked_by_precedence = max(0, len(filtered_ids) - len(predecessor_closed_ids))
            precedence_blocked_by_precedence_count += blocked_by_precedence
            precedence_ready_candidate_ready_total += len(predecessor_closed_ids)
            precedence_ready_filtered_ops += max(
                0,
                len(candidate_ids) - len(predecessor_closed_ids),
            )
            return predecessor_closed_ids

        def effective_candidate_count(
            raw_candidate_ids: set[UUID],
            window_boundary: float,
        ) -> int:
            admitted_candidate_ids = {
                op_id
                for op_id in raw_candidate_ids
                if (
                    op_admission_offset_by_id.get(op_id, op_earliest.get(op_id, 0.0))
                    < window_boundary
                )
            }
            return (
                len(admitted_candidate_ids)
                if admitted_candidate_ids
                else len(raw_candidate_ids)
            )

        def collect_commit_candidates(
            assignments: list[Assignment],
            *,
            commit_boundary: float,
            commit_all: bool,
            frozen_committed_ids: set[UUID] | None = None,
            eligible_ids: set[UUID] | None = None,
        ) -> dict[UUID, Assignment]:
            nonlocal horizon_clipped_assignments

            frozen_ids = committed_op_ids if frozen_committed_ids is None else frozen_committed_ids

            candidates: dict[UUID, Assignment] = {}
            for assignment in assignments:
                op_id = assignment.operation_id
                if op_id in frozen_ids:
                    continue
                if eligible_ids is not None and op_id not in eligible_ids:
                    continue

                end_offset = (assignment.end_time - horizon_start).total_seconds() / 60.0
                if end_offset > horizon_minutes + 1e-9:
                    horizon_clipped_assignments += 1
                    continue

                # Freeze only work that fully completes inside the active horizon.
                # Assignments that cross the rolling boundary must survive as tail
                # so the overlap region can seed the next window.
                if end_offset <= commit_boundary + 1e-9 or commit_all:
                    candidates[op_id] = assignment

            # Commit set must be precedence-closed.
            changed = True
            while changed:
                changed = False
                for op_id in list(candidates.keys()):
                    operation = ops_by_id.get(op_id)
                    predecessor_op_id = (
                        operation.predecessor_op_id if operation is not None else None
                    )
                    if predecessor_op_id is None:
                        continue
                    if (
                        predecessor_op_id not in frozen_ids
                        and predecessor_op_id not in candidates
                    ):
                        del candidates[op_id]
                        changed = True

            return candidates

        def reanchor_inner_assignments(
            assignments: list[Assignment],
            *,
            frozen_assignments: list[Assignment],
            frozen_assignment_by_op: dict[UUID, Assignment],
        ) -> tuple[list[Assignment], int]:
            if not assignments or not frozen_assignments:
                return list(assignments), 0

            original_by_op = {
                assignment.operation_id: assignment for assignment in assignments
            }
            scheduled_assignments = list(frozen_assignments)
            machine_index = MachineIndex(dispatch_context)
            for assignment in scheduled_assignments:
                machine_index.add(assignment)

            anchored_by_op = dict(frozen_assignment_by_op)
            pending_assignments = sorted(
                assignments,
                key=lambda assignment: (
                    assignment.start_time,
                    ops_by_id[assignment.operation_id].seq_in_order,
                    op_positions[assignment.operation_id],
                ),
            )
            reanchored_assignments: list[Assignment] = []

            for _ in range(len(pending_assignments) + 1):
                if not pending_assignments:
                    break
                progress_made = False
                next_pending: list[Assignment] = []

                for assignment in pending_assignments:
                    operation = ops_by_id[assignment.operation_id]
                    earliest_start = op_earliest.get(operation.id, 0.0)
                    if operation.predecessor_op_id is not None:
                        predecessor_assignment = anchored_by_op.get(operation.predecessor_op_id)
                        if predecessor_assignment is None:
                            next_pending.append(assignment)
                            continue
                        predecessor_end = (
                            predecessor_assignment.end_time - horizon_start
                        ).total_seconds() / 60.0
                        earliest_start = max(earliest_start, predecessor_end)

                    slot = find_earliest_feasible_slot(
                        dispatch_context,
                        scheduled_assignments,
                        operation,
                        assignment.work_center_id,
                        earliest_start,
                        machine_index=machine_index,
                    )
                    if slot is None:
                        next_pending.append(assignment)
                        continue

                    anchored_assignment = Assignment(
                        operation_id=operation.id,
                        work_center_id=assignment.work_center_id,
                        start_time=horizon_start + timedelta(minutes=slot.start_offset),
                        end_time=horizon_start + timedelta(minutes=slot.end_offset),
                        setup_minutes=slot.setup_minutes,
                        aux_resource_ids=slot.aux_resource_ids,
                    )
                    scheduled_assignments.append(anchored_assignment)
                    machine_index.add(anchored_assignment)
                    anchored_by_op[operation.id] = anchored_assignment
                    reanchored_assignments.append(anchored_assignment)
                    progress_made = True

                if not progress_made:
                    return list(assignments), 0
                pending_assignments = next_pending

            if pending_assignments:
                return list(assignments), 0

            changed_assignment_count = sum(
                1
                for assignment in reanchored_assignments
                if original_by_op[assignment.operation_id].start_time != assignment.start_time
                or original_by_op[assignment.operation_id].end_time != assignment.end_time
                or original_by_op[assignment.operation_id].work_center_id
                != assignment.work_center_id
            )
            return sorted(
                reanchored_assignments,
                key=lambda assignment: assignment.start_time,
            ), changed_assignment_count

        def select_backtracking_assignments(window_start_offset: float) -> list[Assignment]:
            if (
                not backtracking_enabled
                or backtracking_tail_minutes <= 0.0
                or backtracking_max_ops <= 0
                or not committed_assignments
            ):
                return []

            rewind_boundary = max(0.0, window_start_offset - backtracking_tail_minutes)
            rewound_ids = {
                assignment.operation_id
                for assignment in committed_assignments
                if (
                    (assignment.end_time - horizon_start).total_seconds() / 60.0
                    > rewind_boundary + 1e-9
                )
            }
            if not rewound_ids:
                return []

            changed = True
            while changed:
                changed = False
                for op_id in committed_assignment_by_op:
                    if op_id in rewound_ids:
                        continue
                    operation = ops_by_id.get(op_id)
                    predecessor_op_id = (
                        operation.predecessor_op_id if operation is not None else None
                    )
                    if predecessor_op_id in rewound_ids:
                        rewound_ids.add(op_id)
                        changed = True

            if len(rewound_ids) > backtracking_max_ops:
                return []

            return sorted(
                [committed_assignment_by_op[op_id] for op_id in rewound_ids],
                key=lambda assignment: assignment.start_time,
            )

        def stabilize_temporal_consistency(
            assignments: list[Assignment],
            *,
            max_passes: int = 8,
        ) -> dict[str, int]:
            """Repair residual precedence and machine/setup conflicts in-place.

            The pass is forward-only (only shifts later), bounded, and intended
            as a final consistency stabilization step before objective evaluation.
            """

            if not assignments:
                return {
                    "passes": 0,
                    "precedence_shifts": 0,
                    "machine_shifts": 0,
                }

            assignment_by_op: dict[UUID, Assignment] = {
                assignment.operation_id: assignment for assignment in assignments
            }
            assigned_op_ids = set(assignment_by_op.keys())

            indegree: dict[UUID, int] = {op_id: 0 for op_id in assigned_op_ids}
            successors: dict[UUID, list[UUID]] = defaultdict(list)
            for op_id in assigned_op_ids:
                operation = ops_by_id.get(op_id)
                if operation is None:
                    continue
                predecessor_op_id = operation.predecessor_op_id
                if predecessor_op_id is None or predecessor_op_id not in assigned_op_ids:
                    continue
                successors[predecessor_op_id].append(op_id)
                indegree[op_id] = indegree.get(op_id, 0) + 1

            topo_queue = deque(
                sorted(
                    [op_id for op_id, deg in indegree.items() if deg == 0],
                    key=lambda op_id: (
                        ops_by_id[op_id].seq_in_order if op_id in ops_by_id else 0
                    ),
                )
            )
            topo_order: list[UUID] = []
            while topo_queue:
                op_id = topo_queue.popleft()
                topo_order.append(op_id)
                for succ_id in successors.get(op_id, []):
                    indegree[succ_id] -= 1
                    if indegree[succ_id] == 0:
                        topo_queue.append(succ_id)

            if len(topo_order) < len(assigned_op_ids):
                remaining_ids = assigned_op_ids - set(topo_order)
                topo_order.extend(
                    sorted(
                        remaining_ids,
                        key=lambda op_id: (
                            ops_by_id[op_id].seq_in_order if op_id in ops_by_id else 0
                        ),
                    )
                )

            precedence_shifts = 0
            machine_shifts = 0
            passes = 0

            for pass_index in range(max_passes):
                changed = False
                passes = pass_index + 1

                for op_id in topo_order:
                    operation = ops_by_id.get(op_id)
                    if operation is None or operation.predecessor_op_id is None:
                        continue
                    predecessor_assignment = assignment_by_op.get(operation.predecessor_op_id)
                    current_assignment = assignment_by_op.get(op_id)
                    if predecessor_assignment is None or current_assignment is None:
                        continue
                    if current_assignment.start_time < predecessor_assignment.end_time:
                        delta = predecessor_assignment.end_time - current_assignment.start_time
                        current_assignment.start_time += delta
                        current_assignment.end_time += delta
                        precedence_shifts += 1
                        changed = True

                assignments_by_machine: dict[UUID, list[Assignment]] = defaultdict(list)
                for assignment in assignment_by_op.values():
                    assignments_by_machine[assignment.work_center_id].append(assignment)

                for work_center_id, machine_assignments in assignments_by_machine.items():
                    machine_assignments.sort(key=lambda assignment: assignment.start_time)
                    previous_assignment: Assignment | None = None
                    for current_assignment in machine_assignments:
                        if previous_assignment is None:
                            previous_assignment = current_assignment
                            continue

                        previous_operation = ops_by_id.get(previous_assignment.operation_id)
                        current_operation = ops_by_id.get(current_assignment.operation_id)
                        required_setup = 0
                        if previous_operation is not None and current_operation is not None:
                            required_setup = dispatch_context.setup_minutes.get(
                                (
                                    work_center_id,
                                    previous_operation.state_id,
                                    current_operation.state_id,
                                ),
                                0,
                            )

                        required_start = previous_assignment.end_time + timedelta(
                            minutes=required_setup,
                        )
                        if current_assignment.start_time < required_start:
                            delta = required_start - current_assignment.start_time
                            current_assignment.start_time += delta
                            current_assignment.end_time += delta
                            machine_shifts += 1
                            changed = True

                        previous_assignment = current_assignment

                if not changed:
                    break

            return {
                "passes": passes,
                "precedence_shifts": precedence_shifts,
                "machine_shifts": machine_shifts,
            }

        while window_start_offset < horizon_minutes:
            if max_windows is not None and window_count >= max_windows:
                logger.info("RHC max_windows reached (%d)", max_windows)
                break
            if global_time_exceeded():
                time_limit_reached = True
                logger.warning("RHC time limit reached at window %d", window_count)
                break

            window_end_offset = min(
                window_start_offset + window_minutes + overlap_minutes,
                horizon_minutes,
            )
            window_count += 1

            resolved_predecessor_ids = committed_op_ids | (
                {
                    assignment.operation_id
                    for assignment in previous_window_tail_assignments
                    if assignment.operation_id in ops_by_id
                }
            )

            extend_candidate_frontiers(window_end_offset)
            raw_window_candidate_ids = filter_precedence_ready_candidate_ids(
                collect_raw_window_candidate_ids(),
                window_boundary=window_end_offset,
                resolved_predecessor_ids=resolved_predecessor_ids,
            )
            peak_raw_window_candidate_count = max(
                peak_raw_window_candidate_count,
                len(raw_window_candidate_ids),
            )

            if (
                adaptive_window_enabled
                and candidate_admission_active
                and adaptive_window_min_fill_ratio > 0.0
                and window_end_offset < horizon_minutes
            ):
                target_candidate_count = max(
                    1,
                    int(
                        math.ceil(
                            effective_window_op_cap * adaptive_window_min_fill_ratio
                        )
                    ),
                )
                current_effective_count = effective_candidate_count(
                    raw_window_candidate_ids,
                    window_end_offset,
                )
                if current_effective_count < target_candidate_count:
                    requested_multiplier = min(
                        adaptive_window_max_multiplier,
                        max(
                            1.0,
                            target_candidate_count / max(1, current_effective_count),
                        ),
                    )
                    expanded_window_end_offset = min(
                        horizon_minutes,
                        window_start_offset
                        + (base_window_span_minutes * requested_multiplier),
                    )
                    if expanded_window_end_offset > window_end_offset + 1e-9:
                        window_end_offset = expanded_window_end_offset
                        adaptive_window_expansions += 1
                        adaptive_window_expansion_factors.append(
                            (window_end_offset - window_start_offset)
                            / base_window_span_minutes
                        )
                        extend_candidate_frontiers(window_end_offset)
                        raw_window_candidate_ids = filter_precedence_ready_candidate_ids(
                            collect_raw_window_candidate_ids(),
                            window_boundary=window_end_offset,
                            resolved_predecessor_ids=resolved_predecessor_ids,
                        )
                        peak_raw_window_candidate_count = max(
                            peak_raw_window_candidate_count,
                            len(raw_window_candidate_ids),
                        )

            if not raw_window_candidate_ids:
                carryover_candidate_ids = {
                    assignment.operation_id
                    for assignment in previous_window_tail_assignments
                    if assignment.operation_id in ops_by_id
                    and assignment.operation_id not in committed_op_ids
                }
                if carryover_candidate_ids:
                    raw_window_candidate_ids = carryover_candidate_ids
                    peak_raw_window_candidate_count = max(
                        peak_raw_window_candidate_count,
                        len(raw_window_candidate_ids),
                    )
                    logger.info(
                        "RHC window %d recovered %d carry-over tail ops into an empty frontier",
                        window_count,
                        len(raw_window_candidate_ids),
                    )
                else:
                    bootstrap_candidate_ids: set[UUID] = set()
                    for op in ops_sorted_by_earliest:
                        if op_earliest.get(op.id, 0.0) >= window_end_offset:
                            break
                        if op.id in committed_op_ids:
                            continue
                        bootstrap_candidate_ids.add(op.id)
                        if len(bootstrap_candidate_ids) >= candidate_pool_limit:
                            break

                    if bootstrap_candidate_ids:
                        raw_window_candidate_ids = bootstrap_candidate_ids
                        peak_raw_window_candidate_count = max(
                            peak_raw_window_candidate_count,
                            len(raw_window_candidate_ids),
                        )
                        logger.info(
                            "RHC window %d bootstrap-admitted %d earliest-ready ops "
                            "into an empty frontier",
                            window_count,
                            len(raw_window_candidate_ids),
                        )
                    else:
                        append_inner_window_summary(
                            window=window_count,
                            ops_in_window=0,
                            ops_committed=0,
                            resolution_mode="no_candidates",
                            inner_result=None,
                            spillover_ops=0,
                        )
                        window_start_offset += window_minutes
                        continue

            window_candidate_ids = raw_window_candidate_ids
            window_admission_relaxed = False
            window_admission_relaxation_recovered_ops = 0
            window_full_scan_triggered = False
            window_full_scan_added_ops = 0
            window_full_scan_final_pool = 0
            if candidate_admission_active:
                admitted_window_candidate_ids = {
                    op_id
                    for op_id in raw_window_candidate_ids
                    if (
                        op_admission_offset_by_id.get(op_id, op_earliest.get(op_id, 0.0))
                        < window_end_offset
                    )
                }
                admitted_candidate_count = len(admitted_window_candidate_ids)
                filtered_by_admission = 0
                if admitted_window_candidate_ids:
                    filtered_by_admission = max(
                        0,
                        len(raw_window_candidate_ids) - admitted_candidate_count,
                    )
                    window_candidate_ids = admitted_window_candidate_ids
                else:
                    admission_starvation_count += 1
                if progressive_admission_relaxation_enabled:
                    relaxation_target_count = max(
                        1,
                        int(
                            math.ceil(
                                effective_window_op_cap * admission_relaxation_min_fill_ratio
                            )
                        ),
                    )
                    if (
                        len(raw_window_candidate_ids) > admitted_candidate_count
                        and admitted_candidate_count < relaxation_target_count
                    ):
                        window_candidate_ids = set(raw_window_candidate_ids)
                        window_admission_relaxed = True
                        window_admission_relaxation_recovered_ops = max(
                            0,
                            len(window_candidate_ids) - admitted_candidate_count,
                        )
                        admission_relaxation_windows += 1
                        admission_relaxation_recovered_ops += (
                            window_admission_relaxation_recovered_ops
                        )
                        filtered_by_admission = 0
                        logger.info(
                            "RHC window %d relaxed admission gate: admitted %d/%d raw candidates",
                            window_count,
                            admitted_candidate_count,
                            len(raw_window_candidate_ids),
                        )

                if admission_full_scan_enabled:
                    full_scan_target_count = max(
                        1,
                        int(
                            math.ceil(
                                effective_window_op_cap * admission_full_scan_min_fill_ratio
                            )
                        ),
                    )
                    if len(window_candidate_ids) <= full_scan_target_count:
                        window_full_scan_triggered = True
                        admission_full_scan_triggered_windows += 1
                        full_scan_seed_ids = set(window_candidate_ids)
                        for op in ops_sorted_by_earliest:
                            if op.id in committed_op_ids or op.id in full_scan_seed_ids:
                                continue
                            full_scan_seed_ids.add(op.id)
                            if len(full_scan_seed_ids) >= candidate_pool_limit:
                                break

                        window_full_scan_added_ops = max(
                            0,
                            len(full_scan_seed_ids) - len(window_candidate_ids),
                        )
                        admission_full_scan_added_ops += window_full_scan_added_ops
                        full_scan_candidate_ids = filter_precedence_ready_candidate_ids(
                            full_scan_seed_ids,
                            window_boundary=window_end_offset,
                            resolved_predecessor_ids=resolved_predecessor_ids,
                        )
                        window_full_scan_final_pool = len(full_scan_candidate_ids)
                        admission_full_scan_final_pool_peak = max(
                            admission_full_scan_final_pool_peak,
                            window_full_scan_final_pool,
                        )

                        full_scan_recovered_ops = max(
                            0,
                            len(full_scan_candidate_ids) - len(window_candidate_ids),
                        )
                        if full_scan_recovered_ops > 0:
                            window_candidate_ids = full_scan_candidate_ids
                            window_admission_relaxed = True
                            window_admission_relaxation_recovered_ops += (
                                full_scan_recovered_ops
                            )
                            admission_full_scan_windows += 1
                            admission_full_scan_recovered_ops += full_scan_recovered_ops
                            filtered_by_admission = 0
                            logger.info(
                                "RHC window %d escalated to capped full-scan frontier: +%d candidates (final pool=%d)",
                                window_count,
                                full_scan_recovered_ops,
                                window_full_scan_final_pool,
                            )
                candidate_pool_filtered_ops += filtered_by_admission

            if len(window_candidate_ids) > candidate_pool_limit:
                candidate_pool_clamped_windows += 1
                candidate_pool_filtered_ops += len(window_candidate_ids) - candidate_pool_limit
                window_candidate_ids = set(
                    sorted(
                        window_candidate_ids,
                        key=lambda op_id: (
                            1
                            if (
                                ops_by_id[op_id].predecessor_op_id is not None
                                and ops_by_id[op_id].predecessor_op_id not in committed_op_ids
                            )
                            else 0,
                            op_admission_offset_by_id.get(op_id, op_earliest.get(op_id, 0.0)),
                            order_due_offsets.get(ops_by_id[op_id].order_id, horizon_minutes),
                            ops_by_id[op_id].seq_in_order,
                            op_positions[op_id],
                        ),
                    )[:candidate_pool_limit]
                )

            window_candidate_ids = {
                op_id
                for op_id in window_candidate_ids
                if op_id not in committed_op_ids
            }
            peak_window_candidate_count = max(
                peak_window_candidate_count,
                len(window_candidate_ids),
            )

            if not window_candidate_ids:
                append_inner_window_summary(
                    window=window_count,
                    ops_in_window=0,
                    ops_committed=0,
                    resolution_mode="no_candidates",
                    inner_result=None,
                    candidate_pressure=0.0,
                    due_pressure=0.0,
                    due_drift_minutes=0.0,
                    spillover_ops=0,
                )
                window_start_offset += window_minutes
                continue

            # Stabilize candidate ordering before ranking so tied keys behave
            # deterministically across process runs.
            ordered_window_candidate_ops = [
                ops_by_id[op_id]
                for op_id in sorted(window_candidate_ids, key=op_positions.__getitem__)
            ]

            machine_available_offsets = {
                work_center.id: 0.0
                for work_center in problem.work_centers
            }
            for assignment in committed_assignments:
                end_offset = (assignment.end_time - horizon_start).total_seconds() / 60.0
                machine_available_offsets[assignment.work_center_id] = max(
                    machine_available_offsets.get(assignment.work_center_id, 0.0),
                    end_offset,
                )

            ordered_machine_ids = [work_center.id for work_center in problem.work_centers]
            machine_available_offsets_vector = [
                machine_available_offsets[machine_id]
                for machine_id in ordered_machine_ids
            ]
            machine_index_by_id = {
                machine_id: machine_index
                for machine_index, machine_id in enumerate(ordered_machine_ids)
            }

            eligible_machine_indices = [
                [
                    machine_index_by_id[wc_id]
                    for wc_id in op_eligible_wc_ids[op.id]
                    if wc_id in machine_index_by_id
                ]
                for op in ordered_window_candidate_ops
            ]
            predecessor_end_offsets: list[float] = []
            due_offsets: list[float] = []
            rpt_tail_minutes: list[float] = []
            order_weights: list[float] = []
            p_tilde_minutes: list[float] = []
            for op in ordered_window_candidate_ops:
                predecessor_end = 0.0
                if op.predecessor_op_id is not None:
                    predecessor_assignment = committed_assignment_by_op.get(op.predecessor_op_id)
                    if predecessor_assignment is not None:
                        predecessor_end = (
                            predecessor_assignment.end_time - horizon_start
                        ).total_seconds() / 60.0
                    else:
                        predecessor_end = op_earliest.get(op.id, 0.0)
                predecessor_end_offsets.append(predecessor_end)

                due_offsets.append(order_due_offsets.get(op.order_id, horizon_minutes))
                rpt_tail_minutes.append(
                    op_tail_rpt_by_id.get(op.id, op_mean_duration_by_id.get(op.id, 1.0))
                )

                order_weights.append(
                    max(
                        1.0,
                        float(orders_by_id[op.order_id].priority)
                        if op.order_id in orders_by_id
                        else 1.0,
                    )
                )
                p_tilde_minutes.append(
                    op_mean_duration_by_id.get(op.id, max(op.base_duration_min, 1.0))
                )

            candidate_slacks, candidate_pressures = compute_rhc_candidate_metrics_batch_np(
                machine_available_offsets=machine_available_offsets_vector,
                eligible_machine_indices=eligible_machine_indices,
                predecessor_end_offsets=predecessor_end_offsets,
                due_offsets=due_offsets,
                rpt_tail_minutes=rpt_tail_minutes,
                order_weights=order_weights,
                p_tilde_minutes=p_tilde_minutes,
                avg_total_p=avg_total_p,
                due_pressure_k1=due_pressure_k1,
                due_pressure_overdue_boost=due_pressure_overdue_boost,
            )

            candidate_slack_by_id: dict[UUID, float] = {
                op.id: slack
                for op, slack in zip(
                    ordered_window_candidate_ops,
                    candidate_slacks,
                    strict=True,
                )
            }
            candidate_pressure_by_id: dict[UUID, float] = {
                op.id: pressure
                for op, pressure in zip(
                    ordered_window_candidate_ops,
                    candidate_pressures,
                    strict=True,
                )
            }

            # Cap the window by configured budget and estimated machine throughput.
            uncovered_machines = {
                wc_id
                for op in ordered_window_candidate_ops
                for wc_id in op_eligible_wc_ids[op.id]
            }
            window_heap: list[tuple[float, float, int, int, UUID, bool]] = []
            for op in ordered_window_candidate_ops:
                covers_uncovered = bool(op_eligible_wc_ids[op.id] & uncovered_machines)
                score = candidate_pressure_by_id.get(op.id, 0.0)
                if covers_uncovered:
                    score *= machine_coverage_boost
                heappush(
                    window_heap,
                    (
                        -score,
                        order_due_offsets.get(op.order_id, horizon_minutes),
                        op.seq_in_order,
                        op_positions[op.id],
                        op.id,
                        covers_uncovered,
                    ),
                )

            selected_window_ids: set[UUID] = set()
            capped_selected_ops: list[Operation] = []
            cap_limit = min(effective_window_op_cap, len(ordered_window_candidate_ops))

            while window_heap and len(capped_selected_ops) < cap_limit:
                (
                    neg_score,
                    _due_key,
                    _seq_key,
                    _position_key,
                    op_id,
                    previous_cover,
                ) = heappop(window_heap)
                if op_id in selected_window_ids:
                    continue

                op = ops_by_id[op_id]
                current_cover = bool(op_eligible_wc_ids[op_id] & uncovered_machines)
                current_score = candidate_pressure_by_id.get(op_id, 0.0)
                if current_cover:
                    current_score *= machine_coverage_boost

                if previous_cover != current_cover or abs((-neg_score) - current_score) > 1e-12:
                    heappush(
                        window_heap,
                        (
                            -current_score,
                            order_due_offsets.get(op.order_id, horizon_minutes),
                            op.seq_in_order,
                            op_positions[op.id],
                            op.id,
                            current_cover,
                        ),
                    )
                    continue

                selected_window_ids.add(op_id)
                capped_selected_ops.append(op)
                for wc_id in op_eligible_wc_ids[op_id]:
                    uncovered_machines.discard(wc_id)

            carryover_tail_ids = [
                assignment.operation_id
                for assignment in previous_window_tail_assignments
                if assignment.operation_id in ops_by_id
                and assignment.operation_id not in committed_op_ids
            ]
            for op_id in sorted(set(carryover_tail_ids), key=op_positions.__getitem__):
                if op_id in selected_window_ids:
                    continue
                selected_window_ids.add(op_id)
                capped_selected_ops.append(ops_by_id[op_id])

            rewound_assignments = select_backtracking_assignments(window_start_offset)
            rewound_ids = {assignment.operation_id for assignment in rewound_assignments}
            if rewound_assignments:
                backtracking_windows += 1
                backtracking_ops_total += len(rewound_assignments)
                for assignment in rewound_assignments:
                    if assignment.operation_id not in selected_window_ids:
                        selected_window_ids.add(assignment.operation_id)
                        capped_selected_ops.append(ops_by_id[assignment.operation_id])

            window_ops = sorted(
                capped_selected_ops,
                key=lambda op: (
                    order_due_offsets.get(op.order_id, horizon_minutes),
                    op.seq_in_order,
                    op_earliest.get(op.id, 0.0),
                    op_positions[op.id],
                ),
            )

            window_candidate_pressure = len(window_candidate_ids) / max(
                1,
                effective_window_op_cap,
            )
            candidate_pressure_values.append(window_candidate_pressure)

            due_only_selected_ids = {
                op.id
                for op in window_ops
                if candidate_slack_by_id.get(op.id, 0.0) <= 0.0
            }
            due_pressure_selected_ids.update(due_only_selected_ids)
            window_due_pressure = len(due_only_selected_ids) / max(1, len(window_ops))
            due_pressure_values.append(window_due_pressure)

            window_due_drift_minutes = (
                sum(
                    max(
                        0.0,
                        window_end_offset - order_due_offsets.get(op.order_id, horizon_minutes),
                    )
                    for op in window_ops
                )
                / max(1, len(window_ops))
            )
            due_drift_minutes_values.append(window_due_drift_minutes)

            window_spillover = max(0, len(window_candidate_ids) - len(window_ops))
            spillover_count += window_spillover

            frozen_committed_assignments = [
                assignment
                for assignment in committed_assignments
                if assignment.operation_id not in rewound_ids
            ]
            frozen_committed_assignment_by_op = {
                op_id: assignment
                for op_id, assignment in committed_assignment_by_op.items()
                if op_id not in rewound_ids
            }
            frozen_committed_op_ids = set(frozen_committed_assignment_by_op.keys())

            window_op_ids = self._expand_predecessor_closure(
                {op.id for op in window_ops},
                ops_by_id,
                frozen_committed_op_ids,
            )

            # Clear predecessor links that point to committed (frozen) operations
            # so the sub-problem passes Pydantic validation
            clean_window_ops = []
            for op_id in sorted(window_op_ids, key=op_positions.__getitem__):
                op = ops_by_id[op_id]
                if op.predecessor_op_id and op.predecessor_op_id not in window_op_ids:
                    clean_window_ops.append(op.model_copy(update={"predecessor_op_id": None}))
                else:
                    clean_window_ops.append(op)

            logger.info(
                "RHC window %d: offset=%.0f–%.0f min, %d ops",
                window_count, window_start_offset, window_end_offset, len(clean_window_ops),
            )

            # ------ Attempt inner solver on the window sub-problem ------
            window_solved_via_inner = False
            commit_boundary = window_start_offset + window_minutes
            committed_before_window = len(committed_op_ids)
            inner_result: ScheduleResult | None = None
            inner_rejection_reason: str | None = None
            inner_exception_message: str | None = None
            fallback_iterations: int | None = None
            selected_inner_solver_name = inner_solver_name
            selected_inner_solver = inner_solver
            selected_inner_kwargs = dict(inner_kwargs)
            hybrid_routing_reason: str | None = None
            alns_budget_profile: dict[str, Any] | None = None
            boundary_reanchor_changed_ops = 0

            if (
                hybrid_inner_routing_enabled
                and inner_solver_name == "alns"
                and hybrid_inner_solver is not None
            ):
                hybrid_route_attempts += 1
                due_trigger = window_due_pressure >= hybrid_due_pressure_threshold
                candidate_trigger = (
                    window_candidate_pressure >= hybrid_candidate_pressure_threshold
                )
                size_trigger = len(clean_window_ops) <= hybrid_max_ops
                if size_trigger and (due_trigger or candidate_trigger):
                    selected_inner_solver_name = hybrid_inner_solver_name
                    selected_inner_solver = hybrid_inner_solver
                    selected_inner_kwargs = dict(hybrid_inner_kwargs)
                    hybrid_route_activations += 1
                    if due_trigger and candidate_trigger:
                        hybrid_routing_reason = "due+candidate"
                    elif due_trigger:
                        hybrid_routing_reason = "due"
                    else:
                        hybrid_routing_reason = "candidate"

            def resolve_inner_window_time_cap(
                selected_solver_name: str = selected_inner_solver_name,
                window_op_count: int = 0,
            ) -> float:
                if selected_solver_name == "alns":
                    if alns_inner_window_time_cap_s is not None:
                        return alns_inner_window_time_cap_s
                    if inner_window_time_cap_s is not None:
                        return inner_window_time_cap_s
                    if window_op_count >= alns_inner_window_time_cap_scale_threshold_ops:
                        return alns_inner_window_time_cap_scaled_s
                    return 60.0

                if inner_window_time_cap_s is not None:
                    return inner_window_time_cap_s
                return 60.0

            def scale_alns_inner_budget(
                effective_kwargs: dict[str, Any],
                *,
                per_window_limit: float,
                window_op_count: int,
            ) -> dict[str, Any]:
                requested_max_iterations = max(
                    1,
                    int(effective_kwargs.get("max_iterations", 500)),
                )
                min_destroy = max(1, int(effective_kwargs.get("min_destroy", 20)))
                requested_max_destroy = max(
                    min_destroy,
                    int(effective_kwargs.get("max_destroy", 300)),
                )
                repair_time_limit_s = max(
                    1.0,
                    float(effective_kwargs.get("repair_time_limit_s", 10.0)),
                )
                estimated_repair_s_per_destroyed_op = (
                    max(
                        0.01,
                        float(alns_budget_estimated_repair_s_per_destroyed_op_raw),
                    )
                    if alns_budget_estimated_repair_s_per_destroyed_op_raw is not None
                    else repair_time_limit_s / max(1, requested_max_destroy)
                )
                destroy_cap_from_budget = min(
                    requested_max_destroy,
                    max(
                        min_destroy,
                        int(
                            per_window_limit
                            / max(1, requested_max_iterations)
                            / estimated_repair_s_per_destroyed_op
                        ),
                    ),
                )
                destroy_fraction = max(
                    0.0,
                    float(effective_kwargs.get("destroy_fraction", 0.05)),
                )
                requested_destroy_size = max(
                    min_destroy,
                    int(math.ceil(window_op_count * destroy_fraction)),
                )
                effective_max_destroy = max(
                    min_destroy,
                    min(requested_max_destroy, destroy_cap_from_budget),
                )
                estimated_destroy_size = min(requested_destroy_size, effective_max_destroy)
                estimated_iteration_seconds = max(
                    0.1,
                    estimated_destroy_size * estimated_repair_s_per_destroyed_op,
                )
                effective_max_iterations = min(
                    requested_max_iterations,
                    max(1, int(per_window_limit / estimated_iteration_seconds)),
                )
                effective_repair_time_limit_s = max(
                    0.1,
                    min(
                        alns_dynamic_repair_time_limit_max_s,
                        max(
                            alns_dynamic_repair_time_limit_min_s,
                            effective_max_destroy * alns_dynamic_repair_s_per_destroyed_op,
                        ),
                    ),
                )
                return {
                    "requested_max_iterations": requested_max_iterations,
                    "requested_max_destroy": requested_max_destroy,
                    "effective_max_iterations": effective_max_iterations,
                    "effective_max_destroy": effective_max_destroy,
                    "effective_repair_time_limit_s": effective_repair_time_limit_s,
                    "estimated_repair_s_per_destroyed_op": (
                        estimated_repair_s_per_destroyed_op
                    ),
                    "scaled": (
                        effective_max_iterations != requested_max_iterations
                        or effective_max_destroy != requested_max_destroy
                    ),
                }

            if selected_inner_solver_name != "greedy":
                try:
                    # Build a sub-problem for just this window's operations
                    window_order_ids = {op.order_id for op in clean_window_ops}
                    sub_problem = ScheduleProblem(
                        states=problem.states,
                        orders=[o for o in problem.orders if o.id in window_order_ids],
                        operations=clean_window_ops,
                        work_centers=problem.work_centers,
                        setup_matrix=problem.setup_matrix,
                        auxiliary_resources=problem.auxiliary_resources,
                        aux_requirements=[
                            r for r in problem.aux_requirements
                            if r.operation_id in window_op_ids
                        ],
                        planning_horizon_start=problem.planning_horizon_start,
                        planning_horizon_end=problem.planning_horizon_end,
                    )
                    window_lower_bound = compute_relaxed_makespan_lower_bound(sub_problem)

                    # Compute remaining time budget for this window
                    remaining_time = max(10.0, time_limit_s - (time.monotonic() - t0))
                    per_window_limit = max(
                        10.0,
                        min(
                            remaining_time * inner_window_time_fraction,
                            resolve_inner_window_time_cap(
                                window_op_count=len(clean_window_ops)
                            ),
                        ),
                    )

                    if (
                        selected_inner_solver_name == "alns"
                        and per_window_limit < inner_solver_min_budget_s
                    ):
                        inner_rejection_reason = "inner_skipped_low_budget"
                    else:
                        effective_inner_kwargs = dict(selected_inner_kwargs)
                        external_window_warm_start_by_op = {
                            op_id: assignment
                            for op_id, assignment in external_warm_start_by_op.items()
                            if op_id in window_op_ids
                            and op_id not in frozen_committed_op_ids
                        }
                        warm_start_by_op = dict(external_window_warm_start_by_op)
                        if external_window_warm_start_by_op:
                            external_warm_start_used_windows += 1
                        for assignment in previous_window_tail_assignments:
                            if assignment.operation_id in window_op_ids:
                                warm_start_by_op[assignment.operation_id] = assignment
                        if rewound_assignments:
                            for assignment in rewound_assignments:
                                if assignment.operation_id in window_op_ids:
                                    warm_start_by_op[assignment.operation_id] = assignment
                        if warm_start_by_op:
                            effective_inner_kwargs["warm_start_assignments"] = sorted(
                                warm_start_by_op.values(),
                                key=lambda assignment: assignment.start_time,
                            )
                        if frozen_committed_assignments:
                            effective_inner_kwargs["frozen_assignments"] = list(
                                frozen_committed_assignments
                            )
                            frozen_predecessor_end_offsets = {
                                op.id: int(
                                    round(
                                        (
                                            frozen_committed_assignment_by_op[
                                                op.predecessor_op_id
                                            ].end_time
                                            - horizon_start
                                        ).total_seconds()
                                        / 60.0
                                    )
                                )
                                for op in clean_window_ops
                                if op.predecessor_op_id is not None
                                and op.predecessor_op_id not in window_op_ids
                                and op.predecessor_op_id
                                in frozen_committed_assignment_by_op
                            }
                            if frozen_predecessor_end_offsets:
                                effective_inner_kwargs[
                                    "frozen_predecessor_end_offsets"
                                ] = frozen_predecessor_end_offsets
                        if selected_inner_solver_name == "cpsat":
                            effective_inner_kwargs["auto_greedy_warm_start"] = False
                        if selected_inner_solver_name == "alns":
                            effective_inner_kwargs["due_pressure"] = window_due_pressure
                            effective_inner_kwargs["candidate_pressure"] = (
                                window_candidate_pressure
                            )
                            effective_inner_kwargs.setdefault(
                                "random_seed",
                                random_seed_base + window_count,
                            )
                            effective_inner_kwargs["dynamic_no_improve_enabled"] = (
                                dynamic_no_improve_enabled
                            )
                            effective_inner_kwargs["no_improve_due_alpha"] = no_improve_due_alpha
                            effective_inner_kwargs["no_improve_candidate_beta"] = (
                                no_improve_candidate_beta
                            )
                            if no_improve_min_iters is not None:
                                effective_inner_kwargs["no_improve_min_iters"] = (
                                    no_improve_min_iters
                                )
                            if no_improve_max_iters is not None:
                                effective_inner_kwargs["no_improve_max_iters"] = (
                                    no_improve_max_iters
                                )
                            if alns_budget_auto_scaling_enabled:
                                alns_budget_profile = scale_alns_inner_budget(
                                    effective_inner_kwargs,
                                    per_window_limit=per_window_limit,
                                    window_op_count=len(clean_window_ops),
                                )
                                effective_inner_kwargs["max_iterations"] = int(
                                    alns_budget_profile["effective_max_iterations"]
                                )
                                effective_inner_kwargs["max_destroy"] = int(
                                    alns_budget_profile["effective_max_destroy"]
                                )
                                if alns_dynamic_repair_budget_enabled:
                                    effective_inner_kwargs["repair_time_limit_s"] = float(
                                        alns_budget_profile[
                                            "effective_repair_time_limit_s"
                                        ]
                                    )
                                alns_effective_max_iterations_values.append(
                                    int(alns_budget_profile["effective_max_iterations"])
                                )
                                alns_effective_max_destroy_values.append(
                                    int(alns_budget_profile["effective_max_destroy"])
                                )
                                alns_effective_repair_time_limit_values.append(
                                    float(
                                        alns_budget_profile[
                                            "effective_repair_time_limit_s"
                                        ]
                                    )
                                )
                                if bool(alns_budget_profile["scaled"]):
                                    alns_budget_scaled_windows += 1

                        should_skip_alns_presearch = (
                            selected_inner_solver_name == "alns"
                            and alns_presearch_budget_guard_enabled
                            and len(clean_window_ops) > alns_presearch_max_window_ops
                            and per_window_limit < alns_presearch_min_time_limit_s
                        )
                        if should_skip_alns_presearch:
                            alns_presearch_budget_guard_skipped_windows += 1
                            logger.info(
                                "RHC window %d skipped ALNS pre-search: %d ops exceed guard "
                                "limit=%d at per-window budget %.2fs",
                                window_count,
                                len(clean_window_ops),
                                alns_presearch_max_window_ops,
                                per_window_limit,
                            )
                            inner_result = ScheduleResult(
                                solver_name="alns",
                                status=SolverStatus.ERROR,
                                assignments=[],
                                duration_ms=0,
                                metadata={
                                    "time_limit_exhausted_before_search": True,
                                    "iterations_completed": 0,
                                    "improvements": 0,
                                    "initial_solution_ms": 0,
                                    "budget_guard_skipped_initial_search": True,
                                    "inner_status_override": "not_run_budget_guard",
                                    "inner_solver_executed": False,
                                },
                            )
                        else:
                            inner_result = selected_inner_solver.solve(
                                sub_problem,
                                time_limit_s=per_window_limit,
                                **effective_inner_kwargs,
                            )
                        assert inner_result is not None

                    alns_budget_exhausted_before_search = bool(
                        selected_inner_solver_name == "alns"
                        and inner_result is not None
                        and bool((inner_result.metadata or {}).get(
                            "time_limit_exhausted_before_search"
                        ))
                        and int((inner_result.metadata or {}).get(
                            "iterations_completed",
                            0,
                        ))
                        == 0
                    )

                    if inner_result is not None and (
                        inner_result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
                        and inner_result.assignments
                        and not alns_budget_exhausted_before_search
                    ):
                        boundary_aware_assignments, boundary_reanchor_changed_ops = (
                            reanchor_inner_assignments(
                                inner_result.assignments,
                                frozen_assignments=frozen_committed_assignments,
                                frozen_assignment_by_op=frozen_committed_assignment_by_op,
                            )
                        )
                        if frozen_committed_assignments:
                            boundary_reanchor_windows += 1
                            boundary_reanchor_ops_total += len(boundary_aware_assignments)
                            boundary_reanchor_changed_ops_total += (
                                boundary_reanchor_changed_ops
                            )
                        # Map inner solver assignments into committed set
                        commit_candidates = collect_commit_candidates(
                            boundary_aware_assignments,
                            commit_boundary=commit_boundary,
                            commit_all=window_end_offset >= horizon_minutes,
                            frozen_committed_ids=frozen_committed_op_ids,
                        )
                        committed_now = len(commit_candidates)
                        committed_assignments = list(frozen_committed_assignments)
                        committed_assignment_by_op = dict(frozen_committed_assignment_by_op)
                        committed_op_ids = set(frozen_committed_op_ids)
                        for op_id, assignment in sorted(
                            commit_candidates.items(),
                            key=lambda item: item[1].start_time,
                        ):
                            committed_assignments.append(assignment)
                            committed_assignment_by_op[op_id] = assignment
                            committed_op_ids.add(op_id)
                        previous_window_tail_assignments = sorted(
                            [
                                assignment
                                for assignment in boundary_aware_assignments
                                if assignment.operation_id not in commit_candidates
                            ],
                            key=lambda assignment: assignment.start_time,
                        )
                        window_start_offset += window_minutes
                        window_solved_via_inner = True
                        append_inner_window_summary(
                            window=window_count,
                            ops_in_window=len(clean_window_ops),
                            ops_committed=committed_now,
                            resolution_mode="inner",
                            inner_result=inner_result,
                            lower_bound=window_lower_bound.value,
                            inner_time_limit_s=per_window_limit,
                            candidate_pressure=window_candidate_pressure,
                            due_pressure=window_due_pressure,
                            due_drift_minutes=window_due_drift_minutes,
                            spillover_ops=window_spillover,
                        )
                        if window_admission_relaxed:
                            inner_window_summaries[-1]["admission_relaxed"] = True
                            inner_window_summaries[-1][
                                "admission_relaxation_recovered_ops"
                            ] = window_admission_relaxation_recovered_ops
                        if window_full_scan_triggered:
                            inner_window_summaries[-1]["full_scan_triggered"] = True
                            inner_window_summaries[-1][
                                "full_scan_added_ops"
                            ] = window_full_scan_added_ops
                            inner_window_summaries[-1][
                                "full_scan_final_pool"
                            ] = window_full_scan_final_pool
                        inner_window_summaries[-1]["boundary_reanchor_ops"] = len(
                            boundary_aware_assignments
                        )
                        inner_window_summaries[-1][
                            "boundary_reanchor_changed_ops"
                        ] = boundary_reanchor_changed_ops
                        if alns_budget_profile is not None:
                            inner_window_summaries[-1]["alns_budget_auto_scaled"] = bool(
                                alns_budget_profile["scaled"]
                            )
                            inner_window_summaries[-1][
                                "alns_effective_max_iterations"
                            ] = int(alns_budget_profile["effective_max_iterations"])
                            inner_window_summaries[-1][
                                "alns_effective_max_destroy"
                            ] = int(alns_budget_profile["effective_max_destroy"])
                            inner_window_summaries[-1][
                                "alns_estimated_repair_s_per_destroyed_op"
                            ] = round(
                                float(
                                    alns_budget_profile[
                                        "estimated_repair_s_per_destroyed_op"
                                    ]
                                ),
                                4,
                            )
                            inner_window_summaries[-1][
                                "alns_effective_repair_time_limit_s"
                            ] = round(
                                float(alns_budget_profile["effective_repair_time_limit_s"]),
                                4,
                            )
                        if rewound_assignments:
                            inner_window_summaries[-1]["backtracking_rewind_ops"] = len(
                                rewound_assignments
                            )
                        if hybrid_routing_reason is not None:
                            inner_window_summaries[-1]["inner_solver_selected"] = (
                                selected_inner_solver_name
                            )
                            inner_window_summaries[-1]["hybrid_routing_reason"] = (
                                hybrid_routing_reason
                            )
                        logger.info(
                            "RHC window %d solved by %s inner solver "
                            "(%d ops committed)",
                            window_count,
                            selected_inner_solver_name,
                            committed_now,
                        )
                    else:
                        if inner_result is None:
                            inner_rejection_reason = inner_rejection_reason or "inner_not_run"
                        elif alns_budget_exhausted_before_search:
                            inner_rejection_reason = "inner_time_limit_exhausted_before_search"
                        elif inner_result.status not in (
                            SolverStatus.FEASIBLE,
                            SolverStatus.OPTIMAL,
                        ):
                            inner_rejection_reason = (
                                f"inner_status_{inner_result.status.value}"
                                if hasattr(inner_result.status, "value")
                                else f"inner_status_{inner_result.status}"
                            )
                        else:
                            inner_rejection_reason = "inner_empty_assignments"
                except Exception as exc:
                    inner_rejection_reason = "inner_exception"
                    inner_exception_message = f"{type(exc).__name__}: {exc}"
                    if len(inner_exception_messages_sample) < max_inner_exception_message_samples:
                        inner_exception_messages_sample.append(inner_exception_message)
                    if inner_exception_logs_emitted < max_inner_exception_logs:
                        logger.warning(
                            "RHC window %d: inner solver '%s' failed, falling back to greedy",
                            window_count, selected_inner_solver_name,
                            exc_info=True,
                        )
                        inner_exception_logs_emitted += 1
                    elif inner_exception_logs_emitted == max_inner_exception_logs:
                        logger.warning(
                            "RHC inner solver exception log sample cap reached; suppressing additional stack traces"
                        )
                        inner_exception_logs_emitted += 1

            # ------ Fallback: greedy dispatch (original behavior) ------
            if not window_solved_via_inner:
                previous_window_tail_assignments = []
                # Solve the window by greedy dispatch on its operations, building
                # on top of already-committed assignments.
                scheduled_so_far = list(frozen_committed_assignments)
                scheduled_by_op = dict(frozen_committed_assignment_by_op)
                machine_idx = MachineIndex(dispatch_context)
                for assignment in scheduled_so_far:
                    machine_idx.add(assignment)
                ready_pool = list(clean_window_ops)
                window_scheduled_ids: set[UUID] = set()

                # Sort by priority desc, then seq asc for deterministic ordering
                ready_pool.sort(
                    key=lambda op: (
                        -(orders_by_id[op.order_id].priority if op.order_id in orders_by_id else 0),
                        op.seq_in_order,
                    ),
                )

                max_inner_iters = len(ready_pool) * 3
                inner_iter = 0
                while ready_pool and inner_iter < max_inner_iters:
                    if global_time_exceeded():
                        time_limit_reached = True
                        logger.warning(
                            "RHC time limit reached during window %d greedy scheduling",
                            window_count,
                        )
                        break
                    inner_iter += 1
                    placed_any = False
                    for op in list(ready_pool):
                        if global_time_exceeded():
                            time_limit_reached = True
                            logger.warning(
                                "RHC time limit reached during window %d greedy scheduling",
                                window_count,
                            )
                            break
                        # Check predecessor constraint
                        if op.predecessor_op_id and (
                            op.predecessor_op_id not in committed_op_ids
                            and op.predecessor_op_id not in window_scheduled_ids
                        ):
                            continue  # predecessor not yet scheduled

                        # Find predecessor end time
                        pred_end = 0.0
                        if op.predecessor_op_id:
                            pred_assignment = scheduled_by_op.get(op.predecessor_op_id)
                            if pred_assignment is not None:
                                pred_end = (
                                    pred_assignment.end_time - horizon_start
                                ).total_seconds() / 60.0

                        eligible = (
                            op.eligible_wc_ids
                            if op.eligible_wc_ids
                            else [wc.id for wc in problem.work_centers]
                        )

                        best_slot = None
                        best_wc = None
                        for wc_id in eligible:
                            slot = find_earliest_feasible_slot(
                                dispatch_context,
                                scheduled_so_far,
                                op,
                                wc_id,
                                pred_end,
                                machine_index=machine_idx,
                            )
                            if slot is None:
                                continue
                            if slot.end_offset > horizon_minutes + 1e-9:
                                horizon_clipped_assignments += 1
                                continue
                            if best_slot is None or slot.end_offset < best_slot.end_offset:
                                best_slot = slot
                                best_wc = wc_id

                        if best_slot and best_wc:
                            start = horizon_start + timedelta(
                                minutes=best_slot.start_offset,
                            )
                            end = horizon_start + timedelta(
                                minutes=best_slot.end_offset,
                            )
                            assignment = Assignment(
                                operation_id=op.id,
                                work_center_id=best_wc,
                                start_time=start,
                                end_time=end,
                                setup_minutes=best_slot.setup_minutes,
                                aux_resource_ids=best_slot.aux_resource_ids,
                            )
                            scheduled_so_far.append(assignment)
                            scheduled_by_op[op.id] = assignment
                            machine_idx.add(assignment)
                            window_scheduled_ids.add(op.id)
                            ready_pool.remove(op)
                            placed_any = True

                    if time_limit_reached or not placed_any:
                        break  # no progress possible

                fallback_iterations = inner_iter

                # Commit assignments from this window
                commit_candidates = collect_commit_candidates(
                    scheduled_so_far,
                    commit_boundary=commit_boundary,
                    commit_all=window_end_offset >= horizon_minutes,
                    frozen_committed_ids=frozen_committed_op_ids,
                    eligible_ids=window_scheduled_ids,
                )
                committed_assignments = list(frozen_committed_assignments)
                committed_assignment_by_op = dict(frozen_committed_assignment_by_op)
                committed_op_ids = set(frozen_committed_op_ids)
                for op_id, assignment in sorted(
                    commit_candidates.items(),
                    key=lambda item: item[1].start_time,
                ):
                    committed_assignments.append(assignment)
                    committed_assignment_by_op[op_id] = assignment
                    committed_op_ids.add(op_id)

                if inner_solver_name != "greedy":
                    inner_fallback_windows += 1
                    fallback_reason_code = inner_rejection_reason or "inner_not_accepted"
                    inner_fallback_reason_counts[fallback_reason_code] += 1
                    if fallback_reason_code == "inner_exception":
                        inner_exception_windows += 1
                    if inner_result is None:
                        inner_status_counts["not_run"] += 1
                    else:
                        inner_status = (inner_result.metadata or {}).get(
                            "inner_status_override"
                        )
                        if not isinstance(inner_status, str) or not inner_status:
                            inner_status = (
                                inner_result.status.value
                                if hasattr(inner_result.status, "value")
                                else str(inner_result.status)
                            )
                        inner_status_counts[inner_status] += 1
                    append_inner_window_summary(
                        window=window_count,
                        ops_in_window=len(clean_window_ops),
                        ops_committed=len(committed_op_ids) - committed_before_window,
                        resolution_mode="fallback_greedy",
                        inner_result=inner_result,
                        inner_time_limit_s=per_window_limit,
                        candidate_pressure=window_candidate_pressure,
                        due_pressure=window_due_pressure,
                        due_drift_minutes=window_due_drift_minutes,
                        spillover_ops=window_spillover,
                        fallback_reason=fallback_reason_code,
                        fallback_iterations=fallback_iterations,
                        exception_message=inner_exception_message,
                    )
                    if window_admission_relaxed:
                        inner_window_summaries[-1]["admission_relaxed"] = True
                        inner_window_summaries[-1][
                            "admission_relaxation_recovered_ops"
                        ] = window_admission_relaxation_recovered_ops
                    if window_full_scan_triggered:
                        inner_window_summaries[-1]["full_scan_triggered"] = True
                        inner_window_summaries[-1][
                            "full_scan_added_ops"
                        ] = window_full_scan_added_ops
                        inner_window_summaries[-1][
                            "full_scan_final_pool"
                        ] = window_full_scan_final_pool
                    if alns_budget_profile is not None:
                        inner_window_summaries[-1]["alns_budget_auto_scaled"] = bool(
                            alns_budget_profile["scaled"]
                        )
                        inner_window_summaries[-1][
                            "alns_effective_max_iterations"
                        ] = int(alns_budget_profile["effective_max_iterations"])
                        inner_window_summaries[-1][
                            "alns_effective_max_destroy"
                        ] = int(alns_budget_profile["effective_max_destroy"])
                        inner_window_summaries[-1][
                            "alns_estimated_repair_s_per_destroyed_op"
                        ] = round(
                            float(
                                alns_budget_profile[
                                    "estimated_repair_s_per_destroyed_op"
                                ]
                            ),
                            4,
                        )
                        inner_window_summaries[-1][
                            "alns_effective_repair_time_limit_s"
                        ] = round(
                            float(alns_budget_profile["effective_repair_time_limit_s"]),
                            4,
                        )
                    if rewound_assignments:
                        inner_window_summaries[-1]["backtracking_rewind_ops"] = len(
                            rewound_assignments
                        )
                    inner_window_summaries[-1]["inner_solver_selected"] = (
                        selected_inner_solver_name
                    )
                    if hybrid_routing_reason is not None:
                        inner_window_summaries[-1]["hybrid_routing_reason"] = (
                            hybrid_routing_reason
                        )

                window_start_offset += window_minutes
                if time_limit_reached:
                    break

        # ------- Handle any remaining unscheduled operations -------
        unscheduled_ids = {op.id for op in problem.operations} - committed_op_ids
        if unscheduled_ids:
            if time_limit_reached or global_time_exceeded():
                fallback_repair_skipped = True
                logger.warning(
                    "RHC: %d operations unscheduled after all windows; "
                    "skipping fallback greedy repair because the global time limit is exhausted",
                    len(unscheduled_ids),
                )
            elif not fallback_repair_enabled:
                fallback_repair_skipped = True
                logger.info(
                    "RHC: %d operations unscheduled after all windows; "
                    "skipping fallback greedy repair because fallback_repair_enabled=false",
                    len(unscheduled_ids),
                )
            else:
                fallback_repair_attempted = True
                logger.warning(
                    "RHC: %d operations unscheduled after all windows; "
                    "running fallback greedy repair",
                    len(unscheduled_ids),
                )
                remaining_ops = [op for op in problem.operations if op.id in unscheduled_ids]
                remaining_ops.sort(key=lambda op: op.seq_in_order)
                repair_machine_idx = MachineIndex(dispatch_context)
                for assignment in committed_assignments:
                    repair_machine_idx.add(assignment)
                fallback_iters = len(remaining_ops) * 3
                fi = 0
                while remaining_ops and fi < fallback_iters:
                    if global_time_exceeded():
                        time_limit_reached = True
                        fallback_repair_time_limited = True
                        logger.warning(
                            "RHC fallback greedy repair stopped because the global time "
                            "limit is exhausted"
                        )
                        break
                    fi += 1
                    placed = False
                    for op in list(remaining_ops):
                        if global_time_exceeded():
                            time_limit_reached = True
                            fallback_repair_time_limited = True
                            logger.warning(
                                "RHC fallback greedy repair stopped because the global time "
                                "limit is exhausted"
                            )
                            break
                        if op.predecessor_op_id and op.predecessor_op_id not in committed_op_ids:
                            continue
                        pred_end = 0.0
                        if op.predecessor_op_id:
                            pred_assignment = committed_assignment_by_op.get(op.predecessor_op_id)
                            if pred_assignment is not None:
                                pred_end = (
                                    pred_assignment.end_time - horizon_start
                                ).total_seconds() / 60.0
                        eligible = (
                            op.eligible_wc_ids
                            if op.eligible_wc_ids
                            else [wc.id for wc in problem.work_centers]
                        )
                        best_slot = None
                        best_wc = None
                        for wc_id in eligible:
                            slot = find_earliest_feasible_slot(
                                dispatch_context,
                                committed_assignments,
                                op,
                                wc_id,
                                pred_end,
                                machine_index=repair_machine_idx,
                            )
                            if slot is None:
                                continue
                            if slot.end_offset > horizon_minutes + 1e-9:
                                horizon_clipped_assignments += 1
                                continue
                            if best_slot is None or slot.end_offset < best_slot.end_offset:
                                best_slot = slot
                                best_wc = wc_id
                        if best_slot and best_wc:
                            start = horizon_start + timedelta(
                                minutes=best_slot.start_offset,
                            )
                            end = horizon_start + timedelta(
                                minutes=best_slot.end_offset,
                            )
                            committed_assignments.append(
                                Assignment(
                                    operation_id=op.id,
                                    work_center_id=best_wc,
                                    start_time=start,
                                    end_time=end,
                                    setup_minutes=best_slot.setup_minutes,
                                    aux_resource_ids=best_slot.aux_resource_ids,
                                )
                            )
                            repair_machine_idx.add(committed_assignments[-1])
                            committed_assignment_by_op[op.id] = committed_assignments[-1]
                            committed_op_ids.add(op.id)
                            remaining_ops.remove(op)
                            placed = True
                    if time_limit_reached or not placed:
                        break

        # ------- Final objective evaluation -------
        stabilization_pass_budget = 8 if len(committed_assignments) <= 5_000 else 5
        temporal_stabilization = stabilize_temporal_consistency(
            committed_assignments,
            max_passes=stabilization_pass_budget,
        )
        recompute_assignment_setups(committed_assignments, dispatch_context)

        if not committed_assignments:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return ScheduleResult(
                solver_name=self.name,
                status=SolverStatus.ERROR,
                duration_ms=elapsed_ms,
                metadata={
                    "error": "no assignments produced",
                    "acceleration": acceleration_status,
                    "windows": window_count,
                    "time_limit_reached": time_limit_reached,
                    "horizon_clipped_assignments": horizon_clipped_assignments,
                    "fallback_repair_attempted": fallback_repair_attempted,
                    "fallback_repair_skipped": fallback_repair_skipped,
                    "fallback_repair_time_limited": fallback_repair_time_limited,
                    "ops_unscheduled": len(problem.operations),
                    "lower_bound_upper_bound_comparable": False,
                    "gap": None,
                    "temporal_stabilization": temporal_stabilization,
                },
            )

        # Evaluate
        final_obj = self._evaluate_final(problem, committed_assignments, sdst)
        scheduled_count = len(committed_op_ids)
        total_ops = len(problem.operations)
        status = SolverStatus.FEASIBLE if scheduled_count == total_ops else SolverStatus.ERROR
        bounds_comparable = scheduled_count == total_ops
        gap_ratio = (
            round(
                max(final_obj.makespan_minutes - global_lower_bound.value, 0.0)
                / max(final_obj.makespan_minutes, 1e-9),
                6,
            )
            if bounds_comparable
            else None
        )

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            "RHC finished: %d windows, %d/%d ops scheduled, makespan=%.1f min, %d ms",
            window_count, scheduled_count, total_ops,
            final_obj.makespan_minutes, elapsed_ms,
        )

        inner_solver_windows = sum(
            1
            for summary in inner_window_summaries
            if summary.get("resolution_mode") in {"inner", "fallback_greedy"}
        )
        inner_fallback_ratio = (
            inner_fallback_windows / max(1, inner_solver_windows)
            if inner_solver_windows > 0
            else 0.0
        )
        inner_resolution_counts = {
            "inner": sum(
                1 for summary in inner_window_summaries if summary.get("resolution_mode") == "inner"
            ),
            "fallback_greedy": sum(
                1
                for summary in inner_window_summaries
                if summary.get("resolution_mode") == "fallback_greedy"
            ),
        }

        return ScheduleResult(
            solver_name=self.name,
            status=status,
            assignments=committed_assignments,
            objective=final_obj,
            duration_ms=elapsed_ms,
            metadata={
                "acceleration": acceleration_status,
                "windows_solved": window_count,
                "ops_scheduled": scheduled_count,
                "ops_total": total_ops,
                "lower_bound": round(global_lower_bound.value, 4),
                "upper_bound": round(final_obj.makespan_minutes, 4),
                "gap": gap_ratio,
                "lower_bound_upper_bound_comparable": bounds_comparable,
                "lower_bound_method": "relaxed_precedence_capacity",
                "lower_bound_components": global_lower_bound.as_metadata(),
                "inner_solver": inner_solver_name,
                "inner_solver_windows": inner_solver_windows,
                "inner_fallback_windows": inner_fallback_windows,
                "inner_fallback_ratio": round(inner_fallback_ratio, 4),
                "inner_resolution_counts": inner_resolution_counts,
                "inner_fallback_reason_counts": dict(sorted(inner_fallback_reason_counts.items())),
                "inner_status_counts": dict(sorted(inner_status_counts.items())),
                "inner_exception_windows": inner_exception_windows,
                "inner_exception_message_samples": list(inner_exception_messages_sample),
                "inner_exception_logs_emitted": min(
                    inner_exception_logs_emitted,
                    max_inner_exception_logs,
                ),
                "inner_exception_logs_suppressed": max(
                    inner_exception_logs_emitted - max_inner_exception_logs,
                    0,
                ),
                "inner_fallback_kpi_threshold": inner_fallback_kpi_threshold,
                "inner_fallback_kpi_passed": inner_fallback_ratio <= inner_fallback_kpi_threshold,
                "preprocessing_ms": preprocessing_ms,
                "preprocessing_phase_ms": dict(preprocess_phase_ms),
                "peak_window_candidate_count": peak_window_candidate_count,
                "peak_raw_window_candidate_count": peak_raw_window_candidate_count,
                "due_pressure_selected_ops": len(due_pressure_selected_ids),
                "candidate_pool_limit": candidate_pool_limit,
                "candidate_pool_factor": candidate_pool_factor,
                "adaptive_window_enabled": adaptive_window_enabled,
                "adaptive_window_min_fill_ratio": adaptive_window_min_fill_ratio,
                "adaptive_window_max_multiplier": adaptive_window_max_multiplier,
                "adaptive_window_expansions": adaptive_window_expansions,
                "adaptive_window_mean_multiplier_applied": round(
                    sum(adaptive_window_expansion_factors)
                    / len(adaptive_window_expansion_factors),
                    4,
                )
                if adaptive_window_expansion_factors
                else 1.0,
                "adaptive_window_max_multiplier_applied": round(
                    max(adaptive_window_expansion_factors),
                    4,
                )
                if adaptive_window_expansion_factors
                else 1.0,
                "external_warm_start_supplied_assignments": len(
                    external_warm_start_by_op
                ),
                "external_warm_start_used_windows": external_warm_start_used_windows,
                "candidate_pool_clamped_windows": candidate_pool_clamped_windows,
                "candidate_pool_filtered_ops": candidate_pool_filtered_ops,
                "candidate_admission_enabled": candidate_admission_active,
                "candidate_admission_configured": candidate_admission_enabled,
                "precedence_ready_candidate_filter_enabled": (
                    precedence_ready_candidate_filter_enabled
                ),
                "precedence_ready_filtered_ops": precedence_ready_filtered_ops,
                "precedence_ready_blocked_by_precedence_count": (
                    precedence_blocked_by_precedence_count
                ),
                "precedence_ready_ratio": round(
                    precedence_ready_candidate_ready_total
                    / max(precedence_ready_candidate_ops_total, 1),
                    4,
                ),
                "due_admission_horizon_factor": due_admission_horizon_factor,
                "admission_tail_weight": admission_tail_weight,
                "progressive_admission_relaxation_enabled": (
                    progressive_admission_relaxation_enabled
                ),
                "admission_relaxation_min_fill_ratio": admission_relaxation_min_fill_ratio,
                "admission_relaxation_windows": admission_relaxation_windows,
                "admission_relaxation_recovered_ops": admission_relaxation_recovered_ops,
                "admission_full_scan_enabled": admission_full_scan_enabled,
                "admission_full_scan_min_fill_ratio": admission_full_scan_min_fill_ratio,
                "admission_full_scan_windows": admission_full_scan_windows,
                "admission_full_scan_triggered_windows": admission_full_scan_triggered_windows,
                "admission_full_scan_added_ops": admission_full_scan_added_ops,
                "admission_full_scan_final_pool_peak": admission_full_scan_final_pool_peak,
                "admission_full_scan_recovered_ops": admission_full_scan_recovered_ops,
                "candidate_pressure_mean": round(
                    sum(candidate_pressure_values) / len(candidate_pressure_values),
                    4,
                )
                if candidate_pressure_values
                else 0.0,
                "candidate_pressure_max": round(max(candidate_pressure_values), 4)
                if candidate_pressure_values
                else 0.0,
                "due_pressure_mean": round(
                    sum(due_pressure_values) / len(due_pressure_values),
                    4,
                )
                if due_pressure_values
                else 0.0,
                "due_drift_minutes_mean": round(
                    sum(due_drift_minutes_values) / len(due_drift_minutes_values),
                    2,
                )
                if due_drift_minutes_values
                else 0.0,
                "due_drift_minutes_max": round(max(due_drift_minutes_values), 2)
                if due_drift_minutes_values
                else 0.0,
                "spillover_count": spillover_count,
                "earliest_frontier_advances": admission_frontier_advances,
                "admission_frontier_advances": admission_frontier_advances,
                "admission_starvation_count": admission_starvation_count,
                "due_frontier_advances": due_frontier_advances,
                "effective_window_operation_cap": effective_window_op_cap,
                "window_load_factor": window_load_factor,
                "dynamic_no_improve_enabled": dynamic_no_improve_enabled,
                "no_improve_due_alpha": no_improve_due_alpha,
                "no_improve_candidate_beta": no_improve_candidate_beta,
                "no_improve_min_iters": no_improve_min_iters,
                "no_improve_max_iters": no_improve_max_iters,
                "max_windows": max_windows,
                "inner_solver_min_budget_s": inner_solver_min_budget_s,
                "backtracking_enabled": backtracking_enabled,
                "backtracking_tail_minutes": backtracking_tail_minutes,
                "backtracking_max_ops": backtracking_max_ops,
                "backtracking_windows": backtracking_windows,
                "backtracking_ops_total": backtracking_ops_total,
                "inner_window_time_fraction": inner_window_time_fraction,
                "inner_window_time_cap_s": inner_window_time_cap_s,
                "commit_boundary_mode": "end_time",
                "alns_inner_window_time_cap_s": alns_inner_window_time_cap_s,
                "alns_inner_window_time_cap_scale_threshold_ops": (
                    alns_inner_window_time_cap_scale_threshold_ops
                ),
                "alns_inner_window_time_cap_scaled_s": alns_inner_window_time_cap_scaled_s,
                "alns_budget_auto_scaling_enabled": alns_budget_auto_scaling_enabled,
                "alns_budget_estimated_repair_s_per_destroyed_op": (
                    round(
                        float(alns_budget_estimated_repair_s_per_destroyed_op_raw),
                        4,
                    )
                    if alns_budget_estimated_repair_s_per_destroyed_op_raw is not None
                    else None
                ),
                "alns_dynamic_repair_budget_enabled": alns_dynamic_repair_budget_enabled,
                "alns_dynamic_repair_s_per_destroyed_op": (
                    alns_dynamic_repair_s_per_destroyed_op
                ),
                "alns_dynamic_repair_time_limit_min_s": (
                    alns_dynamic_repair_time_limit_min_s
                ),
                "alns_dynamic_repair_time_limit_max_s": (
                    alns_dynamic_repair_time_limit_max_s
                ),
                "alns_budget_scaled_windows": alns_budget_scaled_windows,
                "alns_presearch_budget_guard_enabled": (
                    alns_presearch_budget_guard_enabled
                ),
                "alns_presearch_max_window_ops": alns_presearch_max_window_ops,
                "alns_presearch_min_time_limit_s": alns_presearch_min_time_limit_s,
                "alns_presearch_budget_guard_skipped_windows": (
                    alns_presearch_budget_guard_skipped_windows
                ),
                "alns_budget_mean_effective_max_iterations": round(
                    sum(alns_effective_max_iterations_values)
                    / len(alns_effective_max_iterations_values),
                    2,
                )
                if alns_effective_max_iterations_values
                else 0.0,
                "alns_budget_mean_effective_max_destroy": round(
                    sum(alns_effective_max_destroy_values)
                    / len(alns_effective_max_destroy_values),
                    2,
                )
                if alns_effective_max_destroy_values
                else 0.0,
                "alns_budget_mean_effective_repair_time_limit_s": round(
                    sum(alns_effective_repair_time_limit_values)
                    / len(alns_effective_repair_time_limit_values),
                    4,
                )
                if alns_effective_repair_time_limit_values
                else 0.0,
                "boundary_reanchor_windows": boundary_reanchor_windows,
                "boundary_reanchor_ops_total": boundary_reanchor_ops_total,
                "boundary_reanchor_changed_ops_total": boundary_reanchor_changed_ops_total,
                "random_seed_base": random_seed_base,
                "hybrid_inner_routing_enabled": hybrid_inner_routing_enabled,
                "hybrid_inner_solver": hybrid_inner_solver_name,
                "hybrid_due_pressure_threshold": hybrid_due_pressure_threshold,
                "hybrid_candidate_pressure_threshold": hybrid_candidate_pressure_threshold,
                "hybrid_max_ops": hybrid_max_ops,
                "hybrid_route_attempts": hybrid_route_attempts,
                "hybrid_route_activations": hybrid_route_activations,
                "hybrid_route_activation_rate": round(
                    hybrid_route_activations / max(1, hybrid_route_attempts),
                    4,
                )
                if hybrid_route_attempts > 0
                else 0.0,
                "horizon_clipped_assignments": horizon_clipped_assignments,
                "temporal_stabilization": temporal_stabilization,
                "time_limit_reached": time_limit_reached,
                "fallback_repair_attempted": fallback_repair_attempted,
                "fallback_repair_skipped": fallback_repair_skipped,
                "fallback_repair_time_limited": fallback_repair_time_limited,
                "ops_unscheduled": total_ops - scheduled_count,
                "inner_window_summaries": inner_window_summaries,
            },
        )

    @staticmethod
    def _make_inner_solver(name: str) -> BaseSolver:
        """Instantiate the inner solver by name."""
        if name == "alns":
            from synaps.solvers.alns_solver import AlnsSolver
            return AlnsSolver()
        elif name == "cpsat":
            from synaps.solvers.cpsat_solver import CpSatSolver
            return CpSatSolver()
        elif name == "greedy":
            from synaps.solvers.greedy_dispatch import GreedyDispatch
            return GreedyDispatch()
        elif name == "beam":
            from synaps.solvers.greedy_dispatch import BeamSearchDispatch
            return BeamSearchDispatch(beam_width=3)
        else:
            from synaps.solvers.greedy_dispatch import GreedyDispatch
            return GreedyDispatch()

    @staticmethod
    def _compute_earliest_starts(
        problem: ScheduleProblem,
        result: dict[UUID, float],
    ) -> None:
        """Compute earliest possible start offset for each operation
        based on cumulative processing times through the precedence chain."""
        ops_by_id = {op.id: op for op in problem.operations}

        indegree = {op.id: 0 for op in problem.operations}
        successors: dict[UUID, list[UUID]] = {}
        for op in problem.operations:
            if op.predecessor_op_id:
                successors.setdefault(op.predecessor_op_id, []).append(op.id)
                indegree[op.id] += 1

        queue: deque[UUID] = deque()
        for op in problem.operations:
            if indegree[op.id] == 0:
                result[op.id] = 0.0
                queue.append(op.id)

        while queue:
            current_id = queue.popleft()
            current_op = ops_by_id[current_id]
            current_end = result.get(current_id, 0.0) + current_op.base_duration_min
            for succ_id in successors.get(current_id, []):
                existing = result.get(succ_id, 0.0)
                if current_end > existing:
                    result[succ_id] = current_end
                indegree[succ_id] -= 1
                if indegree[succ_id] == 0:
                    queue.append(succ_id)

    @staticmethod
    def _propagate_earliest_starts_with_release_and_duration(
        problem: ScheduleProblem,
        result: dict[UUID, float],
        *,
        op_duration_by_id: dict[UUID, float],
        order_release_offsets: dict[UUID, float],
    ) -> None:
        """Tighten earliest offsets with order release times and feasible min durations."""

        ops_by_id = {op.id: op for op in problem.operations}
        indegree = {op.id: 0 for op in problem.operations}
        successors: dict[UUID, list[UUID]] = {}
        for op in problem.operations:
            if op.predecessor_op_id is None:
                continue
            successors.setdefault(op.predecessor_op_id, []).append(op.id)
            indegree[op.id] += 1

        queue: deque[UUID] = deque()
        for op in problem.operations:
            if indegree[op.id] != 0:
                continue
            release_offset = order_release_offsets.get(op.order_id, 0.0)
            result[op.id] = max(result.get(op.id, 0.0), release_offset)
            queue.append(op.id)

        while queue:
            current_id = queue.popleft()
            current_op = ops_by_id[current_id]
            current_duration = max(op_duration_by_id.get(current_id, 0.0), 1e-6)
            current_end = result.get(current_id, 0.0) + current_duration
            for succ_id in successors.get(current_id, []):
                successor = ops_by_id.get(succ_id)
                release_offset = (
                    order_release_offsets.get(successor.order_id, 0.0)
                    if successor is not None
                    else 0.0
                )
                required_start = max(current_end, release_offset)
                if required_start > result.get(succ_id, 0.0):
                    result[succ_id] = required_start
                indegree[succ_id] -= 1
                if indegree[succ_id] == 0:
                    queue.append(succ_id)

    @staticmethod
    def _extract_order_release_offset_minutes(
        order: Any,
        *,
        horizon_start: datetime,
        horizon_minutes: float,
    ) -> float:
        """Parse optional order release metadata into horizon-relative minutes."""

        domain_attributes = getattr(order, "domain_attributes", None) or {}
        direct_keys = (
            "release_offset_min",
            "release_offset_minutes",
            "release_offset",
        )
        for key in direct_keys:
            value = domain_attributes.get(key)
            if isinstance(value, (int, float)):
                return max(0.0, min(float(value), horizon_minutes))

        absolute_keys = ("release_at", "release_datetime", "release_date")
        for key in absolute_keys:
            value = domain_attributes.get(key)
            if isinstance(value, datetime):
                offset = (value - horizon_start).total_seconds() / 60.0
                return max(0.0, min(offset, horizon_minutes))
            if isinstance(value, str) and value:
                try:
                    parsed = datetime.fromisoformat(value)
                except ValueError:
                    continue
                offset = (parsed - horizon_start).total_seconds() / 60.0
                return max(0.0, min(offset, horizon_minutes))

        return 0.0

    @staticmethod
    def _expand_predecessor_closure(
        seed_op_ids: set[UUID],
        ops_by_id: dict[UUID, Operation],
        committed_op_ids: set[UUID],
    ) -> set[UUID]:
        """Return the transitive unresolved predecessor closure for a window seed set."""

        expanded = set(seed_op_ids)
        stack = list(seed_op_ids)
        while stack:
            current_id = stack.pop()
            current_op = ops_by_id.get(current_id)
            if current_op is None or current_op.predecessor_op_id is None:
                continue
            predecessor_id = current_op.predecessor_op_id
            if predecessor_id in committed_op_ids or predecessor_id in expanded:
                continue
            expanded.add(predecessor_id)
            stack.append(predecessor_id)
        return expanded

    @staticmethod
    def _estimate_window_operation_cap(
        problem: ScheduleProblem,
        *,
        window_span_minutes: int,
        window_load_factor: float,
    ) -> int:
        """Estimate a throughput-aware operation budget for one RHC window."""

        if not problem.operations or not problem.work_centers:
            return 1

        total_duration = sum(op.base_duration_min for op in problem.operations)
        average_duration = total_duration / max(len(problem.operations), 1)
        if average_duration <= 0:
            return 1

        machine_capacity_minutes = window_span_minutes * len(problem.work_centers)
        estimated_cap = int((machine_capacity_minutes / average_duration) * window_load_factor)
        return max(1, estimated_cap)

    @staticmethod
    def _evaluate_final(
        problem: ScheduleProblem,
        assignments: list[Assignment],
        sdst: SdstMatrix,
    ) -> ObjectiveValues:
        """Compute final objective values."""
        if not assignments:
            return ObjectiveValues()

        horizon_start = problem.planning_horizon_start
        ops_by_id = {op.id: op for op in problem.operations}

        makespan = max(
            (a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments
        )

        total_setup = 0.0
        total_material_loss = 0.0
        by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            by_machine.setdefault(a.work_center_id, []).append(a)
        for wc_id, ma in by_machine.items():
            ma.sort(key=lambda a: a.start_time)
            for i in range(1, len(ma)):
                prev_state = ops_by_id[ma[i - 1].operation_id].state_id
                curr_state = ops_by_id[ma[i].operation_id].state_id
                total_setup += sdst.get_setup(wc_id, prev_state, curr_state)
                total_material_loss += sdst.get_material_loss(wc_id, prev_state, curr_state)

        order_completion: dict[Any, float] = {}
        for a in assignments:
            op = ops_by_id[a.operation_id]
            end = (a.end_time - horizon_start).total_seconds() / 60.0
            if op.order_id not in order_completion or end > order_completion[op.order_id]:
                order_completion[op.order_id] = end
        total_tardiness = 0.0
        for o in problem.orders:
            comp = order_completion.get(o.id, 0.0)
            due = (o.due_date - horizon_start).total_seconds() / 60.0
            total_tardiness += max(comp - due, 0.0)

        return ObjectiveValues(
            makespan_minutes=makespan,
            total_setup_minutes=total_setup,
            total_material_loss=total_material_loss,
            total_tardiness_minutes=total_tardiness,
        )
