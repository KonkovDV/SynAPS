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

from collections import deque
from heapq import heappop, heappush
import logging
import math
import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

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

        # Parameters
        window_minutes: int = int(kwargs.get("window_minutes", 480))
        overlap_minutes: int = int(kwargs.get("overlap_minutes", 120))
        inner_solver_name: str = str(kwargs.get("inner_solver", "alns"))
        inner_kwargs: dict[str, Any] = dict(kwargs.get("inner_kwargs", {}))
        # Prevent double-passing time_limit_s to inner solver (RHC computes its own per-window budget).
        inner_kwargs.pop("time_limit_s", None)
        time_limit_s: float = float(kwargs.get("time_limit_s", 600))
        inner_solver_min_budget_s: float = float(kwargs.get("inner_solver_min_budget_s", 0.0))
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
        max_candidate_pool_raw = kwargs.get("max_candidate_pool")

        ops_by_id = {op.id: op for op in problem.operations}
        orders_by_id = {o.id: o for o in problem.orders}
        sdst = SdstMatrix.from_problem(problem)
        dispatch_context = build_dispatch_context(problem)

        horizon_start = problem.planning_horizon_start
        horizon_end = problem.planning_horizon_end
        horizon_minutes = (horizon_end - horizon_start).total_seconds() / 60.0

        # Build inner solver
        inner_solver = self._make_inner_solver(inner_solver_name)

        preprocess_t0 = time.monotonic()

        # Compute "earliest possible start" for each operation based on precedence depth
        op_earliest: dict[UUID, float] = {}
        self._compute_earliest_starts(problem, op_earliest)

        # Build due-date offsets for order prioritization
        order_due_offsets: dict[UUID, float] = {}
        for order in problem.orders:
            order_due_offsets[order.id] = (order.due_date - horizon_start).total_seconds() / 60.0

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

        order_ops_sorted: dict[UUID, list[Operation]] = {}
        for order in problem.orders:
            order_ops_sorted[order.id] = sorted(
                [op for op in problem.operations if op.order_id == order.id],
                key=lambda op: op.seq_in_order,
            )

        op_tail_rpt_by_id: dict[UUID, float] = {}
        for order_id, order_ops in order_ops_sorted.items():
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
        preprocessing_ms = int((time.monotonic() - preprocess_t0) * 1000)
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
        due_pressure_selected_ids: set[UUID] = set()
        admission_frontier_advances = 0
        due_frontier_advances = 0
        candidate_pressure_values: list[float] = []
        due_pressure_values: list[float] = []
        due_drift_minutes_values: list[float] = []
        spillover_count = 0
        time_limit_reached = False
        fallback_repair_attempted = False
        fallback_repair_skipped = False
        fallback_repair_time_limited = False
        inner_window_summaries: list[dict[str, Any]] = []

        inner_summary_metadata_keys = (
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
        )

        def append_inner_window_summary(
            *,
            window: int,
            ops_in_window: int,
            ops_committed: int,
            resolution_mode: str,
            inner_result: ScheduleResult | None,
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
            if fallback_iterations is not None:
                summary["fallback_iterations"] = fallback_iterations
            if exception_message is not None:
                summary["inner_exception_message"] = exception_message

            if inner_result is None:
                summary["inner_status"] = "not_run"
                summary["inner_duration_ms"] = 0
            else:
                summary["inner_status"] = (
                    inner_result.status.value
                    if hasattr(inner_result.status, "value")
                    else str(inner_result.status)
                )
                summary["inner_duration_ms"] = inner_result.duration_ms
                for key in inner_summary_metadata_keys:
                    if key in (inner_result.metadata or {}):
                        summary[key] = inner_result.metadata[key]

            inner_window_summaries.append(summary)

        def global_time_exceeded() -> bool:
            return (time.monotonic() - t0) > time_limit_s

        while window_start_offset < horizon_minutes:
            if max_windows is not None and window_count >= max_windows:
                logger.info("RHC max_windows reached (%d)", max_windows)
                break
            if global_time_exceeded():
                time_limit_reached = True
                logger.warning("RHC time limit reached at window %d", window_count)
                break

            window_end_offset = window_start_offset + window_minutes + overlap_minutes
            window_end_offset = min(window_end_offset, horizon_minutes)
            window_count += 1

            while admission_cursor < len(ops_sorted_by_admission):
                op = ops_sorted_by_admission[admission_cursor]
                if (
                    op_admission_offset_by_id.get(op.id, op_earliest.get(op.id, 0.0))
                    >= window_end_offset
                ):
                    break
                admission_candidate_ids.add(op.id)
                admission_cursor += 1
                admission_frontier_advances += 1

            while due_cursor < len(ops_sorted_by_due):
                op = ops_sorted_by_due[due_cursor]
                if order_due_offsets.get(op.order_id, horizon_minutes) >= window_end_offset:
                    break
                due_candidate_ids.add(op.id)
                due_cursor += 1
                due_frontier_advances += 1

            admission_candidate_ids.difference_update(committed_op_ids)
            due_candidate_ids.difference_update(committed_op_ids)

            raw_window_candidate_ids = {
                op_id
                for op_id in (admission_candidate_ids | due_candidate_ids)
                if op_id not in committed_op_ids
            }
            peak_raw_window_candidate_count = max(
                peak_raw_window_candidate_count,
                len(raw_window_candidate_ids),
            )

            if not raw_window_candidate_ids:
                window_start_offset += window_minutes
                continue

            window_candidate_ids = raw_window_candidate_ids
            if candidate_admission_active:
                admitted_window_candidate_ids = {
                    op_id
                    for op_id in raw_window_candidate_ids
                    if (
                        op_admission_offset_by_id.get(op_id, op_earliest.get(op_id, 0.0))
                        < window_end_offset
                    )
                }
                if admitted_window_candidate_ids:
                    candidate_pool_filtered_ops += max(
                        0,
                        len(raw_window_candidate_ids) - len(admitted_window_candidate_ids),
                    )
                    window_candidate_ids = admitted_window_candidate_ids

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

            candidate_slack_by_id: dict[UUID, float] = {}
            candidate_pressure_by_id: dict[UUID, float] = {}
            for op in ordered_window_candidate_ops:
                eligible_wc_ids = op_eligible_wc_ids[op.id]
                if eligible_wc_ids:
                    earliest_machine_ready = min(
                        machine_available_offsets.get(wc_id, 0.0)
                        for wc_id in eligible_wc_ids
                    )
                else:
                    earliest_machine_ready = 0.0

                predecessor_end = 0.0
                if op.predecessor_op_id is not None:
                    predecessor_assignment = committed_assignment_by_op.get(op.predecessor_op_id)
                    if predecessor_assignment is not None:
                        predecessor_end = (
                            predecessor_assignment.end_time - horizon_start
                        ).total_seconds() / 60.0
                    else:
                        predecessor_end = op_earliest.get(op.id, 0.0)
                est_offset = max(predecessor_end, earliest_machine_ready)

                due_offset = order_due_offsets.get(op.order_id, horizon_minutes)
                rpt_tail = op_tail_rpt_by_id.get(op.id, op_mean_duration_by_id.get(op.id, 1.0))
                slack = due_offset - (est_offset + rpt_tail)
                candidate_slack_by_id[op.id] = slack

                order_weight = max(
                    1.0,
                    float(orders_by_id[op.order_id].priority)
                    if op.order_id in orders_by_id
                    else 1.0,
                )
                p_tilde = op_mean_duration_by_id.get(op.id, max(op.base_duration_min, 1.0))
                pressure = (order_weight / max(p_tilde, 1e-6)) * math.exp(
                    -max(0.0, slack) / max(due_pressure_k1 * avg_total_p, 1e-6)
                )
                if slack <= 0.0:
                    pressure *= due_pressure_overdue_boost
                candidate_pressure_by_id[op.id] = pressure

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

            window_op_ids = self._expand_predecessor_closure(
                {op.id for op in window_ops},
                ops_by_id,
                committed_op_ids,
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

            if inner_solver_name != "greedy":
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

                    # Compute remaining time budget for this window
                    remaining_time = max(10.0, time_limit_s - (time.monotonic() - t0))
                    per_window_limit = min(remaining_time * 0.8, 60.0)

                    if (
                        inner_solver_name == "alns"
                        and per_window_limit < inner_solver_min_budget_s
                    ):
                        inner_rejection_reason = "inner_skipped_low_budget"
                    else:
                        effective_inner_kwargs = dict(inner_kwargs)
                        if inner_solver_name == "alns":
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

                        inner_result = inner_solver.solve(
                            sub_problem,
                            time_limit_s=per_window_limit,
                            **effective_inner_kwargs,
                        )
                        assert inner_result is not None

                    if inner_result is not None and (
                        inner_result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
                        and inner_result.assignments
                    ):
                        # Map inner solver assignments into committed set
                        committed_now = 0
                        for a in inner_result.assignments:
                            if a.operation_id not in committed_op_ids:
                                start_offset = (
                                    (a.start_time - horizon_start).total_seconds() / 60.0
                                )
                                if (
                                    start_offset < commit_boundary
                                    or window_end_offset >= horizon_minutes
                                ):
                                    committed_assignments.append(a)
                                    committed_assignment_by_op[a.operation_id] = a
                                    committed_op_ids.add(a.operation_id)
                                    committed_now += 1
                        window_start_offset += window_minutes
                        window_solved_via_inner = True
                        append_inner_window_summary(
                            window=window_count,
                            ops_in_window=len(clean_window_ops),
                            ops_committed=committed_now,
                            resolution_mode="inner",
                            inner_result=inner_result,
                            candidate_pressure=window_candidate_pressure,
                            due_pressure=window_due_pressure,
                            due_drift_minutes=window_due_drift_minutes,
                            spillover_ops=window_spillover,
                        )
                        logger.info(
                            "RHC window %d solved by %s inner solver "
                            "(%d ops committed)",
                            window_count,
                            inner_solver_name,
                            committed_now,
                        )
                    else:
                        if inner_result is None:
                            inner_rejection_reason = inner_rejection_reason or "inner_not_run"
                        elif inner_result.status not in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL):
                            inner_rejection_reason = (
                                f"inner_status_{inner_result.status.value}"
                                if hasattr(inner_result.status, "value")
                                else f"inner_status_{inner_result.status}"
                            )
                        else:
                            inner_rejection_reason = "inner_empty_assignments"
                except Exception:
                    inner_rejection_reason = "inner_exception"
                    inner_exception_message = "inner solver raised exception"
                    logger.warning(
                        "RHC window %d: inner solver '%s' failed, falling back to greedy",
                        window_count, inner_solver_name,
                        exc_info=True,
                    )

            # ------ Fallback: greedy dispatch (original behavior) ------
            if not window_solved_via_inner:
                # Solve the window by greedy dispatch on its operations, building
                # on top of already-committed assignments.
                scheduled_so_far = list(committed_assignments)
                scheduled_by_op = dict(committed_assignment_by_op)
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
                for a in scheduled_so_far:
                    if a.operation_id in committed_op_ids:
                        continue
                    if a.operation_id not in window_scheduled_ids:
                        continue
                    start_offset = (a.start_time - horizon_start).total_seconds() / 60.0
                    # Commit if starts before the overlap boundary, or if it's the last window
                    if start_offset < commit_boundary or window_end_offset >= horizon_minutes:
                        committed_assignments.append(a)
                        committed_assignment_by_op[a.operation_id] = a
                        committed_op_ids.add(a.operation_id)

                if inner_solver_name != "greedy":
                    append_inner_window_summary(
                        window=window_count,
                        ops_in_window=len(clean_window_ops),
                        ops_committed=len(committed_op_ids) - committed_before_window,
                        resolution_mode="fallback_greedy",
                        inner_result=inner_result,
                        candidate_pressure=window_candidate_pressure,
                        due_pressure=window_due_pressure,
                        due_drift_minutes=window_due_drift_minutes,
                        spillover_ops=window_spillover,
                        fallback_reason=inner_rejection_reason or "inner_not_accepted",
                        fallback_iterations=fallback_iterations,
                        exception_message=inner_exception_message,
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
                            "RHC fallback greedy repair stopped because the global time limit is exhausted"
                        )
                        break
                    fi += 1
                    placed = False
                    for op in list(remaining_ops):
                        if global_time_exceeded():
                            time_limit_reached = True
                            fallback_repair_time_limited = True
                            logger.warning(
                                "RHC fallback greedy repair stopped because the global time limit is exhausted"
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
        recompute_assignment_setups(committed_assignments, dispatch_context)

        if not committed_assignments:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return ScheduleResult(
                solver_name=self.name,
                status=SolverStatus.ERROR,
                duration_ms=elapsed_ms,
                metadata={
                    "error": "no assignments produced",
                    "windows": window_count,
                    "time_limit_reached": time_limit_reached,
                    "fallback_repair_attempted": fallback_repair_attempted,
                    "fallback_repair_skipped": fallback_repair_skipped,
                    "fallback_repair_time_limited": fallback_repair_time_limited,
                    "ops_unscheduled": len(problem.operations),
                },
            )

        # Evaluate
        final_obj = self._evaluate_final(problem, committed_assignments, sdst)
        scheduled_count = len(committed_op_ids)
        total_ops = len(problem.operations)
        status = SolverStatus.FEASIBLE if scheduled_count == total_ops else SolverStatus.ERROR

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            "RHC finished: %d windows, %d/%d ops scheduled, makespan=%.1f min, %d ms",
            window_count, scheduled_count, total_ops,
            final_obj.makespan_minutes, elapsed_ms,
        )

        return ScheduleResult(
            solver_name=self.name,
            status=status,
            assignments=committed_assignments,
            objective=final_obj,
            duration_ms=elapsed_ms,
            metadata={
                "windows_solved": window_count,
                "ops_scheduled": scheduled_count,
                "ops_total": total_ops,
                "inner_solver": inner_solver_name,
                "preprocessing_ms": preprocessing_ms,
                "peak_window_candidate_count": peak_window_candidate_count,
                "peak_raw_window_candidate_count": peak_raw_window_candidate_count,
                "due_pressure_selected_ops": len(due_pressure_selected_ids),
                "candidate_pool_limit": candidate_pool_limit,
                "candidate_pool_factor": candidate_pool_factor,
                "candidate_pool_clamped_windows": candidate_pool_clamped_windows,
                "candidate_pool_filtered_ops": candidate_pool_filtered_ops,
                "candidate_admission_enabled": candidate_admission_active,
                "candidate_admission_configured": candidate_admission_enabled,
                "due_admission_horizon_factor": due_admission_horizon_factor,
                "admission_tail_weight": admission_tail_weight,
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
                "random_seed_base": random_seed_base,
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
        {o.id: o for o in problem.orders}

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
