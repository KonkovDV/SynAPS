"""LBBD Solver — Logic-Based Benders Decomposition for MO-FJSP-SDST-ARC.

Decomposes the scheduling problem into:
    Master Problem (HiGHS MIP): assigns operations to machines with relaxed capacity.
    Subproblems (CP-SAT per machine cluster): sequences operations with exact SDST + ARC.

Benders cuts tighten the master's capacity estimate iteratively until convergence.

Features:
    - Greedy ATCS warm-start: seeds initial upper bound from
      GreedyDispatch (toggle via use_greedy_warm_start).
    - Parallel subproblem execution via ProcessPoolExecutor for
      O(K) speedup (toggle via parallel_subproblems).
        - Benders cuts: full-assignment no-goods only (emitted for proven
            infeasible or optimality-status clusters). The capacity,
            setup_cost, machine_tsp, critical_path and load_balance cuts were
            removed in the 2026-07 S1/S2/S3 validity fixes (each could raise
            the master bound above the optimum).
"""

from __future__ import annotations

import math
import os
import time
import warnings
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import highspy
import numpy as np

from synaps.model import (
    Assignment,
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
    WorkCenter,
)
from synaps.solvers import BaseSolver
from synaps.solvers._lbbd_assembly import LaneGroupResolver, enforce_lane_gaps
from synaps.solvers._lbbd_cuts import (
    compute_assignment_setup_lb_total,
    compute_machine_transition_floor,
    compute_machine_tsp_lower_bound,
    compute_sequence_independent_setup_lower_bound,
    cut_kind_lb_contribution,
    cut_pool_fingerprint,
    reported_lower_bound,
)
from synaps.solvers.coverage_outcome import stamp_honest_coverage
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.timegrain import duration_minutes_for

if TYPE_CHECKING:
    from uuid import UUID


class LbbdSolver(BaseSolver):
    """Logic-Based Benders Decomposition solver.

    Iterates between a HiGHS master (assignment) and CP-SAT subproblems
    (per-machine-cluster sequencing) until the optimality gap closes or
    the iteration budget is exhausted.

    Budget contract (D3/D4): ``max_iterations`` is a ceiling and
    ``time_limit_s`` is a hard wall-clock deadline — whichever is hit first
    wins. The per-cluster CP-SAT budget is clamped to the remaining deadline
    before every cluster solve.
    """

    @property
    def name(self) -> str:
        return "lbbd"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        """Master/subproblem iterations under a hard wall-clock deadline (D3)."""
        return stamp_honest_coverage(problem, _LbbdRun(self.name, problem, kwargs).execute())


