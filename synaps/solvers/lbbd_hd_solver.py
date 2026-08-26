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
from synaps.solvers._lbbd_assembly import stamp_parallel_lane_ids
from synaps.solvers._lbbd_cuts import (
    compute_assignment_setup_lb_total,
    compute_machine_transition_floor,
    compute_machine_tsp_lower_bound,
    compute_sequence_independent_setup_lower_bound,
    cut_pool_fingerprint,
    reported_lower_bound,
)
from synaps.solvers.coverage_outcome import refuse_unsupported_calendar, stamp_honest_coverage
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
        refused = refuse_unsupported_calendar(problem, self.name)
        if refused is not None:
            return refused
        t0 = time.monotonic()

        # ---- Configuration ----
        max_iterations: int = int(kwargs.get("max_iterations", 10))
        time_limit_s: int = int(kwargs.get("time_limit_s", 300))
        random_seed: int = int(kwargs.get("random_seed", 42))
        gap_threshold: float = float(kwargs.get("gap_threshold", 0.01))
        max_ops_per_cluster: int = int(kwargs.get("max_ops_per_cluster", 200))
        num_workers: int = int(kwargs.get("num_workers", min(8, os.cpu_count() or 4)))
        sub_num_workers: int = int(kwargs.get("sub_num_workers", 4))
        use_warm_start: bool = bool(kwargs.get("use_warm_start", True))
        setup_relaxation: bool = bool(kwargs.get("setup_relaxation", True))
        setup_cut_top_k: int = max(1, int(kwargs.get("setup_cut_top_k", 3)))
        local_branching_enabled: bool = bool(kwargs.get("local_branching_enabled", False))
        local_branching_delta_ratio: float = min(
            0.95,
            max(0.01, float(kwargs.get("local_branching_delta_ratio", 0.10))),
        )
        local_branching_max_ops: int = max(
            4,
            int(kwargs.get("local_branching_max_ops", 128)),
        )

        sub_time_limit_s: int = max(2, time_limit_s // max(max_iterations, 1))
        # D3: hard wall-clock deadline shared by all cluster solves.
        deadline = t0 + float(time_limit_s)

        # ---- Precompute lookups ----
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        ops_by_id = {op.id: op for op in problem.operations}
        orders_by_id = {o.id: o for o in problem.orders}
        setup_lookup = {
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
            for entry in problem.setup_matrix
        }
        eligible_by_op: dict[UUID, list[UUID]] = {
            op.id: (
                op.eligible_wc_ids if op.eligible_wc_ids else [wc.id for wc in problem.work_centers]
            )
            for op in problem.operations
        }

        # Precedence DAG edges: (predecessor → successor)
        dag_edges: list[tuple[UUID, UUID]] = [
            (op.predecessor_op_id, op.id)
            for op in problem.operations
            if op.predecessor_op_id is not None
        ]

        # Min-setup lower bound per machine
        min_setup_by_wc: dict[UUID, float] = {}
        if setup_relaxation:
            for wc in problem.work_centers:
                transition_floor = compute_machine_transition_floor(
                    problem,
                    eligible_by_op,
                    wc.id,
                    setup_lookup,
                )
                if transition_floor > 0:
                    min_setup_by_wc[wc.id] = transition_floor

        # ---- Measure 3: Greedy warm-start ----
        prev_assignment_map: dict[UUID, UUID] | None = None
        best_assignments: list[Assignment] = []
        best_objective = ObjectiveValues()
        best_ub = float("inf")

        if use_warm_start:
            try:
                from synaps.solvers.greedy_dispatch import GreedyDispatch

                greedy = GreedyDispatch(k1=2.0, k3=0.5)
                warm_result = greedy.solve(problem)
                if (
                    warm_result.status
                    in (
                        SolverStatus.OPTIMAL,
                        SolverStatus.FEASIBLE,
                    )
                    and warm_result.assignments
                ):
                    prev_assignment_map = {
                        a.operation_id: a.work_center_id for a in warm_result.assignments
                    }
                    best_assignments = list(warm_result.assignments)
                    best_objective = warm_result.objective or ObjectiveValues()
                    best_ub = best_objective.makespan_minutes or float("inf")
            except Exception:
                pass  # fallback: cold start

        # ---- LBBD main loop ----
        lb = 0.0
        # Ownership: benders_cuts is a local accumulator created fresh for this
        # solve() invocation. Callers must not pass a shared list; cuts are owned
        # exclusively by this call and mutated only by _register_cut() below.
        benders_cuts: list[_BendersCut] = []
        iteration_log: list[dict[str, Any]] = []
        master_warm_starts = 0
        # R10 (2026-05-03): master-LB telemetry mirrors the standard LBBD
        # solver. Each iteration records its master lower bound; the LB delta
        # observed in iteration N is attributed to the cut kinds added in
        # iteration N-1 (the cuts that are first active in master N).
        lb_evolution: list[float] = []
        ub_evolution: list[float] = []
        prev_master_bound: float = 0.0
        prev_iteration_cut_kinds: list[str] = []
        # R3 (2026-05-03): cut-pool deduplication. Identical (kind,
        # bottleneck_ops, rhs-rounded) fingerprints produce redundant HiGHS
        # rows, which only inflate the master without tightening anything.
        # The register helper is used directly for the inline nogood path;
        # post-`_generate_all_cuts` we dedup the freshly produced cuts in
        # bulk so the helper does not need to be threaded into the cut
        # generator.
        seen_cut_fingerprints: set[
            tuple[str, frozenset[UUID], frozenset[tuple[UUID, UUID]], float]
        ] = set()
        cuts_skipped_duplicate = 0
        # S2 telemetry: optimality/feasibility cuts skipped because the
        # subproblem was not proven (TIMEOUT/ERROR).
        cuts_skipped_unproven_subproblem = 0

        def _register_cut(cut: _BendersCut) -> bool:
            nonlocal cuts_skipped_duplicate
            fp = cut_pool_fingerprint(cut)
            if fp in seen_cut_fingerprints:
                cuts_skipped_duplicate += 1
                return False
            seen_cut_fingerprints.add(fp)
            benders_cuts.append(cut)
            return True

        for iteration in range(1, max_iterations + 1):
            elapsed = time.monotonic() - t0
            if elapsed >= time_limit_s:
                break

            cuts_before_iteration = len(benders_cuts)
            cut_kinds_attributed_now = list(prev_iteration_cut_kinds)

            # ---- Master Problem (Measure 2: with precedence) ----
            if prev_assignment_map is not None:
                master_warm_starts += 1

            master_result, master_proven_infeasible = _solve_precedence_aware_master(
                problem,
                eligible_by_op,
                wc_by_id,
                ops_by_id,
                dag_edges,
                benders_cuts,
                min_setup_by_wc=min_setup_by_wc,
                prev_solution=prev_assignment_map,
                master_time_limit_s=max(
                    1.0, min(deadline - time.monotonic(), float(sub_time_limit_s) + 2.0)
                ),
            )
            if master_result is None:
                failed = _hd_master_failed_result(
                    self.name,
                    t0,
                    iteration,
                    master_proven_infeasible,
                    bool(best_assignments),
                )
                if failed is not None:
                    return stamp_honest_coverage(problem, failed)
                break

            assignment_map, master_bound = master_result
            lb_delta = master_bound - prev_master_bound
            lb_evolution.append(master_bound)
            lb = max(lb, master_bound)
            prev_assignment_map = assignment_map
            prev_master_bound = master_bound

            # ---- Measure 1: Balanced partitioning ----
            clusters = partition_machines(
                problem,
                assignment_map,
                max_ops_per_cluster=max_ops_per_cluster,
            )

            # ---- Measure 4: Parallel subproblems ----
            sub_result = _solve_subproblems_parallel(
                problem,
                assignment_map,
                clusters,
                wc_by_id,
                ops_by_id,
                orders_by_id,
                sub_time_limit_s,
                random_seed,
                num_workers=num_workers,
                sub_num_workers=sub_num_workers,
                deadline=deadline,
            )

            if sub_result[0] is None:
                _sub_ok, _sub_mk, _sub_opt, sub_infeasible_proven = sub_result
                if sub_infeasible_proven:
                    # Proven INFEASIBLE → excluding this assignment is sound.
                    _register_cut(
                        _BendersCut(
                            assignment_map=dict(assignment_map),
                            kind="nogood",
                            rhs=0.0,
                            bottleneck_ops=set(),
                        )
                    )
                else:
                    # S2 gate: a TIMEOUT/ERROR proves nothing; a no-good here
                    # could exclude the optimum and inflate the master bound.
                    cuts_skipped_unproven_subproblem += 1
                iteration_log.append(
                    {
                        "iteration": iteration,
                        "master_bound": master_bound,
                        "sub_makespan": None,
                        "lb_delta": lb_delta,
                        "cut_kinds_attributed": cut_kinds_attributed_now,
                        "status": (
                            "sub_infeasible" if sub_infeasible_proven else "sub_unproven_failure"
                        ),
                    }
                )
                prev_iteration_cut_kinds = [
                    cut.kind for cut in benders_cuts[cuts_before_iteration:]
                ]
                continue

            sub_assignments, sub_makespan, sub_proven_optimal, _ = sub_result
            assert sub_assignments is not None  # narrowed by the `sub_result[0] is None` guard

            # ---- Measure 5: Accelerated post-assembly (F3 lane-aware) ----
            assembled, horizon_ok = _topological_post_assembly(problem, sub_assignments, ops_by_id)
            if assembled is None or not horizon_ok:
                # Horizon overflow / assembly failure is unproven (S2) — do not
                # emit a cut and do not track as an incumbent.
                cuts_skipped_unproven_subproblem += 1
                iteration_log.append(
                    {
                        "iteration": iteration,
                        "master_bound": master_bound,
                        "status": "post_assembly_horizon_or_failure",
                    }
                )
                prev_iteration_cut_kinds = [
                    cut.kind for cut in benders_cuts[cuts_before_iteration:]
                ]
                continue
            sub_assignments = assembled
            horizon_start = problem.planning_horizon_start
            sub_makespan = (
                max((a.end_time - horizon_start).total_seconds() / 60.0 for a in sub_assignments)
                if sub_assignments
                else 0.0
            )

            ub = sub_makespan

            # Track best
            if ub < best_ub:
                best_ub = ub
                ub_evolution.append(best_ub)
                best_assignments = sub_assignments
                best_objective = _compute_objective(problem, sub_assignments)

            iteration_log.append(
                {
                    "iteration": iteration,
                    "master_bound": master_bound,
                    "sub_makespan": sub_makespan,
                    "gap": (ub - lb) / max(ub, 1e-9),
                    "lb_delta": lb_delta,
                    "cut_kinds_attributed": cut_kinds_attributed_now,
                    "status": "feasible",
                    "cluster_count": len(clusters),
                    "max_cluster_ops": max(
                        (
                            sum(1 for op_id, wc_id in assignment_map.items() if wc_id in c)
                            for c in clusters
                        ),
                        default=0,
                    ),
                }
            )

            # Convergence check
            gap = (best_ub - lb) / max(best_ub, 1e-9)
            if gap < gap_threshold:
                prev_iteration_cut_kinds = []
                break

            # ---- Generate Benders cuts ----
            # S2 (2026-07): a full-assignment no-good is emitted only when every
            # cluster was proven OPTIMAL, so its cost is captured in best_ub and
            # `min(master_bound, best_ub)` stays a valid global lower bound.
            cuts_before_gen = len(benders_cuts)
            if sub_proven_optimal:
                _register_cut(
                    _BendersCut(
                        assignment_map=dict(assignment_map),
                        kind="nogood",
                        rhs=0.0,
                        bottleneck_ops=set(),
                    )
                )
            else:
                cuts_skipped_unproven_subproblem += 1
            _generate_all_cuts(
                problem,
                sub_assignments,
                assignment_map,
                benders_cuts,
                sub_makespan,
                wc_by_id,
                ops_by_id,
                setup_cut_top_k=setup_cut_top_k,
                local_branching_enabled=local_branching_enabled,
                local_branching_delta_ratio=local_branching_delta_ratio,
                local_branching_max_ops=local_branching_max_ops,
            )
            # R3: bulk-dedup the cuts that `_generate_all_cuts` just produced
            # so identical fingerprints from earlier iterations do not stack.
            freshly_generated = benders_cuts[cuts_before_gen:]
            del benders_cuts[cuts_before_gen:]
            for fresh_cut in freshly_generated:
                _register_cut(fresh_cut)

            prev_iteration_cut_kinds = [cut.kind for cut in benders_cuts[cuts_before_iteration:]]

        # ---- Build final result ----
        status = SolverStatus.FEASIBLE if best_assignments else SolverStatus.TIMEOUT
        # D2: fully deterministic assignment order (with deterministic cluster
        # collection below and the D1 strict CP-SAT default).
        best_assignments = sorted(
            best_assignments,
            key=lambda a: (str(a.work_center_id), a.start_time, str(a.operation_id)),
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        cut_kinds: dict[str, int] = {}
        for cut in benders_cuts:
            cut_kinds[cut.kind] = cut_kinds.get(cut.kind, 0) + 1

        # Reported lower bound (2026-07 validity fix, audit S1/S2/S3): the
        # cluster subproblem re-assembles independent clusters, so its makespan
        # is an UPPER bound on the assignment's true cost, not a proven
        # minimum. Nogood cuts drive the search but must not tighten the
        # reported lower bound. The only provably-valid bound is the cut-free
        # master relaxation (first iteration's bound).
        #
        # N5 (audit v3): report the RAW relaxation, never min(relaxation,
        # best_ub) — the clamp would make lb <= ub true by construction and
        # silence an invalid relaxation; flag the violation instead.
        raw_relaxation = lb_evolution[0] if lb_evolution else 0.0
        reported_lb, lb_invariant_violated = reported_lower_bound(raw_relaxation, best_ub)
        if lb_invariant_violated:
            warnings.warn(
                f"LBBD-HD lower-bound invariant violated: raw master relaxation "
                f"{raw_relaxation} exceeds incumbent {best_ub}; the relaxation "
                f"is not a valid lower bound.",
                stacklevel=2,
            )

        # R10 (2026-05-03): aggregate per-iteration LB deltas back to the cut
        # kinds that drove them. Iteration-1 (no attributable cuts) and any
        # post-convergence delta accrue to the synthetic master_relaxation
        # source, mirroring the standard LBBD reporting.
        cut_kind_lb_contribution: dict[str, float] = {}
        for entry in iteration_log:
            delta = float(entry.get("lb_delta", 0.0) or 0.0)
            if delta <= 0.0:
                continue
            kinds = entry.get("cut_kinds_attributed") or []
            if not kinds:
                cut_kind_lb_contribution["master_relaxation"] = (
                    cut_kind_lb_contribution.get("master_relaxation", 0.0) + delta
                )
                continue
            share = delta / float(len(kinds))
            for kind in kinds:
                cut_kind_lb_contribution[kind] = cut_kind_lb_contribution.get(kind, 0.0) + share

        # N2 (audit v3): expose whether the Benders master actually learned.
        benders_active = len(benders_cuts) > 0
        quality_warning = None if benders_active else "lbbd_no_cuts_degenerate"
        return stamp_honest_coverage(
            problem,
            ScheduleResult(
                solver_name=self.name,
                status=status,
                assignments=best_assignments,
                objective=best_objective,
                duration_ms=elapsed_ms,
                random_seed=random_seed,
                metadata={
                    "iterations": len(iteration_log),
                    "lower_bound": reported_lb,
                    "upper_bound": best_ub,
                    "gap": (best_ub - reported_lb) / max(best_ub, 1e-9)
                    if best_ub < float("inf")
                    else None,
                    "benders_active": benders_active,
                    "quality_warning": quality_warning,
                    "lower_bound_invariant_violated": lb_invariant_violated,
                    "lower_bound_method": "master_relaxation_benders_hd",
                    "lower_bound_components": {
                        "master_relaxation_lb": reported_lb,
                        "assignment_setup_lb": compute_assignment_setup_lb_total(
                            problem, best_assignments
                        ),
                    },
                    "iteration_log": iteration_log,
                    "lb_evolution": lb_evolution,
                    "ub_evolution": ub_evolution,
                    "cut_kind_lb_contribution": cut_kind_lb_contribution,
                    "gap_threshold": gap_threshold,
                    "setup_relaxation": setup_relaxation,
                    "setup_cut_top_k": setup_cut_top_k,
                    "local_branching_enabled": local_branching_enabled,
                    "local_branching_delta_ratio": local_branching_delta_ratio,
                    "local_branching_max_ops": local_branching_max_ops,
                    "master_warm_start_iterations": master_warm_starts,
                    "max_ops_per_cluster": max_ops_per_cluster,
                    "num_workers": num_workers,
                    "warm_start_used": use_warm_start,
                    "cut_pool": {
                        "size": len(benders_cuts),
                        "kinds": cut_kinds,
                        "skipped_duplicate": cuts_skipped_duplicate,
                        "skipped_unproven_subproblem": cuts_skipped_unproven_subproblem,
                    },
                },
            ),
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
    """
    h = highspy.Highs()
    h.silent()
    # D3: bound the master MILP by the remaining wall budget (see lbbd_solver).
    if master_time_limit_s is not None:
        h.setOptionValue("time_limit", max(1.0, float(master_time_limit_s)))

    # ---- Index maps ----
    var_index: dict[tuple[UUID, UUID], int] = {}
    col_idx = 0

    for op in problem.operations:
        for wc_id in eligible_by_op[op.id]:
            var_index[(op.id, wc_id)] = col_idx
            col_idx += 1

    n_y = col_idx

    # Continuous timing variables: start[i], end[i] for each operation
    op_list = list(problem.operations)
    op_to_idx = {op.id: i for i, op in enumerate(op_list)}

    start_base = n_y
    end_base = start_base + len(op_list)
    cmax_idx = end_base + len(op_list)
    n_vars = cmax_idx + 1

    # ---- Column setup ----
    costs = [0.0] * n_vars
    costs[cmax_idx] = 1.0  # minimize C_max

    lower = [0.0] * n_vars
    upper = [1.0] * n_y  # y binary
    # start, end, C_max continuous [0, inf)
    upper.extend([highspy.kHighsInf] * (n_vars - n_y))

    h.addVars(n_vars, np.array(lower), np.array(upper))
    h.changeColsCost(n_vars, np.arange(n_vars, dtype=np.int32), np.array(costs))

    # Set integrality for binary y vars
    if n_y > 0:
        y_indices = np.arange(n_y, dtype=np.int32)
        y_types = np.array([highspy.HighsVarType.kInteger] * n_y)
        h.changeColsIntegrality(n_y, y_indices, y_types)

    # ---- Constraint 1: Unique assignment ----
    for op in problem.operations:
        indices = [var_index[(op.id, wc_id)] for wc_id in eligible_by_op[op.id]]
        coeffs = [1.0] * len(indices)
        h.addRow(
            1.0,
            1.0,
            len(indices),
            np.array(indices, dtype=np.int32),
            np.array(coeffs),
        )

    # ---- Constraint 2: Timing linkage ----
    # end[i] = start[i] + ∑_k P[i,k] · y[i,k]
    # Rearranged: end[i] - start[i] - ∑ P·y = 0
    for op in problem.operations:
        op_idx = op_to_idx[op.id]
        s_idx = start_base + op_idx
        e_idx = end_base + op_idx

        indices = [e_idx, s_idx]
        coeffs = [1.0, -1.0]

        for wc_id in eligible_by_op[op.id]:
            wc: Any = wc_by_id.get(wc_id)
            if wc is None:
                from types import SimpleNamespace

                wc = SimpleNamespace(id=wc_id, speed_factor=1.0)
            # CP-SAT duration semantics (T-30 aware) so the master timing
            # model matches what the subproblem model realises (S2/S3 validity).
            duration = float(duration_minutes_for(op, wc))
            indices.append(var_index[(op.id, wc_id)])
            coeffs.append(-duration)

        h.addRow(
            0.0,
            0.0,
            len(indices),
            np.array(indices, dtype=np.int32),
            np.array(coeffs),
        )

    # ---- Constraint 3: Precedence ----
    # start[j] ≥ end[i]  →  start[j] - end[i] ≥ 0
    for pred_id, succ_id in dag_edges:
        if pred_id not in op_to_idx or succ_id not in op_to_idx:
            continue
        e_pred = end_base + op_to_idx[pred_id]
        s_succ = start_base + op_to_idx[succ_id]
        h.addRow(
            0.0,
            highspy.kHighsInf,
            2,
            np.array([s_succ, e_pred], dtype=np.int32),
            np.array([1.0, -1.0]),
        )

    # ---- Constraint 4: Relaxed capacity ----
    for wc in problem.work_centers:
        cap_indices: list[int] = []
        cap_coeffs: list[float] = []
        cap_upper_bound = 0.0
        for op in problem.operations:
            key = (op.id, wc.id)
            if key in var_index:
                # CP-SAT duration semantics divided by parallel lanes: a
                # max_parallel-lane machine finishes load L in L / lanes, so
                # the relaxation stays a valid lower bound (see lbbd_solver).
                lanes = float(max(1, wc.max_parallel))
                duration = float(duration_minutes_for(op, wc)) / lanes
                cap_indices.append(var_index[key])
                cap_coeffs.append(duration)
        if not cap_indices:
            continue
        if min_setup_by_wc and wc.id in min_setup_by_wc and wc.max_parallel <= 1:
            ms = min_setup_by_wc[wc.id]
            if ms > 0:
                cap_coeffs = [c + ms for c in cap_coeffs]
                cap_upper_bound = ms
        # ∑ P·y - C_max ≤ 0
        cap_indices.append(cmax_idx)
        cap_coeffs.append(-1.0)
        h.addRow(
            -highspy.kHighsInf,
            cap_upper_bound,
            len(cap_indices),
            np.array(cap_indices, dtype=np.int32),
            np.array(cap_coeffs),
        )

    # ---- Constraint 5: C_max ≥ end[i] for all ops ----
    for op in problem.operations:
        e_idx = end_base + op_to_idx[op.id]
        # C_max - end[i] ≥ 0
        h.addRow(
            0.0,
            highspy.kHighsInf,
            2,
            np.array([cmax_idx, e_idx], dtype=np.int32),
            np.array([1.0, -1.0]),
        )

    # ---- Constraint 6: Benders cuts ----
    for cut in cuts:
        if cut.kind == "nogood":
            indices = []
            coeffs = []
            for op_id, wc_id in cut.assignment_map.items():
                key = (op_id, wc_id)
                if key in var_index:
                    indices.append(var_index[key])
                    coeffs.append(1.0)
            if not indices:
                raise ValueError(
                    "LBBD-HD nogood cut has no bindable variables; refusing silent skip "
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
        elif cut.kind == "local_branching":
            lb_indices: list[int] = []
            for op_id in cut.bottleneck_ops:
                lb_wc = cut.assignment_map.get(op_id)
                if lb_wc is None:
                    continue
                key = (op_id, lb_wc)
                if key in var_index:
                    lb_indices.append(var_index[key])
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

    # ---- Solve ----
    h.changeObjectiveSense(highspy.ObjSense.kMinimize)

    if prev_solution is not None and hasattr(h, "setSolution"):
        hint = [0.0] * n_vars
        for op in problem.operations:
            prev_wc = prev_solution.get(op.id)
            for wc_id in eligible_by_op[op.id]:
                key = (op.id, wc_id)
                if key in var_index:
                    hint[var_index[key]] = 1.0 if wc_id == prev_wc else 0.0
        # Set timing hints from greedy (rough estimates)
        horizon_minutes = (
            problem.planning_horizon_end - problem.planning_horizon_start
        ).total_seconds() / 60
        hint[cmax_idx] = horizon_minutes
        h.setSolution(n_vars, np.arange(n_vars, dtype=np.int32), np.array(hint))

    h.run()

    status = h.getInfoValue("primal_solution_status")[1]
    if status != 2:  # 2 = feasible
        proven_infeasible = h.getModelStatus() == highspy.HighsModelStatus.kInfeasible
        return None, proven_infeasible

    solution = h.getSolution()
    col_values = solution.col_value

    # Extract assignment
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
    # D3 validity: a time-limited master returns a primal incumbent (upper
    # bound on the master optimum); use the proven dual bound so the reported
    # relaxation lower bound stays valid (equals primal at optimality).
    try:
        dual_bound = float(h.getInfoValue("mip_dual_bound")[1])
    except (IndexError, TypeError, ValueError):
        dual_bound = master_bound
    if math.isfinite(dual_bound):
        master_bound = min(master_bound, dual_bound)
    return (assignment_map, master_bound), False


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
) -> tuple[list[Assignment] | None, float, bool, bool]:
    """Solve CP-SAT subproblems in parallel via ProcessPoolExecutor.

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
    all_proven_optimal = True

    effective_workers = min(num_workers, len(clusters))

    with ProcessPoolExecutor(max_workers=effective_workers) as pool:
        futures = {}
        for cluster_index, cluster_wcs in enumerate(clusters):
            wc_list = [str(w) for w in cluster_wcs]
            future = pool.submit(
                _solve_single_cluster,
                problem_dict,
                wc_list,
                assignment_items,
                sub_time_limit_s,
                random_seed,
                sub_num_workers,
            )
            futures[future] = cluster_index

        # D2: buffer by cluster index so merge order is independent of
        # completion order (as_completed is non-deterministic).
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

    horizon_ok = all(a.end_time <= problem.planning_horizon_end for a in assignments)
    return assignments, horizon_ok


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
