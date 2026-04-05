"""LBBD Solver — Logic-Based Benders Decomposition for MO-FJSP-SDST-ARC.

Decomposes the scheduling problem into:
    Master Problem (HiGHS MIP): assigns operations to machines with relaxed capacity.
    Subproblems (CP-SAT per machine cluster): sequences operations with exact SDST + ARC.

Benders cuts tighten the master's capacity estimate iteratively until convergence.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import timedelta
from typing import Any
from uuid import UUID

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
from synaps.solvers.cpsat_solver import CpSatSolver


class LbbdSolver(BaseSolver):
    """Logic-Based Benders Decomposition solver.

    Iterates between a HiGHS master (assignment) and CP-SAT subproblems
    (per-machine-cluster sequencing) until the optimality gap closes or
    the iteration budget is exhausted.
    """

    @property
    def name(self) -> str:
        return "lbbd"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()
        max_iterations: int = int(kwargs.get("max_iterations", 10))
        time_limit_s: int = int(kwargs.get("time_limit_s", 60))
        random_seed: int = int(kwargs.get("random_seed", 42))
        sub_time_limit_s: int = max(1, time_limit_s // max(max_iterations, 1))
        gap_threshold: float = float(kwargs.get("gap_threshold", 0.01))
        setup_relaxation: bool = bool(kwargs.get("setup_relaxation", True))

        # Precompute lookups
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

        # Build aux resource clustering: ops sharing aux resources should
        # be solved together when on the same machine cluster.
        aux_links = _build_aux_resource_links(problem)

        best_assignments: list[Assignment] = []
        best_objective = ObjectiveValues()
        best_ub = float("inf")
        lb = 0.0
        benders_cuts: list[_BendersCut] = []
        iteration_log: list[dict[str, Any]] = []
        prev_assignment_map: dict[UUID, UUID] | None = None
        master_warm_start_iterations = 0

        min_setup_by_wc: dict[UUID, float] = {}
        if setup_relaxation and problem.setup_matrix:
            for work_center in problem.work_centers:
                work_center_setups = [
                    entry.setup_minutes
                    for entry in problem.setup_matrix
                    if entry.work_center_id == work_center.id
                ]
                if not work_center_setups:
                    min_setup_by_wc[work_center.id] = 0.0
                    continue
                positive_setups = [setup for setup in work_center_setups if setup > 0]
                min_setup_by_wc[work_center.id] = min(positive_setups) if positive_setups else 0.0

        for iteration in range(1, max_iterations + 1):
            elapsed = time.monotonic() - t0
            if elapsed >= time_limit_s:
                break

            # --- Master Problem ---
            if prev_assignment_map is not None:
                master_warm_start_iterations += 1
            master_result = _solve_master(
                problem,
                eligible_by_op,
                wc_by_id,
                benders_cuts,
                min_setup_by_wc=min_setup_by_wc,
                prev_solution=prev_assignment_map,
            )
            if master_result is None:
                # Master infeasible — no solution possible
                return ScheduleResult(
                    solver_name=self.name,
                    status=SolverStatus.INFEASIBLE,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    metadata={"iterations": iteration, "reason": "master_infeasible"},
                )

            assignment_map, master_bound = master_result
            lb = max(lb, master_bound)
            prev_assignment_map = assignment_map

            # --- Subproblems (one CP-SAT per machine cluster) ---
            sub_assignments, sub_makespan = _solve_subproblems(
                problem,
                assignment_map,
                aux_links,
                wc_by_id,
                ops_by_id,
                orders_by_id,
                sub_time_limit_s,
                random_seed,
            )

            if sub_assignments is None:
                # Subproblem infeasible for this assignment → add nogood cut
                benders_cuts.append(_BendersCut(
                    assignment_map=dict(assignment_map),
                    kind="nogood",
                    rhs=0.0,
                    bottleneck_ops=set(),
                ))
                iteration_log.append({
                    "iteration": iteration,
                    "master_bound": master_bound,
                    "sub_makespan": None,
                    "status": "sub_infeasible",
                })
                continue

            ub = sub_makespan

            # Track best feasible solution
            if ub < best_ub:
                best_ub = ub
                best_assignments = sub_assignments
                best_objective = _compute_objective(
                    problem, sub_assignments, sub_makespan, wc_by_id, ops_by_id, orders_by_id,
                )

            iteration_log.append({
                "iteration": iteration,
                "master_bound": master_bound,
                "sub_makespan": sub_makespan,
                "gap": (ub - lb) / max(ub, 1e-9),
                "status": "feasible",
            })

            # --- Convergence check ---
            gap = (best_ub - lb) / max(best_ub, 1e-9)
            if gap < gap_threshold:
                break

            # --- Generate Benders cut ---
            bottleneck_wc = max(
                _makespan_by_machine(sub_assignments, problem).items(),
                key=lambda kv: kv[1],
            )[0]
            bottleneck_ops = {
                op_id for op_id, wc_id in assignment_map.items()
                if wc_id == bottleneck_wc
            }
            benders_cuts.append(_BendersCut(
                assignment_map=dict(assignment_map),
                kind="capacity",
                rhs=sub_makespan,
                bottleneck_ops=bottleneck_ops,
            ))

            setup_lookup = {
                (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
                for entry in problem.setup_matrix
            }
            assignments_by_machine: dict[UUID, list[Assignment]] = defaultdict(list)
            for assignment in sub_assignments:
                assignments_by_machine[assignment.work_center_id].append(assignment)

            for work_center_id, machine_assignments in assignments_by_machine.items():
                if len(machine_assignments) < 2:
                    continue
                machine_assignments_sorted = sorted(machine_assignments, key=lambda assignment: assignment.start_time)
                actual_setup_total = 0.0
                for index in range(len(machine_assignments_sorted) - 1):
                    previous_op = ops_by_id.get(machine_assignments_sorted[index].operation_id)
                    current_op = ops_by_id.get(machine_assignments_sorted[index + 1].operation_id)
                    if previous_op is None or current_op is None:
                        continue
                    actual_setup_total += setup_lookup.get(
                        (work_center_id, previous_op.state_id, current_op.state_id),
                        0,
                    )
                if actual_setup_total <= 0:
                    continue
                processing_total = sum(
                    max(
                        1.0,
                        ops_by_id[assignment.operation_id].base_duration_min / wc_by_id[work_center_id].speed_factor,
                    )
                    for assignment in machine_assignments
                )
                benders_cuts.append(_BendersCut(
                    assignment_map=dict(assignment_map),
                    kind="setup_cost",
                    rhs=processing_total + actual_setup_total,
                    bottleneck_ops={assignment.operation_id for assignment in machine_assignments},
                ))

            # --- Load-balance cut (Hooker 2007, §7.3) ---
            # Strengthened form: C_max ≥ max(max_k load_k, total / |M|).
            # The max-load term is a tighter relaxation-free lower bound
            # than the average alone, especially on imbalanced instances
            # where one machine dominates.
            machine_loads = _makespan_by_machine(sub_assignments, problem)
            if machine_loads:
                total_load = sum(machine_loads.values())
                num_machines = max(len(machine_loads), 1)
                avg_load = total_load / num_machines
                max_load = max(machine_loads.values())
                lb_cut_rhs = max(max_load, avg_load)
                if lb_cut_rhs > lb:
                    benders_cuts.append(_BendersCut(
                        assignment_map=dict(assignment_map),
                        kind="load_balance",
                        rhs=lb_cut_rhs,
                        bottleneck_ops=set(),
                    ))

        status = SolverStatus.FEASIBLE if best_assignments else SolverStatus.TIMEOUT
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        cut_kinds: dict[str, int] = {}
        for cut in benders_cuts:
            cut_kinds[cut.kind] = cut_kinds.get(cut.kind, 0) + 1

        return ScheduleResult(
            solver_name=self.name,
            status=status,
            assignments=best_assignments,
            objective=best_objective,
            duration_ms=elapsed_ms,
            random_seed=random_seed,
            metadata={
                "iterations": len(iteration_log),
                "lower_bound": lb,
                "upper_bound": best_ub,
                "gap": (best_ub - lb) / max(best_ub, 1e-9) if best_ub < float("inf") else None,
                "iteration_log": iteration_log,
                "gap_threshold": gap_threshold,
                "setup_relaxation": setup_relaxation,
                "master_warm_start_iterations": master_warm_start_iterations,
                "cut_pool": {
                    "size": len(benders_cuts),
                    "kinds": cut_kinds,
                },
            },
        )


# ---------------------------------------------------------------------------
# Master Problem (HiGHS MIP)
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


def _solve_master(
    problem: ScheduleProblem,
    eligible_by_op: dict[UUID, list[UUID]],
    wc_by_id: dict[UUID, WorkCenter],
    cuts: list[_BendersCut],
    min_setup_by_wc: dict[UUID, float] | None = None,
    prev_solution: dict[UUID, UUID] | None = None,
) -> tuple[dict[UUID, UUID], float] | None:
    """Solve the assignment master problem via HiGHS MIP.

    Decision variables:
        y[i, k] ∈ {0, 1}  — operation i assigned to work center k
        C_max ≥ 0          — relaxed makespan lower bound

    Constraints:
        ∑_k y[i,k] = 1                    ∀ i ∈ ops      (unique assignment)
        ∑_i P[i,k] · y[i,k] ≤ C_max      ∀ k ∈ machines  (relaxed capacity)
        Benders cuts from previous iterations

    Objective: min C_max
    """
    h = highspy.Highs()
    h.silent()

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
        indices = [var_index[(op.id, wc_id)] for wc_id in eligible_by_op[op.id]]
        coeffs = [1.0] * len(indices)
        h.addRow(1.0, 1.0, len(indices), np.array(indices, dtype=np.int32), np.array(coeffs))

    # Constraint 2: relaxed capacity — ∑_i P[i,k] · y[i,k] ≤ C_max for each machine
    for wc in problem.work_centers:
        indices: list[int] = []
        coeffs: list[float] = []
        for op in problem.operations:
            key = (op.id, wc.id)
            if key in var_index:
                duration = max(1.0, op.base_duration_min / wc.speed_factor)
                indices.append(var_index[key])
                coeffs.append(duration)
        if not indices:
            continue
        if min_setup_by_wc and wc.id in min_setup_by_wc:
            min_setup = min_setup_by_wc[wc.id]
            if min_setup > 0:
                coeffs = [coefficient + min_setup for coefficient in coeffs]
        # ∑ P·y - C_max ≤ 0
        indices.append(cmax_idx)
        coeffs.append(-1.0)
        h.addRow(
            -highspy.kHighsInf, 0.0,
            len(indices), np.array(indices, dtype=np.int32), np.array(coeffs),
        )

    # Constraint 3: Benders cuts from previous iterations
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
            if indices:
                h.addRow(
                    -highspy.kHighsInf, len(indices) - 1.0,
                    len(indices), np.array(indices, dtype=np.int32), np.array(coeffs),
                )
        elif cut.kind == "capacity":
            # Combinatorial Benders capacity cut (Hooker & Ottosson 2003).
            #
            # Original:  C_max ≥ rhs − Σ_{i∈B} p_i · (1 − y[i, k_i])
            # Expand:     C_max ≥ rhs − Σ p_i + Σ p_i · y[i, k_i]
            # Rearrange:  C_max − Σ p_i · y[i, k_i] ≥ rhs − Σ p_i
            #
            # The row added to HiGHS is:  C_max − Σ p·y  ≥  rhs − total_p
            indices = [cmax_idx]
            coeffs = [1.0]
            total_processing = 0.0
            for op_id in cut.bottleneck_ops:
                wc_id = cut.assignment_map.get(op_id)
                if wc_id is None:
                    continue
                key = (op_id, wc_id)
                if key not in var_index:
                    continue
                wc = wc_by_id.get(wc_id)
                op = next((o for o in problem.operations if o.id == op_id), None)
                if wc is None or op is None:
                    continue
                p = max(1.0, op.base_duration_min / wc.speed_factor)
                total_processing += p
                indices.append(var_index[key])
                # Negative coefficient: C_max − p·y
                coeffs.append(-p)

            if len(indices) > 1:
                rhs_val = cut.rhs - total_processing
                h.addRow(
                    rhs_val, highspy.kHighsInf,
                    len(indices), np.array(indices, dtype=np.int32), np.array(coeffs),
                )
        elif cut.kind == "load_balance":
            # Load-balance cut: C_max ≥ rhs (simple lower bound)
            h.addRow(
                cut.rhs, highspy.kHighsInf,
                1, np.array([cmax_idx], dtype=np.int32), np.array([1.0]),
            )
        elif cut.kind == "setup_cost":
            indices = [cmax_idx]
            coeffs = [1.0]
            total_processing = 0.0
            for op_id in cut.bottleneck_ops:
                wc_id = cut.assignment_map.get(op_id)
                if wc_id is None:
                    continue
                key = (op_id, wc_id)
                if key not in var_index:
                    continue
                wc = wc_by_id.get(wc_id)
                op = next((operation for operation in problem.operations if operation.id == op_id), None)
                if wc is None or op is None:
                    continue
                processing_time = max(1.0, op.base_duration_min / wc.speed_factor)
                total_processing += processing_time
                indices.append(var_index[key])
                coeffs.append(-processing_time)
            if len(indices) > 1:
                rhs_val = cut.rhs - total_processing
                h.addRow(
                    rhs_val, highspy.kHighsInf,
                    len(indices), np.array(indices, dtype=np.int32), np.array(coeffs),
                )

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
            int((problem.planning_horizon_end - problem.planning_horizon_start).total_seconds() / 60)
        )
        h.setSolution(n_vars, np.arange(n_vars, dtype=np.int32), np.array(hint_values))
    h.run()

    status = h.getInfoValue("primal_solution_status")[1]
    if status != 2:  # 2 = feasible
        return None

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
    return assignment_map, master_bound


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
    op_to_machine = {op_id: wc_id for op_id, wc_id in assignment_map.items()}

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
) -> tuple[list[Assignment] | None, float]:
    """Solve CP-SAT subproblems for each machine cluster.

    Returns (combined_assignments, overall_makespan) or (None, 0) if infeasible.
    """
    clusters = _cluster_machines(assignment_map, aux_links)

    all_assignments: list[Assignment] = []
    overall_makespan = 0.0
    horizon_start = problem.planning_horizon_start

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
            problem, cluster_ops, cluster_wcs, cluster_op_ids,
            assignment_map, wc_by_id, ops_by_id, orders_by_id,
        )

        # Solve with CP-SAT
        cpsat = CpSatSolver()
        result = cpsat.solve(
            sub_problem,
            time_limit_s=sub_time_limit_s,
            random_seed=random_seed,
            num_workers=4,
        )

        if result.status in (SolverStatus.INFEASIBLE, SolverStatus.ERROR):
            return None, 0.0

        if result.status == SolverStatus.TIMEOUT and not result.assignments:
            return None, 0.0

        # Only keep assignments for ops that belong to this cluster
        # (external predecessor ops may also have been solved but are
        # owned by their own cluster).
        cluster_assignments = [
            a for a in result.assignments if a.operation_id in cluster_op_ids
        ]
        all_assignments.extend(cluster_assignments)

        # Track cluster makespan (only cluster-owned assignments, not
        # external predecessors that belong to another cluster).
        if cluster_assignments:
            cluster_makespan = max(
                (a.end_time - horizon_start).total_seconds() / 60.0
                for a in cluster_assignments
            )
            overall_makespan = max(overall_makespan, cluster_makespan)

    # Check completeness — every operation must be assigned
    assigned_ops = {a.operation_id for a in all_assignments}
    all_ops = {op.id for op in problem.operations}
    if assigned_ops != all_ops:
        return None, 0.0

    # Post-assembly precedence and setup enforcement: cross-cluster
    # predecessor timing may diverge because each cluster solves external
    # predecessors independently.  Iterate until both precedence and
    # machine-level setup gaps are satisfied.
    setup_lookup = {
        (e.work_center_id, e.from_state_id, e.to_state_id): timedelta(minutes=e.setup_minutes)
        for e in problem.setup_matrix
    }
    assignment_by_op = {a.operation_id: a for a in all_assignments}

    changed = True
    max_passes = len(problem.operations) * 3  # prevent infinite loops
    passes = 0
    while changed and passes < max_passes:
        changed = False
        passes += 1

        # 1) Precedence: successor must start after predecessor ends
        for op in problem.operations:
            if op.predecessor_op_id is None:
                continue
            pred_a = assignment_by_op.get(op.predecessor_op_id)
            cur_a = assignment_by_op.get(op.id)
            if pred_a is None or cur_a is None:
                continue
            if cur_a.start_time < pred_a.end_time:
                shift = pred_a.end_time - cur_a.start_time
                cur_a.start_time = cur_a.start_time + shift
                cur_a.end_time = cur_a.end_time + shift
                changed = True

        # 2) Machine setup gaps: consecutive ops on same machine need
        #    sufficient gap for state-dependent setup time.
        by_machine: dict[UUID, list[Assignment]] = defaultdict(list)
        for a in all_assignments:
            by_machine[a.work_center_id].append(a)

        for wc_id, machine_assignments in by_machine.items():
            machine_assignments.sort(key=lambda a: a.start_time)
            for idx in range(len(machine_assignments) - 1):
                cur = machine_assignments[idx]
                nxt = machine_assignments[idx + 1]
                cur_state = ops_by_id[cur.operation_id].state_id
                nxt_state = ops_by_id[nxt.operation_id].state_id
                required_setup = setup_lookup.get(
                    (wc_id, cur_state, nxt_state), timedelta(0),
                )
                earliest_next_start = cur.end_time + required_setup
                if nxt.start_time < earliest_next_start:
                    shift = earliest_next_start - nxt.start_time
                    nxt.start_time = nxt.start_time + shift
                    nxt.end_time = nxt.end_time + shift
                    changed = True

    # Recompute overall makespan after shifts
    overall_makespan = max(
        (a.end_time - horizon_start).total_seconds() / 60.0
        for a in all_assignments
    ) if all_assignments else 0.0

    return all_assignments, overall_makespan


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
        op.predecessor_op_id
        for op in cluster_ops
        if op.predecessor_op_id is not None
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
            eligible = [assigned_wc] if assigned_wc and assigned_wc in cluster_wcs else list(cluster_wcs)
            sub_operations.append(Operation(
                id=op.id,
                order_id=op.order_id,
                seq_in_order=op.seq_in_order,
                state_id=op.state_id,
                base_duration_min=op.base_duration_min,
                eligible_wc_ids=eligible,
                predecessor_op_id=op.predecessor_op_id if op.predecessor_op_id in all_op_ids else None,
                domain_attributes=op.domain_attributes,
            ))
        else:
            # External predecessor — restrict to its assigned machine
            assigned_wc = assignment_map.get(op_id)
            if assigned_wc is None:
                continue
            # Add the assigned machine to cluster_wcs temporarily
            eligible = [assigned_wc]
            sub_operations.append(Operation(
                id=op.id,
                order_id=op.order_id,
                seq_in_order=op.seq_in_order,
                state_id=op.state_id,
                base_duration_min=op.base_duration_min,
                eligible_wc_ids=eligible,
                predecessor_op_id=op.predecessor_op_id if op.predecessor_op_id in all_op_ids else None,
                domain_attributes=op.domain_attributes,
            ))

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
        entry for entry in problem.setup_matrix
        if entry.work_center_id in needed_wc_ids
        and entry.from_state_id in needed_state_ids
        and entry.to_state_id in needed_state_ids
    ]

    sub_op_ids = {op.id for op in sub_operations}
    sub_aux_reqs = [
        req for req in problem.aux_requirements
        if req.operation_id in sub_op_ids
    ]
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


def _makespan_by_machine(
    assignments: list[Assignment],
    problem: ScheduleProblem,
) -> dict[UUID, float]:
    """Compute per-machine makespan (max end time offset)."""
    horizon_start = problem.planning_horizon_start
    by_machine: dict[UUID, float] = {}
    for a in assignments:
        end_offset = (a.end_time - horizon_start).total_seconds() / 60.0
        current = by_machine.get(a.work_center_id, 0.0)
        if end_offset > current:
            by_machine[a.work_center_id] = end_offset
    return by_machine


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
        (e.work_center_id, e.from_state_id, e.to_state_id): (e.setup_minutes, e.material_loss)
        for e in problem.setup_matrix
    }

    # Group by machine and sort
    by_machine: dict[UUID, list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_machine[a.work_center_id].append(a)

    total_setup = 0.0
    total_material = 0.0
    for wc_id, machine_assignments in by_machine.items():
        sorted_a = sorted(machine_assignments, key=lambda x: x.start_time)
        for i in range(1, len(sorted_a)):
            prev_op = ops_by_id.get(sorted_a[i - 1].operation_id)
            curr_op = ops_by_id.get(sorted_a[i].operation_id)
            if prev_op and curr_op:
                key = (wc_id, prev_op.state_id, curr_op.state_id)
                setup_min, mat_loss = setup_lookup.get(key, (0, 0.0))
                total_setup += setup_min
                total_material += mat_loss

    # Per-order tardiness
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