class _LbbdRun:
    """One LBBD solve: HiGHS master -> CP-SAT cluster subproblems -> no-goods."""

    def __init__(self, solver_name: str, problem: ScheduleProblem, kwargs: dict[str, Any]):
        self.solver_name = solver_name
        self.problem = problem
        self.t0 = time.monotonic()
        self.max_iterations = int(kwargs.get("max_iterations", 10))
        self.time_limit_s = int(kwargs.get("time_limit_s", 60))
        self.random_seed = int(kwargs.get("random_seed", 42))
        self.sub_time_limit_s = max(1, self.time_limit_s // max(self.max_iterations, 1))
        # D3: hard wall-clock deadline shared by all cluster solves.
        self.deadline = self.t0 + float(self.time_limit_s)
        self.gap_threshold = float(kwargs.get("gap_threshold", 0.01))
        self.setup_relaxation = bool(kwargs.get("setup_relaxation", True))
        self.use_greedy_warm_start = bool(kwargs.get("use_greedy_warm_start", True))
        self.parallel_subproblems = bool(kwargs.get("parallel_subproblems", True))
        self.num_workers = int(kwargs.get("num_workers", min(4, os.cpu_count() or 2)))
        # `enable_machine_tsp_cuts` is accepted for backward compatibility but
        # is a no-op since the 2026-07 S3 validity fix removed those cuts.
        _ = kwargs.get("enable_machine_tsp_cuts", True)
        self.wc_by_id = {wc.id: wc for wc in problem.work_centers}
        self.ops_by_id = {op.id: op for op in problem.operations}
        self.orders_by_id = {o.id: o for o in problem.orders}
        self.setup_lookup = {
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
            for entry in problem.setup_matrix
        }
        self.eligible_by_op: dict[UUID, list[UUID]] = {
            op.id: (
                op.eligible_wc_ids if op.eligible_wc_ids else [wc.id for wc in problem.work_centers]
            )
            for op in problem.operations
        }
        # Ops sharing aux resources are solved together on a machine cluster.
        self.aux_links = _build_aux_resource_links(problem)
        self.best_assignments: list[Assignment] = []
        self.best_objective = ObjectiveValues()
        self.best_ub = float("inf")
        self.lb = 0.0
        self.benders_cuts: list[_BendersCut] = []
        self.iteration_log: list[dict[str, Any]] = []
        self.prev_assignment_map: dict[UUID, UUID] | None = None
        self.master_warm_start_iterations = 0
        # R3: cut-pool dedup by (kind, payload, rhs-rounded) fingerprint.
        self.seen_cut_fingerprints: set[
            tuple[str, frozenset[UUID], frozenset[tuple[UUID, UUID]], float]
        ] = set()
        self.cuts_skipped_duplicate = 0
        # S2: cuts NOT emitted because the subproblem result was unproven.
        self.cuts_skipped_unproven_subproblem = 0
        # lb_evolution[N] is the master bound of iteration N; the delta seen in
        # iteration N is attributed to the cuts generated in iteration N-1.
        self.lb_evolution: list[float] = []
        self.ub_evolution: list[float] = []
        self.prev_master_bound = 0.0
        self.prev_iteration_cut_kinds: list[str] = []
        self.greedy_warm_start_used = False
        self.min_setup_by_wc: dict[UUID, float] = {}

    def _register_cut(self, cut: _BendersCut) -> bool:
        fp = cut_pool_fingerprint(cut)
        if fp in self.seen_cut_fingerprints:
            self.cuts_skipped_duplicate += 1
            return False
        self.seen_cut_fingerprints.add(fp)
        self.benders_cuts.append(cut)
        return True

    def _nogood(self, assignment_map: dict[UUID, UUID]) -> _BendersCut:
        return _BendersCut(
            assignment_map=dict(assignment_map), kind="nogood", rhs=0.0, bottleneck_ops=set()
        )

    def execute(self) -> ScheduleResult:
        if self.setup_relaxation:
            for work_center in self.problem.work_centers:
                floor = compute_machine_transition_floor(
                    self.problem, self.eligible_by_op, work_center.id, self.setup_lookup
                )
                if floor > 0:
                    self.min_setup_by_wc[work_center.id] = floor
        if self.use_greedy_warm_start:
            self._greedy_warm_start()
        for iteration in range(1, self.max_iterations + 1):
            if time.monotonic() - self.t0 >= self.time_limit_s:
                break
            outcome = self._iteration(iteration)
            if isinstance(outcome, ScheduleResult):
                return outcome
            if outcome == "stop":
                break
        return self._final_result()

    def _greedy_warm_start(self) -> None:
        warm_ub, warm_assignments, warm_objective, warm_map = _greedy_warm_start(
            self.problem, self.best_ub
        )
        if warm_map is not None:
            self.prev_assignment_map = warm_map
        if warm_assignments is not None and warm_ub is not None:
            self.best_ub = warm_ub
            self.ub_evolution.append(self.best_ub)
            self.best_assignments = warm_assignments
            self.best_objective = warm_objective  # type: ignore[assignment]
            self.greedy_warm_start_used = True

    def _iteration(self, iteration: int) -> ScheduleResult | str:
        """One master + subproblem round; returns a result, "stop" or "next"."""
        cuts_before = len(self.benders_cuts)
        attributed = list(self.prev_iteration_cut_kinds)
        if self.prev_assignment_map is not None:
            self.master_warm_start_iterations += 1
        master_result, master_proven_infeasible = _solve_master(
            self.problem,
            self.eligible_by_op,
            self.wc_by_id,
            self.benders_cuts,
            min_setup_by_wc=self.min_setup_by_wc,
            prev_solution=self.prev_assignment_map,
            master_time_limit_s=max(
                1.0, min(self.deadline - time.monotonic(), float(self.sub_time_limit_s) + 2.0)
            ),
        )
        if master_result is None:
            failed = _master_failed_result(
                self.solver_name,
                self.t0,
                iteration,
                master_proven_infeasible,
                bool(self.best_assignments),
            )
            return failed if failed is not None else "stop"
        assignment_map, master_bound = master_result
        lb_delta = master_bound - self.prev_master_bound
        self.lb_evolution.append(master_bound)
        self.lb = max(self.lb, master_bound)
        self.prev_assignment_map = assignment_map
        self.prev_master_bound = master_bound
        sub_assignments, sub_makespan, sub_optimal, sub_infeasible = _dispatch_subproblems(
            self.problem,
            assignment_map,
            self.aux_links,
            self.wc_by_id,
            self.ops_by_id,
            self.orders_by_id,
            self.sub_time_limit_s,
            self.random_seed,
            parallel_subproblems=self.parallel_subproblems,
            num_workers=self.num_workers,
            deadline=self.deadline,
        )
        entry: dict[str, Any] = {
            "iteration": iteration,
            "master_bound": master_bound,
            "sub_makespan": sub_makespan if sub_assignments is not None else None,
        }
        if sub_assignments is None:
            self._record_failed_subproblem(
                entry, assignment_map, lb_delta, attributed, sub_infeasible
            )
            self.prev_iteration_cut_kinds = [c.kind for c in self.benders_cuts[cuts_before:]]
            return "next"
        if self._record_feasible_subproblem(
            entry, sub_assignments, sub_makespan, lb_delta, attributed, sub_optimal
        ):
            self.prev_iteration_cut_kinds = []
            return "stop"
        # S2 (2026-07): the sound cut is a full-assignment no-good, emitted ONLY
        # when every cluster was proven OPTIMAL; excluded assignments have known
        # cost >= best_ub, unexcluded ones stay bounded by the relaxation. The
        # capacity / setup_cost / machine_tsp / load_balance / critical_path
        # cuts were removed as invalid master bounds (S1/S2/S3).
        if sub_optimal:
            self._register_cut(self._nogood(assignment_map))
        else:
            self.cuts_skipped_unproven_subproblem += 1
        self.prev_iteration_cut_kinds = [c.kind for c in self.benders_cuts[cuts_before:]]
        return "next"

    def _record_failed_subproblem(
        self,
        entry: dict[str, Any],
        assignment_map: dict[UUID, UUID],
        lb_delta: float,
        attributed: list[str],
        sub_infeasible: bool,
    ) -> None:
        if sub_infeasible:
            # Proven INFEASIBLE for this assignment: excluding it is sound.
            self._register_cut(self._nogood(assignment_map))
        else:
            # S2 gate: TIMEOUT/ERROR without a schedule proves nothing; a no-good
            # would exclude a possibly-optimal assignment.
            self.cuts_skipped_unproven_subproblem += 1
        entry.update(
            {
                "lb_delta": lb_delta,
                "cut_kinds_attributed": attributed,
                "sub_proven_optimal": False,
                "status": "sub_infeasible" if sub_infeasible else "sub_unproven_failure",
            }
        )
        self.iteration_log.append(entry)

    def _record_feasible_subproblem(
        self,
        entry: dict[str, Any],
        sub_assignments: list[Assignment],
        sub_makespan: float,
        lb_delta: float,
        attributed: list[str],
        sub_optimal: bool,
    ) -> bool:
        """Update the incumbent and the log; True when the gap has closed."""
        ub = sub_makespan
        if ub < self.best_ub:
            self.best_ub = ub
            self.ub_evolution.append(self.best_ub)
            self.best_assignments = sub_assignments
            self.best_objective = _compute_objective(
                self.problem,
                sub_assignments,
                sub_makespan,
                self.wc_by_id,
                self.ops_by_id,
                self.orders_by_id,
            )
        entry.update(
            {
                "gap": (ub - self.lb) / max(ub, 1e-9),
                "lb_delta": lb_delta,
                "cut_kinds_attributed": attributed,
                "sub_proven_optimal": sub_optimal,
                "status": "feasible",
            }
        )
        self.iteration_log.append(entry)
        return (self.best_ub - self.lb) / max(self.best_ub, 1e-9) < self.gap_threshold

    def _final_result(self) -> ScheduleResult:
        status = SolverStatus.FEASIBLE if self.best_assignments else SolverStatus.TIMEOUT
        # D2: fully deterministic assignment order (with the deterministic
        # cluster collection and strict CP-SAT, byte-identical across runs).
        best_assignments = sorted(
            self.best_assignments,
            key=lambda a: (str(a.work_center_id), a.start_time, str(a.operation_id)),
        )
        elapsed_ms = int((time.monotonic() - self.t0) * 1000)
        return ScheduleResult(
            solver_name=self.solver_name,
            status=status,
            assignments=best_assignments,
            objective=self.best_objective,
            duration_ms=elapsed_ms,
            random_seed=self.random_seed,
            metadata=self._final_metadata(best_assignments),
        )

    def _reported_lower_bound(self) -> tuple[float, bool]:
        """Cut-free master relaxation (N5: raw, never clamped to the incumbent).

        Cluster subproblems are re-assembled, so ``sub_makespan`` is an UPPER
        bound for its assignment: no-goods drive the search but must not
        tighten the reported bound (observed 92 vs optimum 90). The only valid
        bound is the first, cut-free master relaxation.
        """
        raw_relaxation = self.lb_evolution[0] if self.lb_evolution else 0.0
        reported_lb, violated = reported_lower_bound(raw_relaxation, self.best_ub)
        if violated:
            warnings.warn(
                f"LBBD lower-bound invariant violated: raw master relaxation "
                f"{raw_relaxation} exceeds incumbent {self.best_ub}; the relaxation "
                f"is not a valid lower bound.",
                stacklevel=6,  # the caller of LbbdSolver.solve
            )
        return reported_lb, violated

    def _final_metadata(self, best_assignments: list[Assignment]) -> dict[str, Any]:
        reported_lb, lb_invariant_violated = self._reported_lower_bound()
        cut_kinds: dict[str, int] = {}
        for cut in self.benders_cuts:
            cut_kinds[cut.kind] = cut_kinds.get(cut.kind, 0) + 1
        # N2: no cut ever generated -> the master never learned (degenerate run).
        benders_active = len(self.benders_cuts) > 0
        best_ub = self.best_ub
        return {
            "iterations": len(self.iteration_log),
            "lower_bound": reported_lb,
            "upper_bound": best_ub,
            "gap": (best_ub - reported_lb) / max(best_ub, 1e-9) if best_ub < float("inf") else None,
            "benders_active": benders_active,
            "quality_warning": None if benders_active else "lbbd_no_cuts_degenerate",
            "lower_bound_invariant_violated": lb_invariant_violated,
            "lower_bound_method": "master_relaxation_benders",
            "lower_bound_components": {
                "master_relaxation_lb": reported_lb,
                "assignment_setup_lb": compute_assignment_setup_lb_total(
                    self.problem, best_assignments
                ),
            },
            "iteration_log": self.iteration_log,
            "lb_evolution": self.lb_evolution,
            "ub_evolution": self.ub_evolution,
            "cut_kind_lb_contribution": cut_kind_lb_contribution(self.iteration_log),
            "gap_threshold": self.gap_threshold,
            "setup_relaxation": self.setup_relaxation,
            "master_warm_start_iterations": self.master_warm_start_iterations,
            "greedy_warm_start_used": self.greedy_warm_start_used,
            "parallel_subproblems": self.parallel_subproblems,
            "cut_pool": {
                "size": len(self.benders_cuts),
                "kinds": cut_kinds,
                "skipped_duplicate": self.cuts_skipped_duplicate,
                "skipped_unproven_subproblem": self.cuts_skipped_unproven_subproblem,
            },
        }


class _BendersCut:
    """Represents a Benders cut to add to the master problem."""

    __slots__ = ("assignment_map", "bottleneck_ops", "kind", "rhs")

    def __init__(
        self,
        assignment_map: dict[UUID, UUID],
        kind: str,
        rhs: float,
        bottleneck_ops: set[UUID],
    ) -> None:
        self.assignment_map = assignment_map
        self.kind = kind
        self.rhs = rhs
        self.bottleneck_ops = bottleneck_ops


# R2 (2026-05-03): the three sequence-aware lower-bound helpers were moved to
# `synaps.solvers._lbbd_cuts` so that LBBD and LBBD-HD share a single source
# of truth. The aliases below preserve the historical private names that
# callers and tests already import from this module.


def _deprecated_alias(name: str, fn):  # type: ignore[no-untyped-def]
    """Emit DeprecationWarning on first access to deprecated alias."""

    def wrapper(*args, **kwargs):  # type: ignore[no-untyped-def]
        warnings.warn(
            f"{name} is deprecated; import from synaps.solvers._lbbd_cuts directly",
            DeprecationWarning,
            stacklevel=2,
        )
        return fn(*args, **kwargs)

    return wrapper


_compute_machine_transition_floor = _deprecated_alias(
    "_compute_machine_transition_floor", compute_machine_transition_floor
)
_compute_sequence_independent_setup_lower_bound = _deprecated_alias(
    "_compute_sequence_independent_setup_lower_bound",
    compute_sequence_independent_setup_lower_bound,
)
_compute_machine_tsp_lower_bound = _deprecated_alias(
    "_compute_machine_tsp_lower_bound", compute_machine_tsp_lower_bound
)


def _solve_master(
    problem: ScheduleProblem,
    eligible_by_op: dict[UUID, list[UUID]],
    wc_by_id: dict[UUID, WorkCenter],
    cuts: list[_BendersCut],
    min_setup_by_wc: dict[UUID, float] | None = None,
    prev_solution: dict[UUID, UUID] | None = None,
    master_time_limit_s: float | None = None,
) -> tuple[tuple[dict[UUID, UUID], float] | None, bool]:
    """Solve the assignment master problem via HiGHS MIP.

    Decision variables:
        y[i, k] ∈ {0, 1}  — operation i assigned to work center k
        C_max ≥ 0          — relaxed makespan lower bound

    Constraints:
        ∑_k y[i,k] = 1                    ∀ i ∈ ops      (unique assignment)
        ∑_i P[i,k] · y[i,k] ≤ C_max      ∀ k ∈ machines  (relaxed capacity)
        Benders cuts from previous iterations

    Objective: min C_max

    Returns ``(solution, proven_infeasible)`` where ``solution`` is
    ``(assignment_map, master_bound)`` or None. F12 (audit v4): a None with
    ``proven_infeasible=False`` means the master was INCONCLUSIVE (time limit
    with no incumbent, solver interruption) — the caller must not surface it
    as SolverStatus.INFEASIBLE. Only HiGHS' ``kInfeasible`` model status is a
    proof of infeasibility.
    """
    h = highspy.Highs()
    h.silent()
    # D3: bound the master MILP by the remaining wall budget. An unbounded
    # HiGHS run on a large assignment problem (thousands of binary y vars)
    # could exceed the solver's total time_limit_s on its own; a HiGHS time
    # limit returns the best incumbent (or the LP relaxation bound) instead of
    # blocking. Floored at 1s so the master still makes progress.
    if master_time_limit_s is not None:
        h.setOptionValue("time_limit", max(1.0, float(master_time_limit_s)))

    # Index maps for variables
    var_index: dict[tuple[UUID, UUID], int] = {}
    col_idx = 0

    # Create binary y[i,k] variables
    for op in problem.operations:
        for wc_id in eligible_by_op[op.id]:
            var_index[(op.id, wc_id)] = col_idx
            col_idx += 1

    n_y = col_idx
    cmax_idx = col_idx  # C_max variable
    n_vars = col_idx + 1

    # Add all columns: y variables are binary [0,1], C_max is continuous [0, inf)
    costs = [0.0] * n_y + [1.0]  # minimise C_max
    lower = [0.0] * n_vars
    upper = [1.0] * n_y + [highspy.kHighsInf]

    h.addVars(n_vars, np.array(lower), np.array(upper))
    h.changeColsCost(n_vars, np.arange(n_vars, dtype=np.int32), np.array(costs))

    # Set integrality for binary vars
    col_indices = np.arange(n_y, dtype=np.int32)
    int_types = np.array([highspy.HighsVarType.kInteger] * n_y)
    h.changeColsIntegrality(n_y, col_indices, int_types)

    # Constraint 1: unique assignment — ∑_k y[i,k] = 1 for each operation
    for op in problem.operations:
        unique_indices = [var_index[(op.id, wc_id)] for wc_id in eligible_by_op[op.id]]
        unique_coeffs = [1.0] * len(unique_indices)
        h.addRow(
            1.0,
            1.0,
            len(unique_indices),
            np.array(unique_indices, dtype=np.int32),
            np.array(unique_coeffs),
        )

    # Constraint 2: relaxed capacity — ∑_i P[i,k] · y[i,k] ≤ C_max for each machine
    for wc in problem.work_centers:
        capacity_indices: list[int] = []
        capacity_coeffs: list[float] = []
        capacity_upper_bound = 0.0
        for op in problem.operations:
            key = (op.id, wc.id)
            if key in var_index:
                # CP-SAT duration semantics (max(1, round(p))), divided by the
                # number of parallel lanes: a machine with max_parallel lanes
                # finishes load L in L / max_parallel, so the relaxation
                # `Sum p_i y_i / lanes <= C_max` stays a valid lower bound
                # (matching average_capacity_lb in lower_bounds.py). Without the
                # division the bound over-claims on max_parallel > 1 machines.
                lanes = float(max(1, wc.max_parallel))
                duration = float(duration_minutes_for(op, wc)) / lanes
                capacity_indices.append(var_index[key])
                capacity_coeffs.append(duration)
        if not capacity_indices:
            continue
        # The min-setup transition floor assumes n_k - 1 sequential transitions
        # on a single lane; with parallel lanes that count no longer holds, so
        # only apply it to single-lane machines (keeps the bound valid).
        if min_setup_by_wc and wc.id in min_setup_by_wc and wc.max_parallel <= 1:
            min_setup = min_setup_by_wc[wc.id]
            if min_setup > 0:
                capacity_coeffs = [coefficient + min_setup for coefficient in capacity_coeffs]
                capacity_upper_bound = min_setup
        # ∑ P·y - C_max ≤ 0
        capacity_indices.append(cmax_idx)
        capacity_coeffs.append(-1.0)
        h.addRow(
            -highspy.kHighsInf,
            capacity_upper_bound,
            len(capacity_indices),
            np.array(capacity_indices, dtype=np.int32),
            np.array(capacity_coeffs),
        )

    # Constraint 3: Benders cuts from previous iterations
    _add_benders_cut_rows(h, cuts, var_index, cmax_idx)

    # Solve
    h.changeObjectiveSense(highspy.ObjSense.kMinimize)
    if prev_solution is not None and hasattr(h, "setSolution"):
        hint_values = [0.0] * n_vars
        for op in problem.operations:
            previous_wc = prev_solution.get(op.id)
            for wc_id in eligible_by_op[op.id]:
                key = (op.id, wc_id)
                if key in var_index:
                    hint_values[var_index[key]] = 1.0 if wc_id == previous_wc else 0.0
        hint_values[cmax_idx] = float(
            int(
                (problem.planning_horizon_end - problem.planning_horizon_start).total_seconds() / 60
            )
        )
        h.setSolution(n_vars, np.arange(n_vars, dtype=np.int32), np.array(hint_values))
    h.run()

    status = h.getInfoValue("primal_solution_status")[1]
    if status != 2:  # 2 = feasible
        # F12 (audit v4): only HiGHS kInfeasible is a PROOF; a time-limited
        # master without an incumbent is inconclusive and must not be reported
        # as SolverStatus.INFEASIBLE upstream.
        proven_infeasible = h.getModelStatus() == highspy.HighsModelStatus.kInfeasible
        return None, proven_infeasible

    solution = h.getSolution()
    col_values = solution.col_value

    # Extract assignment: for each op, pick the machine with y closest to 1
    assignment_map: dict[UUID, UUID] = {}
    for op in problem.operations:
        best_val = -1.0
        best_wc: UUID | None = None
        for wc_id in eligible_by_op[op.id]:
            key = (op.id, wc_id)
            val = col_values[var_index[key]]
            if val > best_val:
                best_val = val
                best_wc = wc_id
        if best_wc is not None:
            assignment_map[op.id] = best_wc

    master_bound = col_values[cmax_idx]
    # D3 validity: when the master is time-limited it may return a FEASIBLE but
    # non-optimal incumbent, whose C_max is an UPPER bound on the master
    # optimum, not a valid lower bound. Use the proven dual bound for the
    # reported relaxation LB (it equals the primal at optimality) so the S1/S2/
    # S3 lower-bound-validity invariant is preserved even on time-limited runs.
    try:
        dual_bound = float(h.getInfoValue("mip_dual_bound")[1])
    except (IndexError, TypeError, ValueError):
        dual_bound = master_bound
    if math.isfinite(dual_bound):
        master_bound = min(master_bound, dual_bound)
    return (assignment_map, master_bound), False


# ---------------------------------------------------------------------------
# Subproblems (CP-SAT per machine cluster)
# ---------------------------------------------------------------------------


def _build_aux_resource_links(problem: ScheduleProblem) -> dict[UUID, set[UUID]]:
    """Build mapping: operation_id → set of other operation_ids sharing aux resources.

    Operations linked by shared auxiliary resources should be in the same
    subproblem cluster to maintain feasibility.
    """
    resource_to_ops: dict[UUID, set[UUID]] = defaultdict(set)
    for req in problem.aux_requirements:
        resource_to_ops[req.aux_resource_id].add(req.operation_id)

    links: dict[UUID, set[UUID]] = defaultdict(set)
    for _resource_id, op_set in resource_to_ops.items():
        for op_id in op_set:
            links[op_id].update(op_set - {op_id})
    return dict(links)


def _cluster_machines(
    assignment_map: dict[UUID, UUID],
    aux_links: dict[UUID, set[UUID]],
) -> list[set[UUID]]:
    """Group machines into clusters where linked ops must be co-scheduled.

    Uses union-find to merge machines that share operations linked by
    auxiliary resources.
    """
    # Map each machine to itself initially
    parent: dict[UUID, UUID] = {}
    op_to_machine = dict(assignment_map.items())

    def find(x: UUID) -> UUID:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: UUID, b: UUID) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    all_machines = set(assignment_map.values())
    for m in all_machines:
        parent[m] = m

    # Merge machines that have ops linked by shared aux resources
    for op_id, linked_ops in aux_links.items():
        if op_id not in op_to_machine:
            continue
        m1 = op_to_machine[op_id]
        for linked_op_id in linked_ops:
            if linked_op_id not in op_to_machine:
                continue
            m2 = op_to_machine[linked_op_id]
            if m1 != m2:
                union(m1, m2)

    # Group machines by cluster root
    clusters: dict[UUID, set[UUID]] = defaultdict(set)
    for m in all_machines:
        clusters[find(m)].add(m)

    return list(clusters.values())


