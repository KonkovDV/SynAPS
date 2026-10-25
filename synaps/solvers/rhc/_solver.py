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

Architecture (2026-10 god-function decomposition)
-------------------------------------------------
``RhcSolver.solve`` resolves the keyword mapping (preset -> overrides ->
legacy kwargs) and hands it to :class:`_RhcRun`, a single-use run object:

* :class:`~synaps.solvers.rhc._config.RhcRunConfig` — immutable typed config;
* :class:`_RhcState` — the rolling commitment (what is frozen so far);
* :class:`_RhcTelemetry` — monotone counters published in metadata;
* :class:`_WindowCtx` — everything local to ONE window iteration.

The run is a pipeline ``preprocess -> [global cover] -> window loop ->
residual fill -> finalize``; each window is ``gather candidates -> admit ->
rank/cap -> build sub-problem -> inner solve | greedy fallback -> commit``.
The engine deliberately lives in this module: tests patch module globals
(``find_earliest_feasible_slot``, ``compute_rhc_candidate_metrics_batch_np``,
``time.monotonic``) and the order of wall-clock reads is part of the
replay contract, so the decomposition preserves both exactly.
"""

from __future__ import annotations

import logging
import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from heapq import heappop, heappush
from typing import TYPE_CHECKING, Any

from synaps.accelerators import (
    compute_rhc_candidate_metrics_batch_np,
    get_acceleration_status,
)
from synaps.calendar import work_centers_have_calendar
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
    operations_have_hard_windows,
    recompute_assignment_setups,
)
from synaps.solvers.coverage_outcome import stamp_honest_coverage
from synaps.solvers.lower_bounds import compute_relaxed_makespan_lower_bound
from synaps.solvers.rhc._admission import (
    advance_admission_frontier,
    advance_due_frontier,
    compute_precedence_closed_set,
    count_admitted_candidates,
)
from synaps.solvers.rhc._budget import (
    AlnsBudgetPolicy,
    CoveragePaceController,
    EmpiricalRepairCostEstimator,
    InnerWindowTimeCapPolicy,
    resolve_inner_window_time_cap as _resolve_inner_window_time_cap,
    scale_alns_inner_budget as _scale_alns_inner_budget,
)
from synaps.solvers.rhc._config import RhcRunConfig
from synaps.solvers.rhc._cover import (
    place_operations_greedy,
    place_operations_list_schedule,
    should_use_global_greedy_cover,
)
from synaps.solvers.rhc._cross_window import (
    QUALITY_BUFFER_MAXLEN,
    WindowQualitySummary,
    compute_window_quality_summary,
)
from synaps.solvers.rhc._metadata import build_inner_window_summary
from synaps.solvers.rhc._policy import RhcPolicy, resolve_policy
from synaps.solvers.rhc._warm_start import filter_warm_start_assignments
from synaps.solvers.rhc._window import (
    collect_commit_candidates as _collect_commit_candidates,
    detect_cross_window_stable_ops as _detect_cross_window_stable_ops,
    filter_commit_candidates_by_precedence as _filter_commit_candidates_by_precedence,
    finalize_rhc_claim_status as _finalize_rhc_claim_status,
    reanchor_inner_assignments as _reanchor_inner_assignments,
    select_backtracking_assignments as _select_backtracking_assignments,
    stabilization_pass_budget as _stabilization_pass_budget,
    stabilize_temporal_consistency as _stabilize_temporal_consistency,
)
from synaps.solvers.sdst_matrix import SdstMatrix
from synaps.timegrain import physical_processing_minutes_for

if TYPE_CHECKING:
    from uuid import UUID

    from synaps.solvers._dispatch_support import DispatchContext

logger = logging.getLogger(__name__)

_MAX_INNER_EXCEPTION_LOGS = 3
_MAX_INNER_EXCEPTION_MESSAGE_SAMPLES = 5
_SUCCESS_STATUSES = (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)


class RhcSolver(BaseSolver):
    """Receding Horizon Control wrapper over any inner solver.

    Decomposes the planning horizon into overlapping windows.
    Each window is solved independently (via ALNS, CP-SAT, or any BaseSolver),
    with frozen commitments from prior windows providing boundary conditions.

    Parameters (legacy kwargs still accepted with DeprecationWarning):
        window_minutes: Width of the active scheduling window (default 480 = 8h)
        overlap_minutes: Look-ahead overlap between windows (default 120 = 2h)
        inner_solver: Which solver to use per window ("alns" or "cpsat", default "alns")
        inner_kwargs: Dict of kwargs to pass to the inner solver per window
        max_ops_per_window: Hard cap on operations per window (default 5000)

    The full typed parameter surface is :class:`~synaps.solvers.rhc._config.RhcRunConfig`.
    """

    def __init__(
        self,
        *,
        policy: RhcPolicy | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> None:
        self._policy = policy
        self._overrides = overrides

    @property
    def name(self) -> str:
        return "rhc"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        result = _RhcRun(self, problem, self._resolve_kwargs(kwargs)).execute()
        return stamp_honest_coverage(problem, result)

    def _resolve_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Policy-first resolution: preset -> overrides -> legacy kwargs."""
        if self._policy is not None:
            _, policy_kwargs = resolve_policy(policy=self._policy, overrides=self._overrides)
            # Legacy kwargs still win as final override for backward compat.
            return {**policy_kwargs, **kwargs}
        if kwargs:
            # Pure legacy path — emit deprecation warning once.
            _, legacy_kwargs = resolve_policy(**kwargs)
            return legacy_kwargs
        return kwargs

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
            op_earliest = 0.0
            if op.earliest_start is not None:
                op_earliest = (
                    op.earliest_start - problem.planning_horizon_start
                ).total_seconds() / 60.0
            result[op.id] = max(result.get(op.id, 0.0), release_offset, op_earliest)
            queue.append(op.id)

        while queue:
            current_id = queue.popleft()
            current_duration = max(op_duration_by_id.get(current_id, 0.0), 1e-6)
            current_end = result.get(current_id, 0.0) + current_duration
            for succ_id in successors.get(current_id, []):
                successor = ops_by_id.get(succ_id)
                release_offset = (
                    order_release_offsets.get(successor.order_id, 0.0)
                    if successor is not None
                    else 0.0
                )
                op_earliest = 0.0
                if successor is not None and successor.earliest_start is not None:
                    op_earliest = (
                        successor.earliest_start - problem.planning_horizon_start
                    ).total_seconds() / 60.0
                required_start = max(current_end, release_offset, op_earliest)
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

        release_date = getattr(order, "release_date", None)
        if isinstance(release_date, datetime):
            offset = (release_date - horizon_start).total_seconds() / 60.0
            return max(0.0, min(offset, horizon_minutes))

        domain_attributes = getattr(order, "domain_attributes", None) or {}
        direct_keys = (
            "release_offset_min",
            "release_offset_minutes",
            "release_offset",
        )
        for key in direct_keys:
            value = domain_attributes.get(key)
            if isinstance(value, int | float):
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
        """Compute final objective values.

        W16b-3: delegate to the canonical evaluator so setup is lane-aware
        and unscheduled orders are anchored at the horizon end (F10).
        """
        from synaps.objective import evaluate

        return evaluate(problem, assignments)


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------


@dataclass
class _RhcState:
    """The rolling commitment and cross-window carry-over of one run."""

    committed_assignments: list[Assignment] = field(default_factory=list)
    committed_assignment_by_op: dict[UUID, Assignment] = field(default_factory=dict)
    committed_op_ids: set[UUID] = field(default_factory=set)
    sealed_window_op_ids: set[UUID] = field(default_factory=set)
    prev_committed_by_op: dict[UUID, Assignment] = field(default_factory=dict)
    cross_window_stable_ops: set[UUID] = field(default_factory=set)
    cross_window_variable_fixing_enabled: bool = True
    window_start_offset: float = 0.0
    window_count: int = 0
    admission_cursor: int = 0
    due_cursor: int = 0
    admission_candidate_ids: set[UUID] = field(default_factory=set)
    due_candidate_ids: set[UUID] = field(default_factory=set)
    previous_window_tail_assignments: list[Assignment] = field(default_factory=list)
    # C2 (Task 12.4): Persist ALNS operator weights across RHC windows.
    previous_window_operator_weights: dict[str, float] | None = None
    # C3 (Task 3a): Cross-window quality telemetry buffer.
    quality_summary_buffer: deque[WindowQualitySummary] = field(
        default_factory=lambda: deque(maxlen=QUALITY_BUFFER_MAXLEN)
    )
    # P3.1: op_id -> (machine_id, consecutive_count) for variable fixing.
    op_machine_stability: dict[UUID, tuple[Any, int]] = field(default_factory=dict)
    inner_window_summaries: list[dict[str, Any]] = field(default_factory=list)
    # Unique ops ever deferred by the commit gate (M-1, Red Team iteration 3).
    commit_precedence_deferred_op_ids: set[UUID] = field(default_factory=set)
    window_commit_precedence_deferred_last: int = 0
    global_greedy_cover_used: bool = False
    time_limit_reached: bool = False
    fallback_repair_attempted: bool = False
    fallback_repair_skipped: bool = False
    fallback_repair_time_limited: bool = False


@dataclass
class _RhcTelemetry:
    """Monotone counters and samples published in the result metadata."""

    peak_window_candidate_count: int = 0
    peak_raw_window_candidate_count: int = 0
    candidate_pool_clamped_windows: int = 0
    candidate_pool_filtered_ops: int = 0
    precedence_ready_filtered_ops: int = 0
    precedence_ready_candidate_ops_total: int = 0
    precedence_ready_candidate_ready_total: int = 0
    precedence_blocked_by_precedence_count: int = 0
    due_pressure_selected_ids: set[UUID] = field(default_factory=set)
    admission_frontier_advances: int = 0
    admission_starvation_count: int = 0
    admission_relaxation_windows: int = 0
    admission_relaxation_recovered_ops: int = 0
    admission_full_scan_windows: int = 0
    admission_full_scan_triggered_windows: int = 0
    admission_full_scan_added_ops: int = 0
    admission_full_scan_final_pool_peak: int = 0
    admission_full_scan_recovered_ops: int = 0
    due_frontier_advances: int = 0
    candidate_pressure_values: list[float] = field(default_factory=list)
    due_pressure_values: list[float] = field(default_factory=list)
    due_drift_minutes_values: list[float] = field(default_factory=list)
    spillover_count: int = 0
    hybrid_route_attempts: int = 0
    hybrid_route_activations: int = 0
    inner_fallback_windows: int = 0
    inner_fallback_reason_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    inner_status_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    inner_exception_windows: int = 0
    inner_exception_messages_sample: list[str] = field(default_factory=list)
    inner_exception_logs_emitted: int = 0
    backtracking_windows: int = 0
    backtracking_ops_total: int = 0
    horizon_clipped_assignments: int = 0
    adaptive_window_expansions: int = 0
    adaptive_window_expansion_factors: list[float] = field(default_factory=list)
    alns_budget_scaled_windows: int = 0
    alns_presearch_budget_guard_skipped_windows: int = 0
    alns_effective_max_iterations_values: list[int] = field(default_factory=list)
    alns_effective_max_destroy_values: list[int] = field(default_factory=list)
    alns_effective_repair_time_limit_values: list[float] = field(default_factory=list)
    boundary_reanchor_windows: int = 0
    boundary_reanchor_ops_total: int = 0
    boundary_reanchor_changed_ops_total: int = 0
    external_warm_start_used_windows: int = 0
    coverage_pace_interventions: int = 0
    total_fixed_ops_across_windows: int = 0


@dataclass
class _WindowCtx:
    """Everything local to one window iteration (candidates -> commit)."""

    end_offset: float
    resolved_predecessor_ids: set[UUID]
    raw_candidate_ids: set[UUID] = field(default_factory=set)
    candidate_ids: set[UUID] = field(default_factory=set)
    admission_relaxed: bool = False
    admission_relaxation_recovered_ops: int = 0
    full_scan_triggered: bool = False
    full_scan_added_ops: int = 0
    full_scan_final_pool: int = 0
    window_ops: list[Operation] = field(default_factory=list)
    candidate_slack_by_id: dict[UUID, float] = field(default_factory=dict)
    candidate_pressure: float = 0.0
    due_pressure: float = 0.0
    due_drift_minutes: float = 0.0
    spillover: int = 0
    rewound_assignments: list[Assignment] = field(default_factory=list)
    frozen_assignments: list[Assignment] = field(default_factory=list)
    frozen_assignment_by_op: dict[UUID, Assignment] = field(default_factory=dict)
    frozen_op_ids: set[UUID] = field(default_factory=set)
    window_op_ids: set[UUID] = field(default_factory=set)
    clean_window_ops: list[Operation] = field(default_factory=list)
    frozen_predecessor_end_offsets: dict[Any, int] = field(default_factory=dict)
    missing_frozen_predecessor: bool = False
    solved_via_inner: bool = False
    warm_selection: Any = None
    commit_boundary: float = 0.0
    committed_before_window: int = 0
    inner_result: ScheduleResult | None = None
    inner_rejection_reason: str | None = None
    inner_exception_message: str | None = None
    fallback_iterations: int | None = None
    selected_inner_solver_name: str = ""
    selected_inner_solver: BaseSolver | None = None
    selected_inner_kwargs: dict[str, Any] = field(default_factory=dict)
    hybrid_routing_reason: str | None = None
    alns_budget_profile: dict[str, Any] | None = None
    boundary_reanchor_changed_ops: int = 0
    per_window_limit: float = 0.0
    window_lower_bound: Any = None


