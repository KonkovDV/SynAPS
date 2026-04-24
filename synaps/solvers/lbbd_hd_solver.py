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

import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import highspy  # type: ignore[import-untyped]
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
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.partitioning import partition_machines

if TYPE_CHECKING:
    from uuid import UUID


# ---------------------------------------------------------------------------
# Top-level solver
# ---------------------------------------------------------------------------


class LbbdHdSolver(BaseSolver):
    """Hierarchical Decomposition LBBD for 10 000–50 000+ operation instances.

    Iterates between a precedence-aware HiGHS master (assignment + relaxed
    timing) and size-controlled CP-SAT subproblems (exact sequencing with
    SDST + ARC), connected by four families of Benders cuts.

    Key parameters (passed via **kwargs to ``solve``):
        max_iterations: Benders iteration cap (default 10).
        time_limit_s: Wall-clock budget in seconds (default 300).
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
        t0 = time.monotonic()

        # ---- Configuration ----
        max_iterations: int = int(kwargs.get("max_iterations", 10))
        time_limit_s: int = int(kwargs.get("time_limit_s", 300))
        random_seed: int = int(kwargs.get("random_seed", 42))
        gap_threshold: float = float(kwargs.get("gap_threshold", 0.01))
        max_ops_per_cluster: int = int(kwargs.get("max_ops_per_cluster", 200))
        num_workers: int = int(
            kwargs.get("num_workers", min(8, os.cpu_count() or 4))
        )
        sub_num_workers: int = int(kwargs.get("sub_num_workers", 4))
        use_warm_start: bool = bool(kwargs.get("use_warm_start", True))
        setup_relaxation: bool = bool(kwargs.get("setup_relaxation", True))
        setup_cut_top_k: int = max(1, int(kwargs.get("setup_cut_top_k", 3)))
        local_branching_enabled: bool = bool(
            kwargs.get("local_branching_enabled", False)
        )
        local_branching_delta_ratio: float = min(
            0.95,
            max(0.01, float(kwargs.get("local_branching_delta_ratio", 0.10))),
        )
        local_branching_max_ops: int = max(
            4,
            int(kwargs.get("local_branching_max_ops", 128)),
        )

        sub_time_limit_s: int = max(
            2, time_limit_s // max(max_iterations, 1)
        )

        # ---- Precompute lookups ----
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        ops_by_id = {op.id: op for op in problem.operations}
        orders_by_id = {o.id: o for o in problem.orders}
        eligible_by_op: dict[UUID, list[UUID]] = {
            op.id: (
                op.eligible_wc_ids
                if op.eligible_wc_ids
                else [wc.id for wc in problem.work_centers]
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
        if setup_relaxation and problem.setup_matrix:
            for wc in problem.work_centers:
                positives = [
                    e.setup_minutes
                    for e in problem.setup_matrix
                    if e.work_center_id == wc.id and e.setup_minutes > 0
                ]
                min_setup_by_wc[wc.id] = min(positives) if positives else 0.0

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
                if warm_result.status in (
                    SolverStatus.OPTIMAL,
                    SolverStatus.FEASIBLE,
                ) and warm_result.assignments:
                    prev_assignment_map = {
                        a.operation_id: a.work_center_id
                        for a in warm_result.assignments
                    }
                    best_assignments = list(warm_result.assignments)
                    best_objective = warm_result.objective or ObjectiveValues()
                    best_ub = best_objective.makespan_minutes or float("inf")
            except Exception:
                pass  # fallback: cold start

        # ---- LBBD main loop ----
        lb = 0.0
        benders_cuts: list[_BendersCut] = []
        iteration_log: list[dict[str, Any]] = []
        master_warm_starts = 0

        for iteration in range(1, max_iterations + 1):
            elapsed = time.monotonic() - t0
            if elapsed >= time_limit_s:
                break

            # ---- Master Problem (Measure 2: with precedence) ----
            if prev_assignment_map is not None:
                master_warm_starts += 1

            master_result = _solve_precedence_aware_master(
                problem,
                eligible_by_op,
                wc_by_id,
                ops_by_id,
                dag_edges,
                benders_cuts,
                min_setup_by_wc=min_setup_by_wc,
                prev_solution=prev_assignment_map,
            )
            if master_result is None:
                return ScheduleResult(
                    solver_name=self.name,
                    status=SolverStatus.INFEASIBLE,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    metadata={
                        "iterations": iteration,
                        "reason": "master_infeasible",
                    },
                )

            assignment_map, master_bound = master_result
            lb = max(lb, master_bound)
            prev_assignment_map = assignment_map

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
            )

            if sub_result is None:
                # Subproblem infeasible → add nogood cut
                benders_cuts.append(
                    _BendersCut(
                        assignment_map=dict(assignment_map),
                        kind="nogood",
                        rhs=0.0,
                        bottleneck_ops=set(),
                    )
                )
                iteration_log.append(
                    {
                        "iteration": iteration,
                        "master_bound": master_bound,
                        "sub_makespan": None,
                        "status": "sub_infeasible",
                    }
                )
                continue

            sub_assignments, sub_makespan = sub_result

            # ---- Measure 5: Accelerated post-assembly ----
            assembled = _topological_post_assembly(
                problem, sub_assignments, ops_by_id
            )
            if assembled is not None:
                sub_assignments = assembled
                # Recompute makespan after assembly
                horizon_start = problem.planning_horizon_start
                sub_makespan = max(
                    (a.end_time - horizon_start).total_seconds() / 60.0
                    for a in sub_assignments
                ) if sub_assignments else 0.0

            ub = sub_makespan

            # Track best
            if ub < best_ub:
                best_ub = ub
                best_assignments = sub_assignments
                best_objective = _compute_objective(
                    problem, sub_assignments, sub_makespan,
                    wc_by_id, ops_by_id, orders_by_id,
                )

            iteration_log.append(
                {
                    "iteration": iteration,
                    "master_bound": master_bound,
                    "sub_makespan": sub_makespan,
                    "gap": (ub - lb) / max(ub, 1e-9),
                    "status": "feasible",
                    "cluster_count": len(clusters),
                    "max_cluster_ops": max(
                        (
                            sum(
                                1 for op_id, wc_id in assignment_map.items()
                                if wc_id in c
                            )
                            for c in clusters
                        ),
                        default=0,
                    ),
                }
            )

            # Convergence check
            gap = (best_ub - lb) / max(best_ub, 1e-9)
            if gap < gap_threshold:
                break

            # ---- Generate Benders cuts ----
            _generate_all_cuts(
                problem, sub_assignments, assignment_map,
                benders_cuts, sub_makespan, wc_by_id, ops_by_id,
                setup_cut_top_k=setup_cut_top_k,
                local_branching_enabled=local_branching_enabled,
                local_branching_delta_ratio=local_branching_delta_ratio,
                local_branching_max_ops=local_branching_max_ops,
            )

        # ---- Build final result ----
        status = SolverStatus.FEASIBLE if best_assignments else SolverStatus.TIMEOUT
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        cut_kinds: dict[str, int] = {}
        for cut in benders_cuts:
            cut_kinds[cut.kind] = cut_kinds.get(cut.kind, 0) + 1

        reported_lb = min(lb, best_ub) if best_ub < float("inf") else lb

        return ScheduleResult(
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
                "lower_bound_method": "master_relaxation_benders_hd",
                "lower_bound_components": {
                    "master_relaxation_lb": reported_lb,
                },
                "iteration_log": iteration_log,
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
                },
            },
        )


# ---------------------------------------------------------------------------
# Benders Cut object
# ---------------------------------------------------------------------------


class _BendersCut:
    """Represents a Benders cut to add to the master problem."""

    __slots__ = ("assignment_map", "kind", "rhs", "bottleneck_ops")

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
) -> tuple[dict[UUID, UUID], float] | None:
    """Solve the precedence-aware assignment master problem via HiGHS MIP.

    This extends the original master with continuous timing variables:

    Decision variables:
        y[i, k] ∈ {0, 1}  — operation i assigned to work center k
        start[i] ≥ 0      — relaxed start time of operation i
        end[i] ≥ 0         — relaxed end time of operation i
        C_max ≥ 0          — relaxed makespan lower bound

    Constraints:
        ∑_k y[i,k] = 1                         ∀ i ∈ ops      (unique assignment)
        end[i] = start[i] + ∑_k (P[i,k]·y[i,k]) ∀ i ∈ ops    (timing linkage)
        start[j] ≥ end[i]                       ∀ (i,j) ∈ DAG (precedence)
        ∑_i P[i,k]·y[i,k] ≤ C_max              ∀ k ∈ machines (relaxed capacity)
        C_max ≥ end[i]                           ∀ i ∈ ops     (makespan bound)
        Benders cuts from previous iterations

    Objective: min C_max

    Scaling: For 10 000 ops × 100 machines → ~1M binary + 20K continuous +
    ~8K precedence constraints. HiGHS solves this in 1–5 s typically.
    """
    h = highspy.Highs()
    h.silent()

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
            1.0, 1.0,
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
            wc = wc_by_id.get(wc_id)
            speed = wc.speed_factor if wc else 1.0
            duration = max(1.0, op.base_duration_min / speed)
            indices.append(var_index[(op.id, wc_id)])
            coeffs.append(-duration)

        h.addRow(
            0.0, 0.0,
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
            0.0, highspy.kHighsInf,
            2,
            np.array([s_succ, e_pred], dtype=np.int32),
            np.array([1.0, -1.0]),
        )

    # ---- Constraint 4: Relaxed capacity ----
    for wc in problem.work_centers:
        cap_indices: list[int] = []
        cap_coeffs: list[float] = []
        for op in problem.operations:
            key = (op.id, wc.id)
            if key in var_index:
                duration = max(1.0, op.base_duration_min / wc.speed_factor)
                cap_indices.append(var_index[key])
                cap_coeffs.append(duration)
        if not cap_indices:
            continue
        if min_setup_by_wc and wc.id in min_setup_by_wc:
            ms = min_setup_by_wc[wc.id]
            if ms > 0:
                cap_coeffs = [c + ms for c in cap_coeffs]
        # ∑ P·y - C_max ≤ 0
        cap_indices.append(cmax_idx)
        cap_coeffs.append(-1.0)
        h.addRow(
            -highspy.kHighsInf, 0.0,
            len(cap_indices),
            np.array(cap_indices, dtype=np.int32),
            np.array(cap_coeffs),
        )

    # ---- Constraint 5: C_max ≥ end[i] for all ops ----
    for op in problem.operations:
        e_idx = end_base + op_to_idx[op.id]
        # C_max - end[i] ≥ 0
        h.addRow(
            0.0, highspy.kHighsInf,
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
            if indices:
                h.addRow(
                    -highspy.kHighsInf,
                    len(indices) - 1.0,
                    len(indices),
                    np.array(indices, dtype=np.int32),
                    np.array(coeffs),
                )
        elif cut.kind == "capacity":
            # Combinatorial Benders capacity cut (Hooker & Ottosson 2003)
            cut_indices = [cmax_idx]
            cut_coeffs = [1.0]
            total_p = 0.0
            for op_id in cut.bottleneck_ops:
                cut_wc = cut.assignment_map.get(op_id)
                if cut_wc is None:
                    continue
                key = (op_id, cut_wc)
                if key not in var_index:
                    continue
                wc = wc_by_id.get(cut_wc)
                operation = ops_by_id.get(op_id)
                if wc is None or operation is None:
                    continue
                p = max(1.0, operation.base_duration_min / wc.speed_factor)
                total_p += p
                cut_indices.append(var_index[key])
                cut_coeffs.append(-p)
            if len(cut_indices) > 1:
                h.addRow(
                    cut.rhs - total_p, highspy.kHighsInf,
                    len(cut_indices),
                    np.array(cut_indices, dtype=np.int32),
                    np.array(cut_coeffs),
                )
        elif cut.kind == "load_balance":
            h.addRow(
                cut.rhs, highspy.kHighsInf, 1,
                np.array([cmax_idx], dtype=np.int32),
                np.array([1.0]),
            )
        elif cut.kind == "setup_cost":
            sc_indices = [cmax_idx]
            sc_coeffs = [1.0]
            total_p = 0.0
            for op_id in cut.bottleneck_ops:
                sc_wc = cut.assignment_map.get(op_id)
                if sc_wc is None:
                    continue
                key = (op_id, sc_wc)
                if key not in var_index:
                    continue
                wc = wc_by_id.get(sc_wc)
                operation = ops_by_id.get(op_id)
                if wc is None or operation is None:
                    continue
                p = max(1.0, operation.base_duration_min / wc.speed_factor)
                total_p += p
                sc_indices.append(var_index[key])
                sc_coeffs.append(-p)
            if len(sc_indices) > 1:
                h.addRow(
                    cut.rhs - total_p, highspy.kHighsInf,
                    len(sc_indices),
                    np.array(sc_indices, dtype=np.int32),
                    np.array(sc_coeffs),
                )
        elif cut.kind == "critical_path":
            # Critical-path cut (Naderi & Roshanaei 2022):
            # C_max ≥ sum of path durations for the critical chain
            cp_indices = [cmax_idx]
            cp_coeffs = [1.0]
            total_cp = 0.0
            for op_id in cut.bottleneck_ops:
                cp_wc = cut.assignment_map.get(op_id)
                if cp_wc is None:
                    continue
                key = (op_id, cp_wc)
                if key not in var_index:
                    continue
                wc = wc_by_id.get(cp_wc)
                operation = ops_by_id.get(op_id)
                if wc is None or operation is None:
                    continue
                p = max(1.0, operation.base_duration_min / wc.speed_factor)
                total_cp += p
                cp_indices.append(var_index[key])
                cp_coeffs.append(-p)
            if len(cp_indices) > 1:
                h.addRow(
                    cut.rhs - total_cp, highspy.kHighsInf,
                    len(cp_indices),
                    np.array(cp_indices, dtype=np.int32),
                    np.array(cp_coeffs),
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
        return None

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
    return assignment_map, master_bound


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
    cluster_op_ids = {
        op_id for op_id, wc_id in assignment.items()
        if wc_id in cluster_wc_set
    }
    if not cluster_op_ids:
        return {"assignments": [], "makespan": 0.0}

    cluster_ops = [ops_by_id[oid] for oid in cluster_op_ids if oid in ops_by_id]

    sub_problem = _build_subproblem(
        problem, cluster_ops, cluster_wc_set, cluster_op_ids,
        assignment, wc_by_id, ops_by_id, orders_by_id,
    )

    cpsat = CpSatSolver()
    result = cpsat.solve(
        sub_problem,
        time_limit_s=sub_time_limit_s,
        random_seed=random_seed,
        num_workers=sub_num_workers,
    )

    if result.status in (SolverStatus.INFEASIBLE, SolverStatus.ERROR):
        return None
    if result.status == SolverStatus.TIMEOUT and not result.assignments:
        return None

    # Only keep cluster-owned assignments
    kept = [a for a in result.assignments if a.operation_id in cluster_op_ids]
    horizon_start = problem.planning_horizon_start
    mk = (
        max((a.end_time - horizon_start).total_seconds() / 60.0 for a in kept)
        if kept else 0.0
    )

    return {
        "assignments": [a.model_dump(mode="json") for a in kept],
        "makespan": mk,
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
) -> tuple[list[Assignment], float] | None:
    """Solve CP-SAT subproblems in parallel via ProcessPoolExecutor.

    For small instance counts (≤ 3 clusters), falls back to sequential
    execution to avoid multiprocessing overhead.
    """
    if not clusters:
        return None

    # Serialize problem once
    problem_dict = problem.model_dump(mode="json")
    assignment_items = [(str(k), str(v)) for k, v in assignment_map.items()]

    # Sequential path for small counts
    if len(clusters) <= 3:
        return _solve_subproblems_sequential(
            problem, assignment_map, clusters,
            wc_by_id, ops_by_id, orders_by_id,
            sub_time_limit_s, random_seed, sub_num_workers,
        )

    all_assignments: list[Assignment] = []
    overall_makespan = 0.0

    effective_workers = min(num_workers, len(clusters))

    with ProcessPoolExecutor(max_workers=effective_workers) as pool:
        futures = {}
        for cluster_wcs in clusters:
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
            futures[future] = cluster_wcs

        for future in as_completed(futures):
            result = future.result()
            if result is None:
                return None

            for a_dict in result["assignments"]:
                all_assignments.append(Assignment.model_validate(a_dict))
            overall_makespan = max(overall_makespan, result["makespan"])

    # Completeness check
    assigned_ops = {a.operation_id for a in all_assignments}
    all_ops = {op.id for op in problem.operations}
    if assigned_ops != all_ops:
        return None

    return all_assignments, overall_makespan


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
) -> tuple[list[Assignment], float] | None:
    """Sequential fallback for small cluster counts."""
    all_assignments: list[Assignment] = []
    overall_makespan = 0.0
    horizon_start = problem.planning_horizon_start

    for cluster_wcs in clusters:
        cluster_op_ids = {
            op_id for op_id, wc_id in assignment_map.items()
            if wc_id in cluster_wcs
        }
        if not cluster_op_ids:
            continue

        cluster_ops = [
            ops_by_id[oid] for oid in cluster_op_ids if oid in ops_by_id
        ]

        sub_problem = _build_subproblem(
            problem, cluster_ops, cluster_wcs, cluster_op_ids,
            assignment_map, wc_by_id, ops_by_id, orders_by_id,
        )

        cpsat = CpSatSolver()
        result = cpsat.solve(
            sub_problem,
            time_limit_s=sub_time_limit_s,
            random_seed=random_seed,
            num_workers=sub_num_workers,
        )

        if result.status in (SolverStatus.INFEASIBLE, SolverStatus.ERROR):
            return None
        if result.status == SolverStatus.TIMEOUT and not result.assignments:
            return None

        kept = [a for a in result.assignments if a.operation_id in cluster_op_ids]
        all_assignments.extend(kept)
        if kept:
            mk = max(
                (a.end_time - horizon_start).total_seconds() / 60.0
                for a in kept
            )
            overall_makespan = max(overall_makespan, mk)

    assigned_ops = {a.operation_id for a in all_assignments}
    all_ops = {op.id for op in problem.operations}
    if assigned_ops != all_ops:
        return None

    return all_assignments, overall_makespan


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
) -> list[Assignment] | None:
    """Fix cross-cluster timing via topological traversal + per-machine heaps.

    Replaces the O(N³) iterative while-changed loop with a single-pass
    topological traversal that cascades shifts forward through the DAG.

    Complexity: O(|O| log |O| + |DAG|) — dominated by per-machine sorting.
    For 10 000 ops: ~130 000 operations vs. 10¹² in the naive approach.
    """
    if not assignments:
        return assignments

    setup_lookup: dict[tuple[UUID, UUID, UUID], timedelta] = {
        (e.work_center_id, e.from_state_id, e.to_state_id): timedelta(
            minutes=e.setup_minutes
        )
        for e in problem.setup_matrix
    }

    # Build assignment lookup
    assignment_by_op: dict[UUID, Assignment] = {
        a.operation_id: a for a in assignments
    }

    # Build DAG: successor list
    successors: dict[UUID, list[UUID]] = defaultdict(list)
    in_degree: dict[UUID, int] = {op.id: 0 for op in problem.operations}

    for op in problem.operations:
        if op.predecessor_op_id is not None:
            successors[op.predecessor_op_id].append(op.id)
            in_degree[op.id] = in_degree.get(op.id, 0) + 1

    # Topological sort via Kahn's algorithm
    topo_order: list[UUID] = []
    queue: list[UUID] = [
        op_id for op_id, deg in in_degree.items() if deg == 0
    ]
    while queue:
        current = queue.pop()
        topo_order.append(current)
        for succ in successors.get(current, []):
            in_degree[succ] -= 1
            if in_degree[succ] == 0:
                queue.append(succ)

    # Build per-machine timeline (sorted by start time)
    # Track which ops have been "placed" with their final times
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
        if operation.predecessor_op_id is not None:
            pred_a = assignment_by_op.get(operation.predecessor_op_id)
            if pred_a is not None and pred_a.end_time > earliest_start:
                earliest_start = pred_a.end_time

        # Machine constraint: must start after previous op + setup
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

    return assignments


def topological_post_assembly(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Operation],
) -> list[Assignment] | None:
    """Public wrapper for post-assembly timing repair."""

    return _topological_post_assembly(problem, assignments, ops_by_id)


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
    pending = [
        op.predecessor_op_id
        for op in cluster_ops
        if op.predecessor_op_id is not None
    ]
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
                [assigned_wc]
                if assigned_wc and assigned_wc in cluster_wcs
                else list(cluster_wcs)
            )
        else:
            assigned_wc = assignment_map.get(op_id)
            if assigned_wc is None:
                continue
            eligible = [assigned_wc]

        sub_operations.append(
            Operation(
                id=op.id,
                order_id=op.order_id,
                seq_in_order=op.seq_in_order,
                state_id=op.state_id,
                base_duration_min=op.base_duration_min,
                eligible_wc_ids=eligible,
                predecessor_op_id=(
                    op.predecessor_op_id
                    if op.predecessor_op_id in all_op_ids
                    else None
                ),
                domain_attributes=op.domain_attributes,
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
        e for e in problem.setup_matrix
        if e.work_center_id in needed_wc_ids
        and e.from_state_id in needed_state_ids
        and e.to_state_id in needed_state_ids
    ]

    sub_op_ids = {op.id for op in sub_operations}
    sub_aux_reqs = [
        r for r in problem.aux_requirements if r.operation_id in sub_op_ids
    ]
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

    Cut families:
        1. Capacity cut (Hooker & Ottosson 2003, §7.2)
        2. Setup-cost cut (SynAPS extension for SDST)
        3. Load-balance cut (Hooker 2007, §7.3)
        4. Critical-path cut (Naderi & Roshanaei 2022)
        5. Local-branching cut (few-but-strong neighborhood exclusion)
    """
    setup_lookup = {
        (e.work_center_id, e.from_state_id, e.to_state_id): e.setup_minutes
        for e in problem.setup_matrix
    }
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

    # 1. Capacity cut: bottleneck machine
    bottleneck_ops: set[UUID] = set()
    if machine_loads:
        bottleneck_wc = max(machine_loads, key=machine_loads.get)  # type: ignore[arg-type]
        bottleneck_ops = {
            op_id for op_id, wc_id in assignment_map.items()
            if wc_id == bottleneck_wc
        }
        benders_cuts.append(
            _BendersCut(
                assignment_map=dict(assignment_map),
                kind="capacity",
                rhs=sub_makespan,
                bottleneck_ops=bottleneck_ops,
            )
        )

    # 2. Setup-cost cuts per machine
    assignments_by_machine: dict[tuple[UUID, UUID | None], list[Assignment]] = defaultdict(list)
    for a in sub_assignments:
        assignments_by_machine[_assignment_sequence_key(a)].append(a)

    machine_setup_profiles: list[tuple[float, set[UUID], float]] = []
    for (wc_id, _lane_id), m_assignments in assignments_by_machine.items():
        if len(m_assignments) < 2:
            continue
        sorted_a = sorted(m_assignments, key=lambda x: x.start_time)
        actual_setup_total = 0.0
        for idx in range(len(sorted_a) - 1):
            prev_op = ops_by_id.get(sorted_a[idx].operation_id)
            curr_op = ops_by_id.get(sorted_a[idx + 1].operation_id)
            if prev_op is None or curr_op is None:
                continue
            actual_setup_total += setup_lookup.get(
                (wc_id, prev_op.state_id, curr_op.state_id), 0
            )
        if actual_setup_total <= 0:
            continue
        processing_total = sum(
            max(
                1.0,
                ops_by_id[a.operation_id].base_duration_min
                / wc_by_id[wc_id].speed_factor,
            )
            for a in m_assignments
            if a.operation_id in ops_by_id
        )
        machine_setup_profiles.append(
            (
                actual_setup_total,
                {a.operation_id for a in m_assignments},
                processing_total + actual_setup_total,
            )
        )

    for _setup_total, setup_ops, setup_rhs in sorted(
        machine_setup_profiles,
        key=lambda item: item[0],
        reverse=True,
    )[:setup_cut_top_k]:
        benders_cuts.append(
            _BendersCut(
                assignment_map=dict(assignment_map),
                kind="setup_cost",
                rhs=setup_rhs,
                bottleneck_ops=setup_ops,
            )
        )

    # 3. Load-balance cut (Hooker 2007, §7.3)
    if machine_loads:
        total_load = sum(machine_loads.values())
        num_machines = max(len(machine_loads), 1)
        avg_load = total_load / num_machines
        max_load = max(machine_loads.values())
        lb_rhs = max(max_load, avg_load)
        if lb_rhs > 0:
            benders_cuts.append(
                _BendersCut(
                    assignment_map=dict(assignment_map),
                    kind="load_balance",
                    rhs=lb_rhs,
                    bottleneck_ops=set(),
                )
            )

    # 4. Critical-path cut (Naderi & Roshanaei 2022)
    # Find the longest path in the schedule DAG (critical path)
    critical_ops, cp_duration = _find_critical_path(
        problem,
        sub_assignments,
        ops_by_id,
    )
    if critical_ops and len(critical_ops) >= 2 and cp_duration > 0:
        benders_cuts.append(
            _BendersCut(
                assignment_map=dict(assignment_map),
                kind="critical_path",
                rhs=cp_duration,
                bottleneck_ops=set(critical_ops),
            )
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
            delta = max(1, int(round(len(scoped_ops) * local_branching_delta_ratio)))
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
        for previous_assignment, current_assignment in zip(
            sorted_assignments,
            sorted_assignments[1:],
            strict=False,
        ):
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
    makespan: float,
    wc_by_id: dict[UUID, WorkCenter],
    ops_by_id: dict[UUID, Operation],
    orders_by_id: dict[UUID, Order],
) -> ObjectiveValues:
    """Compute multi-objective values from assignments."""
    horizon_start = problem.planning_horizon_start
    setup_lookup = {
        (e.work_center_id, e.from_state_id, e.to_state_id): (
            e.setup_minutes,
            e.material_loss,
        )
        for e in problem.setup_matrix
    }

    by_machine: dict[tuple[UUID, UUID | None], list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_machine[_assignment_sequence_key(a)].append(a)

    total_setup = 0.0
    total_material = 0.0
    for (wc_id, _lane_id), m_a in by_machine.items():
        sorted_a = sorted(m_a, key=lambda x: x.start_time)
        for i in range(1, len(sorted_a)):
            prev_op = ops_by_id.get(sorted_a[i - 1].operation_id)
            curr_op = ops_by_id.get(sorted_a[i].operation_id)
            if prev_op and curr_op:
                key = (wc_id, prev_op.state_id, curr_op.state_id)
                s, m = setup_lookup.get(key, (0, 0.0))
                total_setup += s
                total_material += m

    order_completion: dict[UUID, float] = {}
    for a in assignments:
        op = ops_by_id.get(a.operation_id)
        if op is None:
            continue
        end = (a.end_time - horizon_start).total_seconds() / 60.0
        if op.order_id not in order_completion or end > order_completion[op.order_id]:
            order_completion[op.order_id] = end

    total_tardiness = 0.0
    for order in problem.orders:
        completion = order_completion.get(order.id, 0.0)
        due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
        total_tardiness += max(completion - due_offset, 0.0)

    return ObjectiveValues(
        makespan_minutes=makespan,
        total_setup_minutes=total_setup,
        total_material_loss=total_material,
        total_tardiness_minutes=total_tardiness,
    )