def _solve_subproblems(
    problem: ScheduleProblem,
    assignment_map: dict[UUID, UUID],
    aux_links: dict[UUID, set[UUID]],
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    orders_by_id: dict[UUID, Order],
    sub_time_limit_s: int,
    random_seed: int,
    *,
    deadline: float | None = None,
) -> tuple[list[Assignment] | None, float, bool, bool]:
    """Solve CP-SAT subproblems for each machine cluster.

    Returns ``(assignments, makespan, proven_optimal, infeasible_proven)``:

    * ``assignments`` is None when no complete schedule was obtained;
    * ``proven_optimal`` is True only when EVERY cluster returned OPTIMAL —
      the S2 gate: optimality/no-good cuts derived from non-proven cluster
      values are unsound (a TIMEOUT makespan is an upper bound, not a
      certificate);
    * ``infeasible_proven`` is True only when a cluster returned a proven
      INFEASIBLE — the only case where a feasibility no-good may be emitted
      (TIMEOUT/ERROR without assignments proves nothing).

    D3: when ``deadline`` (a ``time.monotonic()`` timestamp) is given, the
    per-cluster budget is clamped to the remaining wall-clock budget and no
    new cluster is started past the deadline — previously each cluster spent
    the full ``sub_time_limit_s``, overshooting the solver budget by the
    number of clusters.
    """
    clusters = _cluster_machines(assignment_map, aux_links)

    all_assignments: list[Assignment] = []
    overall_makespan = 0.0
    horizon_start = problem.planning_horizon_start
    all_proven_optimal = True

    for cluster_wcs in clusters:
        # Collect operations assigned to this cluster
        cluster_ops = [
            ops_by_id[op_id]
            for op_id, wc_id in assignment_map.items()
            if wc_id in cluster_wcs and op_id in ops_by_id
        ]
        if not cluster_ops:
            continue

        # Also include predecessor ops that might be in other clusters
        # (for precedence constraint correctness in the subproblem).
        cluster_op_ids = {op.id for op in cluster_ops}

        # Build reduced ScheduleProblem for this cluster
        sub_problem = _build_subproblem(
            problem,
            cluster_ops,
            cluster_wcs,
            cluster_op_ids,
            assignment_map,
            wc_by_id,
            ops_by_id,
            orders_by_id,
        )

        # Solve with CP-SAT
        # D3: clamp the cluster budget to the remaining wall-clock budget.
        cluster_limit_s = sub_time_limit_s
        if deadline is not None:
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                # Deadline hit — incomplete, proves nothing (no cut).
                return None, 0.0, False, False
            cluster_limit_s = max(1, min(sub_time_limit_s, int(remaining_s)))
        cpsat = CpSatSolver()
        result = cpsat.solve(
            sub_problem,
            time_limit_s=cluster_limit_s,
            random_seed=random_seed,
            num_workers=4,
        )

        if result.status == SolverStatus.INFEASIBLE:
            return None, 0.0, False, True
        if result.status == SolverStatus.ERROR:
            return None, 0.0, False, False

        if result.status == SolverStatus.TIMEOUT and not result.assignments:
            return None, 0.0, False, False

        if result.status is not SolverStatus.OPTIMAL:
            all_proven_optimal = False

        # Only keep assignments for ops that belong to this cluster
        # (external predecessor ops may also have been solved but are
        # owned by their own cluster).
        cluster_assignments = [a for a in result.assignments if a.operation_id in cluster_op_ids]
        all_assignments.extend(cluster_assignments)

        # Track cluster makespan (only cluster-owned assignments, not
        # external predecessors that belong to another cluster).
        if cluster_assignments:
            cluster_makespan = max(
                (a.end_time - horizon_start).total_seconds() / 60.0 for a in cluster_assignments
            )
            overall_makespan = max(overall_makespan, cluster_makespan)

    # Check completeness — every operation must be assigned
    assigned_ops = {a.operation_id for a in all_assignments}
    all_ops = {op.id for op in problem.operations}
    if assigned_ops != all_ops:
        return None, 0.0, False, False

    all_assignments, overall_makespan, horizon_ok = _post_assemble_assignments(
        problem,
        all_assignments,
        ops_by_id,
    )
    if not horizon_ok:
        # F3-followup: post-assembly re-enforcement pushed work past the
        # horizon — the merged schedule is physically invalid for this master
        # assignment. Not a PROVEN infeasibility (a different merge could
        # succeed), so no cut; treat as an unproven subproblem failure (S2).
        return None, 0.0, False, False

    return all_assignments, overall_makespan, all_proven_optimal, False


