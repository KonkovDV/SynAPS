"""LBBD-HD Solver — Hierarchical Decomposition LBBD for industrial-scale MO-FJSP-SDST-ARC.

Scales the original LBBD solver from ~500 to 50 000+ operations through five
engineering measures (see §8.2 of the venture memorandum):

    1. Balanced ARC-Aware Partitioning (replaces naive Union-Find)
    2. Precedence-Aware Master (continuous start/end variables in HiGHS)
    3. Greedy ATCS warm-start (initial feasible solution from GreedyDispatch)
    4. Parallel subproblem execution (ProcessPoolExecutor)
    5. Accelerated post-assembly (topological sort + priority-queue per machine)

Academic basis:
    - Hooker & Ottosson (2003): LBBD framework and combinatorial Benders cuts.
    - Naderi & Roshanaei (2022): Critical-path-search LBBD for FJSP, INFORMS J. Opt.
    - Nasirian, Abbasi & Zhang (2025): Analytical cuts for LBBD in scheduling.
    - Schlenkrich & Parragh (2023): Survey of large-scale industrial scheduling decomposition.
    - Karypis & Kumar (1998): Multilevel graph partitioning (METIS concept).
    - Hooker (2019): Logic-Based Benders Decomposition, CUP, 2nd edition.
"""

from __future__ import annotations

import itertools
import os
import time
import warnings
from collections import defaultdict
from contextlib import nullcontext
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
from synaps.solvers._lbbd_assembly import (
    notary_rejections,
    seal_post_assembly_calendar,
    stamp_parallel_lane_ids,
)
from synaps.solvers._lbbd_cuts import (
    compute_assignment_setup_lb_total,
    compute_machine_transition_floor,
    compute_machine_tsp_lower_bound,
    compute_sequence_independent_setup_lower_bound,
    cut_kind_lb_contribution,
    cut_pool_fingerprint,
    reported_lower_bound,
)
from synaps.solvers._lbbd_master import (
    add_assignment_rows,
    add_capacity_rows,
    add_nogood_row,
    extract_master_solution,
)
from synaps.solvers._process_pool import SubproblemPool, solve_clusters
from synaps.solvers.coverage_outcome import stamp_honest_coverage
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.partitioning import partition_machines
from synaps.timegrain import duration_minutes_for

if TYPE_CHECKING:
    from uuid import UUID


# ---------------------------------------------------------------------------
# Top-level solver
# ---------------------------------------------------------------------------


class LbbdHdSolver(BaseSolver):
    """Hierarchical Decomposition LBBD for 10 000-50 000+ operation instances.

    Iterates between a precedence-aware HiGHS master (assignment + relaxed
    timing) and size-controlled CP-SAT subproblems (exact sequencing with
    SDST + ARC), connected by four families of Benders cuts.

    Key parameters (passed via **kwargs to ``solve``):
        max_iterations: Benders iteration CEILING (default 10).
        time_limit_s: HARD wall-clock deadline in seconds (default 300);
            whichever of the two is hit first wins (D3/D4). Per-cluster
            CP-SAT budgets are clamped to the remaining deadline.
        random_seed: CP-SAT random seed (default 42).
        gap_threshold: Optimality gap at which to stop (default 0.01).
        max_ops_per_cluster: Cluster size cap for partitioning (default 200).
        num_workers: Parallel CP-SAT workers (default min(8, cpu_count)).
        sub_num_workers: CP-SAT internal num_workers per subproblem (default 4).
        use_warm_start: Use greedy ATCS warm-start (default True).
        setup_relaxation: Include min-setup lower bound in master (default True).
    """

    @property
    def name(self) -> str:
        return "lbbd_hd"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        return stamp_honest_coverage(problem, _LbbdHdRun(self.name, problem, kwargs).execute())


