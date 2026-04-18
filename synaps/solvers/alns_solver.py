"""ALNS Solver — Adaptive Large Neighborhood Search with Micro-CP-SAT repair.

Scales to 50 000+ operations by iteratively destroying and repairing
sub-regions of a schedule, using exact CP-SAT as the repair operator.

Academic basis:
    - Shaw (1998): Original LNS for VRP
    - Ropke & Pisinger (2006, Transportation Science): ALNS adaptive operator selection
    - Laborie & Godard (2007, CPAIOR): LNS + CP for scheduling
    - Matsuzaki et al. (2024, J. Supercomputing): LNS + MIP for large-scale machining
    - Deng et al. (2026, Memetic Computing): Improved ALNS for distributed scheduling
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import math
import random
import time
from typing import TYPE_CHECKING, Any

from synaps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from synaps.solvers import BaseSolver
from synaps.solvers._dispatch_support import (
    build_dispatch_context,
    recompute_assignment_setups,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.sdst_matrix import SdstMatrix

if TYPE_CHECKING:
    from uuid import UUID

logger = logging.getLogger(__name__)


class RepairStatus(str, Enum):
    """Structured repair status for ALNS repair operators."""

    FEASIBLE = "feasible"
    TIMEOUT = "timeout"
    INFEASIBLE = "infeasible"


@dataclass(frozen=True)
class RepairOutcome:
    """Explicit repair outcome carrying status, payload, and reason."""

    status: RepairStatus
    assignments: tuple[Assignment, ...]
    reason: str


# ---------------------------------------------------------------------------
# Objective evaluation
# ---------------------------------------------------------------------------

def _evaluate_objective(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    sdst: SdstMatrix,
) -> ObjectiveValues:
    """Compute multi-objective values from a set of assignments."""
    if not assignments:
        return ObjectiveValues()

    horizon_start = problem.planning_horizon_start
    ops_by_id = {op.id: op for op in problem.operations}
    {o.id: o for o in problem.orders}

    # Makespan
    makespan = max(
        (a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments
    )

    # Setup and material loss from machine sequences
    total_setup = 0.0
    total_material_loss = 0.0
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for wc_id, machine_assignments in by_machine.items():
        machine_assignments.sort(key=lambda a: a.start_time)
        for i in range(1, len(machine_assignments)):
            prev_state = ops_by_id[machine_assignments[i - 1].operation_id].state_id
            curr_state = ops_by_id[machine_assignments[i].operation_id].state_id
            total_setup += sdst.get_setup(wc_id, prev_state, curr_state)
            total_material_loss += sdst.get_material_loss(wc_id, prev_state, curr_state)

    # Tardiness
    order_completion: dict[Any, float] = {}
    for a in assignments:
        op = ops_by_id[a.operation_id]
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
        total_material_loss=total_material_loss,
        total_tardiness_minutes=total_tardiness,
    )


def _objective_cost(obj: ObjectiveValues, weights: dict[str, float]) -> float:
    """Scalar cost from multi-objective values."""
    return (
        weights.get("makespan", 1.0) * obj.makespan_minutes
        + weights.get("setup", 0.3) * obj.total_setup_minutes
        + weights.get("material_loss", 0.2) * obj.total_material_loss
        + weights.get("tardiness", 0.5) * obj.total_tardiness_minutes
    )


# ---------------------------------------------------------------------------
# Destroy operators
#   random     — uniform random removal
#   worst      — removal by machine-local setup contribution
#                (Shaw 1998; Ropke & Pisinger 2006, Transportation Science)
#   related    — Shaw relatedness removal seeded by a random anchor
#                (Shaw 1998)
#   machine_segment — contiguous segment removal from one machine
#                to break high-cost setup chains (domain heuristic)
# ---------------------------------------------------------------------------

def _destroy_random(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
) -> set[UUID]:
    """Remove a random subset of operations."""
    op_ids = [a.operation_id for a in assignments]
    k = min(destroy_size, len(op_ids))
    return set(rng.sample(op_ids, k))


def _destroy_worst(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
) -> set[UUID]:
    """Remove operations contributing the most to setup cost (worst removal).

    Picks operations whose machine-local setup contribution (predecessor→self
    + self→successor) is highest.
    """
    ops_by_id = {op.id: op for op in problem.operations}
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)

    op_cost: dict[UUID, float] = {}
    for wc_id, machine_assignments in by_machine.items():
        machine_assignments.sort(key=lambda a: a.start_time)
        for i, a in enumerate(machine_assignments):
            cost = 0.0
            op = ops_by_id[a.operation_id]
            if i > 0:
                prev_op = ops_by_id[machine_assignments[i - 1].operation_id]
                cost += sdst.get_setup(wc_id, prev_op.state_id, op.state_id)
                cost += sdst.get_material_loss(wc_id, prev_op.state_id, op.state_id)
            if i < len(machine_assignments) - 1:
                next_op = ops_by_id[machine_assignments[i + 1].operation_id]
                cost += sdst.get_setup(wc_id, op.state_id, next_op.state_id)
                cost += sdst.get_material_loss(wc_id, op.state_id, next_op.state_id)
            op_cost[a.operation_id] = cost

    # Sort by cost descending, add randomness to avoid deterministic loops
    ranked = sorted(op_cost.items(), key=lambda x: -x[1])
    destroyed: set[UUID] = set()
    p_worst = 0.8  # probability of picking the worst vs. random from top-50%
    for op_id, _ in ranked:
        if len(destroyed) >= destroy_size:
            break
        if rng.random() < p_worst:
            destroyed.add(op_id)
    # Fill remainder randomly if needed
    remaining_ids = [a.operation_id for a in assignments if a.operation_id not in destroyed]
    while len(destroyed) < destroy_size and remaining_ids:
        pick = rng.choice(remaining_ids)
        destroyed.add(pick)
        remaining_ids.remove(pick)
    return destroyed


def _destroy_related(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
) -> set[UUID]:
    """Remove operations that are related to a seed operation (Shaw removal).

    Relatedness = same machine assignment + low setup time between them.
    Shaw (1998): operations are related if they share resources and have
    similar processing characteristics.
    """
    if not assignments:
        return set()

    {a.operation_id: a for a in assignments}
    ops_by_id = {op.id: op for op in problem.operations}

    # Pick random seed
    seed_assignment = rng.choice(assignments)
    seed_op = ops_by_id[seed_assignment.operation_id]
    seed_wc = seed_assignment.work_center_id

    # Score relatedness (lower = more related)
    relatedness: list[tuple[float, UUID]] = []
    for a in assignments:
        if a.operation_id == seed_assignment.operation_id:
            continue
        op = ops_by_id[a.operation_id]
        score = 0.0
        # Same machine bonus
        if a.work_center_id == seed_wc:
            score -= 100.0
        # Low setup between seed and this op
        setup = sdst.get_setup(seed_wc, seed_op.state_id, op.state_id)
        score += setup
        # Similar processing time
        score += abs(op.base_duration_min - seed_op.base_duration_min) * 0.5
        relatedness.append((score, a.operation_id))

    relatedness.sort(key=lambda x: x[0])
    destroyed: set[UUID] = {seed_assignment.operation_id}
    for _, op_id in relatedness:
        if len(destroyed) >= destroy_size:
            break
        destroyed.add(op_id)
    return destroyed


def _destroy_machine_segment(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
) -> set[UUID]:
    """Remove a contiguous segment of operations from a random machine.

    Effective for reducing setup chains: removing a sequence from one machine
    and re-optimizing the gap.
    """
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)

    # Pick a machine with enough operations
    valid_machines = [
        (wc_id, sorted(ma, key=lambda a: a.start_time))
        for wc_id, ma in by_machine.items()
        if len(ma) >= 3
    ]
    if not valid_machines:
        return _destroy_random(assignments, problem, sdst, destroy_size, rng)

    wc_id, machine_seq = rng.choice(valid_machines)
    seg_size = min(destroy_size, len(machine_seq))
    start_idx = rng.randint(0, len(machine_seq) - seg_size)
    return {machine_seq[i].operation_id for i in range(start_idx, start_idx + seg_size)}


# All destroy operators (random, worst, related: Shaw/Ropke-Pisinger;
#  machine_segment: domain heuristic for setup-chain disruption)
DESTROY_OPERATORS = [
    ("random", _destroy_random),
    ("worst", _destroy_worst),
    ("related", _destroy_related),
    ("machine_segment", _destroy_machine_segment),
]


def _expand_successor_closure(
    destroyed_op_ids: set[UUID],
    successors_by_op: dict[UUID, list[UUID]],
) -> set[UUID]:
    """Return the transitive successor closure of the destroyed set."""

    expanded = set(destroyed_op_ids)
    # Deterministic frontier order keeps same-seed runs stable across processes.
    frontier = sorted(destroyed_op_ids, key=str)
    while frontier:
        op_id = frontier.pop()
        for successor_id in successors_by_op.get(op_id, []):
            if successor_id not in expanded:
                expanded.add(successor_id)
                frontier.append(successor_id)
    return expanded


def _cap_destroy_set_preserving_successor_closure(
    destroyed_op_ids: set[UUID],
    ops_by_id: dict[UUID, Any],
    successors_by_op: dict[UUID, list[UUID]],
    max_destroy: int,
    rng: random.Random,
) -> set[UUID]:
    """Shrink a destroyed set while preserving successor closure.

    To avoid frozen successors depending on repaired predecessors, the kept set
    must remain successor-closed. We therefore remove roots, not leaves: if an
    operation leaves the destroyed set, its successors may stay destroyed and
    simply treat the predecessor as frozen.
    """

    capped = set(destroyed_op_ids)
    while len(capped) > max_destroy:
        roots = sorted(
            [
            op_id
            for op_id in capped
            if (ops_by_id.get(op_id) is None)
            or (ops_by_id[op_id].predecessor_op_id not in capped)
            ],
            key=str,
        )
        if not roots:
            break
        capped.discard(rng.choice(roots))

    if len(capped) > max_destroy:
        destroyed_list = sorted(capped, key=str)
        rng.shuffle(destroyed_list)
        capped = set(destroyed_list[:max_destroy])

    return capped


# ---------------------------------------------------------------------------
# Repair via CP-SAT (Laborie & Godard 2007: LNS + CP)
# ---------------------------------------------------------------------------

def _repair_cpsat_outcome(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    destroyed_op_ids: set[UUID],
    time_limit_s: int = 10,
    ops_by_id: dict[UUID, Any] | None = None,
    op_positions: dict[UUID, int] | None = None,
) -> RepairOutcome:
    """Repair by solving a sub-problem with CP-SAT over the destroyed operations.

    Frozen assignments constrain the machine timelines. Only the destroyed
    operations (+ their immediate predecessors if outside the set) are modeled.

    Returns explicit status for success, timeout, or infeasible outcomes.
    """
    from synaps.solvers.cpsat_solver import CpSatSolver

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}
    if op_positions is None:
        op_positions = {op.id: index for index, op in enumerate(problem.operations)}

    # Gather operations to re-schedule
    needed_ids = set(destroyed_op_ids)
    # Include predecessors that reference other destroyed ops (chain consistency)
    for op_id in list(destroyed_op_ids):
        op = ops_by_id.get(op_id)
        if op and op.predecessor_op_id and op.predecessor_op_id in destroyed_op_ids:
            needed_ids.add(op.predecessor_op_id)

    # Build sub-operations: for ops whose predecessor is NOT in the sub-problem
    # (i.e., frozen/already scheduled), clear the predecessor reference since
    # the predecessor constraint is already satisfied by the frozen assignment.
    sub_operations = []
    for op_id in sorted(needed_ids, key=op_positions.__getitem__):
        op = ops_by_id[op_id]
        if op.predecessor_op_id and op.predecessor_op_id not in needed_ids:
            # Predecessor is frozen — break the link for the sub-problem
            sub_operations.append(op.model_copy(update={"predecessor_op_id": None}))
        else:
            sub_operations.append(op)

    if not sub_operations:
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason="empty_subproblem",
        )

    # Build sub-problem with the relevant operations only
    sub_problem = ScheduleProblem(
        states=problem.states,
        orders=problem.orders,
        operations=sub_operations,
        work_centers=problem.work_centers,
        setup_matrix=problem.setup_matrix,
        auxiliary_resources=problem.auxiliary_resources,
        aux_requirements=[
            r for r in problem.aux_requirements if r.operation_id in needed_ids
        ],
        planning_horizon_start=problem.planning_horizon_start,
        planning_horizon_end=problem.planning_horizon_end,
    )

    # Solve the sub-problem
    solver = CpSatSolver()
    result = solver.solve(
        sub_problem,
        time_limit_s=time_limit_s,
        num_workers=4,
        enable_symmetry_breaking=False,
    )

    if result.status == SolverStatus.TIMEOUT:
        return RepairOutcome(
            status=RepairStatus.TIMEOUT,
            assignments=(),
            reason="cpsat_timeout",
        )
    if result.status not in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL):
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason=(
                f"cpsat_status_{result.status.value}"
                if hasattr(result.status, "value")
                else f"cpsat_status_{result.status}"
            ),
        )

    repaired_assignments = [a for a in result.assignments if a.operation_id in destroyed_op_ids]
    if len(repaired_assignments) != len(destroyed_op_ids):
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason="partial_assignment",
        )

    # Keep assignment order deterministic for downstream destroy operators.
    repaired_assignments.sort(key=lambda assignment: op_positions[assignment.operation_id])

    return RepairOutcome(
        status=RepairStatus.FEASIBLE,
        assignments=tuple(repaired_assignments),
        reason="ok",
    )


def _repair_cpsat(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    destroyed_op_ids: set[UUID],
    time_limit_s: int = 10,
    ops_by_id: dict[UUID, Any] | None = None,
    op_positions: dict[UUID, int] | None = None,
) -> list[Assignment] | None:
    """Compatibility wrapper preserving legacy Optional[List[Assignment]] API."""

    outcome = _repair_cpsat_outcome(
        problem,
        frozen_assignments,
        destroyed_op_ids,
        time_limit_s=time_limit_s,
        ops_by_id=ops_by_id,
        op_positions=op_positions,
    )
    if outcome.status == RepairStatus.FEASIBLE:
        return list(outcome.assignments)
    return None


def _repair_greedy_outcome(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    destroyed_op_ids: set[UUID],
) -> RepairOutcome:
    """Fallback greedy repair when CP-SAT is too slow for the sub-region."""
    from synaps.solvers.incremental_repair import IncrementalRepair

    repair_solver = IncrementalRepair()
    op_positions = {op.id: index for index, op in enumerate(problem.operations)}
    disrupted_op_ids = sorted(destroyed_op_ids, key=op_positions.__getitem__)

    result = repair_solver.solve(
        problem,
        base_assignments=frozen_assignments,
        disrupted_op_ids=disrupted_op_ids,
        radius=0,
    )

    if result.status == SolverStatus.TIMEOUT:
        return RepairOutcome(
            status=RepairStatus.TIMEOUT,
            assignments=(),
            reason="greedy_timeout",
        )
    if result.status not in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL):
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason=(
                f"greedy_status_{result.status.value}"
                if hasattr(result.status, "value")
                else f"greedy_status_{result.status}"
            ),
        )

    repaired_assignments = [a for a in result.assignments if a.operation_id in destroyed_op_ids]
    if len(repaired_assignments) != len(destroyed_op_ids):
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason="partial_assignment",
        )

    repaired_assignments.sort(key=lambda assignment: op_positions[assignment.operation_id])

    return RepairOutcome(
        status=RepairStatus.FEASIBLE,
        assignments=tuple(repaired_assignments),
        reason="ok",
    )


def _repair_greedy(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    destroyed_op_ids: set[UUID],
) -> list[Assignment] | None:
    """Compatibility wrapper preserving legacy Optional[List[Assignment]] API."""

    outcome = _repair_greedy_outcome(problem, frozen_assignments, destroyed_op_ids)
    if outcome.status == RepairStatus.FEASIBLE:
        return list(outcome.assignments)
    return None


# ---------------------------------------------------------------------------
# Machine overlap check (guard for CP-SAT repair sub-problem gaps)
# ---------------------------------------------------------------------------

def _has_machine_overlap(assignments: list[Assignment]) -> bool:
    """Return True if any two assignments overlap on the same machine."""
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for mc_assigns in by_machine.values():
        mc_assigns.sort(key=lambda x: x.start_time)
        for i in range(1, len(mc_assigns)):
            if mc_assigns[i].start_time < mc_assigns[i - 1].end_time:
                return True
    return False


def _violates_frozen_precedence(
    repaired_assignments: list[Assignment],
    frozen_assignments_by_op: dict[UUID, Assignment],
    ops_by_id: dict[UUID, Any],
) -> bool:
    """Return True when a repaired operation starts before its frozen predecessor ends."""

    repaired_ids = {assignment.operation_id for assignment in repaired_assignments}
    for assignment in repaired_assignments:
        operation = ops_by_id.get(assignment.operation_id)
        if operation is None or operation.predecessor_op_id is None:
            continue
        if operation.predecessor_op_id in repaired_ids:
            continue
        frozen_predecessor = frozen_assignments_by_op.get(operation.predecessor_op_id)
        if frozen_predecessor is not None and assignment.start_time < frozen_predecessor.end_time:
            return True
    return False


def _has_precedence_violation(
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Any],
) -> bool:
    """Return True when any assignment starts before its predecessor ends."""

    assignments_by_op = {assignment.operation_id: assignment for assignment in assignments}
    for assignment in assignments:
        operation = ops_by_id.get(assignment.operation_id)
        if operation is None or operation.predecessor_op_id is None:
            continue
        predecessor_assignment = assignments_by_op.get(operation.predecessor_op_id)
        if predecessor_assignment is not None and assignment.start_time < predecessor_assignment.end_time:
            return True
    return False


# ---------------------------------------------------------------------------
# SA acceptance (Ropke & Pisinger 2006 §4.3)
# ---------------------------------------------------------------------------

def _sa_accept(
    delta_cost: float,
    temperature: float,
    rng: random.Random,
) -> bool:
    """Simulated annealing acceptance criterion."""
    if delta_cost < 0:
        return True
    if temperature < 1e-12:
        return False
    prob = math.exp(-delta_cost / temperature)
    return rng.random() < prob


# ---------------------------------------------------------------------------
# Main ALNS solver
# ---------------------------------------------------------------------------

class AlnsSolver(BaseSolver):
    """Adaptive Large Neighborhood Search with Micro-CP-SAT repair.

    Designed for 5 000–50 000+ operation instances where monolithic CP-SAT
    and LBBD cannot converge in reasonable time.

    Architecture (Ropke & Pisinger 2006):
        1. Generate initial solution via greedy/beam heuristic
        2. Iteratively: destroy (remove k operations) → repair (micro CP-SAT)
        3. Accept/reject via Simulated Annealing
        4. Adapt operator selection probabilities based on success history

    Key parameters:
        max_iterations: Total ALNS iterations (default 500)
        destroy_fraction: Fraction of operations to destroy per iteration (default 0.05)
        min_destroy: Minimum destroy size (default 20)
        max_destroy: Maximum destroy size per iteration (default 300)
        repair_time_limit_s: Time limit for micro CP-SAT repair (default 10)
        sa_initial_temp: Starting temperature for SA (default 100.0)
        sa_cooling_rate: Geometric cooling factor (default 0.995)
        random_seed: For reproducibility (default 42)
    """

    @property
    def name(self) -> str:
        return "alns"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()

        # Parameters
        max_iterations: int = int(kwargs.get("max_iterations", 500))
        time_limit_s: float = float(kwargs.get("time_limit_s", 300))
        destroy_fraction: float = float(kwargs.get("destroy_fraction", 0.05))
        min_destroy: int = int(kwargs.get("min_destroy", 20))
        max_destroy: int = int(kwargs.get("max_destroy", 300))
        repair_time_limit_s: int = int(kwargs.get("repair_time_limit_s", 10))
        sa_initial_temp: float = float(kwargs.get("sa_initial_temp", 100.0))
        sa_cooling_rate: float = float(kwargs.get("sa_cooling_rate", 0.995))
        max_no_improve_base_iters: int = int(kwargs.get("max_no_improve_iters", 0))
        dynamic_no_improve_enabled: bool = bool(
            kwargs.get("dynamic_no_improve_enabled", False)
        )
        due_pressure: float = max(0.0, float(kwargs.get("due_pressure", 0.0)))
        candidate_pressure: float = max(
            0.0,
            float(kwargs.get("candidate_pressure", 0.0)),
        )
        no_improve_due_alpha: float = float(kwargs.get("no_improve_due_alpha", 0.6))
        no_improve_candidate_beta: float = float(
            kwargs.get("no_improve_candidate_beta", 0.4)
        )
        no_improve_min_iters: int = int(
            kwargs.get(
                "no_improve_min_iters",
                max(1, max_no_improve_base_iters // 2)
                if max_no_improve_base_iters > 0
                else 0,
            )
        )
        no_improve_max_iters: int = int(
            kwargs.get(
                "no_improve_max_iters",
                max_no_improve_base_iters * 4 if max_no_improve_base_iters > 0 else 0,
            )
        )
        seed: int = int(kwargs.get("random_seed", 42))
        initial_beam_op_limit: int = int(kwargs.get("initial_beam_op_limit", 60))
        use_cpsat_repair: bool = bool(kwargs.get("use_cpsat_repair", True))
        cpsat_max_destroy_ops: int = int(
            kwargs.get("cpsat_max_destroy_ops", min(20, max_destroy))
        )
        objective_weights: dict[str, float] = dict(
            kwargs.get(
                "objective_weights",
                {"makespan": 1.0, "setup": 0.3, "material_loss": 0.2, "tardiness": 0.5},
            )
        )

        max_no_improve_iters = max_no_improve_base_iters
        if dynamic_no_improve_enabled and max_no_improve_base_iters > 0:
            scaled_no_improve = int(
                round(
                    max_no_improve_base_iters
                    * (
                        1.0
                        + no_improve_due_alpha * due_pressure
                        + no_improve_candidate_beta * candidate_pressure
                    )
                )
            )
            max_no_improve_iters = min(
                no_improve_max_iters,
                max(no_improve_min_iters, scaled_no_improve),
            )

        rng = random.Random(seed)
        n_ops = len(problem.operations)
        ops_by_id = {op.id: op for op in problem.operations}
        op_positions = {op.id: index for index, op in enumerate(problem.operations)}
        successors_by_op: dict[UUID, list[UUID]] = {}
        for op in problem.operations:
            if op.predecessor_op_id is not None:
                successors_by_op.setdefault(op.predecessor_op_id, []).append(op.id)
        sdst = SdstMatrix.from_problem(problem)
        checker = FeasibilityChecker()
        dispatch_context = build_dispatch_context(problem)

        # ------- Phase 1: Initial solution -------
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        initial_solution_t0 = time.monotonic()
        if n_ops <= initial_beam_op_limit:
            initial_solver_name = "beam"
            initial_result = BeamSearchDispatch(beam_width=3).solve(problem)
        else:
            initial_solver_name = "greedy"
            initial_result = GreedyDispatch().solve(problem)

        if not initial_result.assignments or len(initial_result.assignments) != n_ops:
            # Fall back to greedy if beam failed to cover the full instance.
            initial_solver_name = "greedy"
            initial_result = GreedyDispatch().solve(problem)
            if not initial_result.assignments or len(initial_result.assignments) != n_ops:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                return ScheduleResult(
                    solver_name=self.name,
                    status=SolverStatus.ERROR,
                    duration_ms=elapsed_ms,
                    metadata={"error": "initial solution generation failed"},
                )

        initial_solution_ms = int((time.monotonic() - initial_solution_t0) * 1000)
        time_limit_exhausted_before_search = (time.monotonic() - t0) > time_limit_s

        # Current best
        current_assignments = list(initial_result.assignments)
        current_obj = _evaluate_objective(problem, current_assignments, sdst)
        current_cost = _objective_cost(current_obj, objective_weights)
        initial_cost = current_cost

        best_assignments = list(current_assignments)
        best_obj = current_obj
        best_cost = current_cost

        # ------- Phase 2: ALNS operator selection (Roulette Wheel) -------
        n_operators = len(DESTROY_OPERATORS)
        operator_scores = [1.0] * n_operators  # Accumulated scores
        operator_attempts = [1] * n_operators  # Avoid /0
        operator_weights = [1.0 / n_operators] * n_operators

        # Score rewards (Ropke & Pisinger 2006 §4.2)
        sigma_1 = 33.0  # new global best
        sigma_2 = 9.0   # better than current
        sigma_3 = 3.0   # accepted (SA)

        temperature = sa_initial_temp
        destroy_size = max(min_destroy, int(n_ops * destroy_fraction))
        destroy_size = min(destroy_size, max_destroy)

        # Tracking
        improvements = 0
        cpsat_repair_attempts = 0
        cpsat_repairs = 0
        cpsat_repair_skips_large_destroy = 0
        cpsat_repair_timeouts = 0
        greedy_repair_attempts = 0
        greedy_repairs = 0
        greedy_repair_timeouts = 0
        cpsat_repair_ms_total = 0
        greedy_repair_ms_total = 0
        feasibility_failures = 0
        repair_rejection_reasons: dict[str, int] = {}
        iterations_completed = 0
        no_improve_streak = 0
        no_improve_early_stop = False

        logger.info(
            "ALNS starting: %d ops, %d machines, destroy_size=%d, max_iter=%d",
            n_ops,
            len(problem.work_centers),
            destroy_size,
            max_iterations,
        )

        # ------- Phase 3: Main ALNS loop -------
        if time_limit_exhausted_before_search:
            logger.info(
                "ALNS time limit exhausted during initial solution generation (%d ms)",
                initial_solution_ms,
            )
        else:
            for iteration in range(1, max_iterations + 1):
                elapsed = time.monotonic() - t0
                if elapsed > time_limit_s:
                    logger.info("ALNS time limit reached at iteration %d", iteration)
                    break

                iterations_completed = iteration

                # Select destroy operator (roulette wheel)
                total_weight = sum(operator_weights)
                r = rng.random() * total_weight
                cumulative = 0.0
                selected_op_idx = 0
                for idx, w in enumerate(operator_weights):
                    cumulative += w
                    if cumulative >= r:
                        selected_op_idx = idx
                        break

                op_name, destroy_fn = DESTROY_OPERATORS[selected_op_idx]

                # Destroy
                destroyed_ids = destroy_fn(
                    current_assignments, problem, sdst, destroy_size, rng,
                )
                if not destroyed_ids:
                    continue

                destroyed_ids = _expand_successor_closure(
                    destroyed_ids,
                    successors_by_op,
                )
                destroyed_ids = _cap_destroy_set_preserving_successor_closure(
                    destroyed_ids,
                    ops_by_id,
                    successors_by_op,
                    max_destroy,
                    rng,
                )

                # Frozen assignments (everything not destroyed)
                frozen = [a for a in current_assignments if a.operation_id not in destroyed_ids]
                frozen_by_op = {assignment.operation_id: assignment for assignment in frozen}

                # Repair — primary depends on use_cpsat_repair flag
                # CP-SAT repair (Laborie & Godard 2007) when enabled, greedy fallback otherwise
                new_assignments: list[Assignment] | None = None
                repair_used = "none"

                def record_repair_outcome(outcome: RepairOutcome) -> None:
                    if outcome.status == RepairStatus.FEASIBLE:
                        return
                    reason = outcome.reason or outcome.status.value
                    repair_rejection_reasons[reason] = repair_rejection_reasons.get(reason, 0) + 1

                if use_cpsat_repair and len(destroyed_ids) <= cpsat_max_destroy_ops:
                    cpsat_repair_attempts += 1
                    cpsat_repair_t0 = time.monotonic()
                    cpsat_outcome = _repair_cpsat_outcome(
                        problem,
                        frozen,
                        destroyed_ids,
                        time_limit_s=repair_time_limit_s,
                        ops_by_id=ops_by_id,
                        op_positions=op_positions,
                    )
                    cpsat_repair_ms_total += int((time.monotonic() - cpsat_repair_t0) * 1000)
                    if cpsat_outcome.status == RepairStatus.TIMEOUT:
                        cpsat_repair_timeouts += 1
                    if cpsat_outcome.status == RepairStatus.FEASIBLE:
                        cpsat_result = list(cpsat_outcome.assignments)
                        # Quick machine-overlap check against frozen assignments:
                        # CP-SAT sub-problem doesn't see frozen timelines, so verify
                        # no returned assignment overlaps a frozen one on the same machine.
                        test_candidate = frozen + cpsat_result
                        if (
                            not _has_machine_overlap(test_candidate)
                            and not _violates_frozen_precedence(cpsat_result, frozen_by_op, ops_by_id)
                        ):
                            new_assignments = cpsat_result
                            repair_used = "cpsat"
                            cpsat_repairs += 1
                        else:
                            record_repair_outcome(
                                RepairOutcome(
                                    status=RepairStatus.INFEASIBLE,
                                    assignments=(),
                                    reason="cpsat_conflict_with_frozen",
                                )
                            )
                    else:
                        record_repair_outcome(cpsat_outcome)
                elif use_cpsat_repair:
                    cpsat_repair_skips_large_destroy += 1

                if new_assignments is None:
                    greedy_repair_attempts += 1
                    greedy_repair_t0 = time.monotonic()
                    greedy_outcome = _repair_greedy_outcome(problem, frozen, destroyed_ids)
                    greedy_repair_ms_total += int((time.monotonic() - greedy_repair_t0) * 1000)
                    if greedy_outcome.status == RepairStatus.TIMEOUT:
                        greedy_repair_timeouts += 1
                    if greedy_outcome.status == RepairStatus.FEASIBLE:
                        greedy_result = list(greedy_outcome.assignments)
                        test_candidate = frozen + greedy_result
                        if (
                            not _has_machine_overlap(test_candidate)
                            and not _violates_frozen_precedence(greedy_result, frozen_by_op, ops_by_id)
                        ):
                            new_assignments = greedy_result
                            repair_used = "greedy"
                            greedy_repairs += 1
                        else:
                            record_repair_outcome(
                                RepairOutcome(
                                    status=RepairStatus.INFEASIBLE,
                                    assignments=(),
                                    reason="greedy_conflict_with_frozen",
                                )
                            )
                    else:
                        record_repair_outcome(greedy_outcome)

                if new_assignments is None:
                    continue  # repair failed, discard this iteration

                # Assemble candidate solution
                candidate = frozen + new_assignments

                # Quick feasibility sanity check (only check completeness)
                candidate_op_ids = {a.operation_id for a in candidate}
                if len(candidate_op_ids) != n_ops:
                    feasibility_failures += 1
                    continue
                if _has_precedence_violation(candidate, ops_by_id):
                    feasibility_failures += 1
                    continue

                # Evaluate
                candidate_obj = _evaluate_objective(problem, candidate, sdst)
                candidate_cost = _objective_cost(candidate_obj, objective_weights)
                delta = candidate_cost - current_cost

                # SA acceptance
                score_reward = 0.0
                if candidate_cost < best_cost:
                    # New global best
                    best_assignments = list(candidate)
                    best_obj = candidate_obj
                    best_cost = candidate_cost
                    current_assignments = candidate
                    current_obj = candidate_obj
                    current_cost = candidate_cost
                    score_reward = sigma_1
                    improvements += 1
                    no_improve_streak = 0
                    logger.debug(
                        "ALNS iter %d: new best (cost=%.1f, makespan=%.1f, %s destroy, %s repair)",
                        iteration, best_cost, best_obj.makespan_minutes, op_name, repair_used,
                    )
                elif _sa_accept(delta, temperature, rng):
                    current_assignments = candidate
                    current_obj = candidate_obj
                    current_cost = candidate_cost
                    score_reward = sigma_2 if delta < 0 else sigma_3
                    if delta < 0:
                        no_improve_streak = 0
                    else:
                        no_improve_streak += 1
                # else: reject
                else:
                    no_improve_streak += 1

                # Update operator scores
                operator_scores[selected_op_idx] += score_reward
                operator_attempts[selected_op_idx] += 1

                # Update operator weights every 50 iterations (Ropke & Pisinger 2006 §4.2)
                if iteration % 50 == 0:
                    for idx in range(n_operators):
                        if operator_attempts[idx] > 0:
                            operator_weights[idx] = max(
                                0.05,
                                0.5 * operator_weights[idx]
                                + 0.5 * (operator_scores[idx] / operator_attempts[idx]),
                            )
                    operator_scores = [0.0] * n_operators
                    operator_attempts = [1] * n_operators

                # Cool down
                temperature *= sa_cooling_rate

                if max_no_improve_iters > 0 and no_improve_streak >= max_no_improve_iters:
                    no_improve_early_stop = True
                    logger.info(
                        "ALNS early stop: no improvements for %d consecutive iterations",
                        no_improve_streak,
                    )
                    break

        # ------- Phase 4: Final validation -------
        # Recompute setups from final sequence
        recompute_assignment_setups(best_assignments, dispatch_context)
        final_obj = _evaluate_objective(problem, best_assignments, sdst)
        final_cost = _objective_cost(final_obj, objective_weights)

        # Full feasibility check
        violations = checker.check(problem, best_assignments)
        final_violations_before_recovery = len(violations)
        final_violation_recovery_attempted = final_violations_before_recovery > 0
        final_violation_recovered = False
        final_violation_recovery_source: str | None = None

        if final_violation_recovery_attempted:
            # Recover to the initial full schedule if the ALNS incumbent is invalid.
            # This keeps downstream RHC windows from failing due to a rare
            # end-of-search violation in an otherwise schedulable window.
            recovered_assignments = list(initial_result.assignments)
            recompute_assignment_setups(recovered_assignments, dispatch_context)
            recovered_violations = checker.check(problem, recovered_assignments)
            if not recovered_violations:
                logger.warning(
                    "ALNS final incumbent had %d violations; "
                    "recovering to initial solution",
                    final_violations_before_recovery,
                )
                best_assignments = recovered_assignments
                final_obj = _evaluate_objective(problem, best_assignments, sdst)
                final_cost = _objective_cost(final_obj, objective_weights)
                violations = recovered_violations
                final_violation_recovered = True
                final_violation_recovery_source = "initial_solution"
            else:
                logger.warning(
                    "ALNS final incumbent had %d violations; "
                    "initial-solution recovery still has %d violations",
                    final_violations_before_recovery,
                    len(recovered_violations),
                )

        status = SolverStatus.FEASIBLE if not violations else SolverStatus.ERROR

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        logger.info(
            "ALNS finished: %d iterations, %d improvements, cost=%.1f, "
            "makespan=%.1f min, %d cpsat repairs, %d greedy repairs, "
            "%d feasibility failures, %d violations, %d ms",
            iterations_completed, improvements, final_cost,
            final_obj.makespan_minutes, cpsat_repairs, greedy_repairs,
            feasibility_failures, len(violations), elapsed_ms,
        )

        return ScheduleResult(
            solver_name=self.name,
            status=status,
            assignments=best_assignments,
            objective=final_obj,
            duration_ms=elapsed_ms,
            random_seed=seed,
            metadata={
                "iterations_completed": iterations_completed,
                "improvements": improvements,
                "cpsat_repair_attempts": cpsat_repair_attempts,
                "cpsat_repairs": cpsat_repairs,
                "cpsat_repair_skips_large_destroy": cpsat_repair_skips_large_destroy,
                "cpsat_repair_timeouts": cpsat_repair_timeouts,
                "greedy_repair_attempts": greedy_repair_attempts,
                "greedy_repairs": greedy_repairs,
                "greedy_repair_timeouts": greedy_repair_timeouts,
                "repair_rejection_reasons": repair_rejection_reasons,
                "initial_solver": initial_solver_name,
                "initial_beam_op_limit": initial_beam_op_limit,
                "cpsat_max_destroy_ops": cpsat_max_destroy_ops,
                "initial_solution_ms": initial_solution_ms,
                "time_limit_exhausted_before_search": time_limit_exhausted_before_search,
                "max_no_improve_iters": max_no_improve_iters,
                "max_no_improve_base_iters": max_no_improve_base_iters,
                "dynamic_no_improve_enabled": dynamic_no_improve_enabled,
                "due_pressure": round(due_pressure, 4),
                "candidate_pressure": round(candidate_pressure, 4),
                "no_improve_due_alpha": no_improve_due_alpha,
                "no_improve_candidate_beta": no_improve_candidate_beta,
                "no_improve_min_iters": no_improve_min_iters,
                "no_improve_max_iters": no_improve_max_iters,
                "no_improve_early_stop": no_improve_early_stop,
                "no_improve_streak_final": no_improve_streak,
                "cpsat_repair_ms_total": cpsat_repair_ms_total,
                "greedy_repair_ms_total": greedy_repair_ms_total,
                "cpsat_repair_ms_mean": round(cpsat_repair_ms_total / cpsat_repair_attempts, 2)
                if cpsat_repair_attempts > 0
                else 0.0,
                "greedy_repair_ms_mean": round(greedy_repair_ms_total / greedy_repair_attempts, 2)
                if greedy_repair_attempts > 0
                else 0.0,
                "feasibility_failures": feasibility_failures,
                "final_violation_recovery_attempted": final_violation_recovery_attempted,
                "final_violation_recovered": final_violation_recovered,
                "final_violation_recovery_source": final_violation_recovery_source,
                "final_violations_before_recovery": final_violations_before_recovery,
                "final_violations": len(violations),
                "destroy_operators": {
                    name: {
                        "final_weight": round(operator_weights[i], 4),
                    }
                    for i, (name, _) in enumerate(DESTROY_OPERATORS)
                },
                "sdst_matrix_bytes": sdst.memory_bytes(),
                "initial_cost": round(initial_cost, 2),
                "final_cost": round(final_cost, 2),
                "improvement_pct": round(
                    (1 - final_cost / max(initial_cost, 1e-9)) * 100, 2
                ),
            },
        )