def _copy_op_for_cluster(
    op: Operation,
    *,
    eligible: list[UUID],
    all_op_ids: set[UUID],
) -> Operation:
    """Keep per-op windows and duration overrides valid on the cluster WC set."""
    allowed = set(eligible)
    return op.model_copy(
        update={
            "eligible_wc_ids": eligible,
            "predecessor_op_id": (
                op.predecessor_op_id if op.predecessor_op_id in all_op_ids else None
            ),
            "machine_duration_overrides": {
                wc_id: minutes
                for wc_id, minutes in op.machine_duration_overrides.items()
                if wc_id in allowed
            },
        }
    )


def _build_subproblem(
    problem: ScheduleProblem,
    cluster_ops: list[Operation],
    cluster_wcs: set[UUID],
    cluster_op_ids: set[UUID],
    assignment_map: dict[UUID, UUID],
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    orders_by_id: dict[UUID, Order],
) -> ScheduleProblem:
    """Build a reduced ScheduleProblem for a machine cluster.

    The subproblem contains:
    - Only operations assigned to this cluster
    - Only work centers in this cluster
    - Relevant setup entries, states, orders, and aux resources
    - Predecessor operations are included so precedence constraints work
    """
    # Collect all operations: cluster ops + their full predecessor chain
    # so external predecessors keep valid precedence constraints.
    all_op_ids = set(cluster_op_ids)
    pending_predecessors = [
        op.predecessor_op_id for op in cluster_ops if op.predecessor_op_id is not None
    ]
    while pending_predecessors:
        predecessor_id = pending_predecessors.pop()
        if predecessor_id in all_op_ids:
            continue
        all_op_ids.add(predecessor_id)
        predecessor = ops_by_id.get(predecessor_id)
        if predecessor is not None and predecessor.predecessor_op_id is not None:
            pending_predecessors.append(predecessor.predecessor_op_id)

    # If predecessor is outside this cluster, we still need it in the subproblem
    # but restrict it to its assigned machine only
    sub_operations: list[Operation] = []
    for op_id in all_op_ids:
        op = ops_by_id.get(op_id)
        if op is None:
            continue
        if op_id in cluster_op_ids:
            # Restrict to assigned machine(s) within cluster
            assigned_wc = assignment_map.get(op_id)
            eligible = (
                [assigned_wc] if assigned_wc and assigned_wc in cluster_wcs else list(cluster_wcs)
            )
            sub_operations.append(
                _copy_op_for_cluster(op, eligible=eligible, all_op_ids=all_op_ids)
            )
        else:
            # External predecessor — restrict to its assigned machine
            assigned_wc = assignment_map.get(op_id)
            if assigned_wc is None:
                continue
            # Add the assigned machine to cluster_wcs temporarily
            eligible = [assigned_wc]
            sub_operations.append(
                _copy_op_for_cluster(op, eligible=eligible, all_op_ids=all_op_ids)
            )

    # Collect required entities
    needed_state_ids = {op.state_id for op in sub_operations}
    needed_order_ids = {op.order_id for op in sub_operations}
    needed_wc_ids = set(cluster_wcs)
    # Also add WCs for external predecessors
    for op in sub_operations:
        for wc_id in op.eligible_wc_ids:
            needed_wc_ids.add(wc_id)

    sub_states = [s for s in problem.states if s.id in needed_state_ids]
    sub_orders = [o for o in problem.orders if o.id in needed_order_ids]
    sub_wcs = [wc for wc in problem.work_centers if wc.id in needed_wc_ids]

    sub_setup = [
        entry
        for entry in problem.setup_matrix
        if entry.work_center_id in needed_wc_ids
        and entry.from_state_id in needed_state_ids
        and entry.to_state_id in needed_state_ids
    ]

    sub_op_ids = {op.id for op in sub_operations}
    sub_aux_reqs = [req for req in problem.aux_requirements if req.operation_id in sub_op_ids]
    needed_aux_ids = {req.aux_resource_id for req in sub_aux_reqs}
    sub_aux_resources = [r for r in problem.auxiliary_resources if r.id in needed_aux_ids]

    return ScheduleProblem(
        states=sub_states,
        orders=sub_orders,
        operations=sub_operations,
        work_centers=sub_wcs,
        setup_matrix=sub_setup,
        auxiliary_resources=sub_aux_resources,
        aux_requirements=sub_aux_reqs,
        planning_horizon_start=problem.planning_horizon_start,
        planning_horizon_end=problem.planning_horizon_end,
    )