class _LbbdHdRun:
    """One LBBD-HD solve: precedence-aware master -> clustered CP-SAT -> cuts."""

    def __init__(self, solver_name: str, problem: ScheduleProblem, kwargs: dict[str, Any]):
        self.solver_name = solver_name
        self.problem = problem
        self.t0 = time.monotonic()
        self._configure(kwargs)
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
        # Precedence DAG edges: (predecessor -> successor).
        self.dag_edges: list[tuple[UUID, UUID]] = [
            (op.predecessor_op_id, op.id)
            for op in problem.operations
            if op.predecessor_op_id is not None
        ]
        self.min_setup_by_wc: dict[UUID, float] = {}
        self.prev_assignment_map: dict[UUID, UUID] | None = None
        self.best_assignments: list[Assignment] = []
        self.best_objective = ObjectiveValues()
        self.best_ub = float("inf")
        self.lb = 0.0
        # Ownership: the cut pool is created fresh for this run and mutated
        # only through _register_cut().
        self.benders_cuts: list[_BendersCut] = []
        self.iteration_log: list[dict[str, Any]] = []
        self.master_warm_starts = 0
        # R10: lb_evolution[N] is the master bound of iteration N; the delta
        # seen in iteration N is attributed to the cuts added in iteration N-1.
        self.lb_evolution: list[float] = []
        # Candidate incumbents the independent notary refused (source, kinds).
        self.incumbent_rejections: list[dict[str, Any]] = []
        self.ub_evolution: list[float] = []
        self.prev_master_bound = 0.0
        self.prev_iteration_cut_kinds: list[str] = []
        # R3: identical (kind, bottleneck_ops, rhs-rounded) fingerprints only
        # inflate the HiGHS master; they are counted and dropped.
        self.seen_cut_fingerprints: set[
            tuple[str, frozenset[UUID], frozenset[tuple[UUID, UUID]], float]
        ] = set()
        self.cuts_skipped_duplicate = 0
        # S2: optimality/feasibility cuts skipped because the subproblem was
        # not proven (TIMEOUT/ERROR).
        self.cuts_skipped_unproven_subproblem = 0
        self.warm_start_error: str | None = None

    def _configure(self, kwargs: dict[str, Any]) -> None:
        self.max_iterations = int(kwargs.get("max_iterations", 10))
        self.time_limit_s = int(kwargs.get("time_limit_s", 300))
        self.random_seed = int(kwargs.get("random_seed", 42))
        self.gap_threshold = float(kwargs.get("gap_threshold", 0.01))
        self.max_ops_per_cluster = int(kwargs.get("max_ops_per_cluster", 200))
        self.num_workers = int(kwargs.get("num_workers", min(8, os.cpu_count() or 4)))
        self.sub_num_workers = int(kwargs.get("sub_num_workers", 4))
        # KI-R3: one subproblem process pool for the whole solve.
        self.pool = SubproblemPool(self.num_workers)
        self.use_warm_start = bool(kwargs.get("use_warm_start", True))
        self.setup_relaxation = bool(kwargs.get("setup_relaxation", True))
        self.setup_cut_top_k = max(1, int(kwargs.get("setup_cut_top_k", 3)))
        self.local_branching_enabled = bool(kwargs.get("local_branching_enabled", False))
        self.local_branching_delta_ratio = min(
            0.95, max(0.01, float(kwargs.get("local_branching_delta_ratio", 0.10)))
        )
        self.local_branching_max_ops = max(4, int(kwargs.get("local_branching_max_ops", 128)))
        self.sub_time_limit_s = max(2, self.time_limit_s // max(self.max_iterations, 1))
        # D3: hard wall-clock deadline shared by all cluster solves.
        self.deadline = self.t0 + float(self.time_limit_s)

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
            for wc in self.problem.work_centers:
                floor = compute_machine_transition_floor(
                    self.problem, self.eligible_by_op, wc.id, self.setup_lookup
                )
                if floor > 0:
                    self.min_setup_by_wc[wc.id] = floor
        if self.use_warm_start:
            self._greedy_warm_start()  # Measure 3
        try:
            for iteration in range(1, self.max_iterations + 1):
                if time.monotonic() - self.t0 >= self.time_limit_s:
                    break
                outcome = self._iteration(iteration)
                if isinstance(outcome, ScheduleResult):
                    return outcome
                if outcome == "stop":
                    break
        finally:
            self.pool.close()
        return self._final_result()

    def _greedy_warm_start(self) -> None:
        try:
            from synaps.solvers.greedy_dispatch import GreedyDispatch

            warm_result = GreedyDispatch(k1=2.0, k3=0.5).solve(self.problem)
        except Exception as exc:  # cold start, but say why in the metadata
            self.warm_start_error = type(exc).__name__
            return
        if (
            warm_result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
            and warm_result.assignments
        ):
            self.prev_assignment_map = {
                a.operation_id: a.work_center_id for a in warm_result.assignments
            }
            if self._notary_refuses("greedy_warm_start", list(warm_result.assignments)):
                return
            self.best_assignments = list(warm_result.assignments)
            self.best_objective = warm_result.objective or ObjectiveValues()
            self.best_ub = self.best_objective.makespan_minutes or float("inf")

    def _iteration(self, iteration: int) -> ScheduleResult | str:
        """One master + subproblem round; returns a result, "stop" or "next"."""
        cuts_before = len(self.benders_cuts)
        attributed = list(self.prev_iteration_cut_kinds)
        master = self._solve_master(iteration)
        if not isinstance(master, tuple):
            return master
        assignment_map, master_bound, lb_delta = master
        # Measure 1: balanced partitioning; Measure 4: parallel subproblems.
        clusters = partition_machines(
            self.problem, assignment_map, max_ops_per_cluster=self.max_ops_per_cluster
        )
        sub_assignments, _sub_makespan, sub_proven_optimal, sub_infeasible_proven = (
            _solve_subproblems_parallel(
                self.problem,
                assignment_map,
                clusters,
                self.wc_by_id,
                self.ops_by_id,
                self.orders_by_id,
                self.sub_time_limit_s,
                self.random_seed,
                num_workers=self.num_workers,
                sub_num_workers=self.sub_num_workers,
                deadline=self.deadline,
                pool=self.pool,
            )
        )
        if sub_assignments is None:
            self._record_failed_subproblem(
                iteration, master_bound, assignment_map, lb_delta, attributed, sub_infeasible_proven
            )
            self.prev_iteration_cut_kinds = [c.kind for c in self.benders_cuts[cuts_before:]]
            return "next"
        # Measure 5: accelerated post-assembly (F3 lane-aware).
        assembled, horizon_ok = _topological_post_assembly(
            self.problem, sub_assignments, self.ops_by_id
        )
        if assembled is None or not horizon_ok:
            # Horizon overflow / assembly failure is unproven (S2): no cut and
            # no incumbent.
            self.cuts_skipped_unproven_subproblem += 1
            self.iteration_log.append(
                {
                    "iteration": iteration,
                    "master_bound": master_bound,
                    "status": "post_assembly_horizon_or_failure",
                }
            )
        else:
            sub_makespan = _assembled_makespan(self.problem, assembled)
            entry: dict[str, Any] = {"iteration": iteration, "master_bound": master_bound}
            if self._record_feasible_subproblem(
                entry, assembled, sub_makespan, assignment_map, clusters, lb_delta, attributed
            ):
                self.prev_iteration_cut_kinds = []
                return "stop"
            self._generate_cuts(assignment_map, assembled, sub_makespan, sub_proven_optimal)
        self.prev_iteration_cut_kinds = [c.kind for c in self.benders_cuts[cuts_before:]]
        return "next"

    def _solve_master(
        self, iteration: int
    ) -> tuple[dict[UUID, UUID], float, float] | ScheduleResult | str:
        """Measure 2: precedence-aware HiGHS master; (map, bound, LB delta) or a stop."""
        if self.prev_assignment_map is not None:
            self.master_warm_starts += 1
        master_result, master_proven_infeasible = _solve_precedence_aware_master(
            self.problem,
            self.eligible_by_op,
            self.wc_by_id,
            self.ops_by_id,
            self.dag_edges,
            self.benders_cuts,
            min_setup_by_wc=self.min_setup_by_wc,
            prev_solution=self.prev_assignment_map,
            master_time_limit_s=max(
                1.0, min(self.deadline - time.monotonic(), float(self.sub_time_limit_s) + 2.0)
            ),
        )
        if master_result is None:
            failed = _hd_master_failed_result(
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
        return assignment_map, master_bound, lb_delta

    def _record_failed_subproblem(
        self,
        iteration: int,
        master_bound: float,
        assignment_map: dict[UUID, UUID],
        lb_delta: float,
        attributed: list[str],
        sub_infeasible_proven: bool,
    ) -> None:
        if sub_infeasible_proven:
            # Proven INFEASIBLE -> excluding this assignment is sound.
            self._register_cut(self._nogood(assignment_map))
        else:
            # S2 gate: a TIMEOUT/ERROR proves nothing; a no-good here could
            # exclude the optimum and inflate the master bound.
            self.cuts_skipped_unproven_subproblem += 1
        self.iteration_log.append(
            {
                "iteration": iteration,
                "master_bound": master_bound,
                "sub_makespan": None,
                "lb_delta": lb_delta,
                "cut_kinds_attributed": attributed,
                "status": "sub_infeasible" if sub_infeasible_proven else "sub_unproven_failure",
            }
        )

    def _record_feasible_subproblem(
        self,
        entry: dict[str, Any],
        sub_assignments: list[Assignment],
        sub_makespan: float,
        assignment_map: dict[UUID, UUID],
        clusters: list[set[UUID]],
        lb_delta: float,
        attributed: list[str],
    ) -> bool:
        """Update the incumbent and the log; True when the gap has closed."""
        ub = sub_makespan
        if ub < self.best_ub and self._notary_refuses("merged_subproblems", sub_assignments):
            entry["incumbent_rejected"] = self.incumbent_rejections[-1]["kinds"]
        elif ub < self.best_ub:
            self.best_ub = ub
            self.ub_evolution.append(self.best_ub)
            self.best_assignments = sub_assignments
            self.best_objective = _compute_objective(self.problem, sub_assignments)
        entry.update(
            {
                "sub_makespan": sub_makespan,
                "gap": (ub - self.lb) / max(ub, 1e-9),
                "lb_delta": lb_delta,
                "cut_kinds_attributed": attributed,
                "status": "feasible",
                "cluster_count": len(clusters),
                "max_cluster_ops": max(
                    (
                        sum(1 for _op_id, wc_id in assignment_map.items() if wc_id in c)
                        for c in clusters
                    ),
                    default=0,
                ),
            }
        )
        self.iteration_log.append(entry)
        return (self.best_ub - self.lb) / max(self.best_ub, 1e-9) < self.gap_threshold

    def _notary_refuses(self, source: str, assignments: list[Assignment]) -> bool:
        """True (and recorded) when a candidate incumbent has proven hard violations."""
        kinds = notary_rejections(self.problem, assignments)
        if kinds:
            self.incumbent_rejections.append({"source": source, "kinds": kinds})
        return bool(kinds)

    def _generate_cuts(
        self,
        assignment_map: dict[UUID, UUID],
        sub_assignments: list[Assignment],
        sub_makespan: float,
        sub_proven_optimal: bool,
    ) -> None:
        # S2 (2026-07): a full-assignment no-good is emitted only when every
        # cluster was proven OPTIMAL, so its cost is captured in best_ub and
        # `min(master_bound, best_ub)` stays a valid global lower bound.
        cuts_before_gen = len(self.benders_cuts)
        if sub_proven_optimal:
            self._register_cut(self._nogood(assignment_map))
        else:
            self.cuts_skipped_unproven_subproblem += 1
        _generate_all_cuts(
            self.problem,
            sub_assignments,
            assignment_map,
            self.benders_cuts,
            sub_makespan,
            self.wc_by_id,
            self.ops_by_id,
            setup_cut_top_k=self.setup_cut_top_k,
            local_branching_enabled=self.local_branching_enabled,
            local_branching_delta_ratio=self.local_branching_delta_ratio,
            local_branching_max_ops=self.local_branching_max_ops,
        )
        # R3: bulk-dedup the cuts `_generate_all_cuts` just produced so that
        # identical fingerprints from earlier iterations do not stack.
        freshly_generated = self.benders_cuts[cuts_before_gen:]
        del self.benders_cuts[cuts_before_gen:]
        for fresh_cut in freshly_generated:
            self._register_cut(fresh_cut)

    def _final_result(self) -> ScheduleResult:
        status = SolverStatus.FEASIBLE if self.best_assignments else SolverStatus.TIMEOUT
        # D2: fully deterministic assignment order (with deterministic cluster
        # collection and the D1 strict CP-SAT default).
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
        """Cut-free master relaxation (S1/S2/S3 validity fix; N5: never clamped).

        The cluster subproblem re-assembles independent clusters, so its
        makespan is an UPPER bound on the assignment's true cost; no-goods
        drive the search but must not tighten the reported bound. Reporting
        ``min(relaxation, best_ub)`` would make ``lb <= ub`` true by
        construction and silence an invalid relaxation, so the raw value is
        reported and a violation is flagged instead.
        """
        raw_relaxation = self.lb_evolution[0] if self.lb_evolution else 0.0
        reported_lb, violated = reported_lower_bound(raw_relaxation, self.best_ub)
        if violated:
            warnings.warn(
                f"LBBD-HD lower-bound invariant violated: raw master relaxation "
                f"{raw_relaxation} exceeds incumbent {self.best_ub}; the relaxation "
                f"is not a valid lower bound.",
                stacklevel=6,  # the caller of LbbdHdSolver.solve
            )
        return reported_lb, violated

    def _final_metadata(self, best_assignments: list[Assignment]) -> dict[str, Any]:
        reported_lb, lb_invariant_violated = self._reported_lower_bound()
        cut_kinds: dict[str, int] = {}
        for cut in self.benders_cuts:
            cut_kinds[cut.kind] = cut_kinds.get(cut.kind, 0) + 1
        # N2 (audit v3): expose whether the Benders master actually learned.
        benders_active = len(self.benders_cuts) > 0
        best_ub = self.best_ub
        metadata: dict[str, Any] = {
            "iterations": len(self.iteration_log),
            "lower_bound": reported_lb,
            "upper_bound": best_ub,
            "gap": (best_ub - reported_lb) / max(best_ub, 1e-9) if best_ub < float("inf") else None,
            "benders_active": benders_active,
            "quality_warning": None if benders_active else "lbbd_no_cuts_degenerate",
            "lower_bound_invariant_violated": lb_invariant_violated,
            "lower_bound_method": "master_relaxation_benders_hd",
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
            "setup_cut_top_k": self.setup_cut_top_k,
            "local_branching_enabled": self.local_branching_enabled,
            "local_branching_delta_ratio": self.local_branching_delta_ratio,
            "local_branching_max_ops": self.local_branching_max_ops,
            "master_warm_start_iterations": self.master_warm_starts,
            "max_ops_per_cluster": self.max_ops_per_cluster,
            "num_workers": self.num_workers,
            "warm_start_used": self.use_warm_start,
            "cut_pool": {
                "size": len(self.benders_cuts),
                "kinds": cut_kinds,
                "skipped_duplicate": self.cuts_skipped_duplicate,
                "skipped_unproven_subproblem": self.cuts_skipped_unproven_subproblem,
            },
        }
        if self.warm_start_error is not None:
            metadata["warm_start_error"] = self.warm_start_error
        if self.incumbent_rejections:
            metadata["incumbent_rejections"] = self.incumbent_rejections
        return metadata


def _assembled_makespan(problem: ScheduleProblem, assignments: list[Assignment]) -> float:
    """Makespan in minutes of a post-assembled schedule (0 when empty)."""
    horizon_start = problem.planning_horizon_start
    return (
        max((a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments)
        if assignments
        else 0.0
    )


# ---------------------------------------------------------------------------
# Benders Cut object
# ---------------------------------------------------------------------------


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


# R2 (2026-05-03): the sequence-aware lower-bound helpers were moved to
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


# ---------------------------------------------------------------------------
# Measure 2: Precedence-Aware Master Problem (HiGHS MIP)
# ---------------------------------------------------------------------------


def _solve_precedence_aware_master(
    problem: ScheduleProblem,
    eligible_by_op: dict[UUID, list[UUID]],
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    dag_edges: list[tuple[UUID, UUID]],
    cuts: list[_BendersCut],
    min_setup_by_wc: dict[UUID, float] | None = None,
    prev_solution: dict[UUID, UUID] | None = None,
    master_time_limit_s: float | None = None,
) -> tuple[tuple[dict[UUID, UUID], float] | None, bool]:
    """Solve the precedence-aware assignment master problem via HiGHS MIP.

    Returns ``((assignment_map, master_bound), proven_infeasible)``. When the
    master yields no incumbent, ``proven_infeasible`` is True only for a HiGHS
    ``kInfeasible`` status (F12); a time-limit miss is ``(None, False)``.

    Rows, in order (the order is part of HiGHS' search path): unique
    assignment, timing linkage ``end = start + Σ P·y``, chain precedence,
    relaxed capacity, ``C_max ≥ end`` and the Benders cuts.
    """
    del ops_by_id  # the layout indexes operations by position
    h = highspy.Highs()
    h.silent()
    # D3: bound the master MILP by the remaining wall budget (see lbbd_solver).
    if master_time_limit_s is not None:
        h.setOptionValue("time_limit", max(1.0, float(master_time_limit_s)))
    layout = _HdMasterLayout.add_columns(h, problem, eligible_by_op)
    add_assignment_rows(h, problem, eligible_by_op, layout.var_index)
    _add_timing_rows(h, problem, eligible_by_op, wc_by_id, layout)
    _add_precedence_rows(h, dag_edges, layout)
    add_capacity_rows(h, problem, layout.var_index, layout.cmax_idx, min_setup_by_wc)
    _add_makespan_rows(h, problem, layout)
    _add_hd_cut_rows(h, cuts, layout.var_index)
    h.changeObjectiveSense(highspy.ObjSense.kMinimize)
    if prev_solution is not None and hasattr(h, "setSolution"):
        _hint_hd_master(h, problem, eligible_by_op, layout, prev_solution)
    h.run()
    return extract_master_solution(h, problem, eligible_by_op, layout.var_index, layout.cmax_idx)


class _HdMasterLayout:
    """Column layout: ``y[i, k]`` binaries, then ``start[i]``, ``end[i]``, ``C_max``."""

    __slots__ = ("cmax_idx", "end_base", "n_vars", "op_to_idx", "start_base", "var_index")

    def __init__(
        self,
        var_index: dict[tuple[UUID, UUID], int],
        op_to_idx: dict[UUID, int],
        start_base: int,
        end_base: int,
        cmax_idx: int,
    ) -> None:
        self.var_index = var_index
        self.op_to_idx = op_to_idx
        self.start_base = start_base
        self.end_base = end_base
        self.cmax_idx = cmax_idx
        self.n_vars = cmax_idx + 1

    @classmethod
    def add_columns(
        cls, h: Any, problem: ScheduleProblem, eligible_by_op: dict[UUID, list[UUID]]
    ) -> _HdMasterLayout:
        var_index: dict[tuple[UUID, UUID], int] = {}
        col_idx = 0
        for op in problem.operations:
            for wc_id in eligible_by_op[op.id]:
                var_index[(op.id, wc_id)] = col_idx
                col_idx += 1
        n_y = col_idx
        op_to_idx = {op.id: i for i, op in enumerate(problem.operations)}
        start_base = n_y
        end_base = start_base + len(problem.operations)
        layout = cls(var_index, op_to_idx, start_base, end_base, end_base + len(op_to_idx))
        n_vars = layout.n_vars
        costs = [0.0] * n_vars
        costs[layout.cmax_idx] = 1.0  # minimize C_max
        # y binary in [0, 1]; start, end and C_max continuous in [0, inf).
        upper = [1.0] * n_y + [highspy.kHighsInf] * (n_vars - n_y)
        h.addVars(n_vars, np.array([0.0] * n_vars), np.array(upper))
        h.changeColsCost(n_vars, np.arange(n_vars, dtype=np.int32), np.array(costs))
        if n_y > 0:
            h.changeColsIntegrality(
                n_y,
                np.arange(n_y, dtype=np.int32),
                np.array([highspy.HighsVarType.kInteger] * n_y),
            )
        return layout


def _add_timing_rows(
    h: Any,
    problem: ScheduleProblem,
    eligible_by_op: dict[UUID, list[UUID]],
    wc_by_id: dict[UUID, WorkCenter],
    layout: _HdMasterLayout,
) -> None:
    """Timing linkage ``end[i] - start[i] - ∑_k P[i,k] · y[i,k] = 0``."""
    for op in problem.operations:
        op_idx = layout.op_to_idx[op.id]
        indices = [layout.end_base + op_idx, layout.start_base + op_idx]
        coeffs = [1.0, -1.0]
        for wc_id in eligible_by_op[op.id]:
            wc: Any = wc_by_id.get(wc_id)
            if wc is None:
                from types import SimpleNamespace

                wc = SimpleNamespace(id=wc_id, speed_factor=1.0)
            # CP-SAT duration semantics (T-30 aware) so the master timing
            # model matches what the subproblem model realises (S2/S3 validity).
            indices.append(layout.var_index[(op.id, wc_id)])
            coeffs.append(-float(duration_minutes_for(op, wc)))
        h.addRow(
            0.0,
            0.0,
            len(indices),
            np.array(indices, dtype=np.int32),
            np.array(coeffs),
        )


def _add_precedence_rows(
    h: Any, dag_edges: list[tuple[UUID, UUID]], layout: _HdMasterLayout
) -> None:
    """Precedence ``start[j] - end[i] ≥ 0`` for every DAG edge ``i → j``."""
    for pred_id, succ_id in dag_edges:
        if pred_id not in layout.op_to_idx or succ_id not in layout.op_to_idx:
            continue
        h.addRow(
            0.0,
            highspy.kHighsInf,
            2,
            np.array(
                [
                    layout.start_base + layout.op_to_idx[succ_id],
                    layout.end_base + layout.op_to_idx[pred_id],
                ],
                dtype=np.int32,
            ),
            np.array([1.0, -1.0]),
        )


def _add_makespan_rows(h: Any, problem: ScheduleProblem, layout: _HdMasterLayout) -> None:
    """``C_max - end[i] ≥ 0`` for every operation."""
    for op in problem.operations:
        h.addRow(
            0.0,
            highspy.kHighsInf,
            2,
            np.array([layout.cmax_idx, layout.end_base + layout.op_to_idx[op.id]], dtype=np.int32),
            np.array([1.0, -1.0]),
        )


def _add_hd_cut_rows(
    h: Any, cuts: list[_BendersCut], var_index: dict[tuple[UUID, UUID], int]
) -> None:
    """No-good and local-branching rows; retired or unknown kinds raise."""
    for cut in cuts:
        if cut.kind == "nogood":
            add_nogood_row(h, cut.assignment_map, var_index, "LBBD-HD")
        elif cut.kind in ("setup_cost", "machine_tsp"):
            # Wave 11 / M1 + KI-S3: generation is retired; refuse to apply if injected.
            raise ValueError(
                f"LBBD cut kind {cut.kind!r} is permanently retired (KI-S3); "
                "refusing to apply sentinel optimality cuts"
            )
        elif cut.kind == "local_branching":
            lb_indices = [
                var_index[(op_id, lb_wc)]
                for op_id in cut.bottleneck_ops
                if (lb_wc := cut.assignment_map.get(op_id)) is not None
                and (op_id, lb_wc) in var_index
            ]
            if lb_indices:
                # Enforce at least delta assignment changes in this neighborhood:
                # sum(match incumbent assignments) <= |S| - delta
                h.addRow(
                    -highspy.kHighsInf,
                    cut.rhs,
                    len(lb_indices),
                    np.array(lb_indices, dtype=np.int32),
                    np.ones(len(lb_indices)),
                )
        else:
            raise ValueError(
                f"Unknown LBBD-HD cut kind {cut.kind!r}; refusing silent no-op (Wave 12 / M12-1)."
            )


def _hint_hd_master(
    h: Any,
    problem: ScheduleProblem,
    eligible_by_op: dict[UUID, list[UUID]],
    layout: _HdMasterLayout,
    prev_solution: dict[UUID, UUID],
) -> None:
    """Warm-start ``y`` from the previous assignment; ``C_max`` at the horizon."""
    hint = [0.0] * layout.n_vars
    for op in problem.operations:
        prev_wc = prev_solution.get(op.id)
        for wc_id in eligible_by_op[op.id]:
            key = (op.id, wc_id)
            if key in layout.var_index:
                hint[layout.var_index[key]] = 1.0 if wc_id == prev_wc else 0.0
    hint[layout.cmax_idx] = (
        problem.planning_horizon_end - problem.planning_horizon_start
    ).total_seconds() / 60
    h.setSolution(layout.n_vars, np.arange(layout.n_vars, dtype=np.int32), np.array(hint))


# ---------------------------------------------------------------------------
# Measure 4: Parallel Subproblem Execution
# ---------------------------------------------------------------------------


def _solve_single_cluster(
    problem_dict: dict[str, Any],
    cluster_wcs: list[Any],
    assignment_map_items: list[tuple[str, str]],
    sub_time_limit_s: int,
    random_seed: int,
    sub_num_workers: int,
) -> dict[str, Any] | None:
    """Solve a single cluster subproblem (runs in a worker process).

    Accepts serializable arguments to work with ProcessPoolExecutor.
    Returns a dict with assignments data or None if infeasible.
    """
    from uuid import UUID

    from synaps.model import ScheduleProblem

    problem = ScheduleProblem.model_validate(problem_dict)
    cluster_wc_set = {UUID(w) for w in cluster_wcs}
    assignment = {UUID(k): UUID(v) for k, v in assignment_map_items}

    ops_by_id = {op.id: op for op in problem.operations}
    orders_by_id = {o.id: o for o in problem.orders}
    wc_by_id = {wc.id: wc for wc in problem.work_centers}

    # Collect operations for this cluster
    cluster_op_ids = {op_id for op_id, wc_id in assignment.items() if wc_id in cluster_wc_set}
    if not cluster_op_ids:
        return {"assignments": [], "makespan": 0.0, "proven_optimal": True}

    cluster_ops = [ops_by_id[oid] for oid in cluster_op_ids if oid in ops_by_id]

    sub_problem = _build_subproblem(
        problem,
        cluster_ops,
        cluster_wc_set,
        cluster_op_ids,
        assignment,
        wc_by_id,
        ops_by_id,
        orders_by_id,
    )

    cpsat = CpSatSolver()
    result = cpsat.solve(
        sub_problem,
        time_limit_s=sub_time_limit_s,
        random_seed=random_seed,
        num_workers=sub_num_workers,
    )

    if result.status == SolverStatus.INFEASIBLE:
        return {"failed": True, "infeasible_proven": True}
    if result.status == SolverStatus.ERROR:
        return {"failed": True, "infeasible_proven": False}
    if result.status == SolverStatus.TIMEOUT and not result.assignments:
        return {"failed": True, "infeasible_proven": False}

    # Only keep cluster-owned assignments
    kept = [a for a in result.assignments if a.operation_id in cluster_op_ids]
    horizon_start = problem.planning_horizon_start
    mk = max((a.end_time - horizon_start).total_seconds() / 60.0 for a in kept) if kept else 0.0

    return {
        "assignments": [a.model_dump(mode="json") for a in kept],
        "makespan": mk,
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
    sub_num_workers: int = 4,
    deadline: float | None = None,
    pool: SubproblemPool | None = None,
) -> tuple[list[Assignment] | None, float, bool, bool]:
    """Solve CP-SAT subproblems in parallel on the solve's process pool (KI-R3).

    Returns ``(assignments, makespan, proven_optimal, infeasible_proven)`` —
    ``proven_optimal`` is True only when every cluster returned OPTIMAL (S2
    gate); ``infeasible_proven`` only on a proven INFEASIBLE cluster.
    For small instance counts (≤ 3 clusters), falls back to sequential
    execution to avoid multiprocessing overhead.

    D3: the per-cluster budget is clamped to the remaining wall-clock budget
    (``deadline`` is a ``time.monotonic()`` timestamp); no new cluster batch
    is started past the deadline.
    """
    if not clusters:
        return None, 0.0, False, False

    if deadline is not None:
        remaining_s = deadline - time.monotonic()
        if remaining_s <= 0:
            return None, 0.0, False, False
        sub_time_limit_s = max(1, min(sub_time_limit_s, int(remaining_s)))

    # Serialize problem once
    problem_dict = problem.model_dump(mode="json")
    assignment_items = [(str(k), str(v)) for k, v in assignment_map.items()]

    # Sequential path for small counts
    if len(clusters) <= 3:
        return _solve_subproblems_sequential(
            problem,
            assignment_map,
            clusters,
            wc_by_id,
            ops_by_id,
            orders_by_id,
            sub_time_limit_s,
            random_seed,
            sub_num_workers,
            deadline=deadline,
        )

    all_assignments: list[Assignment] = []
    overall_makespan = 0.0
    jobs = [
        (
            problem_dict,
            [str(w) for w in wcs],
            assignment_items,
            sub_time_limit_s,
            random_seed,
            sub_num_workers,
        )
        for wcs in clusters
    ]
    with (
        SubproblemPool(min(num_workers, len(clusters))) if pool is None else nullcontext(pool)
    ) as active:
        results_by_index, infeasible_proven = solve_clusters(active, _solve_single_cluster, jobs)
    if results_by_index is None:
        return None, 0.0, False, infeasible_proven
    all_proven_optimal = True
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

    return all_assignments, overall_makespan, all_proven_optimal, False


def _solve_subproblems_sequential(
    problem: ScheduleProblem,
    assignment_map: dict[UUID, UUID],
    clusters: list[set[UUID]],
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    orders_by_id: dict[UUID, Order],
    sub_time_limit_s: int,
    random_seed: int,
    sub_num_workers: int,
    *,
    deadline: float | None = None,
) -> tuple[list[Assignment] | None, float, bool, bool]:
    """Sequential fallback for small cluster counts.

    Same 4-tuple contract as :func:`_solve_subproblems_parallel`.
    D3: per-cluster budget clamped to the remaining deadline; no new cluster
    is started past the deadline.
    """
    all_assignments: list[Assignment] = []
    overall_makespan = 0.0
    horizon_start = problem.planning_horizon_start
    all_proven_optimal = True

    for cluster_wcs in clusters:
        cluster_op_ids = {op_id for op_id, wc_id in assignment_map.items() if wc_id in cluster_wcs}
        if not cluster_op_ids:
            continue

        cluster_ops = [ops_by_id[oid] for oid in cluster_op_ids if oid in ops_by_id]

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

        cluster_limit_s = sub_time_limit_s
        if deadline is not None:
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                return None, 0.0, False, False
            cluster_limit_s = max(1, min(sub_time_limit_s, int(remaining_s)))
        cpsat = CpSatSolver()
        result = cpsat.solve(
            sub_problem,
            time_limit_s=cluster_limit_s,
            random_seed=random_seed,
            num_workers=sub_num_workers,
        )

        if result.status == SolverStatus.INFEASIBLE:
            return None, 0.0, False, True
        if result.status == SolverStatus.ERROR:
            return None, 0.0, False, False
        if result.status == SolverStatus.TIMEOUT and not result.assignments:
            return None, 0.0, False, False
        if result.status is not SolverStatus.OPTIMAL:
            all_proven_optimal = False

        kept = [a for a in result.assignments if a.operation_id in cluster_op_ids]
        all_assignments.extend(kept)
        if kept:
            mk = max((a.end_time - horizon_start).total_seconds() / 60.0 for a in kept)
            overall_makespan = max(overall_makespan, mk)

    assigned_ops = {a.operation_id for a in all_assignments}
    all_ops = {op.id for op in problem.operations}
    if assigned_ops != all_ops:
        return None, 0.0, False, False

    return all_assignments, overall_makespan, all_proven_optimal, False


def _hd_master_failed_result(
    solver_name: str,
    t0: float,
    iteration: int,
    proven_infeasible: bool,
    has_incumbent: bool,
) -> ScheduleResult | None:
    """Result to return on a failed HD master, or None to break with incumbent."""
    if has_incumbent:
        return None
    if not proven_infeasible:
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


def _assignment_sequence_key(assignment: Assignment) -> tuple[UUID, UUID | None]:
    return assignment.work_center_id, assignment.lane_id


def _find_earliest_machine_slot(
    timeline: list[tuple[float, float, UUID, UUID]],
    *,
    earliest_start: Any,
    duration: timedelta,
    operation_state_id: UUID,
    work_center_id: UUID,
    setup_lookup: dict[tuple[UUID, UUID, UUID], timedelta],
    horizon_start: Any,
) -> tuple[Any, int]:
    """Return the earliest feasible machine slot and insertion index."""

    candidate_start = earliest_start
    if not timeline:
        return candidate_start, 0

    for index, (start_offset, end_offset, next_state_id, _next_op_id) in enumerate(timeline):
        next_start = horizon_start + timedelta(minutes=start_offset)
        candidate_end = candidate_start + duration
        setup_to_next = setup_lookup.get(
            (work_center_id, operation_state_id, next_state_id),
            timedelta(0),
        )
        if candidate_end + setup_to_next <= next_start:
            return candidate_start, index

        previous_end = horizon_start + timedelta(minutes=end_offset)
        setup_from_previous = setup_lookup.get(
            (work_center_id, next_state_id, operation_state_id),
            timedelta(0),
        )
        available_after_previous = previous_end + setup_from_previous
        if available_after_previous > candidate_start:
            candidate_start = available_after_previous

    return candidate_start, len(timeline)


def find_earliest_machine_slot(
    timeline: list[tuple[float, float, UUID, UUID]],
    *,
    earliest_start: Any,
    duration: timedelta,
    operation_state_id: UUID,
    work_center_id: UUID,
    setup_lookup: dict[tuple[UUID, UUID, UUID], timedelta],
    horizon_start: Any,
) -> tuple[Any, int]:
    """Public wrapper for earliest-gap insertion on one machine lane."""

    return _find_earliest_machine_slot(
        timeline,
        earliest_start=earliest_start,
        duration=duration,
        operation_state_id=operation_state_id,
        work_center_id=work_center_id,
        setup_lookup=setup_lookup,
        horizon_start=horizon_start,
    )


# ---------------------------------------------------------------------------
# Measure 5: Accelerated Post-Assembly (O(N log N))
# ---------------------------------------------------------------------------


def _topological_post_assembly(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Operation],
) -> tuple[list[Assignment] | None, bool]:
    """Fix cross-cluster timing via topological traversal + per-lane heaps.

    F3 (audit v4): before building timelines, stamp ``lane_id`` on parallel
    machines via the shared exact lane inference so ops are not serialized
    onto a single ``(wc, None)`` pseudo-lane. Returns
    ``(assignments, horizon_ok)``.

    Complexity: O(|O| log |O| + |DAG|) — dominated by per-machine sorting.
    """
    if not assignments:
        return assignments, True

    stamp_parallel_lane_ids(problem, assignments, ops_by_id, lane_tag_prefix="lbbd-hd-lane")

    setup_lookup: dict[tuple[UUID, UUID, UUID], timedelta] = {
        (e.work_center_id, e.from_state_id, e.to_state_id): timedelta(minutes=e.setup_minutes)
        for e in problem.setup_matrix
    }

    # Build assignment lookup
    assignment_by_op: dict[UUID, Assignment] = {a.operation_id: a for a in assignments}

    # Build DAG: successor list
    successors: dict[UUID, list[UUID]] = defaultdict(list)
    in_degree: dict[UUID, int] = {op.id: 0 for op in problem.operations}

    for op in problem.operations:
        if op.predecessor_op_id is not None:
            successors[op.predecessor_op_id].append(op.id)
            in_degree[op.id] = in_degree.get(op.id, 0) + 1

    # Topological sort via Kahn's algorithm
    topo_order: list[UUID] = []
    queue: list[UUID] = [op_id for op_id, deg in in_degree.items() if deg == 0]
    while queue:
        current = queue.pop()
        topo_order.append(current)
        for succ in successors.get(current, []):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    # Build per-lane timeline (sorted by start time)
    # machine/lane → sorted list of (start_offset, end_offset, state_id, op_id)
    machine_timeline: dict[
        tuple[UUID, UUID | None],
        list[tuple[float, float, UUID, UUID]],
    ] = defaultdict(list)

    horizon_start = problem.planning_horizon_start

    # Process in topological order
    for op_id in topo_order:
        a = assignment_by_op.get(op_id)
        if a is None:
            continue

        operation = ops_by_id.get(op_id)
        if operation is None:
            continue

        wc_id = a.work_center_id
        duration = a.end_time - a.start_time

        # Precedence constraint: must start after predecessor ends
        earliest_start = a.start_time
        if operation.earliest_start is not None and operation.earliest_start > earliest_start:
            earliest_start = operation.earliest_start
        if operation.predecessor_op_id is not None:
            pred_a = assignment_by_op.get(operation.predecessor_op_id)
            if pred_a is not None and pred_a.end_time > earliest_start:
                earliest_start = pred_a.end_time

        # Machine constraint: must start after previous op + setup ON THE SAME LANE
        timeline = machine_timeline[_assignment_sequence_key(a)]
        earliest_start, insert_index = _find_earliest_machine_slot(
            timeline,
            earliest_start=earliest_start,
            duration=duration,
            operation_state_id=operation.state_id,
            work_center_id=wc_id,
            setup_lookup=setup_lookup,
            horizon_start=horizon_start,
        )

        # Place the operation
        a.start_time = earliest_start
        a.end_time = earliest_start + duration

        start_offset = (a.start_time - horizon_start).total_seconds() / 60.0
        end_offset = (a.end_time - horizon_start).total_seconds() / 60.0
        timeline.insert(insert_index, (start_offset, end_offset, operation.state_id, op_id))

    if not seal_post_assembly_calendar(problem, assignments, ops_by_id, setup_lookup):
        return assignments, False
    return assignments, all(a.end_time <= problem.planning_horizon_end for a in assignments)


def topological_post_assembly(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Operation],
) -> list[Assignment] | None:
    """Public wrapper for post-assembly timing repair."""

    assembled, horizon_ok = _topological_post_assembly(problem, assignments, ops_by_id)
    if assembled is None or not horizon_ok:
        return None
    return assembled


# ---------------------------------------------------------------------------
# Subproblem construction (shared with parallel workers)
# ---------------------------------------------------------------------------


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

    Includes the full predecessor chain for precedence correctness.
    """
    all_op_ids = set(cluster_op_ids)
    pending = [op.predecessor_op_id for op in cluster_ops if op.predecessor_op_id is not None]
    while pending:
        pred_id = pending.pop()
        if pred_id in all_op_ids:
            continue
        all_op_ids.add(pred_id)
        pred = ops_by_id.get(pred_id)
        if pred is not None and pred.predecessor_op_id is not None:
            pending.append(pred.predecessor_op_id)

    sub_operations: list[Operation] = []
    for op_id in all_op_ids:
        op = ops_by_id.get(op_id)
        if op is None:
            continue
        if op_id in cluster_op_ids:
            assigned_wc = assignment_map.get(op_id)
            eligible = (
                [assigned_wc] if assigned_wc and assigned_wc in cluster_wcs else list(cluster_wcs)
            )
        else:
            assigned_wc = assignment_map.get(op_id)
            if assigned_wc is None:
                continue
            eligible = [assigned_wc]

        sub_operations.append(
            op.model_copy(
                update={
                    "eligible_wc_ids": eligible,
                    "predecessor_op_id": (
                        op.predecessor_op_id if op.predecessor_op_id in all_op_ids else None
                    ),
                    "machine_duration_overrides": {
                        wc_id: minutes
                        for wc_id, minutes in op.machine_duration_overrides.items()
                        if wc_id in set(eligible)
                    },
                }
            )
        )

    needed_state_ids = {op.state_id for op in sub_operations}
    needed_order_ids = {op.order_id for op in sub_operations}
    needed_wc_ids = set(cluster_wcs)
    for op in sub_operations:
        for wc_id in op.eligible_wc_ids:
            needed_wc_ids.add(wc_id)

    sub_states = [s for s in problem.states if s.id in needed_state_ids]
    sub_orders = [o for o in problem.orders if o.id in needed_order_ids]
    sub_wcs = [wc for wc in problem.work_centers if wc.id in needed_wc_ids]
    sub_setup = [
        e
        for e in problem.setup_matrix
        if e.work_center_id in needed_wc_ids
        and e.from_state_id in needed_state_ids
        and e.to_state_id in needed_state_ids
    ]

    sub_op_ids = {op.id for op in sub_operations}
    sub_aux_reqs = [r for r in problem.aux_requirements if r.operation_id in sub_op_ids]
    needed_aux_ids = {r.aux_resource_id for r in sub_aux_reqs}
    sub_aux = [r for r in problem.auxiliary_resources if r.id in needed_aux_ids]

    return ScheduleProblem(
        states=sub_states,
        orders=sub_orders,
        operations=sub_operations,
        work_centers=sub_wcs,
        setup_matrix=sub_setup,
        auxiliary_resources=sub_aux,
        aux_requirements=sub_aux_reqs,
        planning_horizon_start=problem.planning_horizon_start,
        planning_horizon_end=problem.planning_horizon_end,
    )


# ---------------------------------------------------------------------------
# Cut generation (capacity, nogood, load-balance, setup, critical-path)
# ---------------------------------------------------------------------------


def _generate_all_cuts(
    problem: ScheduleProblem,
    sub_assignments: list[Assignment],
    assignment_map: dict[UUID, UUID],
    benders_cuts: list[_BendersCut],
    sub_makespan: float,
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    *,
    setup_cut_top_k: int,
    local_branching_enabled: bool,
    local_branching_delta_ratio: float,
    local_branching_max_ops: int,
) -> None:
    """Generate all applicable Benders cuts from subproblem solutions.

    Cut families (2026-07 validity fixes applied):
        1. Capacity cut — REMOVED (S2: rhs was an achieved upper bound).
        2. Setup-cost / machine_tsp — REMOVED (S3: L(S) over-claims).
        3. Load-balance cut — REMOVED (S1: fake optimality certificate).
        4. Critical-path cut — REMOVED (realized contention-inflated path).
        5. Local-branching cut (few-but-strong neighborhood exclusion) — kept.
    The valid full-assignment no-good is emitted by the caller only when the
    subproblem was proven OPTIMAL.
    """
    horizon_start = problem.planning_horizon_start

    # Per-machine makespan
    machine_loads: dict[UUID, float] = {}
    by_machine: dict[UUID, list[Assignment]] = defaultdict(list)
    for a in sub_assignments:
        by_machine[a.work_center_id].append(a)
        end_offset = (a.end_time - horizon_start).total_seconds() / 60.0
        current = machine_loads.get(a.work_center_id, 0.0)
        if end_offset > current:
            machine_loads[a.work_center_id] = end_offset

    # 1. Capacity cut: REMOVED (S2 validity fix, 2026-07).
    # The former capacity cut used rhs=sub_makespan (post-assembly global
    # makespan) with a processing-only discount — an achieved upper bound, not
    # a proven minimum, invalid as a master lower bound. `bottleneck_ops` is
    # still computed below for local-branching scoping only.
    bottleneck_ops: set[UUID] = set()
    if machine_loads:
        bottleneck_wc = max(machine_loads, key=machine_loads.get)  # type: ignore[arg-type]
        bottleneck_ops = {
            op_id for op_id, wc_id in assignment_map.items() if wc_id == bottleneck_wc
        }

    # 2. Setup-cost / machine_tsp cuts: REMOVED (S3 validity fix, 2026-07).
    # These asserted `C_max >= Sum p_i + L(S)` for the set S on a machine. Even
    # in a conditional no-good form the right side is valid only if L(S) is a
    # true setup-path lower bound — but `compute_machine_tsp_lower_bound` (BHK)
    # and `compute_sequence_independent_setup_lower_bound` OVER-claim it (audit
    # S3), so the no-good right side can exceed the proven optimum. Re-enabling
    # requires a validated setup lower bound. Bound strength now comes from the
    # master capacity relaxation plus proven-optimal full-assignment no-goods.

    # 3. Load-balance bound: REMOVED (S1 fix, 2026-07).
    # The previous `load_balance` cut added `C_max >= max_k completion_k`
    # unconditionally (no y variables), where completion_k is the incumbent's
    # per-machine finish time (`machine_loads` above is completion time, not
    # processing load). That asserts `C_max >= makespan(incumbent)` for every
    # assignment, forbidding improvement and forcing a fake gap -> 0. The valid
    # y-dependent load bound is already the master capacity constraint; the
    # valid y-independent global floor is `average_capacity_lb` in
    # lower_bounds.py. Note: LBBD-HD had no `if lb_rhs > lb` guard, so this
    # implementation was even more aggressive than the base solver's.

    # 4. Critical-path cut: REMOVED (2026-07 validity fix).
    # The former cut used the incumbent's realized (contention-inflated)
    # longest path as a master right side with a processing-only discount,
    # over-claiming even on setup-free instances. `critical_ops` is still
    # computed for local-branching scoping only, not emitted as a cut.
    critical_ops, _cp_duration = _find_critical_path(
        problem,
        sub_assignments,
        ops_by_id,
    )

    # 5. Few-but-strong local branching cut (optional)
    if local_branching_enabled and assignment_map:
        scoped_ops: list[UUID]
        if critical_ops:
            scoped_ops = list(critical_ops)
        elif bottleneck_ops:
            scoped_ops = list(bottleneck_ops)
        else:
            scoped_ops = list(assignment_map.keys())

        if len(scoped_ops) > local_branching_max_ops:

            def _local_branching_duration(op_id: UUID) -> float:
                operation = ops_by_id.get(op_id)
                return float(operation.base_duration_min) if operation is not None else 0.0

            scoped_ops = sorted(
                scoped_ops,
                key=_local_branching_duration,
                reverse=True,
            )[:local_branching_max_ops]

        if scoped_ops:
            delta = max(1, round(len(scoped_ops) * local_branching_delta_ratio))
            rhs = max(0, len(scoped_ops) - delta)
            benders_cuts.append(
                _BendersCut(
                    assignment_map=dict(assignment_map),
                    kind="local_branching",
                    rhs=float(rhs),
                    bottleneck_ops=set(scoped_ops),
                )
            )


def _find_critical_path(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Operation],
) -> tuple[list[UUID], float]:
    """Find the longest realized path over precedence and machine-sequence arcs."""

    if not assignments:
        return [], 0.0

    assignment_by_op = {assignment.operation_id: assignment for assignment in assignments}
    setup_lookup = {
        (entry.work_center_id, entry.from_state_id, entry.to_state_id): float(entry.setup_minutes)
        for entry in problem.setup_matrix
    }
    predecessors: dict[UUID, list[tuple[UUID, float]]] = defaultdict(list)

    for operation in problem.operations:
        if (
            operation.predecessor_op_id is not None
            and operation.id in assignment_by_op
            and operation.predecessor_op_id in assignment_by_op
        ):
            predecessors[operation.id].append((operation.predecessor_op_id, 0.0))

    assignments_by_sequence: dict[tuple[UUID, UUID | None], list[Assignment]] = defaultdict(list)
    for assignment in assignments:
        assignments_by_sequence[_assignment_sequence_key(assignment)].append(assignment)

    for (work_center_id, _lane_id), sequence_assignments in assignments_by_sequence.items():
        sorted_assignments = sorted(
            sequence_assignments,
            key=lambda assignment: assignment.start_time,
        )
        for previous_assignment, current_assignment in itertools.pairwise(sorted_assignments):
            previous_operation = ops_by_id.get(previous_assignment.operation_id)
            current_operation = ops_by_id.get(current_assignment.operation_id)
            if previous_operation is None or current_operation is None:
                continue
            setup_duration = setup_lookup.get(
                (work_center_id, previous_operation.state_id, current_operation.state_id),
                0.0,
            )
            predecessors[current_assignment.operation_id].append(
                (previous_assignment.operation_id, setup_duration)
            )

    longest_duration: dict[UUID, float] = {}
    predecessor_choice: dict[UUID, UUID | None] = {}

    for assignment in sorted(assignments, key=lambda item: (item.end_time, item.start_time)):
        node_duration = (assignment.end_time - assignment.start_time).total_seconds() / 60.0
        best_duration = node_duration
        best_predecessor: UUID | None = None

        for predecessor_op_id, edge_duration in predecessors.get(assignment.operation_id, []):
            prior_duration = longest_duration.get(predecessor_op_id)
            if prior_duration is None:
                continue
            candidate_duration = prior_duration + edge_duration + node_duration
            if candidate_duration > best_duration:
                best_duration = candidate_duration
                best_predecessor = predecessor_op_id

        longest_duration[assignment.operation_id] = best_duration
        predecessor_choice[assignment.operation_id] = best_predecessor

    latest_op_id = max(longest_duration, key=lambda op_id: longest_duration[op_id])
    path: list[UUID] = []
    current: UUID | None = latest_op_id
    visited: set[UUID] = set()
    while current is not None and current not in visited:
        visited.add(current)
        path.append(current)
        current = predecessor_choice.get(current)

    path.reverse()
    return path, longest_duration[latest_op_id]


def find_critical_path(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Operation],
) -> tuple[list[UUID], float]:
    """Public wrapper for the realized schedule critical-path computation."""

    return _find_critical_path(problem, assignments, ops_by_id)


# ---------------------------------------------------------------------------
# Objective computation
# ---------------------------------------------------------------------------


def _compute_objective(
    problem: ScheduleProblem,
    assignments: list[Assignment],
) -> ObjectiveValues:
    """Canonical multi-objective values via ``synaps.objective.evaluate`` (F3/F10)."""
    from synaps.objective import evaluate

    return evaluate(problem, assignments)