# ---------------------------------------------------------------------------
# The run engine
# ---------------------------------------------------------------------------


class _RhcRun:
    """One ``RhcSolver.solve`` invocation as an explicit, inspectable pipeline."""

    # --- immutable context filled by _init_context / _preprocess -----------
    ops_by_id: dict[UUID, Operation]
    orders_by_id: dict[UUID, Any]
    external_warm_start_by_op: dict[UUID, Assignment]
    sdst: SdstMatrix
    dispatch_context: DispatchContext
    default_wc_ids: list[UUID]
    horizon_start: datetime
    original_horizon_end: datetime
    original_horizon_minutes: float
    horizon_minutes: float
    horizon_end: datetime
    planning_horizon_extended: bool
    order_due_offsets: dict[UUID, float]
    order_release_offsets: dict[UUID, float]
    op_earliest: dict[UUID, float]
    op_positions: dict[UUID, int]
    op_eligible_wc_ids: dict[UUID, set[UUID]]
    op_mean_duration_by_id: dict[UUID, float]
    op_min_duration_by_id: dict[UUID, float]
    avg_total_p: float
    op_tail_rpt_by_id: dict[UUID, float]
    op_admission_offset_by_id: dict[UUID, float]
    ops_sorted_by_admission: list[Operation]
    ops_sorted_by_due: list[Operation]
    ops_sorted_by_earliest: list[Operation]
    preprocessing_ms: int
    effective_window_op_cap: int
    candidate_pool_limit: int
    candidate_admission_active: bool
    alns_budget_auto_scaling_enabled: bool
    base_window_span_minutes: float
    preprocess_phase_ms: dict[str, int]
    _phase_t0: float

    def __init__(self, solver: RhcSolver, problem: ScheduleProblem, kwargs: dict[str, Any]):
        self.solver = solver
        self.problem = problem
        self.t0 = time.monotonic()
        self.acceleration_status = get_acceleration_status()
        self.global_lower_bound = compute_relaxed_makespan_lower_bound(problem)
        self.cfg = cfg = RhcRunConfig.from_kwargs(kwargs)
        ab = cfg.alns_budget
        # Materialize the budget-policy snapshots once; the pure kernels in
        # synaps.solvers.rhc._budget consume them.
        self.inner_window_cap_policy = InnerWindowTimeCapPolicy(
            inner_window_time_cap_s=ab.inner_window_time_cap_s,
            alns_inner_window_time_cap_s=ab.alns_inner_window_time_cap_s,
            alns_inner_window_time_cap_scaled_s=ab.alns_inner_window_time_cap_scaled_s,
            alns_inner_window_time_cap_scale_threshold_ops=(
                ab.alns_inner_window_time_cap_scale_threshold_ops
            ),
        )
        self.alns_budget_policy = AlnsBudgetPolicy(
            estimated_repair_s_per_destroyed_op_raw=(
                ab.alns_budget_estimated_repair_s_per_destroyed_op_raw
            ),
            dynamic_repair_time_limit_min_s=ab.alns_dynamic_repair_time_limit_min_s,
            dynamic_repair_time_limit_max_s=ab.alns_dynamic_repair_time_limit_max_s,
            dynamic_repair_s_per_destroyed_op=ab.alns_dynamic_repair_s_per_destroyed_op,
        )
        # R2 (EMA calibration): solver-scoped repair-cost estimator, updated
        # after every ALNS window from `observed_repair_s_per_destroyed_op`.
        self.repair_cost_estimator = EmpiricalRepairCostEstimator(
            alpha=max(0.0, min(1.0, ab.alns_repair_cost_alpha)),
        )
        # W1 (2026-07): coverage pace guard (opt-in).
        self.pace = CoveragePaceController(
            total_ops=len(problem.operations),
            time_limit_s=cfg.budget.window_time_limit_s,
            threshold=cfg.cover.coverage_pace_threshold,
            min_windows=cfg.cover.coverage_pace_min_windows,
        )
        self.st = _RhcState()
        self.tel = _RhcTelemetry()
        self._init_context()
        self.inner_solver = solver._make_inner_solver(cfg.inner.inner_solver_name)
        self.hybrid_inner_solver: BaseSolver | None = None
        if cfg.inner.hybrid_inner_routing_enabled and cfg.inner.inner_solver_name == "alns":
            self.hybrid_inner_solver = solver._make_inner_solver(cfg.inner.hybrid_inner_solver_name)

    # ------------------------------------------------------------------ setup

    def _init_context(self) -> None:
        problem = self.problem
        self.ops_by_id = {op.id: op for op in problem.operations}
        self.orders_by_id = {o.id: o for o in problem.orders}
        self.external_warm_start_by_op = {
            assignment.operation_id: assignment
            for assignment in self.cfg.external_warm_start_assignments
            if assignment.operation_id in self.ops_by_id
        }
        self.sdst = SdstMatrix.from_problem(problem)
        self.dispatch_context = build_dispatch_context(problem)
        self.default_wc_ids = [wc.id for wc in problem.work_centers]
        self.horizon_start = problem.planning_horizon_start
        self.original_horizon_end = problem.planning_horizon_end
        self.original_horizon_minutes = (
            self.original_horizon_end - self.horizon_start
        ).total_seconds() / 60.0
        factor = self.cfg.geometry.coverage_horizon_extension_factor
        self.horizon_minutes = self.original_horizon_minutes * factor
        self.horizon_end = self.horizon_start + timedelta(minutes=self.horizon_minutes)
        self.planning_horizon_extended = factor > 1.0 + 1e-12

    def _mark_phase(self, name: str) -> None:
        now = time.monotonic()
        self.preprocess_phase_ms[name] = int((now - self._phase_t0) * 1000)
        self._phase_t0 = now

    def _preprocess(self) -> None:
        """Offsets, earliest starts, operation statistics and candidate orderings."""
        problem = self.problem
        preprocess_t0 = time.monotonic()
        self.preprocess_phase_ms = {}
        self._phase_t0 = preprocess_t0
        self._compute_order_offsets()
        self._mark_phase("due_offsets")
        # Precedence-constrained earliest offsets, tightened below with
        # release-aware and machine-speed-aware lower bounds.
        self.op_earliest = {}
        self.solver._compute_earliest_starts(problem, self.op_earliest)
        self._mark_phase("earliest_starts")
        self._compute_operation_stats()
        self._mark_phase("operation_stats")
        self._compute_admission_offsets()
        self._mark_phase("admission_offsets")
        self._compute_candidate_orderings()
        self._mark_phase("candidate_orderings")
        self.preprocessing_ms = int((time.monotonic() - preprocess_t0) * 1000)
        self._derive_window_caps()

    def _compute_order_offsets(self) -> None:
        self.order_due_offsets = {}
        self.order_release_offsets = {}
        for order in self.problem.orders:
            self.order_due_offsets[order.id] = (
                order.due_date - self.horizon_start
            ).total_seconds() / 60.0
            self.order_release_offsets[order.id] = (
                self.solver._extract_order_release_offset_minutes(
                    order,
                    horizon_start=self.horizon_start,
                    horizon_minutes=self.horizon_minutes,
                )
            )

    def _compute_operation_stats(self) -> None:
        problem = self.problem
        self.op_positions = {op.id: index for index, op in enumerate(problem.operations)}
        all_work_center_ids = {work_center.id for work_center in problem.work_centers}
        wc_speed_by_id = {
            work_center.id: max(work_center.speed_factor, 1e-6)
            for work_center in problem.work_centers
        }
        self.op_eligible_wc_ids = {
            op.id: (set(op.eligible_wc_ids) if op.eligible_wc_ids else set(all_work_center_ids))
            for op in problem.operations
        }
        self.op_mean_duration_by_id = {}
        self.op_min_duration_by_id = {}
        wc_by_id = {work_center.id: work_center for work_center in problem.work_centers}
        for op in problem.operations:
            effective_durations = []
            for wc_id in self.op_eligible_wc_ids[op.id]:
                wc: Any = wc_by_id.get(wc_id)
                if wc is None:
                    from types import SimpleNamespace

                    wc = SimpleNamespace(id=wc_id, speed_factor=wc_speed_by_id.get(wc_id, 1.0))
                effective_durations.append(physical_processing_minutes_for(op, wc))
            if not effective_durations:
                effective_durations = [max(op.base_duration_min, 1.0)]
            self.op_mean_duration_by_id[op.id] = max(
                sum(effective_durations) / len(effective_durations),
                1e-6,
            )
            self.op_min_duration_by_id[op.id] = max(min(effective_durations), 1e-6)
        self.solver._propagate_earliest_starts_with_release_and_duration(
            problem,
            self.op_earliest,
            op_duration_by_id=self.op_min_duration_by_id,
            order_release_offsets=self.order_release_offsets,
        )

    def _compute_admission_offsets(self) -> None:
        """Due-release admission offsets: due - horizon + w * remaining-work tail."""
        problem = self.problem
        rms_processing = math.sqrt(
            sum(duration * duration for duration in self.op_mean_duration_by_id.values())
            / max(1, len(self.op_mean_duration_by_id))
        )
        self.avg_total_p = max(rms_processing, 1e-6)
        positive_setups = [
            entry.setup_minutes for entry in problem.setup_matrix if entry.setup_minutes > 0
        ]
        expected_setup = sum(positive_setups) / len(positive_setups) if positive_setups else 0.0
        ops_by_order: dict[UUID, list[Operation]] = {}
        for op in problem.operations:
            ops_by_order.setdefault(op.order_id, []).append(op)
        self.op_tail_rpt_by_id = {}
        for order_ops in ops_by_order.values():
            suffix_sum = 0.0
            ordered = sorted(order_ops, key=lambda op: op.seq_in_order)
            for remaining_edges, op in enumerate(reversed(ordered)):
                suffix_sum += self.op_min_duration_by_id.get(op.id, max(op.base_duration_min, 1.0))
                self.op_tail_rpt_by_id[op.id] = suffix_sum + remaining_edges * expected_setup
        geometry = self.cfg.geometry
        admission_horizon_minutes = (
            geometry.window_minutes + geometry.overlap_minutes
        ) * self.cfg.admission.due_admission_horizon_factor
        self.op_admission_offset_by_id = {}
        for op in problem.operations:
            due_offset = self.order_due_offsets.get(op.order_id, self.horizon_minutes)
            rpt_tail = self.op_tail_rpt_by_id.get(
                op.id, self.op_mean_duration_by_id.get(op.id, 1.0)
            )
            due_release_offset = (
                due_offset
                - admission_horizon_minutes
                + self.cfg.admission.admission_tail_weight * rpt_tail
            )
            self.op_admission_offset_by_id[op.id] = max(
                self.op_earliest.get(op.id, 0.0), due_release_offset
            )

    def _admission_sort_key(self, op: Operation) -> tuple[float, float, int]:
        return (
            self.op_admission_offset_by_id.get(op.id, self.op_earliest.get(op.id, 0.0)),
            self.order_due_offsets.get(op.order_id, self.horizon_minutes),
            op.seq_in_order,
        )

    def _compute_candidate_orderings(self) -> None:
        operations = self.problem.operations
        due = self.order_due_offsets
        self.ops_sorted_by_admission = sorted(operations, key=self._admission_sort_key)
        self.ops_sorted_by_due = sorted(
            operations,
            key=lambda op: (
                due.get(op.order_id, self.horizon_minutes),
                op.seq_in_order,
                self.op_earliest.get(op.id, 0.0),
            ),
        )
        self.ops_sorted_by_earliest = sorted(
            operations,
            key=lambda op: (
                self.op_earliest.get(op.id, 0.0),
                due.get(op.order_id, self.horizon_minutes),
                op.seq_in_order,
                self.op_positions[op.id],
            ),
        )

    def _derive_window_caps(self) -> None:
        """Throughput-aware window cap, candidate pool limit and admission gate."""
        problem, geometry = self.problem, self.cfg.geometry
        n_ops = len(problem.operations)
        self.effective_window_op_cap = geometry.max_ops_per_window
        if n_ops > geometry.max_ops_per_window:
            self.effective_window_op_cap = min(
                geometry.max_ops_per_window,
                self.solver._estimate_window_operation_cap(
                    problem,
                    window_span_minutes=geometry.window_minutes + geometry.overlap_minutes,
                    window_load_factor=geometry.window_load_factor,
                ),
            )
        max_pool = self.cfg.admission.max_candidate_pool
        self.candidate_pool_limit = max(
            self.effective_window_op_cap,
            (
                max_pool
                if max_pool is not None
                else math.ceil(
                    self.effective_window_op_cap * self.cfg.admission.candidate_pool_factor
                )
            ),
        )
        self.candidate_admission_active = (
            self.cfg.admission.candidate_admission_enabled and n_ops > self.effective_window_op_cap
        )
        if not self.candidate_admission_active:
            self.op_admission_offset_by_id = {
                op.id: self.op_earliest.get(op.id, 0.0) for op in problem.operations
            }
            self.ops_sorted_by_admission = sorted(problem.operations, key=self._admission_sort_key)
        auto_raw = self.cfg.alns_budget.alns_budget_auto_scaling_raw
        self.alns_budget_auto_scaling_enabled = (
            bool(auto_raw) if auto_raw is not None else n_ops > self.effective_window_op_cap
        )
        self.base_window_span_minutes = max(
            float(geometry.window_minutes + geometry.overlap_minutes), 1.0
        )

    # ---------------------------------------------------------- orchestration

    def execute(self) -> ScheduleResult:
        self._preprocess()
        if should_use_global_greedy_cover(
            inner_solver_name=self.cfg.inner.inner_solver_name,
            n_ops=len(self.problem.operations),
            min_ops=self.cfg.cover.global_greedy_cover_min_ops,
            has_hard_windows=operations_have_hard_windows(self.problem.operations),
            has_machine_calendar=work_centers_have_calendar(self.problem.work_centers),
        ):
            self._run_global_cover()
        self._run_window_loop()
        self._residual_fill()
        return self._finalize()

    # ------------------------------------------------------------ time budget

    def _elapsed(self) -> float:
        return time.monotonic() - self.t0

    def _global_time_exceeded(self) -> bool:
        return (time.monotonic() - self.t0) > self.cfg.budget.time_limit_s

    def _window_budget_exceeded(self) -> bool:
        """True when windows must stop to preserve coverage reserve."""
        return (time.monotonic() - self.t0) > self.cfg.budget.window_time_limit_s

    def _coverage_deadline_exceeded(self) -> bool:
        """True when residual coverage greedy must also stop."""
        return (time.monotonic() - self.t0) > self.cfg.budget.coverage_deadline_s

    # ------------------------------------------------------- global cover path

    def _run_global_cover(self) -> None:
        """Coverage-complete constructive path: one list-schedule for all ops."""
        st, cover = self.st, self.cfg.cover
        st.global_greedy_cover_used = True
        cover_stats = place_operations_list_schedule(
            operations=self.problem.operations,
            dispatch_context=self.dispatch_context,
            assignments=st.committed_assignments,
            assignment_by_op=st.committed_assignment_by_op,
            scheduled_ids=st.committed_op_ids,
            horizon_start=self.horizon_start,
            horizon_minutes=self.horizon_minutes,
            op_earliest=self.op_earliest,
            default_wc_ids=self.default_wc_ids,
            deadline_exceeded=self._coverage_deadline_exceeded,
            cover_ready_rule=cover.cover_ready_rule,
            order_priority_by_id={order.id: order.priority for order in self.problem.orders},
            cover_atcs_floor_window=cover.cover_atcs_floor_window,
            cover_atcs_exhaust_window=cover.cover_atcs_exhaust_window,
        )
        self.tel.horizon_clipped_assignments += cover_stats.clipped
        if cover_stats.time_limited:
            st.time_limit_reached = True
        logger.info(
            "RHC global greedy cover placed %d/%d ops in %d passes (clipped=%d gap_inserted=%d)",
            cover_stats.placed,
            len(self.problem.operations),
            cover_stats.passes,
            cover_stats.clipped,
            cover_stats.gap_inserted,
        )

    # -------------------------------------------------------------- window loop

    def _run_window_loop(self) -> None:
        st = self.st
        max_windows = self.cfg.geometry.max_windows
        while (not st.global_greedy_cover_used) and st.window_start_offset < self.horizon_minutes:
            if max_windows is not None and st.window_count >= max_windows:
                logger.info("RHC max_windows reached (%d)", max_windows)
                break
            if self._window_budget_exceeded():
                st.time_limit_reached = True
                logger.warning(
                    "RHC window budget reached at window %d (reserve=%.1fs for coverage fallback)",
                    st.window_count,
                    self.cfg.budget.coverage_reserve_s,
                )
                break
            if not self._run_one_window():
                break

    def _run_one_window(self) -> bool:
        """Solve one window. Returns False when the loop must stop."""
        st, geometry = self.st, self.cfg.geometry
        w = _WindowCtx(
            end_offset=min(
                st.window_start_offset + geometry.window_minutes + geometry.overlap_minutes,
                self.horizon_minutes,
            ),
            resolved_predecessor_ids=set(),
        )
        st.window_count += 1
        if st.window_count > 1:
            st.sealed_window_op_ids.update(st.committed_op_ids)
        w.resolved_predecessor_ids = st.committed_op_ids | {
            assignment.operation_id
            for assignment in st.previous_window_tail_assignments
            if assignment.operation_id in self.ops_by_id
        }
        self._gather_raw_candidates(w)
        if not w.raw_candidate_ids and not self._recover_empty_frontier(w):
            self._skip_empty_window(pressures=False)
            return True
        self._admit_candidates(w)
        if not w.candidate_ids:
            self._skip_empty_window(pressures=True)
            return True
        self._rank_and_cap_window(w)
        self._measure_window_pressure(w)
        self._build_window_operations(w)
        logger.info(
            "RHC window %d: offset=%.0f-%.0f min, %d ops",
            st.window_count,
            st.window_start_offset,
            w.end_offset,
            len(w.clean_window_ops),
        )
        self._attempt_inner_solve(w)
        if not w.solved_via_inner:
            return self._run_greedy_fallback(w)
        return True

    def _skip_empty_window(self, *, pressures: bool) -> None:
        if pressures:
            self._append_inner_window_summary(
                window=self.st.window_count,
                ops_in_window=0,
                ops_committed=0,
                resolution_mode="no_candidates",
                inner_result=None,
                candidate_pressure=0.0,
                due_pressure=0.0,
                due_drift_minutes=0.0,
                spillover_ops=0,
            )
        else:
            self._append_inner_window_summary(
                window=self.st.window_count,
                ops_in_window=0,
                ops_committed=0,
                resolution_mode="no_candidates",
                inner_result=None,
                spillover_ops=0,
            )
        self.st.window_start_offset += self.cfg.geometry.window_minutes

    def _append_inner_window_summary(self, **summary_kwargs: Any) -> None:
        """Append one per-window telemetry row (pure builder in ``_metadata``)."""
        st = self.st
        self.st.inner_window_summaries.append(
            build_inner_window_summary(
                **summary_kwargs,
                stable_ops_count=len(st.cross_window_stable_ops)
                if st.cross_window_variable_fixing_enabled
                else None,
            )
        )

    # ------------------------------------------------------ candidate frontier

    def _extend_candidate_frontiers(self, window_boundary: float) -> None:
        st = self.st
        new_admitted, st.admission_cursor = advance_admission_frontier(
            cursor=st.admission_cursor,
            ops_sorted_by_admission=self.ops_sorted_by_admission,
            op_admission_offset_by_id=self.op_admission_offset_by_id,
            op_earliest=self.op_earliest,
            window_boundary=window_boundary,
        )
        st.admission_candidate_ids.update(new_admitted)
        self.tel.admission_frontier_advances += len(new_admitted)
        new_due, st.due_cursor = advance_due_frontier(
            cursor=st.due_cursor,
            ops_sorted_by_due=self.ops_sorted_by_due,
            order_due_offsets=self.order_due_offsets,
            horizon_minutes=self.horizon_minutes,
            window_boundary=window_boundary,
        )
        st.due_candidate_ids.update(new_due)
        self.tel.due_frontier_advances += len(new_due)

    def _collect_raw_window_candidate_ids(self) -> set[UUID]:
        st = self.st
        st.admission_candidate_ids.difference_update(st.committed_op_ids)
        st.due_candidate_ids.difference_update(st.committed_op_ids)
        return {
            op_id
            for op_id in (st.admission_candidate_ids | st.due_candidate_ids)
            if op_id not in st.committed_op_ids
        }

    def _filter_precedence_ready_candidate_ids(
        self,
        candidate_ids: set[UUID],
        *,
        window_boundary: float,
        resolved_predecessor_ids: set[UUID],
    ) -> set[UUID]:
        tel = self.tel
        if not self.cfg.admission.precedence_ready_candidate_filter_enabled or not candidate_ids:
            return candidate_ids
        tel.precedence_ready_candidate_ops_total += len(candidate_ids)
        filtered_ids = {
            op_id for op_id in candidate_ids if self.op_earliest.get(op_id, 0.0) < window_boundary
        }
        if not filtered_ids:
            tel.precedence_ready_filtered_ops += len(candidate_ids)
            return filtered_ids
        # Keep only ops whose unresolved predecessors are reachable in the same
        # candidate set (or already resolved by commits / tail carry-over).
        predecessor_closed_ids = compute_precedence_closed_set(
            filtered_ids,
            ops_by_id=self.ops_by_id,
            resolved_predecessor_ids=resolved_predecessor_ids,
        )
        tel.precedence_blocked_by_precedence_count += max(
            0, len(filtered_ids) - len(predecessor_closed_ids)
        )
        tel.precedence_ready_candidate_ready_total += len(predecessor_closed_ids)
        tel.precedence_ready_filtered_ops += max(
            0, len(candidate_ids) - len(predecessor_closed_ids)
        )
        return predecessor_closed_ids

    def _refresh_raw_candidates(self, w: _WindowCtx) -> None:
        self._extend_candidate_frontiers(w.end_offset)
        w.raw_candidate_ids = self._filter_precedence_ready_candidate_ids(
            self._collect_raw_window_candidate_ids(),
            window_boundary=w.end_offset,
            resolved_predecessor_ids=w.resolved_predecessor_ids,
        )
        self.tel.peak_raw_window_candidate_count = max(
            self.tel.peak_raw_window_candidate_count, len(w.raw_candidate_ids)
        )

    def _gather_raw_candidates(self, w: _WindowCtx) -> None:
        """Advance the frontiers; expand an under-filled window adaptively."""
        geometry = self.cfg.geometry
        self._refresh_raw_candidates(w)
        if not (
            geometry.adaptive_window_enabled
            and self.candidate_admission_active
            and geometry.adaptive_window_min_fill_ratio > 0.0
            and w.end_offset < self.horizon_minutes
        ):
            return
        target_candidate_count = max(
            1, math.ceil(self.effective_window_op_cap * geometry.adaptive_window_min_fill_ratio)
        )
        current_effective_count = count_admitted_candidates(
            w.raw_candidate_ids,
            op_admission_offset_by_id=self.op_admission_offset_by_id,
            op_earliest=self.op_earliest,
            window_boundary=w.end_offset,
        )
        if current_effective_count >= target_candidate_count:
            return
        requested_multiplier = min(
            geometry.adaptive_window_max_multiplier,
            max(1.0, target_candidate_count / max(1, current_effective_count)),
        )
        window_start = self.st.window_start_offset
        expanded_end = min(
            self.horizon_minutes,
            window_start + (self.base_window_span_minutes * requested_multiplier),
        )
        if expanded_end > w.end_offset + 1e-9:
            w.end_offset = expanded_end
            self.tel.adaptive_window_expansions += 1
            self.tel.adaptive_window_expansion_factors.append(
                (w.end_offset - window_start) / self.base_window_span_minutes
            )
            self._refresh_raw_candidates(w)

    def _recover_empty_frontier(self, w: _WindowCtx) -> bool:
        """Carry-over tail or bootstrap the earliest-ready ops; False when none."""
        st = self.st
        carryover_ids = {
            assignment.operation_id
            for assignment in st.previous_window_tail_assignments
            if assignment.operation_id in self.ops_by_id
            and assignment.operation_id not in st.committed_op_ids
        }
        if carryover_ids:
            recovered, how = carryover_ids, "recovered %d carry-over tail ops into"
        else:
            bootstrap_ids: set[UUID] = set()
            for op in self.ops_sorted_by_earliest:
                if self.op_earliest.get(op.id, 0.0) >= w.end_offset:
                    break
                if op.id in st.committed_op_ids:
                    continue
                bootstrap_ids.add(op.id)
                if len(bootstrap_ids) >= self.candidate_pool_limit:
                    break
            if not bootstrap_ids:
                return False
            recovered, how = bootstrap_ids, "bootstrap-admitted %d earliest-ready ops into"
        w.raw_candidate_ids = recovered
        self.tel.peak_raw_window_candidate_count = max(
            self.tel.peak_raw_window_candidate_count, len(recovered)
        )
        logger.info("RHC window %d " + how + " an empty frontier", st.window_count, len(recovered))
        return True

    # --------------------------------------------------------------- admission

    def _admit_candidates(self, w: _WindowCtx) -> None:
        """Admission gate (+ progressive relaxation / full scan), pool clamp."""
        w.candidate_ids = w.raw_candidate_ids
        if self.candidate_admission_active:
            filtered_by_admission = self._apply_admission_gate(w)
            if self.cfg.admission.admission_full_scan_enabled and self._apply_full_scan(w):
                filtered_by_admission = 0
            self.tel.candidate_pool_filtered_ops += filtered_by_admission
        self._clamp_candidate_pool(w)
        st = self.st
        w.candidate_ids = {op_id for op_id in w.candidate_ids if op_id not in st.committed_op_ids}
        self.tel.peak_window_candidate_count = max(
            self.tel.peak_window_candidate_count, len(w.candidate_ids)
        )

    def _apply_admission_gate(self, w: _WindowCtx) -> int:
        """Return the number of raw candidates filtered by the due-release gate."""
        admission, tel = self.cfg.admission, self.tel
        raw = w.raw_candidate_ids
        admitted = {
            op_id
            for op_id in raw
            if self.op_admission_offset_by_id.get(op_id, self.op_earliest.get(op_id, 0.0))
            < w.end_offset
        }
        admitted_count = len(admitted)
        filtered_by_admission = 0
        if admitted:
            filtered_by_admission = max(0, len(raw) - admitted_count)
            w.candidate_ids = admitted
        else:
            tel.admission_starvation_count += 1
        if not admission.progressive_admission_relaxation_enabled:
            return filtered_by_admission
        relaxation_target = max(
            1,
            math.ceil(self.effective_window_op_cap * admission.admission_relaxation_min_fill_ratio),
        )
        if len(raw) > admitted_count and admitted_count < relaxation_target:
            w.candidate_ids = set(raw)
            w.admission_relaxed = True
            w.admission_relaxation_recovered_ops = max(0, len(w.candidate_ids) - admitted_count)
            tel.admission_relaxation_windows += 1
            tel.admission_relaxation_recovered_ops += w.admission_relaxation_recovered_ops
            filtered_by_admission = 0
            logger.info(
                "RHC window %d relaxed admission gate: admitted %d/%d raw candidates",
                self.st.window_count,
                admitted_count,
                len(raw),
            )
        return filtered_by_admission

    def _apply_full_scan(self, w: _WindowCtx) -> bool:
        """Escalate a starved pool to a capped earliest-first full scan."""
        tel, st = self.tel, self.st
        full_scan_target = max(
            1,
            math.ceil(
                self.effective_window_op_cap * self.cfg.admission.admission_full_scan_min_fill_ratio
            ),
        )
        if len(w.candidate_ids) > full_scan_target:
            return False
        w.full_scan_triggered = True
        tel.admission_full_scan_triggered_windows += 1
        seed_ids = set(w.candidate_ids)
        for op in self.ops_sorted_by_earliest:
            if op.id in st.committed_op_ids or op.id in seed_ids:
                continue
            seed_ids.add(op.id)
            if len(seed_ids) >= self.candidate_pool_limit:
                break
        w.full_scan_added_ops = max(0, len(seed_ids) - len(w.candidate_ids))
        tel.admission_full_scan_added_ops += w.full_scan_added_ops
        full_scan_ids = self._filter_precedence_ready_candidate_ids(
            seed_ids,
            window_boundary=w.end_offset,
            resolved_predecessor_ids=w.resolved_predecessor_ids,
        )
        w.full_scan_final_pool = len(full_scan_ids)
        tel.admission_full_scan_final_pool_peak = max(
            tel.admission_full_scan_final_pool_peak, w.full_scan_final_pool
        )
        recovered = max(0, len(full_scan_ids) - len(w.candidate_ids))
        if recovered <= 0:
            return False
        w.candidate_ids = full_scan_ids
        w.admission_relaxed = True
        w.admission_relaxation_recovered_ops += recovered
        tel.admission_full_scan_windows += 1
        tel.admission_full_scan_recovered_ops += recovered
        logger.info(
            "RHC window %d escalated to capped full-scan frontier: +%d candidates (final pool=%d)",
            st.window_count,
            recovered,
            w.full_scan_final_pool,
        )
        return True

    def _clamp_candidate_pool(self, w: _WindowCtx) -> None:
        limit = self.candidate_pool_limit
        if len(w.candidate_ids) <= limit:
            return
        st, ops_by_id = self.st, self.ops_by_id
        self.tel.candidate_pool_clamped_windows += 1
        self.tel.candidate_pool_filtered_ops += len(w.candidate_ids) - limit
        w.candidate_ids = set(
            sorted(
                w.candidate_ids,
                key=lambda op_id: (
                    1
                    if (
                        ops_by_id[op_id].predecessor_op_id is not None
                        and ops_by_id[op_id].predecessor_op_id not in st.committed_op_ids
                    )
                    else 0,
                    self.op_admission_offset_by_id.get(op_id, self.op_earliest.get(op_id, 0.0)),
                    self.order_due_offsets.get(ops_by_id[op_id].order_id, self.horizon_minutes),
                    ops_by_id[op_id].seq_in_order,
                    self.op_positions[op_id],
                ),
            )[:limit]
        )

    # ------------------------------------------------------------ rank and cap

    def _candidate_metrics(
        self, ordered_ops: list[Operation]
    ) -> tuple[dict[UUID, float], dict[UUID, float]]:
        """Due slack and pressure per candidate (native/NumPy batch kernel)."""
        st, problem = self.st, self.problem
        machine_available = {work_center.id: 0.0 for work_center in problem.work_centers}
        for assignment in st.committed_assignments:
            end_offset = (assignment.end_time - self.horizon_start).total_seconds() / 60.0
            machine_available[assignment.work_center_id] = max(
                machine_available.get(assignment.work_center_id, 0.0), end_offset
            )
        ordered_machine_ids = [work_center.id for work_center in problem.work_centers]
        machine_index_by_id = {machine_id: i for i, machine_id in enumerate(ordered_machine_ids)}
        predecessor_end_offsets: list[float] = []
        for op in ordered_ops:
            predecessor_end = 0.0
            if op.predecessor_op_id is not None:
                pred_assignment = st.committed_assignment_by_op.get(op.predecessor_op_id)
                if pred_assignment is not None:
                    predecessor_end = (
                        pred_assignment.end_time - self.horizon_start
                    ).total_seconds() / 60.0
                else:
                    predecessor_end = self.op_earliest.get(op.id, 0.0)
            predecessor_end_offsets.append(predecessor_end)
        slacks, pressures = compute_rhc_candidate_metrics_batch_np(
            machine_available_offsets=[machine_available[m] for m in ordered_machine_ids],
            eligible_machine_indices=[
                [
                    machine_index_by_id[wc]
                    for wc in self.op_eligible_wc_ids[op.id]
                    if wc in machine_index_by_id
                ]
                for op in ordered_ops
            ],
            predecessor_end_offsets=predecessor_end_offsets,
            due_offsets=[
                self.order_due_offsets.get(op.order_id, self.horizon_minutes) for op in ordered_ops
            ],
            rpt_tail_minutes=[
                self.op_tail_rpt_by_id.get(op.id, self.op_mean_duration_by_id.get(op.id, 1.0))
                for op in ordered_ops
            ],
            order_weights=[self._order_weight(op) for op in ordered_ops],
            p_tilde_minutes=[
                self.op_mean_duration_by_id.get(op.id, max(op.base_duration_min, 1.0))
                for op in ordered_ops
            ],
            avg_total_p=self.avg_total_p,
            due_pressure_k1=self.cfg.admission.due_pressure_k1,
            due_pressure_overdue_boost=self.cfg.admission.due_pressure_overdue_boost,
        )
        slack_by_id = dict(zip((op.id for op in ordered_ops), slacks, strict=True))
        pressure_by_id = dict(zip((op.id for op in ordered_ops), pressures, strict=True))
        return slack_by_id, pressure_by_id

    def _order_weight(self, op: Operation) -> float:
        return max(
            1.0,
            float(self.orders_by_id[op.order_id].priority)
            if op.order_id in self.orders_by_id
            else 1.0,
        )

    def _rank_and_cap_window(self, w: _WindowCtx) -> None:
        """Pressure-ranked, machine-coverage-boosted cap + carry-over + rewind."""
        st = self.st
        # Stabilize candidate ordering before ranking so tied keys behave
        # deterministically across process runs.
        ordered_ops = [
            self.ops_by_id[op_id]
            for op_id in sorted(w.candidate_ids, key=self.op_positions.__getitem__)
        ]
        w.candidate_slack_by_id, pressure_by_id = self._candidate_metrics(ordered_ops)
        selected_ids, capped_ops = self._select_by_pressure(ordered_ops, pressure_by_id)
        carryover_tail_ids = [
            assignment.operation_id
            for assignment in st.previous_window_tail_assignments
            if assignment.operation_id in self.ops_by_id
            and assignment.operation_id not in st.committed_op_ids
        ]
        for op_id in sorted(set(carryover_tail_ids), key=self.op_positions.__getitem__):
            if op_id in selected_ids:
                continue
            selected_ids.add(op_id)
            capped_ops.append(self.ops_by_id[op_id])
        w.rewound_assignments = self._select_backtracking_assignments(st.window_start_offset)
        rewound_ids = {assignment.operation_id for assignment in w.rewound_assignments}
        # W16-P0-1: a rewound op is no longer committed — it must not stay
        # sealed as immutable for the final stabilize pass.
        st.sealed_window_op_ids.difference_update(rewound_ids)
        if w.rewound_assignments:
            self.tel.backtracking_windows += 1
            self.tel.backtracking_ops_total += len(w.rewound_assignments)
            for assignment in w.rewound_assignments:
                if assignment.operation_id not in selected_ids:
                    selected_ids.add(assignment.operation_id)
                    capped_ops.append(self.ops_by_id[assignment.operation_id])
        w.window_ops = sorted(
            capped_ops,
            key=lambda op: (
                self.order_due_offsets.get(op.order_id, self.horizon_minutes),
                op.seq_in_order,
                self.op_earliest.get(op.id, 0.0),
                self.op_positions[op.id],
            ),
        )

    def _select_by_pressure(
        self, ordered_ops: list[Operation], pressure_by_id: dict[UUID, float]
    ) -> tuple[set[UUID], list[Operation]]:
        """Lazy-heap greedy selection; covering a still-uncovered machine boosts."""
        boost = self.cfg.admission.machine_coverage_boost
        uncovered = {wc_id for op in ordered_ops for wc_id in self.op_eligible_wc_ids[op.id]}

        def entry(op: Operation, cover: bool) -> tuple[float, float, int, int, UUID, bool]:
            score = pressure_by_id.get(op.id, 0.0) * (boost if cover else 1.0)
            due = self.order_due_offsets.get(op.order_id, self.horizon_minutes)
            return (-score, due, op.seq_in_order, self.op_positions[op.id], op.id, cover)

        heap: list[tuple[float, float, int, int, UUID, bool]] = []
        for op in ordered_ops:
            heappush(heap, entry(op, bool(self.op_eligible_wc_ids[op.id] & uncovered)))
        selected_ids: set[UUID] = set()
        capped_ops: list[Operation] = []
        cap_limit = min(self.effective_window_op_cap, len(ordered_ops))
        while heap and len(capped_ops) < cap_limit:
            neg_score, _due, _seq, _pos, op_id, previous_cover = heappop(heap)
            if op_id in selected_ids:
                continue
            op = self.ops_by_id[op_id]
            current_cover = bool(self.op_eligible_wc_ids[op_id] & uncovered)
            current_score = pressure_by_id.get(op_id, 0.0)
            if current_cover:
                current_score *= boost
            if previous_cover != current_cover or abs((-neg_score) - current_score) > 1e-12:
                heappush(heap, entry(op, current_cover))
                continue
            selected_ids.add(op_id)
            capped_ops.append(op)
            for wc_id in self.op_eligible_wc_ids[op_id]:
                uncovered.discard(wc_id)
        return selected_ids, capped_ops

    def _measure_window_pressure(self, w: _WindowCtx) -> None:
        tel, window_ops = self.tel, w.window_ops
        w.candidate_pressure = len(w.candidate_ids) / max(1, self.effective_window_op_cap)
        tel.candidate_pressure_values.append(w.candidate_pressure)
        due_only_ids = {
            op.id for op in window_ops if w.candidate_slack_by_id.get(op.id, 0.0) <= 0.0
        }
        tel.due_pressure_selected_ids.update(due_only_ids)
        w.due_pressure = len(due_only_ids) / max(1, len(window_ops))
        tel.due_pressure_values.append(w.due_pressure)
        w.due_drift_minutes = sum(
            max(0.0, w.end_offset - self.order_due_offsets.get(op.order_id, self.horizon_minutes))
            for op in window_ops
        ) / max(1, len(window_ops))
        tel.due_drift_minutes_values.append(w.due_drift_minutes)
        w.spillover = max(0, len(w.candidate_ids) - len(window_ops))
        tel.spillover_count += w.spillover

    def _build_window_operations(self, w: _WindowCtx) -> None:
        """Frozen boundary, predecessor closure, frozen offsets, clean sub-ops."""
        st = self.st
        rewound_ids = {assignment.operation_id for assignment in w.rewound_assignments}
        w.frozen_assignments = [
            a for a in st.committed_assignments if a.operation_id not in rewound_ids
        ]
        w.frozen_assignment_by_op = {
            op_id: a
            for op_id, a in st.committed_assignment_by_op.items()
            if op_id not in rewound_ids
        }
        w.frozen_op_ids = set(w.frozen_assignment_by_op.keys())
        w.window_op_ids = self.solver._expand_predecessor_closure(
            {op.id for op in w.window_ops}, self.ops_by_id, w.frozen_op_ids
        )
        # Wave 13 / C13-1: build frozen predecessor offsets from ORIGINAL ops
        # BEFORE clearing edges for ScheduleProblem validation.
        for op_id in w.window_op_ids:
            pred_id = self.ops_by_id[op_id].predecessor_op_id
            if pred_id is None or pred_id in w.window_op_ids:
                continue
            frozen_pred = w.frozen_assignment_by_op.get(pred_id)
            if frozen_pred is None:
                w.missing_frozen_predecessor = True
                break
            w.frozen_predecessor_end_offsets[op_id] = math.ceil(
                (frozen_pred.end_time - self.horizon_start).total_seconds() / 60.0
            )
        # Clear predecessor links to frozen ops so the sub-problem validates.
        for op_id in sorted(w.window_op_ids, key=self.op_positions.__getitem__):
            op = self.ops_by_id[op_id]
            if op.predecessor_op_id and op.predecessor_op_id not in w.window_op_ids:
                w.clean_window_ops.append(op.model_copy(update={"predecessor_op_id": None}))
            else:
                w.clean_window_ops.append(op)

    # -------------------------------------------------------------- inner path

    def _attempt_inner_solve(self, w: _WindowCtx) -> None:
        """Route, budget and run the inner solver; commit on acceptance."""
        st, inner = self.st, self.cfg.inner
        w.commit_boundary = st.window_start_offset + self.cfg.geometry.window_minutes
        w.committed_before_window = len(st.committed_op_ids)
        w.selected_inner_solver_name = inner.inner_solver_name
        w.selected_inner_solver = self.inner_solver
        w.selected_inner_kwargs = dict(inner.inner_kwargs)
        # Wave 14 / C14-crash: always defined for fallback telemetry.
        w.per_window_limit = 0.0
        self._route_hybrid_inner(w)
        self._apply_coverage_pace_guard(w)
        if w.missing_frozen_predecessor:
            # Wave 13 / C13-1: refuse exact inner path without a frozen pred.
            w.inner_rejection_reason = "missing_frozen_predecessor"
            w.selected_inner_solver_name = "greedy"
        if w.selected_inner_solver_name == "greedy":
            return
        try:
            self._run_inner_solver(w)
        except Exception as exc:
            self._record_inner_exception(w, exc)

    def _route_hybrid_inner(self, w: _WindowCtx) -> None:
        inner = self.cfg.inner
        if not (
            inner.hybrid_inner_routing_enabled
            and inner.inner_solver_name == "alns"
            and self.hybrid_inner_solver is not None
        ):
            return
        self.tel.hybrid_route_attempts += 1
        due_trigger = w.due_pressure >= inner.hybrid_due_pressure_threshold
        candidate_trigger = w.candidate_pressure >= inner.hybrid_candidate_pressure_threshold
        size_trigger = len(w.clean_window_ops) <= inner.hybrid_max_ops
        if not (size_trigger and (due_trigger or candidate_trigger)):
            return
        w.selected_inner_solver_name = inner.hybrid_inner_solver_name
        w.selected_inner_solver = self.hybrid_inner_solver
        w.selected_inner_kwargs = dict(inner.hybrid_inner_kwargs)
        self.tel.hybrid_route_activations += 1
        if due_trigger and candidate_trigger:
            w.hybrid_routing_reason = "due+candidate"
        elif due_trigger:
            w.hybrid_routing_reason = "due"
        else:
            w.hybrid_routing_reason = "candidate"

    def _apply_coverage_pace_guard(self, w: _WindowCtx) -> None:
        cover = self.cfg.cover
        if not (
            cover.coverage_pace_guard_enabled
            and w.selected_inner_solver_name != "greedy"
            and self.pace.should_intervene(time.monotonic() - self.t0)
        ):
            return
        # Coverage pace below threshold: spend this window on the cheap greedy
        # commit path so the outer coverage KPI recovers.
        w.inner_rejection_reason = "coverage_pace_guard"
        w.selected_inner_solver_name = "greedy"
        self.tel.coverage_pace_interventions += 1
        logger.info(
            "RHC coverage pace guard: window %d switched to greedy "
            "(pace_ratio=%.3f < threshold=%.3f)",
            self.st.window_count,
            self.pace.pace_ratio(time.monotonic() - self.t0) or 0.0,
            cover.coverage_pace_threshold,
        )

    def _build_window_subproblem(self, w: _WindowCtx) -> ScheduleProblem:
        """Sub-problem bounded to the commit band (coverage yield)."""
        problem, geometry = self.problem, self.cfg.geometry
        window_order_ids = {op.order_id for op in w.clean_window_ops}
        if geometry.window_bound_inner_horizon and w.end_offset + 1e-9 < self.horizon_minutes:
            sub_horizon_end = min(
                self.horizon_end,
                self.horizon_start
                + timedelta(minutes=w.end_offset + geometry.window_horizon_slack_minutes),
            )
        else:
            sub_horizon_end = self.horizon_end
        return ScheduleProblem(
            states=problem.states,
            orders=[o for o in problem.orders if o.id in window_order_ids],
            operations=w.clean_window_ops,
            work_centers=problem.work_centers,
            setup_matrix=problem.setup_matrix,
            auxiliary_resources=problem.auxiliary_resources,
            aux_requirements=[
                r for r in problem.aux_requirements if r.operation_id in w.window_op_ids
            ],
            planning_horizon_start=problem.planning_horizon_start,
            planning_horizon_end=sub_horizon_end,
        )

    def _run_inner_solver(self, w: _WindowCtx) -> None:
        inner = self.cfg.inner
        sub_problem = self._build_window_subproblem(w)
        w.window_lower_bound = compute_relaxed_makespan_lower_bound(sub_problem)
        # Respect coverage reserve: do not let inner solvers eat residual fill time.
        remaining_time = max(
            1.0, self.cfg.budget.window_time_limit_s - (time.monotonic() - self.t0)
        )
        w.per_window_limit = max(
            1.0,
            min(
                remaining_time * inner.inner_window_time_fraction,
                _resolve_inner_window_time_cap(
                    selected_solver_name=w.selected_inner_solver_name,
                    window_op_count=len(w.clean_window_ops),
                    policy=self.inner_window_cap_policy,
                ),
            ),
        )
        if (
            w.selected_inner_solver_name == "alns"
            and w.per_window_limit < inner.inner_solver_min_budget_s
        ):
            w.inner_rejection_reason = "inner_skipped_low_budget"
        else:
            effective_kwargs = self._prepare_inner_kwargs(w)
            if self._should_skip_alns_presearch(w):
                w.inner_result = self._budget_guard_skip_result()
            else:
                assert w.selected_inner_solver is not None
                w.inner_result = w.selected_inner_solver.solve(
                    sub_problem, time_limit_s=w.per_window_limit, **effective_kwargs
                )
            assert w.inner_result is not None
        self._absorb_alns_feedback(w)
        self._accept_or_reject_inner_result(w)

    def _record_inner_exception(self, w: _WindowCtx, exc: Exception) -> None:
        tel = self.tel
        w.inner_rejection_reason = "inner_exception"
        w.inner_exception_message = f"{type(exc).__name__}: {exc}"
        if len(tel.inner_exception_messages_sample) < _MAX_INNER_EXCEPTION_MESSAGE_SAMPLES:
            tel.inner_exception_messages_sample.append(w.inner_exception_message)
        if tel.inner_exception_logs_emitted < _MAX_INNER_EXCEPTION_LOGS:
            logger.warning(
                "RHC window %d: inner solver '%s' failed, falling back to greedy",
                self.st.window_count,
                w.selected_inner_solver_name,
                exc_info=True,
            )
            tel.inner_exception_logs_emitted += 1
        elif tel.inner_exception_logs_emitted == _MAX_INNER_EXCEPTION_LOGS:
            logger.warning(
                "RHC inner solver exception log sample "
                "cap reached; suppressing additional stack traces"
            )
            tel.inner_exception_logs_emitted += 1

    def _prepare_inner_kwargs(self, w: _WindowCtx) -> dict[str, Any]:
        """Warm start, frozen boundary and solver-specific hand-off kwargs."""
        st, problem = self.st, self.problem
        effective: dict[str, Any] = dict(w.selected_inner_kwargs)
        warm_candidates: list[Assignment] = []
        has_external_candidates = False
        for op_id, assignment in self.external_warm_start_by_op.items():
            if op_id in w.window_op_ids:
                warm_candidates.append(assignment)
                has_external_candidates = True
        for assignment in st.previous_window_tail_assignments:
            if assignment.operation_id in w.window_op_ids:
                warm_candidates.append(assignment)
        for assignment in w.rewound_assignments:
            if assignment.operation_id in w.window_op_ids:
                warm_candidates.append(assignment)
        w.warm_selection = filter_warm_start_assignments(
            warm_candidates,
            active_window_op_ids=w.window_op_ids,
            frozen_committed_op_ids=w.frozen_op_ids,
            frozen_boundary_assignments=w.frozen_assignments,
        )
        if has_external_candidates:
            self.tel.external_warm_start_used_windows += 1
        if w.warm_selection.assignments:
            effective["warm_start_assignments"] = sorted(
                w.warm_selection.assignments, key=lambda assignment: assignment.start_time
            )
        if w.frozen_assignments:
            effective["frozen_assignments"] = list(w.frozen_assignments)
            # Wave 13 / C13-1: offsets + full context (built before pred clear).
            if w.frozen_predecessor_end_offsets:
                effective["frozen_predecessor_end_offsets"] = dict(w.frozen_predecessor_end_offsets)
            effective["frozen_context_operations"] = list(problem.operations)
            effective["frozen_aux_requirements"] = list(problem.aux_requirements)
        if w.selected_inner_solver_name == "cpsat":
            effective["auto_greedy_warm_start"] = False
        if w.selected_inner_solver_name == "alns":
            self._apply_alns_inner_kwargs(w, effective)
        return effective

    def _apply_alns_inner_kwargs(self, w: _WindowCtx, effective: dict[str, Any]) -> None:
        st, inner = self.st, self.cfg.inner
        effective["due_pressure"] = w.due_pressure
        effective["candidate_pressure"] = w.candidate_pressure
        effective.setdefault("random_seed", inner.random_seed_base + st.window_count)
        effective["dynamic_no_improve_enabled"] = inner.dynamic_no_improve_enabled
        # C2 (Task 12.4): seed the adaptive mechanism with the previous weights.
        if st.previous_window_operator_weights is not None:
            effective["initial_operator_weights"] = st.previous_window_operator_weights
        # C3 (Task 3a.4): cross-window quality hints when learning is enabled.
        if inner.cross_window_learning_enabled and st.quality_summary_buffer:
            effective["cross_window_hints"] = list(st.quality_summary_buffer)
        if st.cross_window_variable_fixing_enabled and st.cross_window_stable_ops:
            effective["fixed_op_ids"] = list(st.cross_window_stable_ops)
        effective["no_improve_due_alpha"] = inner.no_improve_due_alpha
        effective["no_improve_candidate_beta"] = inner.no_improve_candidate_beta
        if inner.no_improve_min_iters is not None:
            effective["no_improve_min_iters"] = inner.no_improve_min_iters
        if inner.no_improve_max_iters is not None:
            effective["no_improve_max_iters"] = inner.no_improve_max_iters
        if self.alns_budget_auto_scaling_enabled:
            self._scale_alns_budget(w, effective)
        if inner.variable_fixing_enabled:
            self._apply_variable_fixing(w, effective)

    def _scale_alns_budget(self, w: _WindowCtx, effective: dict[str, Any]) -> None:
        tel = self.tel
        # The EMA override (R2) wins over the static policy raw value; current()
        # returns None until the first observation (kernel fallback path).
        profile = _scale_alns_inner_budget(
            effective_kwargs=effective,
            per_window_limit=w.per_window_limit,
            window_op_count=len(w.clean_window_ops),
            policy=self.alns_budget_policy,
            override_estimated_repair_s_per_destroyed_op=self.repair_cost_estimator.current(),
        )
        w.alns_budget_profile = profile
        effective["max_iterations"] = int(profile["effective_max_iterations"])
        effective["max_destroy"] = int(profile["effective_max_destroy"])
        if self.cfg.alns_budget.alns_dynamic_repair_budget_enabled:
            effective["repair_time_limit_s"] = float(profile["effective_repair_time_limit_s"])
        tel.alns_effective_max_iterations_values.append(int(profile["effective_max_iterations"]))
        tel.alns_effective_max_destroy_values.append(int(profile["effective_max_destroy"]))
        tel.alns_effective_repair_time_limit_values.append(
            float(profile["effective_repair_time_limit_s"])
        )
        if bool(profile["scaled"]):
            tel.alns_budget_scaled_windows += 1

    def _apply_variable_fixing(self, w: _WindowCtx, effective: dict[str, Any]) -> None:
        """P3.1: pass ops that kept their machine for >= min_frequency windows."""
        inner = self.cfg.inner
        window_fixed_op_ids: set[UUID] = set()
        max_fixed = int(len(w.clean_window_ops) * inner.variable_fixing_max_ratio)
        for op in w.clean_window_ops:
            if len(window_fixed_op_ids) >= max_fixed:
                break
            entry = self.st.op_machine_stability.get(op.id)
            if entry is not None and entry[1] >= inner.variable_fixing_min_frequency:
                window_fixed_op_ids.add(op.id)
        if not window_fixed_op_ids:
            return
        effective["fixed_op_ids"] = window_fixed_op_ids
        self.tel.total_fixed_ops_across_windows += len(window_fixed_op_ids)
        logger.debug(
            "RHC window %d: variable fixing %d ops (%.1f%%)",
            self.st.window_count,
            len(window_fixed_op_ids),
            100.0 * len(window_fixed_op_ids) / max(1, len(w.clean_window_ops)),
        )

    def _should_skip_alns_presearch(self, w: _WindowCtx) -> bool:
        """R1: estimated-cost budget guard (legacy raw op-count guard fallback)."""
        ab = self.cfg.alns_budget
        is_alns = w.selected_inner_solver_name == "alns"
        n_ops = len(w.clean_window_ops)
        legacy_hit = (
            is_alns
            and ab.alns_presearch_budget_guard_enabled
            and n_ops > ab.alns_presearch_max_window_ops
            and w.per_window_limit < ab.alns_presearch_min_time_limit_s
        )
        estimated_hit = False
        profile = w.alns_budget_profile
        estimated_run_s = 0.0
        if self.alns_budget_auto_scaling_enabled and profile is not None:
            estimated_run_s = (
                float(profile["estimated_repair_s_per_destroyed_op"])
                * int(profile["effective_max_destroy"])
                * int(profile["effective_max_iterations"])
            )
            estimated_hit = (
                is_alns
                and ab.alns_presearch_budget_guard_enabled
                and estimated_run_s > w.per_window_limit
            )
            skip = estimated_hit
        else:
            skip = legacy_hit
        if not skip:
            return False
        self.tel.alns_presearch_budget_guard_skipped_windows += 1
        if (legacy_hit and not estimated_hit) or profile is None:
            logger.info(
                "RHC window %d skipped ALNS pre-search: %d ops exceed guard "
                "limit=%d at per-window budget %.2fs",
                self.st.window_count,
                n_ops,
                ab.alns_presearch_max_window_ops,
                w.per_window_limit,
            )
        else:
            logger.info(
                "RHC window %d skipped ALNS pre-search: estimated run %.2fs "
                "exceeds per-window budget %.2fs (iters=%d destroy=%d)",
                self.st.window_count,
                estimated_run_s,
                w.per_window_limit,
                int(profile["effective_max_iterations"]),
                int(profile["effective_max_destroy"]),
            )
        return True

    @staticmethod
    def _budget_guard_skip_result() -> ScheduleResult:
        return ScheduleResult(
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

    def _absorb_alns_feedback(self, w: _WindowCtx) -> None:
        """R2 EMA repair-cost calibration + C2 operator-weight persistence."""
        if w.selected_inner_solver_name != "alns" or w.inner_result is None:
            return
        metadata = w.inner_result.metadata or {}
        self.repair_cost_estimator.update(metadata.get("observed_repair_s_per_destroyed_op"))
        extracted_weights = metadata.get("alns_final_operator_weights")
        if isinstance(extracted_weights, dict) and extracted_weights:
            self.st.previous_window_operator_weights = extracted_weights

    def _accept_or_reject_inner_result(self, w: _WindowCtx) -> None:
        result = w.inner_result
        metadata = (result.metadata or {}) if result is not None else {}
        exhausted_before_search = bool(
            w.selected_inner_solver_name == "alns"
            and result is not None
            and bool(metadata.get("time_limit_exhausted_before_search"))
            and int(metadata.get("iterations_completed", 0)) == 0
        )
        if (
            result is not None
            and result.status in _SUCCESS_STATUSES
            and result.assignments
            and not exhausted_before_search
        ):
            self._commit_inner_result(w, result)
            return
        if result is None:
            w.inner_rejection_reason = w.inner_rejection_reason or "inner_not_run"
        elif exhausted_before_search:
            w.inner_rejection_reason = "inner_time_limit_exhausted_before_search"
        elif result.status not in _SUCCESS_STATUSES:
            w.inner_rejection_reason = (
                f"inner_status_{result.status.value}"
                if hasattr(result.status, "value")
                else f"inner_status_{result.status}"
            )
        else:
            w.inner_rejection_reason = "inner_empty_assignments"

    def _commit_inner_result(self, w: _WindowCtx, result: ScheduleResult) -> None:
        st, tel = self.st, self.tel
        boundary_aware, w.boundary_reanchor_changed_ops = _reanchor_inner_assignments(
            result.assignments,
            frozen_assignments=w.frozen_assignments,
            frozen_assignment_by_op=w.frozen_assignment_by_op,
            dispatch_context=self.dispatch_context,
            machine_index_factory=MachineIndex,
            find_earliest_feasible_slot=find_earliest_feasible_slot,
            ops_by_id=self.ops_by_id,
            op_earliest=self.op_earliest,
            op_positions=self.op_positions,
            horizon_start=self.horizon_start,
        )
        if w.frozen_assignments and not boundary_aware:
            # Wave 13 / H13-3: reanchor failed closed — do not commit.
            w.inner_rejection_reason = "reanchor_failed"
            w.inner_result = None
            return
        if w.frozen_assignments:
            tel.boundary_reanchor_windows += 1
            tel.boundary_reanchor_ops_total += len(boundary_aware)
            tel.boundary_reanchor_changed_ops_total += w.boundary_reanchor_changed_ops
        commit_candidates = self._collect_commit_candidates(
            boundary_aware,
            commit_boundary=w.commit_boundary,
            commit_all=w.end_offset >= self.horizon_minutes,
            frozen_committed_ids=w.frozen_op_ids,
            frozen_committed_assignment_by_op=w.frozen_assignment_by_op,
        )
        self._commit_window(w, commit_candidates)
        if self.cfg.cover.coverage_pace_guard_enabled:
            # Audit 2026-10 (A-08): the pace controller must observe EVERY
            # solved window. Observing only greedy-fallback windows hid the
            # slow-but-successful inner windows the guard exists to catch.
            self.pace.observe_window(len(st.committed_op_ids) - w.committed_before_window)
        st.previous_window_tail_assignments = sorted(
            [a for a in boundary_aware if a.operation_id not in commit_candidates],
            key=lambda assignment: assignment.start_time,
        )
        st.window_start_offset += self.cfg.geometry.window_minutes
        w.solved_via_inner = True
        if self.cfg.inner.variable_fixing_enabled:
            self._update_machine_stability(boundary_aware)
        # C3 (Task 3a.3): window_start_offset already advanced by window_minutes,
        # so the actual span = end - start + step.
        window_span = max(
            w.end_offset - st.window_start_offset + self.cfg.geometry.window_minutes,
            self.base_window_span_minutes,
        )
        st.quality_summary_buffer.append(
            compute_window_quality_summary(
                window_index=st.window_count,
                assignments=boundary_aware,
                window_span_minutes=window_span,
                order_due_offsets=self.order_due_offsets,
                ops_by_id=self.ops_by_id,
                horizon_start=self.horizon_start,
            )
        )
        self._record_inner_success_summary(w, result, len(commit_candidates), len(boundary_aware))

    def _update_machine_stability(self, assignments: list[Assignment]) -> None:
        stability = self.st.op_machine_stability
        for assignment in assignments:
            oid, assigned_wc_id = assignment.operation_id, assignment.work_center_id
            prev = stability.get(oid)
            if prev is not None and prev[0] == assigned_wc_id:
                stability[oid] = (assigned_wc_id, prev[1] + 1)
            else:
                stability[oid] = (assigned_wc_id, 1)

    def _record_inner_success_summary(
        self, w: _WindowCtx, result: ScheduleResult, committed_now: int, reanchored_ops: int
    ) -> None:
        self._append_inner_window_summary(
            window=self.st.window_count,
            ops_in_window=len(w.clean_window_ops),
            ops_committed=committed_now,
            resolution_mode="inner",
            inner_result=result,
            lower_bound=w.window_lower_bound.value,
            inner_time_limit_s=w.per_window_limit,
            candidate_pressure=w.candidate_pressure,
            due_pressure=w.due_pressure,
            due_drift_minutes=w.due_drift_minutes,
            spillover_ops=w.spillover,
        )
        summary = self.st.inner_window_summaries[-1]
        self._annotate_admission(summary, w)
        summary["boundary_reanchor_ops"] = reanchored_ops
        summary["boundary_reanchor_changed_ops"] = w.boundary_reanchor_changed_ops
        if self.cfg.cover.commit_precedence_gate_enabled:
            summary["commit_precedence_deferred_ops"] = (
                self.st.window_commit_precedence_deferred_last
            )
        self._annotate_alns_budget(summary, w)
        if w.rewound_assignments:
            summary["backtracking_rewind_ops"] = len(w.rewound_assignments)
        if w.hybrid_routing_reason is not None:
            summary["inner_solver_selected"] = w.selected_inner_solver_name
            summary["hybrid_routing_reason"] = w.hybrid_routing_reason
        logger.info(
            "RHC window %d solved by %s inner solver (%d ops committed)",
            self.st.window_count,
            w.selected_inner_solver_name,
            committed_now,
        )

    @staticmethod
    def _annotate_admission(summary: dict[str, Any], w: _WindowCtx) -> None:
        if w.warm_selection is not None and w.warm_selection.rejected_reason_counts:
            summary["warm_start_rejected_reason_counts"] = dict(
                w.warm_selection.rejected_reason_counts
            )
        if w.admission_relaxed:
            summary["admission_relaxed"] = True
            summary["admission_relaxation_recovered_ops"] = w.admission_relaxation_recovered_ops
        if w.full_scan_triggered:
            summary["full_scan_triggered"] = True
            summary["full_scan_added_ops"] = w.full_scan_added_ops
            summary["full_scan_final_pool"] = w.full_scan_final_pool

    @staticmethod
    def _annotate_alns_budget(summary: dict[str, Any], w: _WindowCtx) -> None:
        profile = w.alns_budget_profile
        if profile is None:
            return
        summary["alns_budget_auto_scaled"] = bool(profile["scaled"])
        summary["alns_effective_max_iterations"] = int(profile["effective_max_iterations"])
        summary["alns_effective_max_destroy"] = int(profile["effective_max_destroy"])
        summary["alns_estimated_repair_s_per_destroyed_op"] = round(
            float(profile["estimated_repair_s_per_destroyed_op"]), 4
        )
        summary["alns_effective_repair_time_limit_s"] = round(
            float(profile["effective_repair_time_limit_s"]), 4
        )

    # ------------------------------------------------------------- commit core

    def _collect_commit_candidates(
        self,
        assignments: list[Assignment],
        *,
        commit_boundary: float,
        commit_all: bool,
        frozen_committed_ids: set[UUID] | None,
        frozen_committed_assignment_by_op: dict[UUID, Assignment],
        eligible_ids: set[UUID] | None = None,
    ) -> dict[UUID, Assignment]:
        st = self.st
        frozen_ids = st.committed_op_ids if frozen_committed_ids is None else frozen_committed_ids
        candidates, clipped_count = _collect_commit_candidates(
            assignments,
            commit_boundary=commit_boundary,
            commit_all=commit_all,
            frozen_ids=frozen_ids,
            eligible_ids=eligible_ids,
            horizon_start=self.horizon_start,
            horizon_minutes=self.horizon_minutes,
            ops_by_id=self.ops_by_id,
        )
        self.tel.horizon_clipped_assignments += clipped_count
        st.window_commit_precedence_deferred_last = 0
        if self.cfg.cover.commit_precedence_gate_enabled and candidates:
            candidates, deferred_op_ids = _filter_commit_candidates_by_precedence(
                candidates,
                committed_assignment_by_op=frozen_committed_assignment_by_op,
                ops_by_id=self.ops_by_id,
            )
            if deferred_op_ids:
                st.window_commit_precedence_deferred_last = len(deferred_op_ids)
                st.commit_precedence_deferred_op_ids.update(deferred_op_ids)
                logger.info(
                    "RHC commit precedence gate: deferred %d candidate(s) "
                    "to preserve cross-window precedence",
                    len(deferred_op_ids),
                )
        return candidates

    def _commit_window(self, w: _WindowCtx, commit_candidates: dict[UUID, Assignment]) -> None:
        """Rebuild the commitment = frozen boundary + this window's commits."""
        st = self.st
        st.committed_assignments = list(w.frozen_assignments)
        st.committed_assignment_by_op = dict(w.frozen_assignment_by_op)
        st.committed_op_ids = set(w.frozen_op_ids)
        for op_id, assignment in sorted(
            commit_candidates.items(), key=lambda item: item[1].start_time
        ):
            st.committed_assignments.append(assignment)
            st.committed_assignment_by_op[op_id] = assignment
            st.committed_op_ids.add(op_id)
        st.sealed_window_op_ids.intersection_update(st.committed_op_ids)
        if st.cross_window_variable_fixing_enabled:
            st.cross_window_stable_ops = _detect_cross_window_stable_ops(
                prev_committed_by_op=st.prev_committed_by_op,
                curr_committed_by_op=st.committed_assignment_by_op,
            )
            st.prev_committed_by_op = dict(st.committed_assignment_by_op)

    def _select_backtracking_assignments(self, window_start_offset: float) -> list[Assignment]:
        cover, st = self.cfg.cover, self.st
        return _select_backtracking_assignments(
            window_start_offset=window_start_offset,
            backtracking_enabled=cover.backtracking_enabled,
            backtracking_tail_minutes=cover.backtracking_tail_minutes,
            backtracking_max_ops=cover.backtracking_max_ops,
            committed_assignments=st.committed_assignments,
            committed_assignment_by_op=st.committed_assignment_by_op,
            ops_by_id=self.ops_by_id,
            horizon_start=self.horizon_start,
        )

    # ------------------------------------------------------- greedy fallback

    def _run_greedy_fallback(self, w: _WindowCtx) -> bool:
        """Greedy dispatch on the window ops; returns False when out of budget."""
        st = self.st
        st.previous_window_tail_assignments = []
        scheduled_so_far, window_scheduled_ids = self._greedy_place_window_ops(w)
        commit_candidates = self._collect_commit_candidates(
            scheduled_so_far,
            commit_boundary=w.commit_boundary,
            commit_all=w.end_offset >= self.horizon_minutes,
            frozen_committed_ids=w.frozen_op_ids,
            frozen_committed_assignment_by_op=w.frozen_assignment_by_op,
            eligible_ids=window_scheduled_ids,
        )
        self._commit_window(w, commit_candidates)
        if self.cfg.inner.inner_solver_name != "greedy":
            self._record_fallback_summary(w)
        if self.cfg.cover.coverage_pace_guard_enabled:
            self.pace.observe_window(len(st.committed_op_ids) - w.committed_before_window)
        st.window_start_offset += self.cfg.geometry.window_minutes
        return not st.time_limit_reached

    def _greedy_place_window_ops(self, w: _WindowCtx) -> tuple[list[Assignment], set[UUID]]:
        """Repeated priority sweeps until no op can be placed (or budget ends)."""
        st = self.st
        scheduled_so_far = list(w.frozen_assignments)
        scheduled_by_op = dict(w.frozen_assignment_by_op)
        machine_idx = MachineIndex(self.dispatch_context)
        for assignment in scheduled_so_far:
            machine_idx.add(assignment)
        ready_pool = list(w.clean_window_ops)
        window_scheduled_ids: set[UUID] = set()
        # Sort by priority desc, then seq asc for deterministic ordering.
        ready_pool.sort(
            key=lambda op: (
                -(
                    self.orders_by_id[op.order_id].priority
                    if op.order_id in self.orders_by_id
                    else 0
                ),
                op.seq_in_order,
            ),
        )
        max_inner_iters = len(ready_pool) * 3
        inner_iter = 0
        while ready_pool and inner_iter < max_inner_iters:
            if self._fallback_budget_exhausted():
                break
            inner_iter += 1
            placed_any = False
            for op in list(ready_pool):
                if self._fallback_budget_exhausted():
                    break
                placed = self._greedy_place_one(
                    w, op, scheduled_so_far, scheduled_by_op, window_scheduled_ids, machine_idx
                )
                if placed is None:
                    continue
                scheduled_so_far.append(placed)
                scheduled_by_op[op.id] = placed
                machine_idx.add(placed)
                window_scheduled_ids.add(op.id)
                ready_pool.remove(op)
                placed_any = True
            if st.time_limit_reached or not placed_any:
                break  # no progress possible
        w.fallback_iterations = inner_iter
        return scheduled_so_far, window_scheduled_ids

    def _fallback_budget_exhausted(self) -> bool:
        if not self._window_budget_exceeded():
            return False
        self.st.time_limit_reached = True
        logger.warning(
            "RHC window budget reached during window %d greedy scheduling",
            self.st.window_count,
        )
        return True

    def _greedy_place_one(
        self,
        w: _WindowCtx,
        op: Operation,
        scheduled_so_far: list[Assignment],
        scheduled_by_op: dict[UUID, Assignment],
        window_scheduled_ids: set[UUID],
        machine_idx: MachineIndex,
    ) -> Assignment | None:
        """Earliest-completion slot for one op, or None when not placeable now."""
        st = self.st
        # Wave 13: use ORIGINAL predecessor (clean_window_ops may have cleared it).
        pred_id = self.ops_by_id.get(op.id, op).predecessor_op_id
        if pred_id and (pred_id not in st.committed_op_ids and pred_id not in window_scheduled_ids):
            return None  # predecessor not yet scheduled
        pred_end = 0.0
        if pred_id:
            pred_assignment: Assignment | None = scheduled_by_op.get(pred_id)
            if pred_assignment is None:
                pred_assignment = w.frozen_assignment_by_op.get(pred_id)
            if pred_assignment is None:
                return None  # missing frozen pred — refuse place
            pred_end = (pred_assignment.end_time - self.horizon_start).total_seconds() / 60.0
        eligible = op.eligible_wc_ids if op.eligible_wc_ids else self.default_wc_ids
        best_slot = None
        best_wc = None
        # RT-20 F1: floor by release-propagated earliest start, not just the
        # predecessor's committed end (release_date violation otherwise).
        op_floor = max(pred_end, self.op_earliest.get(op.id, 0.0))
        for wc_id in eligible:
            slot = find_earliest_feasible_slot(
                self.dispatch_context,
                scheduled_so_far,
                op,
                wc_id,
                op_floor,
                machine_index=machine_idx,
            )
            if slot is None:
                continue
            if slot.end_offset > self.horizon_minutes + 1e-9:
                self.tel.horizon_clipped_assignments += 1
                continue
            if best_slot is None or slot.end_offset < best_slot.end_offset:
                best_slot = slot
                best_wc = wc_id
        if not (best_slot and best_wc):
            return None
        return Assignment(
            operation_id=op.id,
            work_center_id=best_wc,
            start_time=self.horizon_start + timedelta(minutes=best_slot.start_offset),
            end_time=self.horizon_start + timedelta(minutes=best_slot.end_offset),
            setup_minutes=best_slot.setup_minutes,
            aux_resource_ids=best_slot.aux_resource_ids,
        )

    def _record_fallback_summary(self, w: _WindowCtx) -> None:
        st, tel = self.st, self.tel
        tel.inner_fallback_windows += 1
        reason = w.inner_rejection_reason or "inner_not_accepted"
        tel.inner_fallback_reason_counts[reason] += 1
        if reason == "inner_exception":
            tel.inner_exception_windows += 1
        result = w.inner_result
        if result is None:
            tel.inner_status_counts["not_run"] += 1
        else:
            inner_status = (result.metadata or {}).get("inner_status_override")
            if not isinstance(inner_status, str) or not inner_status:
                inner_status = (
                    result.status.value if hasattr(result.status, "value") else str(result.status)
                )
            tel.inner_status_counts[inner_status] += 1
        self._append_inner_window_summary(
            window=st.window_count,
            ops_in_window=len(w.clean_window_ops),
            ops_committed=len(st.committed_op_ids) - w.committed_before_window,
            resolution_mode="fallback_greedy",
            inner_result=result,
            inner_time_limit_s=w.per_window_limit,
            candidate_pressure=w.candidate_pressure,
            due_pressure=w.due_pressure,
            due_drift_minutes=w.due_drift_minutes,
            spillover_ops=w.spillover,
            fallback_reason=reason,
            fallback_iterations=w.fallback_iterations,
            exception_message=w.inner_exception_message,
        )
        summary = st.inner_window_summaries[-1]
        self._annotate_admission(summary, w)
        self._annotate_alns_budget(summary, w)
        if w.rewound_assignments:
            summary["backtracking_rewind_ops"] = len(w.rewound_assignments)
        summary["inner_solver_selected"] = w.selected_inner_solver_name
        if self.cfg.cover.commit_precedence_gate_enabled:
            summary["commit_precedence_deferred_ops"] = st.window_commit_precedence_deferred_last
        if w.hybrid_routing_reason is not None:
            summary["hybrid_routing_reason"] = w.hybrid_routing_reason

    # ----------------------------------------------------------- residual fill

    def _residual_fill(self) -> None:
        """Coverage fallback for operations left unscheduled by the windows."""
        st, budget = self.st, self.cfg.budget
        unscheduled_ids = {op.id for op in self.problem.operations} - st.committed_op_ids
        if not unscheduled_ids:
            return
        can_run = budget.fallback_repair_enabled and (
            not self._coverage_deadline_exceeded()
            if budget.fallback_repair_on_timeout
            else not (st.time_limit_reached or self._global_time_exceeded())
        )
        if not budget.fallback_repair_enabled:
            st.fallback_repair_skipped = True
            logger.info(
                "RHC: %d operations unscheduled after all windows; "
                "skipping fallback greedy repair because fallback_repair_enabled=false",
                len(unscheduled_ids),
            )
            return
        if not can_run:
            st.fallback_repair_skipped = True
            logger.warning(
                "RHC: %d operations unscheduled after all windows; "
                "skipping fallback greedy repair because the coverage deadline is exhausted "
                "(time_limit=%.1fs soft_budget=%.1fs on_timeout=%s)",
                len(unscheduled_ids),
                budget.time_limit_s,
                budget.fallback_repair_soft_budget_s,
                budget.fallback_repair_on_timeout,
            )
            return
        self._run_residual_greedy(unscheduled_ids)

    def _run_residual_greedy(self, unscheduled_ids: set[UUID]) -> None:
        st, budget = self.st, self.cfg.budget
        st.fallback_repair_attempted = True
        logger.warning(
            "RHC: %d operations unscheduled after all windows; "
            "running fallback greedy repair (reserve=%.1fs soft_budget=%.1fs)",
            len(unscheduled_ids),
            budget.coverage_reserve_s,
            budget.fallback_repair_soft_budget_s if budget.fallback_repair_on_timeout else 0.0,
        )
        remaining_ops = [op for op in self.problem.operations if op.id in unscheduled_ids]
        remaining_ops.sort(key=lambda op: op.seq_in_order)
        repair_machine_idx = MachineIndex(self.dispatch_context)
        repair_machine_idx.extend(st.committed_assignments)
        cover_stats = place_operations_greedy(
            operations=remaining_ops,
            dispatch_context=self.dispatch_context,
            assignments=st.committed_assignments,
            assignment_by_op=st.committed_assignment_by_op,
            scheduled_ids=st.committed_op_ids,
            machine_index=repair_machine_idx,
            horizon_start=self.horizon_start,
            horizon_minutes=self.horizon_minutes,
            op_earliest=self.op_earliest,
            default_wc_ids=self.default_wc_ids,
            deadline_exceeded=self._coverage_deadline_exceeded,
        )
        self.tel.horizon_clipped_assignments += cover_stats.clipped
        if cover_stats.time_limited:
            st.time_limit_reached = True
            st.fallback_repair_time_limited = True
            logger.warning(
                "RHC fallback greedy repair stopped because the coverage deadline is exhausted"
            )

    # ---------------------------------------------------------------- finalize

    def _finalize(self) -> ScheduleResult:
        st = self.st
        temporal_stabilization = _stabilize_temporal_consistency(
            st.committed_assignments,
            ops_by_id=self.ops_by_id,
            setup_minutes=self.dispatch_context.setup_minutes,
            max_passes=_stabilization_pass_budget(
                ops_by_id=self.ops_by_id, assigned_op_ids=st.committed_op_ids
            ),
            immutable_op_ids=st.sealed_window_op_ids,
            horizon_end=self.original_horizon_end,
            dispatch_context=self.dispatch_context,
        )
        recompute_assignment_setups(st.committed_assignments, self.dispatch_context)
        if not st.committed_assignments:
            return self._empty_result(temporal_stabilization)
        final_obj = self.solver._evaluate_final(self.problem, st.committed_assignments, self.sdst)
        scheduled_count = len(st.committed_op_ids)
        total_ops = len(self.problem.operations)
        status, notary_meta = _finalize_rhc_claim_status(
            problem=self.problem,
            assignments=st.committed_assignments,
            scheduled_count=scheduled_count,
            total_ops=total_ops,
            stabilization=temporal_stabilization,
        )
        elapsed_ms = int((time.monotonic() - self.t0) * 1000)
        final_pace_ratio = (
            self.pace.pace_ratio(time.monotonic() - self.t0)
            if self.cfg.cover.coverage_pace_guard_enabled
            else None
        )
        logger.info(
            "RHC finished: %d windows, %d/%d ops scheduled, makespan=%.1f min, %d ms",
            st.window_count,
            scheduled_count,
            total_ops,
            final_obj.makespan_minutes,
            elapsed_ms,
        )
        metadata = {
            **self._meta_core(final_obj, status, scheduled_count, total_ops),
            **self._meta_pace_and_admission(final_pace_ratio),
            **self._meta_pressure_and_budget(),
            **self._meta_tail(temporal_stabilization, notary_meta, scheduled_count, total_ops),
        }
        return ScheduleResult(
            solver_name=self.solver.name,
            status=status,
            assignments=st.committed_assignments,
            objective=final_obj,
            duration_ms=elapsed_ms,
            metadata=metadata,
        )

    def _empty_result(self, temporal_stabilization: dict[str, int]) -> ScheduleResult:
        st = self.st
        elapsed_ms = int((time.monotonic() - self.t0) * 1000)
        return ScheduleResult(
            solver_name=self.solver.name,
            status=SolverStatus.ERROR,
            duration_ms=elapsed_ms,
            metadata={
                "error": "no assignments produced",
                "acceleration": self.acceleration_status,
                "windows": st.window_count,
                "time_limit_reached": st.time_limit_reached,
                "horizon_clipped_assignments": self.tel.horizon_clipped_assignments,
                "fallback_repair_attempted": st.fallback_repair_attempted,
                "fallback_repair_skipped": st.fallback_repair_skipped,
                "fallback_repair_time_limited": st.fallback_repair_time_limited,
                "ops_unscheduled": len(self.problem.operations),
                "lower_bound_upper_bound_comparable": False,
                "gap": None,
                "temporal_stabilization": temporal_stabilization,
            },
        )

    def _meta_core(
        self, final_obj: ObjectiveValues, status: SolverStatus, scheduled: int, total: int
    ) -> dict[str, Any]:
        st, tel, inner = self.st, self.tel, self.cfg.inner
        bounds_comparable = status == SolverStatus.FEASIBLE
        lower = self.global_lower_bound.value
        gap_ratio = (
            round(
                max(final_obj.makespan_minutes - lower, 0.0)
                / max(final_obj.makespan_minutes, 1e-9),
                6,
            )
            if bounds_comparable
            else None
        )
        modes = [summary.get("resolution_mode") for summary in st.inner_window_summaries]
        inner_solver_windows = sum(1 for mode in modes if mode in {"inner", "fallback_greedy"})
        inner_fallback_ratio = (
            tel.inner_fallback_windows / max(1, inner_solver_windows)
            if inner_solver_windows > 0
            else 0.0
        )
        logs = tel.inner_exception_logs_emitted
        return {
            "acceleration": self.acceleration_status,
            "windows_solved": st.window_count,
            "global_greedy_cover": st.global_greedy_cover_used,
            "global_greedy_cover_min_ops": self.cfg.cover.global_greedy_cover_min_ops,
            "ops_scheduled": scheduled,
            "ops_total": total,
            "lower_bound": round(lower, 4),
            "upper_bound": round(final_obj.makespan_minutes, 4),
            "gap": gap_ratio,
            "lower_bound_upper_bound_comparable": bounds_comparable,
            "lower_bound_method": "relaxed_precedence_capacity",
            "lower_bound_components": self.global_lower_bound.as_metadata(),
            "inner_solver": inner.inner_solver_name,
            "inner_solver_windows": inner_solver_windows,
            "inner_fallback_windows": tel.inner_fallback_windows,
            "inner_fallback_ratio": round(inner_fallback_ratio, 4),
            "inner_resolution_counts": {
                "inner": modes.count("inner"),
                "fallback_greedy": modes.count("fallback_greedy"),
            },
            "inner_fallback_reason_counts": dict(sorted(tel.inner_fallback_reason_counts.items())),
            "inner_status_counts": dict(sorted(tel.inner_status_counts.items())),
            "inner_exception_windows": tel.inner_exception_windows,
            "inner_exception_message_samples": list(tel.inner_exception_messages_sample),
            "inner_exception_logs_emitted": min(logs, _MAX_INNER_EXCEPTION_LOGS),
            "inner_exception_logs_suppressed": max(logs - _MAX_INNER_EXCEPTION_LOGS, 0),
            "inner_fallback_kpi_threshold": inner.inner_fallback_kpi_threshold,
            "inner_fallback_kpi_passed": inner_fallback_ratio <= inner.inner_fallback_kpi_threshold,
        }

    def _meta_pace_and_admission(self, final_pace_ratio: float | None) -> dict[str, Any]:
        st, tel, cover, adm, geo = (
            self.st,
            self.tel,
            self.cfg.cover,
            self.cfg.admission,
            self.cfg.geometry,
        )
        factors = tel.adaptive_window_expansion_factors
        return {
            "coverage_pace_guard_enabled": cover.coverage_pace_guard_enabled,
            "coverage_pace_threshold": cover.coverage_pace_threshold,
            "coverage_pace_min_windows": cover.coverage_pace_min_windows,
            "coverage_pace_interventions": tel.coverage_pace_interventions,
            "coverage_pace_windows_observed": self.pace.windows_observed,
            "coverage_pace_final_ratio": (
                round(final_pace_ratio, 4) if final_pace_ratio is not None else None
            ),
            "commit_precedence_gate_enabled": cover.commit_precedence_gate_enabled,
            "commit_precedence_deferred_ops_total": len(st.commit_precedence_deferred_op_ids),
            "preprocessing_ms": self.preprocessing_ms,
            "preprocessing_phase_ms": dict(self.preprocess_phase_ms),
            "peak_window_candidate_count": tel.peak_window_candidate_count,
            "peak_raw_window_candidate_count": tel.peak_raw_window_candidate_count,
            "due_pressure_selected_ops": len(tel.due_pressure_selected_ids),
            "candidate_pool_limit": self.candidate_pool_limit,
            "candidate_pool_factor": adm.candidate_pool_factor,
            "adaptive_window_enabled": geo.adaptive_window_enabled,
            "adaptive_window_min_fill_ratio": geo.adaptive_window_min_fill_ratio,
            "adaptive_window_max_multiplier": geo.adaptive_window_max_multiplier,
            "adaptive_window_expansions": tel.adaptive_window_expansions,
            "adaptive_window_mean_multiplier_applied": round(sum(factors) / len(factors), 4)
            if factors
            else 1.0,
            "adaptive_window_max_multiplier_applied": round(max(factors), 4) if factors else 1.0,
            "external_warm_start_supplied_assignments": len(self.external_warm_start_by_op),
            "external_warm_start_used_windows": tel.external_warm_start_used_windows,
            "candidate_pool_clamped_windows": tel.candidate_pool_clamped_windows,
            "candidate_pool_filtered_ops": tel.candidate_pool_filtered_ops,
            "candidate_admission_enabled": self.candidate_admission_active,
            "candidate_admission_configured": adm.candidate_admission_enabled,
            "precedence_ready_candidate_filter_enabled": (
                adm.precedence_ready_candidate_filter_enabled
            ),
            "precedence_ready_filtered_ops": tel.precedence_ready_filtered_ops,
            "precedence_ready_blocked_by_precedence_count": (
                tel.precedence_blocked_by_precedence_count
            ),
            "precedence_ready_ratio": round(
                tel.precedence_ready_candidate_ready_total
                / max(tel.precedence_ready_candidate_ops_total, 1),
                4,
            ),
            "due_admission_horizon_factor": adm.due_admission_horizon_factor,
            "admission_tail_weight": adm.admission_tail_weight,
            "progressive_admission_relaxation_enabled": (
                adm.progressive_admission_relaxation_enabled
            ),
            "admission_relaxation_min_fill_ratio": adm.admission_relaxation_min_fill_ratio,
            "admission_relaxation_windows": tel.admission_relaxation_windows,
            "admission_relaxation_recovered_ops": tel.admission_relaxation_recovered_ops,
            "admission_full_scan_enabled": adm.admission_full_scan_enabled,
            "admission_full_scan_min_fill_ratio": adm.admission_full_scan_min_fill_ratio,
            "admission_full_scan_windows": tel.admission_full_scan_windows,
            "admission_full_scan_triggered_windows": tel.admission_full_scan_triggered_windows,
            "admission_full_scan_added_ops": tel.admission_full_scan_added_ops,
            "admission_full_scan_final_pool_peak": tel.admission_full_scan_final_pool_peak,
            "admission_full_scan_recovered_ops": tel.admission_full_scan_recovered_ops,
        }

    def _meta_pressure_and_budget(self) -> dict[str, Any]:
        tel, inner, geo, ab = self.tel, self.cfg.inner, self.cfg.geometry, self.cfg.alns_budget
        cover = self.cfg.cover
        return {
            **_mean_max("candidate_pressure", tel.candidate_pressure_values, 4, mean_only=False),
            **_mean_max("due_pressure", tel.due_pressure_values, 4, mean_only=True),
            **_mean_max("due_drift_minutes", tel.due_drift_minutes_values, 2, mean_only=False),
            "spillover_count": tel.spillover_count,
            "earliest_frontier_advances": tel.admission_frontier_advances,
            "admission_frontier_advances": tel.admission_frontier_advances,
            "admission_starvation_count": tel.admission_starvation_count,
            "due_frontier_advances": tel.due_frontier_advances,
            "effective_window_operation_cap": self.effective_window_op_cap,
            "window_load_factor": geo.window_load_factor,
            "dynamic_no_improve_enabled": inner.dynamic_no_improve_enabled,
            "no_improve_due_alpha": inner.no_improve_due_alpha,
            "no_improve_candidate_beta": inner.no_improve_candidate_beta,
            "no_improve_min_iters": inner.no_improve_min_iters,
            "no_improve_max_iters": inner.no_improve_max_iters,
            "max_windows": geo.max_windows,
            "inner_solver_min_budget_s": inner.inner_solver_min_budget_s,
            "backtracking_enabled": cover.backtracking_enabled,
            "backtracking_tail_minutes": cover.backtracking_tail_minutes,
            "backtracking_max_ops": cover.backtracking_max_ops,
            "backtracking_windows": tel.backtracking_windows,
            "backtracking_ops_total": tel.backtracking_ops_total,
            "inner_window_time_fraction": inner.inner_window_time_fraction,
            "inner_window_time_cap_s": ab.inner_window_time_cap_s,
            "commit_boundary_mode": "end_time",
            "alns_inner_window_time_cap_s": ab.alns_inner_window_time_cap_s,
            "alns_inner_window_time_cap_scale_threshold_ops": (
                ab.alns_inner_window_time_cap_scale_threshold_ops
            ),
            "alns_inner_window_time_cap_scaled_s": ab.alns_inner_window_time_cap_scaled_s,
            **self._meta_alns_budget(),
        }

    def _meta_alns_budget(self) -> dict[str, Any]:
        tel, ab, estimator = self.tel, self.cfg.alns_budget, self.repair_cost_estimator
        raw_estimate = ab.alns_budget_estimated_repair_s_per_destroyed_op_raw
        return {
            "alns_budget_auto_scaling_enabled": self.alns_budget_auto_scaling_enabled,
            "alns_budget_estimated_repair_s_per_destroyed_op": (
                round(float(raw_estimate), 4) if raw_estimate is not None else None
            ),
            "alns_dynamic_repair_budget_enabled": ab.alns_dynamic_repair_budget_enabled,
            "alns_dynamic_repair_s_per_destroyed_op": ab.alns_dynamic_repair_s_per_destroyed_op,
            "alns_dynamic_repair_time_limit_min_s": ab.alns_dynamic_repair_time_limit_min_s,
            "alns_dynamic_repair_time_limit_max_s": ab.alns_dynamic_repair_time_limit_max_s,
            # R2 (EMA calibration) telemetry: final estimator state.
            "alns_repair_cost_ema_alpha": ab.alns_repair_cost_alpha,
            "alns_repair_cost_ema_estimate_s_per_destroyed_op": (
                round(estimator.estimate, 6) if estimator.estimate is not None else None
            ),
            "alns_repair_cost_ema_observation_count": estimator.observation_count,
            "alns_budget_scaled_windows": tel.alns_budget_scaled_windows,
            "alns_presearch_budget_guard_enabled": ab.alns_presearch_budget_guard_enabled,
            "alns_presearch_max_window_ops": ab.alns_presearch_max_window_ops,
            "alns_presearch_min_time_limit_s": ab.alns_presearch_min_time_limit_s,
            "alns_presearch_budget_guard_skipped_windows": (
                tel.alns_presearch_budget_guard_skipped_windows
            ),
            "alns_budget_mean_effective_max_iterations": _mean(
                tel.alns_effective_max_iterations_values, 2
            ),
            "alns_budget_mean_effective_max_destroy": _mean(
                tel.alns_effective_max_destroy_values, 2
            ),
            "alns_budget_mean_effective_repair_time_limit_s": _mean(
                tel.alns_effective_repair_time_limit_values, 4
            ),
        }

    def _meta_tail(
        self,
        temporal_stabilization: dict[str, int],
        notary_meta: dict[str, Any],
        scheduled: int,
        total: int,
    ) -> dict[str, Any]:
        st, tel, inner, budget = self.st, self.tel, self.cfg.inner, self.cfg.budget
        geo = self.cfg.geometry
        return {
            "boundary_reanchor_windows": tel.boundary_reanchor_windows,
            "boundary_reanchor_ops_total": tel.boundary_reanchor_ops_total,
            "boundary_reanchor_changed_ops_total": tel.boundary_reanchor_changed_ops_total,
            "random_seed_base": inner.random_seed_base,
            "hybrid_inner_routing_enabled": inner.hybrid_inner_routing_enabled,
            "hybrid_inner_solver": inner.hybrid_inner_solver_name,
            "hybrid_due_pressure_threshold": inner.hybrid_due_pressure_threshold,
            "hybrid_candidate_pressure_threshold": inner.hybrid_candidate_pressure_threshold,
            "hybrid_max_ops": inner.hybrid_max_ops,
            "hybrid_route_attempts": tel.hybrid_route_attempts,
            "hybrid_route_activations": tel.hybrid_route_activations,
            "hybrid_route_activation_rate": round(
                tel.hybrid_route_activations / max(1, tel.hybrid_route_attempts), 4
            )
            if tel.hybrid_route_attempts > 0
            else 0.0,
            "horizon_clipped_assignments": tel.horizon_clipped_assignments,
            "temporal_stabilization": temporal_stabilization,
            **notary_meta,
            "time_limit_reached": st.time_limit_reached,
            "wall_clock_path_dependent": bool(st.time_limit_reached),
            "determinism": budget.determinism,
            "determinism_violated": bool(st.time_limit_reached) and budget.determinism == "strict",
            "search_stop_reason": "wall_clock" if st.time_limit_reached else "completed",
            "time_limit_s": budget.time_limit_s,
            "window_time_limit_s": budget.window_time_limit_s,
            "coverage_reserve_s": budget.coverage_reserve_s,
            "coverage_deadline_s": budget.coverage_deadline_s,
            "coverage_time_reserve_fraction": budget.coverage_time_reserve_fraction,
            "fallback_repair_on_timeout": budget.fallback_repair_on_timeout,
            "fallback_repair_soft_budget_s": budget.fallback_repair_soft_budget_s,
            "coverage_horizon_extension_factor": geo.coverage_horizon_extension_factor,
            "window_bound_inner_horizon": geo.window_bound_inner_horizon,
            "window_horizon_slack_minutes": geo.window_horizon_slack_minutes,
            "planning_horizon_extended": self.planning_horizon_extended,
            "original_planning_horizon_end": self.original_horizon_end.isoformat(),
            "effective_planning_horizon_end": self.horizon_end.isoformat(),
            "original_horizon_minutes": self.original_horizon_minutes,
            "effective_horizon_minutes": self.horizon_minutes,
            "fallback_repair_attempted": st.fallback_repair_attempted,
            "fallback_repair_skipped": st.fallback_repair_skipped,
            "fallback_repair_time_limited": st.fallback_repair_time_limited,
            "ops_unscheduled": total - scheduled,
            "cross_window_variable_fixing_enabled": st.cross_window_variable_fixing_enabled,
            "cross_window_stable_ops_total": len(st.cross_window_stable_ops),
            "cross_window_stable_ops_count_per_window": [
                s.get("cross_window_stable_ops_count", 0) for s in st.inner_window_summaries
            ],
            "inner_window_summaries": st.inner_window_summaries,
        }


def _mean(values: list[int] | list[float], digits: int) -> float:
    return round(sum(values) / len(values), digits) if values else 0.0


def _mean_max(
    prefix: str, values: list[float], digits: int, *, mean_only: bool
) -> dict[str, float]:
    """``<prefix>_mean`` (and ``<prefix>_max``) with the historical rounding."""
    out = {f"{prefix}_mean": _mean(values, digits)}
    if not mean_only:
        out[f"{prefix}_max"] = round(max(values), digits) if values else 0.0
    return out