# ---------------------------------------------------------------------------
# Objective computation
# ---------------------------------------------------------------------------


def _compute_objective(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    makespan: float,
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    orders_by_id: dict[UUID, Order],
) -> ObjectiveValues:
    """Canonical objective for a merged LBBD incumbent (F3/F4, audit v4).

    Delegates to ``synaps.objective.evaluate`` — the single definition (P0-6).
    Pre-v4 this re-derived the vector inline: it grouped by MACHINE (phantom
    cross-lane setups on parallel work centers, F3), understated tardiness for
    unscheduled orders (F10), and left ``weighted_sum`` at 0.0 (F4). The
    ``makespan`` argument is retained for signature compatibility; the
    canonical evaluator recomputes it from the assignments.
    """
    del makespan, wc_by_id, ops_by_id, orders_by_id  # canonical path recomputes
    from synaps.objective import evaluate

    return evaluate(problem, list(assignments))


# ---------------------------------------------------------------------------
# Parallel subproblem execution (ProcessPoolExecutor)
# ---------------------------------------------------------------------------


def _solve_single_cluster_worker(
    problem_dict: dict[str, Any],
    cluster_wc_ids: list[str],
    assignment_items: list[tuple[str, str]],
    sub_time_limit_s: int,
    random_seed: int,
) -> dict[str, Any] | None:
    """Solve one cluster's CP-SAT subproblem in a worker process.

    Accepts JSON-serializable arguments to work with ProcessPoolExecutor.
    Returns a dict with 'assignments' (list of dicts) and 'makespan' (float),
    or None if the subproblem is infeasible.
    """
    from uuid import UUID

    problem = ScheduleProblem.model_validate(problem_dict)
    cluster_wcs = {UUID(w) for w in cluster_wc_ids}
    assignment_map = {UUID(k): UUID(v) for k, v in assignment_items}

    wc_by_id = {wc.id: wc for wc in problem.work_centers}
    ops_by_id = {op.id: op for op in problem.operations}
    orders_by_id = {o.id: o for o in problem.orders}

    cluster_op_ids = {op_id for op_id, wc_id in assignment_map.items() if wc_id in cluster_wcs}
    cluster_ops = [ops_by_id[oid] for oid in cluster_op_ids if oid in ops_by_id]
    if not cluster_ops:
        return {"assignments": [], "makespan": 0.0, "proven_optimal": True}

    sub_problem = _build_subproblem(
        problem,
        cluster_ops,
        cluster_wcs,
        cluster_op_ids,
        assignment_map,
        wc_by_id,
        ops_by_id,
        orders_by_id,
    )

    cpsat = CpSatSolver()
    result = cpsat.solve(
        sub_problem,
        time_limit_s=sub_time_limit_s,
        random_seed=random_seed,
        num_workers=4,
    )

    if result.status == SolverStatus.INFEASIBLE:
        return {"failed": True, "infeasible_proven": True}
    if result.status == SolverStatus.ERROR:
        return {"failed": True, "infeasible_proven": False}
    if result.status == SolverStatus.TIMEOUT and not result.assignments:
        return {"failed": True, "infeasible_proven": False}

    cluster_assignments = [a for a in result.assignments if a.operation_id in cluster_op_ids]
    horizon_start = problem.planning_horizon_start
    cluster_makespan = (
        max((a.end_time - horizon_start).total_seconds() / 60.0 for a in cluster_assignments)
        if cluster_assignments
        else 0.0
    )

    return {
        "assignments": [a.model_dump(mode="json") for a in cluster_assignments],
        "makespan": cluster_makespan,
        "proven_optimal": result.status is SolverStatus.OPTIMAL,
    }


def _solve_subproblems_parallel(
    problem: ScheduleProblem,
    assignment_map: dict[UUID, UUID],
    clusters: list[set[UUID]],
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    orders_by_id: dict[UUID, Order],
    sub_time_limit_s: int,
    random_seed: int,
    *,
    num_workers: int = 4,
    deadline: float | None = None,
) -> tuple[list[Assignment] | None, float, bool, bool]:
    """Solve CP-SAT subproblems in parallel via ProcessPoolExecutor.

    Returns the same 4-tuple contract as :func:`_solve_subproblems`:
    ``(assignments, makespan, proven_optimal, infeasible_proven)``.

    Provides O(K) speedup proportional to the number of machine clusters K,
    removing the GIL bottleneck from the sequential Benders loop.
    Falls back to sequential for ≤3 clusters to avoid multiprocessing overhead.

    D3: the shared per-cluster budget is clamped to the remaining wall-clock
    budget at submission time; with all clusters running concurrently this
    bounds the wall overshoot to a single clamped cluster budget.
    """
    if deadline is not None:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            return None, 0.0, False, False
        sub_time_limit_s = max(1, min(sub_time_limit_s, int(remaining_s)))
    problem_dict = problem.model_dump(mode="json")
    assignment_items = [(str(k), str(v)) for k, v in assignment_map.items()]

    all_assignments: list[Assignment] = []
    overall_makespan = 0.0
    all_proven_optimal = True
    effective_workers = min(num_workers, len(clusters))

    with ProcessPoolExecutor(max_workers=effective_workers) as pool:
        futures = {}
        for cluster_index, cluster_wcs in enumerate(clusters):
            wc_list = [str(w) for w in cluster_wcs]
            future = pool.submit(
                _solve_single_cluster_worker,
                problem_dict,
                wc_list,
                assignment_items,
                sub_time_limit_s,
                random_seed,
            )
            futures[future] = cluster_index

        # D2: buffer results by cluster index so the merged assignment order is
        # independent of completion order (as_completed is non-deterministic).
        results_by_index: dict[int, dict[str, Any]] = {}
        for future in as_completed(futures):
            cluster_index = futures[future]
            result = future.result()
            if result is None or result.get("failed"):
                infeasible_proven = bool(result.get("infeasible_proven")) if result else False
                return None, 0.0, False, infeasible_proven
            results_by_index[cluster_index] = result

    for cluster_index in sorted(results_by_index):
        result = results_by_index[cluster_index]
        if not result.get("proven_optimal", False):
            all_proven_optimal = False
        for a_dict in result["assignments"]:
            all_assignments.append(Assignment.model_validate(a_dict))
        overall_makespan = max(overall_makespan, result["makespan"])

    # Completeness check
    assigned_ops = {a.operation_id for a in all_assignments}
    all_ops = {op.id for op in problem.operations}
    if assigned_ops != all_ops:
        return None, 0.0, False, False

    all_assignments, overall_makespan, horizon_ok = _post_assemble_assignments(
        problem,
        all_assignments,
        ops_by_id,
    )
    if not horizon_ok:
        # Post-assembly horizon overflow: unproven failure, no cut (S2).
        return None, 0.0, False, False

    return all_assignments, overall_makespan, all_proven_optimal, False


def _greedy_warm_start(
    problem: ScheduleProblem, best_ub: float
) -> tuple[
    float | None,
    list[Assignment] | None,
    ObjectiveValues | None,
    dict[UUID, UUID] | None,
]:
    """GreedyDispatch seed: (ub, assignments, objective, master_map).

    ``master_map`` is returned whenever greedy finds a feasible schedule (even
    if it does not improve ``best_ub``), so the master can warm-start from it.
    Improved incumbent fields are non-None only when greedy beats ``best_ub``.
    """
    from synaps.solvers.greedy_dispatch import GreedyDispatch

    greedy_result = GreedyDispatch().solve(problem)
    if greedy_result.status != SolverStatus.FEASIBLE or not greedy_result.assignments:
        return None, None, None, None
    warm_map = {a.operation_id: a.work_center_id for a in greedy_result.assignments}
    greedy_makespan = greedy_result.objective.makespan_minutes
    if greedy_makespan < best_ub:
        return (
            greedy_makespan,
            list(greedy_result.assignments),
            greedy_result.objective,
            warm_map,
        )
    return None, None, None, warm_map


def _dispatch_subproblems(
    problem: ScheduleProblem,
    assignment_map: dict[UUID, UUID],
    aux_links: Any,
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    orders_by_id: dict[UUID, Order],
    sub_time_limit_s: int,
    random_seed: int,
    *,
    parallel_subproblems: bool,
    num_workers: int,
    deadline: float,
) -> tuple[list[Assignment] | None, float, bool, bool]:
    """Route to serial or parallel cluster subproblem solves."""
    clusters = _cluster_machines(assignment_map, aux_links)
    if parallel_subproblems and len(clusters) > 3:
        return _solve_subproblems_parallel(
            problem,
            assignment_map,
            clusters,
            wc_by_id,
            ops_by_id,
            orders_by_id,
            sub_time_limit_s,
            random_seed,
            num_workers=num_workers,
            deadline=deadline,
        )
    return _solve_subproblems(
        problem,
        assignment_map,
        aux_links,
        wc_by_id,
        ops_by_id,
        orders_by_id,
        sub_time_limit_s,
        random_seed,
        deadline=deadline,
    )


def _master_failed_result(
    solver_name: str,
    t0: float,
    iteration: int,
    proven_infeasible: bool,
    has_incumbent: bool,
) -> ScheduleResult | None:
    """Result to return on a failed master, or None to break with the incumbent.

    With the S2 no-good cuts, a PROVEN-infeasible master usually means the
    assignment space is EXHAUSTED (every assignment has been explored and
    excluded), not that the problem is infeasible. If a feasible schedule was
    already found, the search is complete over the explored space — return the
    best incumbent rather than a spurious INFEASIBLE.
    """
    if has_incumbent:
        return None
    if not proven_infeasible:
        # F12 (audit v4): a time-limited master that found no incumbent is
        # INCONCLUSIVE. Reporting INFEASIBLE here was spurious — the
        # assignment space was not exhausted, the budget was.
        return ScheduleResult(
            solver_name=solver_name,
            status=SolverStatus.TIMEOUT,
            duration_ms=int((time.monotonic() - t0) * 1000),
            metadata={
                "iterations": iteration,
                "reason": "master_no_incumbent_within_budget",
            },
        )
    return ScheduleResult(
        solver_name=solver_name,
        status=SolverStatus.INFEASIBLE,
        duration_ms=int((time.monotonic() - t0) * 1000),
        metadata={"iterations": iteration, "reason": "master_infeasible"},
    )


def _add_benders_cut_rows(
    h: Any,
    cuts: list[Any],
    var_index: dict[tuple[UUID, UUID], int],
    cmax_idx: int,
) -> None:
    """Append all Benders-cut rows to the HiGHS master model."""
    for cut in cuts:
        if cut.kind == "nogood":
            # Exclude exact assignment: ∑ y[i, assignment[i]] ≤ |ops| - 1
            indices = []
            coeffs = []
            for op_id, wc_id in cut.assignment_map.items():
                key = (op_id, wc_id)
                if key in var_index:
                    indices.append(var_index[key])
                    coeffs.append(1.0)
            if not indices:
                raise ValueError(
                    "LBBD nogood cut has no bindable variables; refusing silent skip "
                    "(Wave 14 / H14-nogood)."
                )
            h.addRow(
                -highspy.kHighsInf,
                len(indices) - 1.0,
                len(indices),
                np.array(indices, dtype=np.int32),
                np.array(coeffs),
            )
        elif cut.kind in ("setup_cost", "machine_tsp"):
            # Wave 11 / M1 + KI-S3: generation is retired; refuse to apply if injected.
            raise ValueError(
                f"LBBD cut kind {cut.kind!r} is permanently retired (KI-S3); "
                "refusing to apply sentinel optimality cuts"
            )
        else:
            raise ValueError(
                f"Unknown LBBD cut kind {cut.kind!r}; refusing silent no-op (Wave 12 / M12-1)."
            )


def _post_assemble_assignments(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Operation],
) -> tuple[list[Assignment], float, bool]:
    """Enforce cross-cluster precedence and setup gaps after subproblem merge.

    F3 (audit v4): parallel machines are grouped PER LANE, not serialized into
    a single sequence. Pre-v4 the gap walk treated a max_parallel > 1
    machine as one serial resource, which degraded quality, charged phantom
    cross-lane setups, and could report makespans for illegal schedules.

    Returns (assignments, makespan, horizon_ok). horizon_ok is False when the
    re-enforcement pushed any assignment past planning_horizon_end.
    """
    setup_lookup = {
        (e.work_center_id, e.from_state_id, e.to_state_id): timedelta(minutes=e.setup_minutes)
        for e in problem.setup_matrix
    }
    resolver = LaneGroupResolver(
        wc_by_id={wc.id: wc for wc in problem.work_centers},
        ops_by_id=ops_by_id,
        setup_minutes_lookup={
            key: value.total_seconds() / 60.0 for key, value in setup_lookup.items()
        },
    )
    assignment_by_op = {assignment.operation_id: assignment for assignment in assignments}

    changed = True
    max_passes = len(problem.operations) * 3  # prevent infinite loops
    passes = 0
    while changed and passes < max_passes:
        changed = False
        passes += 1

        for op in problem.operations:
            if op.predecessor_op_id is None:
                continue
            pred_assignment = assignment_by_op.get(op.predecessor_op_id)
            cur_assignment = assignment_by_op.get(op.id)
            if pred_assignment is None or cur_assignment is None:
                continue
            if cur_assignment.start_time < pred_assignment.end_time:
                shift = pred_assignment.end_time - cur_assignment.start_time
                cur_assignment.start_time = cur_assignment.start_time + shift
                cur_assignment.end_time = cur_assignment.end_time + shift
                changed = True

        by_machine: dict[UUID, list[Assignment]] = defaultdict(list)
        for assignment in assignments:
            by_machine[assignment.work_center_id].append(assignment)

        for work_center_id, machine_assignments in by_machine.items():
            for lane in resolver.groups(work_center_id, machine_assignments):
                if enforce_lane_gaps(work_center_id, lane, ops_by_id, setup_lookup):
                    changed = True

    horizon_start = problem.planning_horizon_start
    horizon_end = problem.planning_horizon_end
    makespan = (
        max((a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments)
        if assignments
        else 0.0
    )
    horizon_ok = all(a.end_time <= horizon_end for a in assignments)
    return assignments, makespan, horizon_ok
