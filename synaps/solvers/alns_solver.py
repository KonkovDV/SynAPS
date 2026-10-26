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

import logging
import math
import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from synaps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from synaps.solvers import BaseSolver
from synaps.solvers._alns_config import AlnsRunConfig
from synaps.solvers._dispatch_support import (
    APPEND_GAP_SCAN_MIN_OPS,
    MachineIndex,
    build_dispatch_context,
    find_earliest_feasible_slot,
    has_aux_capacity_violation,
    recompute_assignment_setups,
)
from synaps.solvers._time_windows import operation_earliest_offset_minutes
from synaps.solvers.coverage_outcome import stamp_honest_coverage
from synaps.solvers.feasibility_checker import FeasibilityChecker

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False
from synaps.solvers.lower_bounds import compute_relaxed_makespan_lower_bound
from synaps.solvers.sdst_matrix import SdstMatrix
from synaps.timegrain import duration_minutes_for

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from uuid import UUID

logger = logging.getLogger(__name__)


class RepairStatus(StrEnum):
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


@dataclass(frozen=True, slots=True)
class AlnsIterationRecord:
    """Per-iteration ALNS metrics record for convergence diagnostics.

    Used when ``record_iteration_metrics=True`` to capture a bounded trace
    (max 500 records) of the ALNS search trajectory.
    """

    iteration: int
    operator_name: str
    destroy_size: int
    repair_status: str  # "feasible", "timeout", "infeasible"
    candidate_cost: float
    best_cost: float
    temperature: float
    accepted: bool
    improved: bool

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for metadata embedding."""
        return {
            "iteration": self.iteration,
            "operator_name": self.operator_name,
            "destroy_size": self.destroy_size,
            "repair_status": self.repair_status,
            "candidate_cost": self.candidate_cost,
            "best_cost": self.best_cost,
            "temperature": self.temperature,
            "accepted": self.accepted,
            "improved": self.improved,
        }


# ---------------------------------------------------------------------------
# Objective evaluation
# ---------------------------------------------------------------------------


def _sum_machine_transitions(
    sdst: SdstMatrix,
    ops_by_id: dict[Any, Any],
    machine_assignments: list[Assignment],
) -> tuple[float, float, float]:
    """Sum setup / material / energy along a single machine timeline."""
    setup = 0.0
    loss = 0.0
    energy = 0.0
    for i in range(1, len(machine_assignments)):
        prev_state = ops_by_id[machine_assignments[i - 1].operation_id].state_id
        curr_state = ops_by_id[machine_assignments[i].operation_id].state_id
        wc_id = machine_assignments[i].work_center_id
        setup += sdst.get_setup(wc_id, prev_state, curr_state)
        loss += sdst.get_material_loss(wc_id, prev_state, curr_state)
        energy += sdst.get_energy(wc_id, prev_state, curr_state)
    return setup, loss, energy


def _evaluate_objective(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    sdst: SdstMatrix,
    *,
    ops_by_id: dict[Any, Any] | None = None,
) -> ObjectiveValues:
    """Compute multi-objective values from a set of assignments."""
    horizon_start = problem.planning_horizon_start
    horizon_span = (problem.planning_horizon_end - horizon_start).total_seconds() / 60.0
    if not assignments:
        # F10: with nothing scheduled, every order completes at the horizon
        # end (maximally late) — not for free at t=0.
        return ObjectiveValues(
            total_tardiness_minutes=sum(
                max(
                    horizon_span - (order.due_date - horizon_start).total_seconds() / 60.0,
                    0.0,
                )
                for order in problem.orders
            )
        )

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    # Makespan
    makespan = max((a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments)

    # Setup and material loss from machine sequences
    total_setup = 0.0
    total_material_loss = 0.0
    total_energy = 0.0
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for _wc_id, machine_assignments in by_machine.items():
        machine_assignments.sort(key=lambda a: a.start_time)
        setup, loss, energy = _sum_machine_transitions(sdst, ops_by_id, machine_assignments)
        total_setup += setup
        total_material_loss += loss
        total_energy += energy

    # Tardiness (F10: unscheduled orders complete at the horizon end, so ALNS
    # cannot "improve" the objective by dropping a late order).
    order_completion: dict[Any, float] = {}
    for a in assignments:
        op = ops_by_id[a.operation_id]
        end = (a.end_time - horizon_start).total_seconds() / 60.0
        if op.order_id not in order_completion or end > order_completion[op.order_id]:
            order_completion[op.order_id] = end
    total_tardiness = 0.0
    for order in problem.orders:
        completion = order_completion.get(order.id, horizon_span)
        due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
        total_tardiness += max(completion - due_offset, 0.0)

    return ObjectiveValues(
        makespan_minutes=makespan,
        total_setup_minutes=total_setup,
        total_material_loss=total_material_loss,
        total_tardiness_minutes=total_tardiness,
        total_energy_kwh=total_energy,
    )


def _normalize_objective_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Align ALNS weights with :data:`synaps.objective.DEFAULT_WEIGHTS` + aliases.

    Accepts legacy ``material_loss`` / ``energy_kwh`` keys and maps them onto the
    canonical ``material`` / ``energy`` keys used by :func:`synaps.objective.scalarize`
    (Wave 11 / H3).
    """
    from synaps.objective import DEFAULT_WEIGHTS

    normalized = dict(DEFAULT_WEIGHTS)
    if not weights:
        return normalized
    normalized.update(weights)
    if "material" not in weights and "material_loss" in weights:
        normalized["material"] = float(weights["material_loss"])
    if "energy" not in weights and "energy_kwh" in weights:
        normalized["energy"] = float(weights["energy_kwh"])
    # Keep legacy aliases readable for any direct .get("material_loss") call sites.
    normalized.setdefault("material_loss", float(normalized.get("material", 0.0)))
    normalized.setdefault("energy_kwh", float(normalized.get("energy", 0.0)))
    return normalized


def _objective_cost(obj: ObjectiveValues, weights: dict[str, float] | None) -> float:
    """Scalar cost from multi-objective values (canonical :func:`scalarize`)."""
    from synaps.objective import scalarize

    return scalarize(obj, _normalize_objective_weights(weights))


def _constructive_seed_cost(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    sdst: SdstMatrix,
    ops_by_id: dict[Any, Any],
    objective_weights: dict[str, float],
) -> float:
    return _objective_cost(
        _evaluate_objective(problem, assignments, sdst, ops_by_id=ops_by_id),
        objective_weights,
    )


def _maybe_prefer_python_seed(
    problem: ScheduleProblem,
    native_assignments: list[Assignment],
    *,
    n_ops: int,
    initial_beam_op_limit: int,
    seed_budget_s: float,
    sdst: SdstMatrix,
    ops_by_id: dict[Any, Any],
    objective_weights: dict[str, float],
    is_valid: Any,
) -> tuple[str, list[Assignment]]:
    """Keep native seed unless a small-n Python constructive is strictly cheaper.

    Native ``greedy_repair`` is a fast complete packing, not a quality
    constructive. On instances small enough for beam/greedy, tournament so
    ALNS does not start from a worse-than-greedy incumbent. Large *n* keeps
    native-only to protect the long-horizon path.
    """
    if n_ops > initial_beam_op_limit:
        return "native_greedy", native_assignments

    from synaps.solvers.greedy_dispatch import GreedyDispatch

    greedy = GreedyDispatch().solve(problem, time_limit_s=seed_budget_s)
    greedy_assignments = list(greedy.assignments)
    if not is_valid(greedy_assignments):
        return "native_greedy", native_assignments
    native_cost = _constructive_seed_cost(
        problem, native_assignments, sdst, ops_by_id, objective_weights
    )
    greedy_cost = _constructive_seed_cost(
        problem, greedy_assignments, sdst, ops_by_id, objective_weights
    )
    if greedy_cost < native_cost - 1e-9:
        return "greedy", greedy_assignments
    return "native_greedy", native_assignments


def _try_unconstrained_list_schedule_seed(
    problem: ScheduleProblem,
    *,
    dispatch_context: Any,
    n_ops: int,
    frozen_assignments: list[Assignment],
    deadline_exceeded: Callable[[], bool] | None,
) -> ScheduleResult | None:
    """Complete large-n seed via COVER list-schedule.

    Does not change ``global_greedy_cover_min_ops``. Machine calendar skips
    this ALNS seed path (auto-route stays ``CALENDAR_AWARE``). Hard per-op windows are
    allowed: list-schedule already clips ``latest_finish``. Frozen RHC inner
    windows skip it.
    """

    if frozen_assignments or n_ops < APPEND_GAP_SCAN_MIN_OPS:
        return None
    from synaps.calendar import work_centers_have_calendar
    from synaps.solvers.rhc._cover import place_operations_list_schedule
    from synaps.solvers.rhc._solver import RhcSolver

    if work_centers_have_calendar(problem.work_centers):
        return None
    horizon_start = problem.planning_horizon_start
    horizon_minutes = (problem.planning_horizon_end - horizon_start).total_seconds() / 60.0
    op_earliest: dict[Any, float] = {}
    RhcSolver._compute_earliest_starts(problem, op_earliest)
    assignments: list[Assignment] = []
    assignment_by_op: dict[Any, Assignment] = {}
    scheduled_ids: set[Any] = set()
    place_operations_list_schedule(
        operations=problem.operations,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        op_earliest=op_earliest,
        default_wc_ids=[work_center.id for work_center in problem.work_centers],
        deadline_exceeded=deadline_exceeded,
    )
    if not assignments:
        return None
    status = SolverStatus.FEASIBLE if len(assignments) == n_ops else SolverStatus.TIMEOUT
    return ScheduleResult(
        solver_name="list_schedule_cover",
        status=status,
        assignments=assignments,
    )


# ---------------------------------------------------------------------------
# Incremental objective evaluation (P2.1 — avoids full re-sort every iter)
# ---------------------------------------------------------------------------


@dataclass
class _MachineObjectiveCache:
    """Per-machine cached objective components for incremental ALNS evaluation."""

    # Per-machine makespan (max end offset), setup, material loss, and energy
    machine_makespan: dict[Any, float]
    machine_setup: dict[Any, float]
    machine_loss: dict[Any, float]
    machine_energy: dict[Any, float]
    # Aggregate totals
    total_makespan: float
    total_setup: float
    total_material_loss: float
    total_energy: float
    total_tardiness: float
    # Pre-computed order completion offsets
    order_completion: dict[Any, float]
    # Pre-computed order due offsets (minutes from horizon_start)
    order_due_offsets: dict[Any, float]


def _build_machine_objective_cache(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    sdst: SdstMatrix,
    *,
    ops_by_id: dict[Any, Any],
    horizon_start: Any,
    order_due_offsets: dict[Any, float] | None = None,
) -> _MachineObjectiveCache:
    """Build per-machine cache for incremental objective evaluation."""
    machine_makespan: dict[Any, float] = {}
    machine_setup: dict[Any, float] = {}
    machine_loss: dict[Any, float] = {}
    machine_energy: dict[Any, float] = {}

    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)

    for wc_id, ma in by_machine.items():
        ma.sort(key=lambda a: a.start_time)
        machine_makespan[wc_id] = max(
            (a.end_time - horizon_start).total_seconds() / 60.0 for a in ma
        )
        setup, loss, energy = _sum_machine_transitions(sdst, ops_by_id, ma)
        machine_setup[wc_id] = setup
        machine_loss[wc_id] = loss
        machine_energy[wc_id] = energy

    total_makespan = max(machine_makespan.values()) if machine_makespan else 0.0
    total_setup = sum(machine_setup.values())
    total_material_loss = sum(machine_loss.values())
    total_energy = sum(machine_energy.values())

    order_completion: dict[Any, float] = {}
    for a in assignments:
        op = ops_by_id[a.operation_id]
        end = (a.end_time - horizon_start).total_seconds() / 60.0
        if op.order_id not in order_completion or end > order_completion[op.order_id]:
            order_completion[op.order_id] = end

    if order_due_offsets is None:
        order_due_offsets = {
            order.id: (order.due_date - horizon_start).total_seconds() / 60.0
            for order in problem.orders
        }

    # F10: an order with no scheduled ops completes at the horizon end.
    horizon_span = (problem.planning_horizon_end - horizon_start).total_seconds() / 60.0
    total_tardiness = 0.0
    for order in problem.orders:
        completion = order_completion.get(order.id, horizon_span)
        total_tardiness += max(completion - order_due_offsets[order.id], 0.0)

    return _MachineObjectiveCache(
        machine_makespan=machine_makespan,
        machine_setup=machine_setup,
        machine_loss=machine_loss,
        machine_energy=machine_energy,
        total_makespan=total_makespan,
        total_setup=total_setup,
        total_material_loss=total_material_loss,
        total_energy=total_energy,
        total_tardiness=total_tardiness,
        order_completion=order_completion,
        order_due_offsets=order_due_offsets,
    )


def _evaluate_objective_incremental(
    problem: ScheduleProblem,
    candidate: list[Assignment],
    sdst: SdstMatrix,
    *,
    ops_by_id: dict[Any, Any],
    horizon_start: Any,
    affected_machine_ids: set[Any],
    base_cache: _MachineObjectiveCache,
) -> tuple[ObjectiveValues, _MachineObjectiveCache]:
    """Recompute objective only for affected machines, reusing cached values.

    Returns the new ObjectiveValues and an updated cache for the candidate.
    """
    # Rebuild only affected machines
    affected_assignments: dict[Any, list[Assignment]] = {}
    for a in candidate:
        if a.work_center_id in affected_machine_ids:
            affected_assignments.setdefault(a.work_center_id, []).append(a)

    new_machine_makespan = dict(base_cache.machine_makespan)
    new_machine_setup = dict(base_cache.machine_setup)
    new_machine_loss = dict(base_cache.machine_loss)
    new_machine_energy = dict(base_cache.machine_energy)

    # Remove affected machines that may now be empty
    for wc_id in affected_machine_ids:
        if wc_id not in affected_assignments:
            new_machine_makespan.pop(wc_id, None)
            new_machine_setup.pop(wc_id, None)
            new_machine_loss.pop(wc_id, None)
            new_machine_energy.pop(wc_id, None)

    for wc_id, ma in affected_assignments.items():
        ma.sort(key=lambda a: a.start_time)
        new_machine_makespan[wc_id] = max(
            (a.end_time - horizon_start).total_seconds() / 60.0 for a in ma
        )
        setup, loss, energy = _sum_machine_transitions(sdst, ops_by_id, ma)
        new_machine_setup[wc_id] = setup
        new_machine_loss[wc_id] = loss
        new_machine_energy[wc_id] = energy

    total_makespan = max(new_machine_makespan.values()) if new_machine_makespan else 0.0
    total_setup = sum(new_machine_setup.values())
    total_material_loss = sum(new_machine_loss.values())
    total_energy = sum(new_machine_energy.values())

    # Recompute order completion (affected operations may change order completion)
    new_order_completion = dict(base_cache.order_completion)
    # Reset affected orders' completion to re-scan
    affected_order_ids: set[Any] = set()
    for a in candidate:
        if a.work_center_id in affected_machine_ids:
            op = ops_by_id[a.operation_id]
            affected_order_ids.add(op.order_id)

    # Re-derive completion for affected orders from all assignments. POP the
    # stale entries (not reset to 0.0): an affected order may end up with no
    # assignments, and F10 requires it to complete at the horizon END.
    for oid in affected_order_ids:
        new_order_completion.pop(oid, None)
    for a in candidate:
        op = ops_by_id[a.operation_id]
        if op.order_id in affected_order_ids:
            end = (a.end_time - horizon_start).total_seconds() / 60.0
            if end > new_order_completion.get(op.order_id, 0.0):
                new_order_completion[op.order_id] = end

    horizon_span = (problem.planning_horizon_end - horizon_start).total_seconds() / 60.0
    total_tardiness = 0.0
    order_due_offsets = base_cache.order_due_offsets
    for order in problem.orders:
        completion = new_order_completion.get(order.id, horizon_span)
        total_tardiness += max(completion - order_due_offsets[order.id], 0.0)

    obj = ObjectiveValues(
        makespan_minutes=total_makespan,
        total_setup_minutes=total_setup,
        total_material_loss=total_material_loss,
        total_tardiness_minutes=total_tardiness,
        total_energy_kwh=total_energy,
    )

    new_cache = _MachineObjectiveCache(
        machine_makespan=new_machine_makespan,
        machine_setup=new_machine_setup,
        machine_loss=new_machine_loss,
        machine_energy=new_machine_energy,
        total_makespan=total_makespan,
        total_setup=total_setup,
        total_material_loss=total_material_loss,
        total_energy=total_energy,
        total_tardiness=total_tardiness,
        order_completion=new_order_completion,
        order_due_offsets=order_due_offsets,
    )
    return obj, new_cache


# ---------------------------------------------------------------------------
# Destroy operators
#   random     — uniform random removal
#   worst      — removal by machine-local setup contribution
#                (Shaw 1998; Ropke & Pisinger 2006, Transportation Science)
#   related    — Shaw relatedness removal seeded by a random anchor
#                (Shaw 1998)
#   machine_segment — contiguous segment removal from one machine
#                to break high-cost setup chains (domain heuristic)
#   precedence_chain — R8 order-based ejection chain removal
#                (Voudouris & Tsang 1999; Ropke & Pisinger 2006 §3.3)
#   critical_path — longest-path bottleneck-chain removal via topological DP
#                (Kelley & Walker 1959; Adams, Balas & Zawack 1988)
# ---------------------------------------------------------------------------


def _destroy_random(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
    **_kwargs: Any,
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
    *,
    ops_by_id: dict[Any, Any] | None = None,
    energy_weight: float = 0.0,
    **_kwargs: Any,
) -> set[UUID]:
    """Remove operations contributing the most to setup cost (worst removal).

    Picks operations whose machine-local setup contribution (predecessor→self
    + self→successor) is highest. When ``energy_weight > 0``, also charges
    ``energy_weight * energy_kwh`` on the same transitions (Wave 7.1). The
    native scorer is setup-only, so energy-weighted runs stay on the Python
    reference path.
    """
    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    # --- Try native scoring path (setup-only; skip when energy is weighted) ---
    native_scores = None
    if float(energy_weight) == 0.0:
        native_scores = _destroy_worst_native_scores(assignments, sdst, ops_by_id)
    op_cost_by_id: dict[UUID, float]
    if native_scores is not None:
        # native_scores is a dict[UUID, float] of per-operation costs
        op_cost_by_id = native_scores
    else:
        # --- Python reference implementation (authoritative) ---
        by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            by_machine.setdefault(a.work_center_id, []).append(a)

        op_cost_by_id = {}
        for wc_id, machine_assignments in by_machine.items():
            machine_assignments.sort(key=lambda a: a.start_time)
            for i, a in enumerate(machine_assignments):
                cost = 0.0
                op = ops_by_id[a.operation_id]
                if i > 0:
                    prev_op = ops_by_id[machine_assignments[i - 1].operation_id]
                    cost += sdst.get_setup(wc_id, prev_op.state_id, op.state_id)
                    cost += sdst.get_material_loss(wc_id, prev_op.state_id, op.state_id)
                    cost += float(energy_weight) * sdst.get_energy(
                        wc_id, prev_op.state_id, op.state_id
                    )
                if i < len(machine_assignments) - 1:
                    next_op = ops_by_id[machine_assignments[i + 1].operation_id]
                    cost += sdst.get_setup(wc_id, op.state_id, next_op.state_id)
                    cost += sdst.get_material_loss(wc_id, op.state_id, next_op.state_id)
                    cost += float(energy_weight) * sdst.get_energy(
                        wc_id, op.state_id, next_op.state_id
                    )
                op_cost_by_id[a.operation_id] = cost

    # Sort by cost descending, add randomness to avoid deterministic loops
    ranked = sorted(op_cost_by_id.items(), key=lambda x: -x[1])
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


def _destroy_worst_native_scores(
    assignments: list[Assignment],
    sdst: SdstMatrix,
    ops_by_id: dict[Any, Any],
) -> dict[UUID, float] | None:
    """Attempt native scoring for _destroy_worst. Returns None if unavailable.

    Builds the CSR machine-sorted structure and delegates to the native
    compute_destroy_worst_scores function. The native function computes
    setup-cost contributions only (not material loss) — matching the design
    spec for the native acceleration path.
    """
    if not _HAS_NUMPY:
        return None

    from synaps.accelerators import compute_destroy_worst_scores_native

    # Build CSR machine grouping sorted by start_time
    by_machine: dict[Any, list[tuple[int, Assignment]]] = {}
    assign_idx_map: dict[UUID, int] = {}
    for idx, a in enumerate(assignments):
        assign_idx_map[a.operation_id] = idx
        by_machine.setdefault(a.work_center_id, []).append((idx, a))

    n_assignments = len(assignments)
    n_machines = len(by_machine)

    # Build CSR offsets and indices
    machine_offsets = np.zeros(n_machines + 1, dtype=np.int64)
    assignment_indices_list: list[int] = []

    for m_idx, (_wc_id, machine_assigns) in enumerate(by_machine.items()):
        # Sort by start_time within each machine
        machine_assigns.sort(key=lambda x: x[1].start_time)
        machine_offsets[m_idx + 1] = machine_offsets[m_idx] + len(machine_assigns)
        for orig_idx, _a in machine_assigns:
            assignment_indices_list.append(orig_idx)

    assignment_indices = np.array(assignment_indices_list, dtype=np.int64)

    # Build per-assignment state indices and wc indices
    state_ids = np.zeros(n_assignments, dtype=np.int64)
    wc_indices = np.zeros(n_assignments, dtype=np.int64)

    for idx, a in enumerate(assignments):
        op = ops_by_id[a.operation_id]
        si = sdst.state_id_to_idx.get(op.state_id, -1)
        wi = sdst.wc_id_to_idx.get(a.work_center_id, -1)
        state_ids[idx] = si
        wc_indices[idx] = wi

    # Flatten SDST setup matrix to float64
    sdst_setup_flat = sdst.setup_minutes.astype(np.float64).ravel()

    result = compute_destroy_worst_scores_native(
        machine_offsets=machine_offsets,
        assignment_indices=assignment_indices,
        state_ids=state_ids,
        sdst_setup_flat=sdst_setup_flat,
        wc_indices=wc_indices,
        n_wc=sdst.n_wc,
        n_states=sdst.n_states,
    )

    if result is None:
        return None

    # Map back to operation UUIDs
    scores: dict[UUID, float] = {}
    for idx, a in enumerate(assignments):
        scores[a.operation_id] = float(result[idx])

    return scores


def _destroy_related(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
    **_kwargs: Any,
) -> set[UUID]:
    """Remove operations that are related to a seed operation (Shaw removal).

    Relatedness = same machine assignment + low setup time + temporal proximity.
    Shaw (1998): operations are related if they share resources and have
    similar processing characteristics.
    """
    if not assignments:
        return set()

    if ops_by_id is None:
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
        # R7: Temporal proximity — operations closer in time are more related
        # (Ropke & Pisinger 2006: temporal relatedness prevents idle-time gaps
        # from decoupling structurally adjacent operations).
        time_gap_minutes = abs((a.start_time - seed_assignment.start_time).total_seconds() / 60.0)
        score += time_gap_minutes * 0.01
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
    *,
    ops_by_id: dict[Any, Any] | None = None,
    **_kwargs: Any,
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

    _wc_id, machine_seq = rng.choice(valid_machines)
    seg_size = min(destroy_size, len(machine_seq))
    start_idx = rng.randint(0, len(machine_seq) - seg_size)
    return {machine_seq[i].operation_id for i in range(start_idx, start_idx + seg_size)}


def _destroy_precedence_chain(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
    **_kwargs: Any,
) -> set[UUID]:
    """Remove all operations of a randomly selected order (precedence-chain removal).

    R8 — Forces complete re-sequencing of an entire work order.
    Particularly effective for large instances where a single order occupies
    multiple work centers across many time windows, creating compounding
    sequencing errors.  Voudouris & Tsang (1999) term similar moves
    "ejection chains"; Ropke & Pisinger (2006) §3.3 generalise them as
    order-based removal.
    """
    if not assignments:
        return set()

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}
    ops_by_order: dict[Any, list[UUID]] = {}
    for a in assignments:
        op = ops_by_id.get(a.operation_id)
        if op is None:
            continue
        ops_by_order.setdefault(op.order_id, []).append(a.operation_id)

    if not ops_by_order:
        return _destroy_random(assignments, problem, sdst, destroy_size, rng)

    # Prefer orders that fit fully within destroy_size (clean chain removal)
    valid_orders = [
        (oid, oids) for oid, oids in ops_by_order.items() if 1 <= len(oids) <= destroy_size
    ]
    if valid_orders:
        _order_id, op_ids = rng.choice(valid_orders)
        return set(op_ids)

    # Fall back to largest order, capped at destroy_size
    _order_id, op_ids = max(ops_by_order.items(), key=lambda x: len(x[1]))
    return set(rng.sample(op_ids, min(destroy_size, len(op_ids))))


def _destroy_critical_path(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
    **_kwargs: Any,
) -> set[UUID]:
    """Remove operations on the critical path of the current schedule.

    Builds a combined DAG of precedence edges and machine-sequence edges
    (sorted by start_time), then computes the longest path via topological
    sort + dynamic programming in O(N + E) time.

    The critical path is the chain from a source node to the makespan-defining
    operation. Destroying it forces ALNS repair to focus on the bottleneck.

    The path weight is the sum of operation durations: setups, idle time and
    releases are not on it, so the chain is a duration-critical chain of the
    sequence DAG rather than the time-tight chain of the schedule (audit Q-05).

    Academic basis:
        - Kelley & Walker (1959): Critical Path Method (CPM)
        - Adams, Balas & Zawack (1988): shifting bottleneck + critical path
          for job-shop scheduling
    """
    if not assignments:
        return set()

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    dag = _ScheduleDag(assignments, ops_by_id)
    longest = dag.longest_paths()
    # If topological sort didn't cover all nodes (cycle in graph), fall back
    if longest is None:
        return _destroy_random(assignments, problem, sdst, destroy_size, rng)
    dist, predecessor_on_path = longest

    # Find the makespan-defining operation (node with maximum dist)
    makespan_op_id = max(dag.assigned_op_ids, key=lambda op_id: dist.get(op_id, 0.0))

    # Trace back the critical path
    critical_path: list[UUID] = []
    current: UUID | None = makespan_op_id
    while current is not None:
        critical_path.append(current)
        current = predecessor_on_path.get(current)
    critical_path.reverse()

    # Cap to destroy_size (take from the end — closer to makespan bottleneck)
    if len(critical_path) > destroy_size:
        critical_path = critical_path[-destroy_size:]

    if len(critical_path) < destroy_size:
        return _extend_with_machine_neighbors(
            critical_path, dag.by_machine, ops_by_id, sdst, destroy_size
        )
    return set(critical_path)


class _ScheduleDag:
    """Precedence + machine-sequence DAG of a schedule, durations as node weights."""

    def __init__(self, assignments: list[Assignment], ops_by_id: Mapping[Any, Any]) -> None:
        assignment_by_op: dict[UUID, Assignment] = {a.operation_id: a for a in assignments}
        # Machine sequences sorted by start_time
        self.by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            self.by_machine.setdefault(a.work_center_id, []).append(a)
        for wc_id in self.by_machine:
            self.by_machine[wc_id].sort(key=lambda a: a.start_time)
        # Node weight = the operation's duration in minutes; the longest path
        # length is then the sum of durations along the path:
        #   dist[node] = duration[node] + max(dist[predecessor on the path])
        self.op_duration: dict[UUID, float] = {
            a.operation_id: (a.end_time - a.start_time).total_seconds() / 60.0 for a in assignments
        }
        self.assigned_op_ids = set(assignment_by_op.keys())
        # Forward edges: precedence (op.predecessor_op_id -> op.id), then
        # machine sequence (consecutive operations on one machine).
        self.successors: dict[UUID, list[UUID]] = {}
        self.in_degree: dict[UUID, int] = {}
        for op_id in self.assigned_op_ids:
            self.successors.setdefault(op_id, [])
            self.in_degree.setdefault(op_id, 0)
        for op_id in self.assigned_op_ids:
            op = ops_by_id.get(op_id)
            if op is None:
                continue
            pred_id = op.predecessor_op_id
            if pred_id is not None and pred_id in self.assigned_op_ids:
                self._edge(pred_id, op_id)
        for machine_seq in self.by_machine.values():
            for i in range(len(machine_seq) - 1):
                self._edge(machine_seq[i].operation_id, machine_seq[i + 1].operation_id)

    def _edge(self, source: UUID, target: UUID) -> None:
        self.successors.setdefault(source, []).append(target)
        self.in_degree[target] = self.in_degree.get(target, 0) + 1

    def longest_paths(self) -> tuple[dict[UUID, float], dict[UUID, UUID | None]] | None:
        """Kahn order + forward DP; None when the graph has a cycle."""
        from collections import deque

        in_degree = self.in_degree
        queue: deque[UUID] = deque(
            op_id for op_id in self.assigned_op_ids if in_degree.get(op_id, 0) == 0
        )
        topo_order: list[UUID] = []
        while queue:
            node = queue.popleft()
            topo_order.append(node)
            for succ in self.successors.get(node, []):
                in_degree[succ] -= 1
                if in_degree[succ] == 0:
                    queue.append(succ)
        if len(topo_order) != len(self.assigned_op_ids):
            return None
        # dist[node] = longest path ending at node (inclusive of its duration)
        dist: dict[UUID, float] = {node: self.op_duration.get(node, 0.0) for node in topo_order}
        predecessor_on_path: dict[UUID, UUID | None] = dict.fromkeys(topo_order)
        for node in topo_order:
            node_dist = dist[node]
            for succ in self.successors.get(node, []):
                candidate_dist = node_dist + self.op_duration.get(succ, 0.0)
                if candidate_dist > dist[succ]:
                    dist[succ] = candidate_dist
                    predecessor_on_path[succ] = node
        return dist, predecessor_on_path


def _extend_with_machine_neighbors(
    critical_path: list[UUID],
    by_machine: dict[Any, list[Assignment]],
    ops_by_id: Mapping[Any, Any],
    sdst: SdstMatrix,
    destroy_size: int,
) -> set[UUID]:
    """Pad a short critical path with its machine neighbours, highest setup first.

    Candidates are the immediate machine-sequence predecessor / successor of
    each path node, scored by ``setup(prev -> self) + setup(self -> next)``.
    """
    critical_set = set(critical_path)
    op_to_machine_pos: dict[UUID, tuple[Any, int]] = {}
    for wc_id, machine_seq in by_machine.items():
        for i, a in enumerate(machine_seq):
            op_to_machine_pos[a.operation_id] = (wc_id, i)

    candidates: list[tuple[float, UUID]] = []
    seen_candidates: set[UUID] = set()
    for cp_op_id in critical_path:
        pos_info = op_to_machine_pos.get(cp_op_id)
        if pos_info is None:
            continue
        wc_id, idx = pos_info
        machine_seq = by_machine[wc_id]
        for neighbor_idx in (idx - 1, idx + 1):
            if neighbor_idx < 0 or neighbor_idx >= len(machine_seq):
                continue
            neighbor_op_id = machine_seq[neighbor_idx].operation_id
            if neighbor_op_id in critical_set or neighbor_op_id in seen_candidates:
                continue
            seen_candidates.add(neighbor_op_id)
            neighbor_op = ops_by_id.get(neighbor_op_id)
            if neighbor_op is None:
                continue
            cost = 0.0
            if neighbor_idx > 0:
                prev_op = ops_by_id.get(machine_seq[neighbor_idx - 1].operation_id)
                if prev_op is not None:
                    cost += sdst.get_setup(wc_id, prev_op.state_id, neighbor_op.state_id)
            if neighbor_idx < len(machine_seq) - 1:
                next_op = ops_by_id.get(machine_seq[neighbor_idx + 1].operation_id)
                if next_op is not None:
                    cost += sdst.get_setup(wc_id, neighbor_op.state_id, next_op.state_id)
            candidates.append((cost, neighbor_op_id))

    # Sort by setup contribution descending (highest cost first), then fill.
    candidates.sort(key=lambda x: -x[0])
    for _cost, op_id in candidates:
        if len(critical_set) >= destroy_size:
            break
        critical_set.add(op_id)
    return critical_set


def _destroy_due_pressure(
    assignments: list[Assignment],
    problem: ScheduleProblem,
    sdst: SdstMatrix,
    destroy_size: int,
    rng: random.Random,
    *,
    ops_by_id: dict[Any, Any] | None = None,
    **_kwargs: Any,
) -> set[UUID]:
    """Remove operations from orders with the highest weighted tardiness.

    Ranks orders by ``tardiness x order_weight`` (descending), then from each
    top-tardy order selects operations that are temporally latest in the order
    chain (highest ``end_time``).  Destroying the tail of an order is the
    cheapest way to recover tardiness, since the final operations are the ones
    missing the due date — moving them backward in time reduces the order's
    completion and therefore its tardiness contribution.

    Order weight follows the repository convention used by the greedy dispatcher
    (``greedy_dispatch.py``): ``priority / 500.0``, which normalises around the
    default priority of 500.

    Fallback semantics (task 2.2):
        When no orders are currently tardy, the operator falls back to orders
        with the smallest positive slack (``due_offset - latest_end_offset``).
        Smallest-slack orders are closest to becoming tardy and therefore the
        most valuable to re-optimise before they slip.  Within each such
        order, operations are selected in descending ``end_time`` order — the
        same temporally-latest-first policy used in the tardy branch.

    Successor closure (task 2.3):
        The returned set is a raw selection; callers wrap the result in
        ``_expand_successor_closure`` (see the ALNS main loop), which keeps the
        invariant that transitive successors of destroyed operations are also
        destroyed.

    Academic basis:
        - Pinedo (2012, *Scheduling: Theory, Algorithms, and Systems* §3):
          weighted tardiness is the standard tardiness objective in
          single-machine and job-shop scheduling.
        - Ropke & Pisinger (2006, Transportation Science): problem-specific
          destroy operators focused on the dominant cost component outperform
          uniform random removal in ALNS.
    """
    if not assignments:
        return set()

    if ops_by_id is None:
        ops_by_id = {op.id: op for op in problem.operations}

    horizon_start = problem.planning_horizon_start
    orders_by_id = {order.id: order for order in problem.orders}

    # Compute per-order latest end offset (minutes from horizon_start) and
    # group assignments by order for later selection.
    order_latest_end: dict[Any, float] = {}
    assignments_by_order: dict[Any, list[Assignment]] = {}
    for a in assignments:
        op = ops_by_id.get(a.operation_id)
        if op is None:
            continue
        end_offset = (a.end_time - horizon_start).total_seconds() / 60.0
        prev = order_latest_end.get(op.order_id)
        if prev is None or end_offset > prev:
            order_latest_end[op.order_id] = end_offset
        assignments_by_order.setdefault(op.order_id, []).append(a)

    # Compute weighted tardiness per order.
    # weight = priority / 500.0 (greedy_dispatch.py convention: normalise around
    # the default priority of 500).
    weighted_tardiness: list[tuple[float, Any]] = []
    for order_id, latest_end in order_latest_end.items():
        order = orders_by_id.get(order_id)
        if order is None:
            continue
        due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
        tardiness = max(0.0, latest_end - due_offset)
        if tardiness <= 0.0:
            continue
        weight = order.priority / 500.0
        weighted_tardiness.append((tardiness * weight, order_id))

    # Task 2.2: when no orders are tardy, fall back to orders with the
    # smallest positive slack (due_offset - latest_end_offset).  Orders that
    # are closest to slipping are the most valuable to re-optimise.
    if not weighted_tardiness:
        positive_slack: list[tuple[float, Any]] = []
        for order_id, latest_end in order_latest_end.items():
            order = orders_by_id.get(order_id)
            if order is None:
                continue
            due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
            slack = due_offset - latest_end
            if slack <= 0.0:
                # No positive slack: either already tardy (handled above) or
                # exactly on the due date; skip.
                continue
            positive_slack.append((slack, order_id))

        if not positive_slack:
            return set()

        # Rank by ascending slack (smallest slack first = most urgent).
        positive_slack.sort(key=lambda x: x[0])

        slack_destroyed: set[UUID] = set()
        for _slack, order_id in positive_slack:
            if len(slack_destroyed) >= destroy_size:
                break
            order_assignments = assignments_by_order.get(order_id, [])
            order_assignments.sort(key=lambda a: a.end_time, reverse=True)
            for a in order_assignments:
                if len(slack_destroyed) >= destroy_size:
                    break
                slack_destroyed.add(a.operation_id)

        return slack_destroyed

    # Rank tardy orders by weighted tardiness (descending).
    weighted_tardiness.sort(key=lambda x: -x[0])

    # Walk top-tardy orders and, within each, destroy operations in
    # descending end_time order (temporally latest first).
    destroyed: set[UUID] = set()
    for _score, order_id in weighted_tardiness:
        if len(destroyed) >= destroy_size:
            break
        order_assignments = assignments_by_order.get(order_id, [])
        order_assignments.sort(key=lambda a: a.end_time, reverse=True)
        for a in order_assignments:
            if len(destroyed) >= destroy_size:
                break
            destroyed.add(a.operation_id)

    return destroyed


# All destroy operators (random, worst, related: Shaw/Ropke-Pisinger;
#  machine_segment: domain heuristic for setup-chain disruption;
#  precedence_chain: R8 order-based ejection for work-order level re-sequencing;
#  critical_path: Kelley/Walker & Adams-Balas-Zawack bottleneck-chain removal;
#  due_pressure: Pinedo weighted-tardiness order-tail removal with slack fallback)
DESTROY_OPERATORS: list[tuple[str, Callable[..., Any]]] = [
    ("random", _destroy_random),
    ("worst", _destroy_worst),
    ("related", _destroy_related),
    ("machine_segment", _destroy_machine_segment),
    ("precedence_chain", _destroy_precedence_chain),
    ("critical_path", _destroy_critical_path),
    ("due_pressure", _destroy_due_pressure),
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
    num_workers: int = 1,
    ops_by_id: Mapping[Any, Any] | None = None,
    op_positions: Mapping[Any, int] | None = None,
    frozen_predecessor_end_offsets: Mapping[Any, float] | None = None,
    frozen_context_operations: list[Any] | None = None,
) -> RepairOutcome:
    """Repair by solving a sub-problem with CP-SAT over the destroyed operations.

    Frozen assignments constrain the machine timelines. Only the destroyed
    operations (+ their immediate predecessors if outside the set) are modeled.

    ``frozen_predecessor_end_offsets`` is keyed by **operation id** and remains
    authoritative when predecessor edges were cleared for ScheduleProblem
    validation (Wave 14 / C14-1; RHC composition).

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

    all_work_center_ids = [work_center.id for work_center in problem.work_centers]
    relevant_machine_ids = {
        work_center_id
        for operation in sub_operations
        for work_center_id in (
            operation.eligible_wc_ids if operation.eligible_wc_ids else all_work_center_ids
        )
    }
    relevant_frozen_assignments = [
        assignment
        for assignment in frozen_assignments
        if assignment.work_center_id in relevant_machine_ids
    ]
    frozen_assignments_by_op = {
        assignment.operation_id: assignment for assignment in frozen_assignments
    }
    # Wave 14 / C14-1: start from caller offsets (survive pred clear).
    offsets: dict[Any, int] = {
        op_id: int(offset) for op_id, offset in dict(frozen_predecessor_end_offsets or {}).items()
    }
    for op_id in destroyed_op_ids:
        operation = ops_by_id.get(op_id)
        if operation is None or operation.predecessor_op_id is None:
            continue
        if operation.predecessor_op_id in needed_ids:
            continue

        frozen_predecessor = frozen_assignments_by_op.get(operation.predecessor_op_id)
        if frozen_predecessor is None:
            if op_id not in offsets:
                return RepairOutcome(
                    status=RepairStatus.INFEASIBLE,
                    assignments=(),
                    reason="missing_frozen_predecessor",
                )
            continue

        offsets[op_id] = max(
            0,
            math.ceil(
                (frozen_predecessor.end_time - problem.planning_horizon_start).total_seconds()
                / 60.0
            ),
        )

    # Build sub-problem with the relevant operations only
    sub_problem = ScheduleProblem(
        states=problem.states,
        orders=problem.orders,
        operations=sub_operations,
        work_centers=problem.work_centers,
        setup_matrix=problem.setup_matrix,
        auxiliary_resources=problem.auxiliary_resources,
        aux_requirements=[r for r in problem.aux_requirements if r.operation_id in needed_ids],
        planning_horizon_start=problem.planning_horizon_start,
        planning_horizon_end=problem.planning_horizon_end,
    )

    # Solve the sub-problem
    solver = CpSatSolver()
    try:
        result = solver.solve(
            sub_problem,
            time_limit_s=time_limit_s,
            num_workers=max(1, int(num_workers)),
            auto_greedy_warm_start=False,
            enable_symmetry_breaking=False,
            frozen_assignments=relevant_frozen_assignments,
            frozen_predecessor_end_offsets=offsets,
            frozen_context_operations=list(frozen_context_operations or problem.operations),
            frozen_aux_requirements=list(problem.aux_requirements),
        )
    except ValueError as exc:
        return RepairOutcome(
            status=RepairStatus.INFEASIBLE,
            assignments=(),
            reason=f"cpsat_frozen_guard:{exc}",
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
    ops_by_id: Mapping[Any, Any] | None = None,
    op_positions: Mapping[Any, int] | None = None,
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
    *,
    use_native_greedy_repair: bool = True,
    native_skip_reasons: list[str] | None = None,
) -> RepairOutcome:
    """Fallback greedy repair when CP-SAT is too slow for the sub-region.

    When native acceleration is available and ``use_native_greedy_repair`` is True,
    attempts the Rust greedy repair first (10-30x faster). Falls back to the Python
    IncrementalRepair path if native is unavailable, returns invalid results, or
    fails feasibility validation.
    """
    op_positions = {op.id: index for index, op in enumerate(problem.operations)}
    disrupted_op_ids = sorted(destroyed_op_ids, key=op_positions.__getitem__)

    # Native greedy_repair is unbounded at n>=2000 (K3.6). Python IncrementalRepair
    # on thousands of holes is the same class of hang; caller skips completion.
    if use_native_greedy_repair and _HAS_NUMPY and len(disrupted_op_ids) > 0:
        native_result = _try_native_greedy_repair(
            problem,
            frozen_assignments,
            disrupted_op_ids,
            op_positions,
            skip_reasons=native_skip_reasons,
        )
        if native_result is not None:
            return native_result

    # --- Python fallback path ---
    from synaps.solvers.incremental_repair import IncrementalRepair

    repair_solver = IncrementalRepair()

    result = repair_solver.solve(
        problem,
        base_assignments=frozen_assignments,
        disrupted_op_ids=disrupted_op_ids,
        # radius=0: only the destroyed ops are re-placed; frozen assignments are
        # truly frozen. radius=1 caused regressions because IncrementalRepair
        # freed successor ops jointly but _repair_greedy_outcome filtered them out,
        # leaving stale successor positions that conflicted with the new placements.
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


def _release_offset_by_op(problem: ScheduleProblem) -> dict[UUID, float]:
    """M1 / G11: floor per op from order release_date and op.earliest_start."""
    horizon_start = problem.planning_horizon_start
    orders_by_id = {order.id: order for order in problem.orders}
    offsets: dict[UUID, float] = {}
    for op in problem.operations:
        order = orders_by_id.get(op.order_id)
        offset = operation_earliest_offset_minutes(op, order, horizon_start)
        if offset > 0:
            offsets[op.id] = offset
    return offsets


def _window_notary_violations(
    problem: ScheduleProblem,
    assignments: list[Assignment],
) -> list[Any]:
    """Notary view that keeps frozen extra-ops as occupancy, not UNKNOWN faults.

    Violations whose ``operation_id`` is outside the window problem (committed
    extras from prior RHC windows) are occupancy context, not a window claim
    fault. ``MACHINE_OVERLAP`` is kept: that kind is stamped on the machine,
    not on the foreign op id.
    """
    known_op_ids = {operation.id for operation in problem.operations}
    kept: list[Any] = []
    for violation in FeasibilityChecker().check(problem, assignments):
        kind = getattr(violation, "kind", None)
        if kind == "UNKNOWN_OPERATION":
            continue
        operation_id = getattr(violation, "operation_id", None)
        if (
            operation_id is not None
            and operation_id not in known_op_ids
            and kind == "HORIZON_BOUND_VIOLATION"
        ):
            continue
        kept.append(violation)
    return kept


def _native_repair_skip_reason(problem: ScheduleProblem) -> str | None:
    """Native greedy_repair has no calendar ABI; skip rather than inject 24/7."""
    from synaps.calendar import work_centers_have_calendar

    if problem.aux_requirements:
        return "aux_requirements"
    if any(int(getattr(wc, "max_parallel", 1) or 1) > 1 for wc in problem.work_centers):
        return "parallel_machines"
    if work_centers_have_calendar(problem.work_centers):
        return "calendar"
    return None


def _native_repair_blocking_violations(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    repaired_assignments: list[Assignment],
    disrupted_op_ids: list[UUID],
) -> list[Any]:
    """Filter window-subproblem notary noise from frozen extra-ops.

    Frozen committed ops from prior RHC windows are not in the window
    ``problem.operations``, so a naive ``check(problem, frozen+repaired)``
    emits UNKNOWN_OPERATION for every frozen row and silently disables
    native repair. Keep only faults that touch repaired/disrupted ops.
    """
    from synaps.solvers.feasibility_checker import ADVISORY_VIOLATION_KINDS

    violations = FeasibilityChecker().check(
        problem, list(frozen_assignments) + list(repaired_assignments)
    )
    disrupted = set(disrupted_op_ids)
    problem_op_ids = {operation.id for operation in problem.operations}
    blocking = []
    for violation in violations:
        if getattr(violation, "kind", None) in ADVISORY_VIOLATION_KINDS:
            continue
        if getattr(violation, "kind", None) == "UNKNOWN_OPERATION":
            continue
        operation_id = getattr(violation, "operation_id", None)
        if operation_id is not None and operation_id not in problem_op_ids:
            continue
        if (
            getattr(violation, "kind", None) == "MISSING_ASSIGNMENT"
            and operation_id not in disrupted
        ):
            continue
        blocking.append(violation)
    return blocking


def _native_repair_meta_from_skips(skip_reasons: list[str]) -> dict[str, Any]:
    """ALNS metadata for observe-only native greedy override skips (Wave 7.2 / RT H1)."""
    return {
        "native_greedy_repair_fallback_reason": (skip_reasons[-1] if skip_reasons else None),
        "native_greedy_repair_override_skips": sum(
            1 for reason in skip_reasons if reason == "machine_duration_overrides"
        ),
    }


def _ops_have_machine_duration_overrides(operations: list[Any]) -> bool:
    """True when any op carries T-30 ``machine_duration_overrides``.

    The native greedy kernel ranks machines with ``base_duration / speed`` only
    (Wave 5 H2 / Wave 6.1). When overrides are present, skip native and use the
    Python path that calls ``duration_minutes_for``.
    """
    return any(getattr(op, "machine_duration_overrides", None) for op in operations)


def _native_eligible_machine_indices(
    op: Any,
    wc_id_to_idx: Mapping[Any, int],
    all_wc_ids: list[Any],
) -> list[int]:
    """Pack one CSR row. Empty ``eligible_wc_ids`` means all work centers."""
    source = op.eligible_wc_ids if op.eligible_wc_ids else all_wc_ids
    indices: list[int] = []
    for wc_id in source:
        wc_idx = wc_id_to_idx.get(wc_id)
        if wc_idx is not None:
            indices.append(wc_idx)
    return indices


# D3: do not start a repair when remaining wall is below this many seconds.
_ALNS_MIN_REPAIR_REMAINING_S = 1.0


def _alns_wall_clock_honesty_meta(
    determinism: str,
    time_limit_exhausted_before_search: bool,
    iterations_completed: int,
    max_iterations: int,
    elapsed_s: float,
    time_limit_s: float,
    *,
    no_improve: bool = False,
) -> dict[str, Any]:
    """Stamp how the ALNS loop stopped. Not a bitwise-identity certificate.

    ``wall_clock_path_dependent`` is True only when the stop was a wall cut
    (including exhaustion before search). Repair still clamps to remaining
    wall budget on a ``max_iterations`` stop — that residual is not this flag.
    ``determinism_violated`` stays informational: never a CI error.
    The search loop also stops when remaining wall is below
    ``_ALNS_MIN_REPAIR_REMAINING_S`` (D3). That cut is a wall cut, not
    ``completed``.
    """
    if time_limit_exhausted_before_search:
        stop = "wall_clock_before_search"
    elif (
        elapsed_s + _ALNS_MIN_REPAIR_REMAINING_S >= time_limit_s
        and iterations_completed < max_iterations
    ):
        stop = "wall_clock"
    elif iterations_completed >= max_iterations:
        stop = "max_iterations"
    elif no_improve:
        stop = "no_improve"
    else:
        stop = "completed"
    wall = stop.startswith("wall_clock")
    return {
        "determinism": determinism,
        "determinism_violated": determinism == "strict" and wall,
        "wall_clock_path_dependent": wall,
        "search_stop_reason": stop,
    }


def _try_native_greedy_repair(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    disrupted_op_ids: list[UUID],
    op_positions: dict[UUID, int],
    *,
    skip_reasons: list[str] | None = None,
) -> RepairOutcome | None:
    """Attempt native greedy repair. Returns RepairOutcome or None to fall through.

    Builds the flat numpy arrays expected by the Rust greedy_repair_batch function,
    calls it, converts results back to Assignment objects, and validates feasibility.
    Returns None if native is unavailable, input construction fails, or the result
    fails basic validation.
    """
    from synaps.accelerators import _native_greedy_repair_batch

    # Record aux/parallel skips even when the native wheel is absent (CI test-fast).
    skip = _native_repair_skip_reason(problem)
    if skip is not None:
        if skip_reasons is not None:
            skip_reasons.append(skip)
        return None
    if max(len(problem.operations), len(disrupted_op_ids)) >= APPEND_GAP_SCAN_MIN_OPS:
        if skip_reasons is not None:
            skip_reasons.append("large_n_append_scan")
        return None
    if _native_greedy_repair_batch is None:
        return None

    try:
        ops_by_id = {op.id: op for op in problem.operations}
        if _ops_have_machine_duration_overrides(
            [ops_by_id[op_id] for op_id in disrupted_op_ids if op_id in ops_by_id]
        ):
            if skip_reasons is not None:
                skip_reasons.append("machine_duration_overrides")
            return None
        repaired_assignments = _native_greedy_dispatch(
            problem, disrupted_op_ids, ops_by_id, frozen_assignments, skip_reasons=skip_reasons
        )
        if repaired_assignments is None:
            return None

        # Quick feasibility validation: ignore UNKNOWN_OPERATION on frozen
        # ops that live outside the window sub-problem (W16 / RT coverage #6).
        if _native_repair_blocking_violations(
            problem, frozen_assignments, repaired_assignments, disrupted_op_ids
        ):
            if skip_reasons is not None:
                skip_reasons.append("validation_failed")
            return None

        # Sort by original operation position for deterministic output
        repaired_assignments.sort(key=lambda a: op_positions[a.operation_id])

        return RepairOutcome(
            status=RepairStatus.FEASIBLE,
            assignments=tuple(repaired_assignments),
            reason="native_greedy",
        )

    except Exception:
        # Any error in native path — silently fall through to Python
        return None


def _try_native_initial_seed(
    problem: ScheduleProblem,
    *,
    frozen_assignments: list[Assignment],
    ops_by_id: dict[Any, Any],
    frozen_assignments_by_op: dict[Any, Assignment],
) -> list[Assignment] | None:
    """Attempt native greedy dispatch for ALL operations as ALNS initial seed.

    Reuses greedy_repair_batch with disrupted_op_ids = all problem operations.
    Returns a list of Assignments or None if native is unavailable/fails.
    """
    from synaps.accelerators import _native_greedy_repair_batch

    if _native_repair_skip_reason(problem) is not None:
        return None
    if len(problem.operations) >= APPEND_GAP_SCAN_MIN_OPS:
        return None
    if _native_greedy_repair_batch is None:
        return None
    if _ops_have_machine_duration_overrides(list(ops_by_id.values())):
        return None

    try:
        # Operations are already in topological order in problem.operations
        # (predecessor always appears before dependent).
        all_op_ids = [op.id for op in problem.operations]
        if not all_op_ids:
            return None
        return _native_greedy_dispatch(problem, all_op_ids, ops_by_id, frozen_assignments)

    except Exception:
        # Any error in native path — silently fall through to Python
        return None


class _NativeDispatchInputs:
    """Structure-of-arrays input of the Rust ``greedy_repair_batch`` kernel."""

    __slots__ = (
        "base_durations",
        "eligible_indices",
        "eligible_offsets",
        "local_idx",
        "n_states",
        "n_wc",
        "predecessor_indices",
        "sdst_setup_flat",
        "speed_factors",
        "state_ids",
    )

    def __init__(
        self,
        problem: ScheduleProblem,
        op_ids: list[Any],
        ops_by_id: Mapping[Any, Any],
        wc_id_to_idx: dict[Any, int],
        state_id_to_idx: dict[Any, int],
    ) -> None:
        self.n_wc = len(problem.work_centers)
        self.n_states = len(problem.states)
        n = len(op_ids)
        # Map the dispatched op IDs to local indices for predecessor resolution
        self.local_idx = {op_id: i for i, op_id in enumerate(op_ids)}
        self.base_durations = np.empty(n, dtype=np.float64)
        self.predecessor_indices = np.full(n, -1, dtype=np.int64)
        self.state_ids = np.empty(n, dtype=np.int64)
        # CSR for eligible machines
        self.eligible_offsets = np.empty(n + 1, dtype=np.int64)
        self.eligible_offsets[0] = 0
        self.eligible_indices = np.empty(0, dtype=np.int64)
        self.sdst_setup_flat = np.zeros(self.n_wc * self.n_states * self.n_states, dtype=np.float64)
        for entry in problem.setup_matrix:
            wi = wc_id_to_idx.get(entry.work_center_id)
            fi = state_id_to_idx.get(entry.from_state_id)
            ti = state_id_to_idx.get(entry.to_state_id)
            if wi is not None and fi is not None and ti is not None:
                self.sdst_setup_flat[
                    wi * self.n_states * self.n_states + fi * self.n_states + ti
                ] = float(entry.setup_minutes)
        self.speed_factors = np.array(
            [wc.speed_factor for wc in problem.work_centers], dtype=np.float64
        )

    def fill_operations(
        self,
        op_ids: list[Any],
        ops_by_id: Mapping[Any, Any],
        wc_id_to_idx: dict[Any, int],
        state_id_to_idx: dict[Any, int],
        all_wc_ids: list[Any],
    ) -> bool:
        """Per-operation rows; False when an operation has no eligible machine."""
        eligible_flat: list[int] = []
        for i, op_id in enumerate(op_ids):
            op = ops_by_id[op_id]
            self.base_durations[i] = float(op.base_duration_min)
            self.state_ids[i] = state_id_to_idx.get(op.state_id, -1)
            # The kernel only tracks predecessors inside the dispatched set; a
            # predecessor outside it (frozen) becomes a start floor afterwards.
            if op.predecessor_op_id is not None:
                local_pred = self.local_idx.get(op.predecessor_op_id)
                if local_pred is not None:
                    self.predecessor_indices[i] = local_pred
            eligible_wc_indices = _native_eligible_machine_indices(op, wc_id_to_idx, all_wc_ids)
            if not eligible_wc_indices:
                return False
            eligible_flat.extend(eligible_wc_indices)
            self.eligible_offsets[i + 1] = len(eligible_flat)
        self.eligible_indices = np.array(eligible_flat, dtype=np.int64)
        return True

    def setup_after(self, machine: int, prev_state: int, curr_state: int) -> float:
        """Changeover from the machine's last state, 0 when either state is unknown."""
        n_states = self.n_states
        if 0 <= prev_state < n_states and 0 <= curr_state < n_states:
            return float(
                self.sdst_setup_flat[
                    machine * n_states * n_states + prev_state * n_states + curr_state
                ]
            )
        return 0.0


def _native_greedy_dispatch(
    problem: ScheduleProblem,
    op_ids: list[Any],
    ops_by_id: Mapping[Any, Any],
    frozen_assignments: list[Assignment],
    *,
    skip_reasons: list[str] | None = None,
) -> list[Assignment] | None:
    """Dispatch ``op_ids`` (topological order) with the Rust kernel after the frozen set.

    The kernel dispatches from ``t = 0`` with no initial machine state; a
    single forward pass then shifts every operation past the frozen machine
    availability, its release, a frozen or shifted predecessor and the setup
    from the machine's last state, and snaps the span to the integer grain.
    Returns None when the kernel is unavailable or the input is unusable.
    """
    from synaps.accelerators import greedy_repair_batch_native

    wc_id_to_idx = {wc.id: idx for idx, wc in enumerate(problem.work_centers)}
    state_id_to_idx = {s.id: idx for idx, s in enumerate(problem.states)}
    inputs = _NativeDispatchInputs(problem, op_ids, ops_by_id, wc_id_to_idx, state_id_to_idx)
    machine_available_at, machine_last_state, frozen_end_offsets = _frozen_machine_floors(
        problem, frozen_assignments, ops_by_id, wc_id_to_idx, state_id_to_idx
    )
    all_wc_ids = [wc.id for wc in problem.work_centers]
    if not inputs.fill_operations(op_ids, ops_by_id, wc_id_to_idx, state_id_to_idx, all_wc_ids):
        if skip_reasons is not None:
            skip_reasons.append("empty_eligible_machines")
        return None

    native_result = greedy_repair_batch_native(
        base_durations=inputs.base_durations,
        predecessor_indices=inputs.predecessor_indices,
        eligible_offsets=inputs.eligible_offsets,
        eligible_indices=inputs.eligible_indices,
        state_ids=inputs.state_ids,
        sdst_setup_flat=inputs.sdst_setup_flat,
        n_wc=inputs.n_wc,
        n_states=inputs.n_states,
        speed_factors=inputs.speed_factors,
    )
    if native_result is None:
        return None
    start_offsets, end_offsets, assigned_machine_indices = native_result
    if not _shift_past_frozen(
        problem,
        op_ids,
        ops_by_id,
        inputs,
        (start_offsets, end_offsets, assigned_machine_indices),
        (machine_available_at, machine_last_state, frozen_end_offsets),
    ):
        return None
    return _native_offsets_to_assignments(
        problem, op_ids, start_offsets, end_offsets, assigned_machine_indices
    )


def _shift_past_frozen(
    problem: ScheduleProblem,
    op_ids: list[Any],
    ops_by_id: Mapping[Any, Any],
    inputs: _NativeDispatchInputs,
    native: tuple[Any, Any, Any],
    floors: tuple[Any, Any, dict[Any, float]],
) -> bool:
    """Forward pass in topological order, in place; False on an invalid machine
    index or a predecessor that is neither dispatched nor frozen."""
    start_offsets, end_offsets, assigned_machine_indices = native
    machine_available_at, machine_last_state, frozen_end_offsets = floors
    release_offsets = _release_offset_by_op(problem)
    op_end_offset = np.copy(end_offsets)
    for i, op_id in enumerate(op_ids):
        op = ops_by_id[op_id]
        m = int(assigned_machine_indices[i])
        if m < 0 or m >= inputs.n_wc:
            return False  # Invalid machine assignment

        # Minimum start from the frozen machine availability
        min_start = machine_available_at[m]

        # M1: cannot start before the order release_date.
        release_offset = release_offsets.get(op_id)
        if release_offset is not None:
            min_start = max(min_start, release_offset)

        # Frozen predecessor constraint
        if op.predecessor_op_id is not None and op.predecessor_op_id not in inputs.local_idx:
            if op.predecessor_op_id not in frozen_end_offsets:
                return False  # Wave 13 / C13-3: never default missing pred to 0.0
            min_start = max(min_start, frozen_end_offsets[op.predecessor_op_id])

        # Local predecessor (handled by native, but our shifts move it)
        if inputs.predecessor_indices[i] >= 0:
            min_start = max(min_start, op_end_offset[int(inputs.predecessor_indices[i])])

        curr_state = int(inputs.state_ids[i])
        setup = inputs.setup_after(m, int(machine_last_state[m]), curr_state)
        actual_start = max(float(start_offsets[i]), min_start + setup)
        # F2 (audit v4): the native kernel returns raw ``base/speed`` float
        # spans; snap to the canonical integer ceil grain (P0-4) so ALNS
        # reserves the same duration as every other solver. The old 1-min
        # checker tolerance existed only to absorb this divergence.
        actual_end = actual_start + float(duration_minutes_for(op, problem.work_centers[m]))

        start_offsets[i] = actual_start
        end_offsets[i] = actual_end
        op_end_offset[i] = actual_end
        machine_available_at[m] = actual_end
        machine_last_state[m] = curr_state
    return True


def _frozen_machine_floors(
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    ops_by_id: Mapping[Any, Any],
    wc_id_to_idx: dict[Any, int],
    state_id_to_idx: dict[Any, int],
) -> tuple[Any, Any, dict[Any, float]]:
    """Per machine: frozen availability and last state; per frozen op: its end offset."""
    horizon_start = problem.planning_horizon_start
    # machine_available_at[m] = end offset of the last frozen assignment on m
    machine_available_at = np.zeros(len(problem.work_centers), dtype=np.float64)
    machine_last_state = np.full(len(problem.work_centers), -1, dtype=np.int64)
    frozen_by_machine: dict[int, list[Assignment]] = {}
    for fa in frozen_assignments:
        m_idx = wc_id_to_idx.get(fa.work_center_id)
        if m_idx is not None:
            frozen_by_machine.setdefault(m_idx, []).append(fa)
    for m_idx, machine_fas in frozen_by_machine.items():
        machine_fas.sort(key=lambda a: a.end_time)
        last_fa = machine_fas[-1]
        machine_available_at[m_idx] = (last_fa.end_time - horizon_start).total_seconds() / 60.0
        last_op = ops_by_id.get(last_fa.operation_id)
        if last_op is not None:
            machine_last_state[m_idx] = state_id_to_idx.get(last_op.state_id, -1)
    frozen_end_offsets = {
        fa.operation_id: (fa.end_time - horizon_start).total_seconds() / 60.0
        for fa in frozen_assignments
    }
    return machine_available_at, machine_last_state, frozen_end_offsets


def _native_offsets_to_assignments(
    problem: ScheduleProblem,
    op_ids: list[Any],
    start_offsets: Any,
    end_offsets: Any,
    assigned_machine_indices: Any,
) -> list[Assignment] | None:
    """Minute offsets → ``Assignment`` objects; None on an unmappable machine index."""
    idx_to_wc_id = {idx: wc.id for idx, wc in enumerate(problem.work_centers)}
    horizon_start = problem.planning_horizon_start
    assignments: list[Assignment] = []
    for i, op_id in enumerate(op_ids):
        wc_id = idx_to_wc_id.get(int(assigned_machine_indices[i]))
        if wc_id is None:
            return None  # Can't map machine index back
        assignments.append(
            Assignment(
                operation_id=op_id,
                work_center_id=wc_id,
                start_time=horizon_start + timedelta(minutes=float(start_offsets[i])),
                end_time=horizon_start + timedelta(minutes=float(end_offsets[i])),
            )
        )
    return assignments


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


def _has_machine_overlap(
    assignments: list[Assignment],
    *,
    ops_by_id: Mapping[Any, Any] | None = None,
    setup_minutes: Mapping[tuple[Any, Any, Any], int] | None = None,
) -> bool:
    """Return True if any two assignments overlap on the same machine.

    When ``ops_by_id`` and ``setup_minutes`` are provided, consecutive jobs on
    the same work center must also leave the SDST gap (A15-P0-3). Default
    remains processing-only overlap so calibration callers stay cheap.
    """
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for wc_id, mc_assigns in by_machine.items():
        mc_assigns.sort(key=lambda x: x.start_time)
        for i in range(1, len(mc_assigns)):
            previous, current = mc_assigns[i - 1], mc_assigns[i]
            gap = timedelta(0)
            if ops_by_id is not None and setup_minutes is not None:
                previous_op = ops_by_id.get(previous.operation_id)
                current_op = ops_by_id.get(current.operation_id)
                if previous_op is not None and current_op is not None:
                    setup = setup_minutes.get(
                        (wc_id, previous_op.state_id, current_op.state_id),
                        0,
                    )
                    gap = timedelta(minutes=int(setup))
            if current.start_time < previous.end_time + gap:
                return True
    return False


def _occupancy_conflict_violations(
    assignments: list[Assignment],
    dispatch_context: Any,
) -> list[Any]:
    """Checker-blind frozen extra-ops still occupy machines/aux (W16-P0-2)."""
    from synaps.solvers.feasibility_checker import FeasibilityViolation

    if _has_machine_overlap(assignments) or has_aux_capacity_violation(
        dispatch_context, assignments
    ):
        return [
            FeasibilityViolation(
                "MACHINE_OVERLAP",
                "frozen extra-op occupancy overlaps the incumbent",
            )
        ]
    return []


def _violates_frozen_precedence(
    repaired_assignments: list[Assignment],
    frozen_assignments_by_op: Mapping[Any, Assignment],
    ops_by_id: Mapping[Any, Any],
    *,
    frozen_predecessor_end_offsets: Mapping[Any, float] | None = None,
    horizon_start: Any | None = None,
) -> bool:
    """Return True when a repaired operation starts before its frozen predecessor ends.

    Also honors op-id ``frozen_predecessor_end_offsets`` when predecessor edges
    were cleared (Wave 14 / C14-1).
    """

    offsets = dict(frozen_predecessor_end_offsets or {})
    repaired_ids = {assignment.operation_id for assignment in repaired_assignments}
    for assignment in repaired_assignments:
        operation = ops_by_id.get(assignment.operation_id)
        if operation is None:
            continue
        if operation.predecessor_op_id is not None:
            if operation.predecessor_op_id in repaired_ids:
                continue
            frozen_predecessor = frozen_assignments_by_op.get(operation.predecessor_op_id)
            if frozen_predecessor is None:
                continue
            if assignment.start_time < frozen_predecessor.end_time:
                return True
            continue
        # Cleared pred: enforce provided end-offset floor when horizon is known.
        if assignment.operation_id in offsets and horizon_start is not None:
            floor = horizon_start + timedelta(minutes=float(offsets[assignment.operation_id]))
            if assignment.start_time < floor:
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
        if (
            predecessor_assignment is not None
            and assignment.start_time < predecessor_assignment.end_time
        ):
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


def _update_operator_weights_for_segment(
    operator_scores: list[float],
    operator_attempts: list[int],
    *,
    reset_mix: float,
    min_weight: float = 0.05,
) -> list[float]:
    """Refresh operator weights from the current segment and reset towards uniform."""

    n_operators = len(operator_scores)
    if n_operators == 0:
        return []

    segment_rewards = [
        operator_scores[idx] / operator_attempts[idx] if operator_attempts[idx] > 0 else 0.0
        for idx in range(n_operators)
    ]
    reward_mass = sum(max(reward, 0.0) for reward in segment_rewards)
    if reward_mass > 0:
        normalized = [max(reward, 0.0) / reward_mass for reward in segment_rewards]
    else:
        normalized = [1.0 / n_operators] * n_operators

    uniform_weight = 1.0 / n_operators
    blended = [
        max(
            min_weight,
            (1.0 - reset_mix) * normalized[idx] + reset_mix * uniform_weight,
        )
        for idx in range(n_operators)
    ]
    total = sum(blended)
    return [weight / total for weight in blended]


def _normalize_initial_operator_weights(
    raw: Any,
    operator_names: list[str],
) -> list[float]:
    """Normalize caller-supplied initial operator weights to a probability vector.

    Handles three input forms:
      - ``None`` → uniform ``[1/n]*n``
      - ``dict[str, float]`` → filter to positive finite floats matching
        *operator_names*; fill missing with mean of recognized; normalize to
        sum 1.0. If ALL names are missing/invalid → log warning, uniform.
      - ``list[float]`` (or tuple) → if length matches and all values are
        non-negative finite → normalize. Otherwise log warning, uniform.
      - Any other type → log warning, uniform.

    Returns a list of floats summing to 1.0 with length == len(operator_names).
    """
    n = len(operator_names)
    if n == 0:
        return []

    uniform: list[float] = [1.0 / n] * n

    if raw is None:
        return uniform

    if isinstance(raw, dict):
        # Extract recognized positive finite values
        recognized: list[tuple[int, float]] = []
        for idx, name in enumerate(operator_names):
            val = raw.get(name)
            if val is not None:
                try:
                    fval = float(val)
                except (TypeError, ValueError):
                    continue
                if fval > 0.0 and math.isfinite(fval):
                    recognized.append((idx, fval))

        if not recognized:
            logger.warning(
                "initial_operator_weights dict has no recognized positive finite "
                "entries for current operators — falling back to uniform weights"
            )
            return uniform

        # Fill missing names with mean of recognized values
        mean_recognized = sum(v for _, v in recognized) / len(recognized)
        recognized_indices = {idx for idx, _ in recognized}
        weights = [0.0] * n
        for idx, val in recognized:
            weights[idx] = val
        for idx in range(n):
            if idx not in recognized_indices:
                weights[idx] = mean_recognized

        weight_sum = sum(weights)
        if weight_sum <= 0.0:
            return uniform
        return [w / weight_sum for w in weights]

    if isinstance(raw, list | tuple):
        if len(raw) != n:
            logger.warning(
                "initial_operator_weights list length %d does not match "
                "operator count %d — falling back to uniform weights",
                len(raw),
                n,
            )
            return uniform

        # Validate all non-negative finite
        parsed: list[float] = []
        for val in raw:
            try:
                fval = float(val)
            except (TypeError, ValueError):
                logger.warning(
                    "initial_operator_weights list contains non-numeric value — "
                    "falling back to uniform weights"
                )
                return uniform
            if not math.isfinite(fval) or fval < 0.0:
                logger.warning(
                    "initial_operator_weights list contains negative or non-finite "
                    "value — falling back to uniform weights"
                )
                return uniform
            parsed.append(fval)

        weight_sum = sum(parsed)
        if weight_sum <= 0.0:
            return uniform
        return [w / weight_sum for w in parsed]

    # Unrecognized type
    logger.warning(
        "initial_operator_weights has unrecognized type %s — falling back to uniform weights",
        type(raw).__name__,
    )
    return uniform


def _compute_effective_temperature(
    *,
    base_temp: float,
    due_pressure: float,
    candidate_pressure: float,
    due_alpha: float,
    candidate_beta: float,
    min_temp: float,
    max_temp: float,
) -> float:
    """Compute the pressure-adjusted SA temperature, clamped to [min_temp, max_temp].

    Pure function — no side effects, no logging, no state reads. Mirrors the
    inline formula currently used in the ALNS main loop and post-calibration
    recompute.

        factor    = 1.0 + due_alpha * due_pressure + candidate_beta * candidate_pressure
        effective = base_temp * factor
        return max(min_temp, min(max_temp, effective))

    Audit note (2026-05-10): the current ALNS search behavior is that the
    effective temperature is NON-DECREASING with increasing ``due_pressure``
    (holding all else fixed) — higher pressure widens SA exploration. The
    earlier design-doc claim that temperature should decrease monotonically
    with pressure was rejected by the audit. Do not invert this formula.
    """
    factor = 1.0 + due_alpha * due_pressure + candidate_beta * candidate_pressure
    effective = base_temp * factor
    return max(min_temp, min(max_temp, effective))


def _calibrate_sa_temperature(
    problem: ScheduleProblem,
    current_assignments: list[Assignment],
    *,
    current_cost: float,
    objective_weights: dict[str, float],
    sdst: SdstMatrix,
    destroy_size: int,
    max_destroy: int,
    ops_by_id: dict[UUID, Any],
    successors_by_op: dict[UUID, list[UUID]],
    trials: int,
    acceptance_probability: float,
    seed: int,
    fallback_temperature: float,
) -> tuple[float, int]:
    """Estimate a base SA temperature from sampled worsening greedy-repair deltas."""

    if trials <= 0 or not (0.0 < acceptance_probability < 1.0):
        return fallback_temperature, 0

    calibration_rng = random.Random(seed ^ 0xA11CE)
    positive_deltas: list[float] = []

    for _ in range(trials):
        _, destroy_fn = DESTROY_OPERATORS[calibration_rng.randrange(len(DESTROY_OPERATORS))]
        destroyed_ids = destroy_fn(
            current_assignments,
            problem,
            sdst,
            destroy_size,
            calibration_rng,
            ops_by_id=ops_by_id,
        )
        if not destroyed_ids:
            continue

        destroyed_ids = _expand_successor_closure(destroyed_ids, successors_by_op)
        destroyed_ids = _cap_destroy_set_preserving_successor_closure(
            destroyed_ids,
            ops_by_id,
            successors_by_op,
            max_destroy,
            calibration_rng,
        )

        frozen = [
            assignment
            for assignment in current_assignments
            if assignment.operation_id not in destroyed_ids
        ]
        repair_outcome = _repair_greedy_outcome(problem, frozen, destroyed_ids)
        if repair_outcome.status != RepairStatus.FEASIBLE:
            continue

        candidate = frozen + list(repair_outcome.assignments)
        candidate_op_ids = {assignment.operation_id for assignment in candidate}
        if len(candidate_op_ids) != len(problem.operations):
            continue
        if _has_precedence_violation(candidate, ops_by_id):
            continue
        if _has_machine_overlap(candidate):
            continue

        candidate_obj = _evaluate_objective(problem, candidate, sdst, ops_by_id=ops_by_id)
        candidate_cost = _objective_cost(candidate_obj, objective_weights)
        delta = candidate_cost - current_cost
        if delta > 0:
            positive_deltas.append(delta)

    if not positive_deltas:
        return fallback_temperature, 0

    mean_positive_delta = sum(positive_deltas) / len(positive_deltas)
    calibrated_temperature = -mean_positive_delta / math.log(acceptance_probability)
    return calibrated_temperature, len(positive_deltas)


def _earliest_after_frozen_blockers(
    *,
    slot_start: float,
    slot_end: float,
    work_center_id: Any,
    required_resource_ids: set[Any],
    blockers: list[tuple[Assignment, float, float, set[Any]]],
) -> float | None:
    """Latest end among frozen extra-ops that overlap ``slot``, else None.

    Taking ``max`` (not the first hit) is required: a short blocker in front
    of a long one must not pin ``earliest_start`` so the same slot is
    re-emitted forever (float dust on datetime→minutes).
    """
    overlapping_ends = [
        blocker_end
        for (
            blocker_assignment,
            blocker_start,
            blocker_end,
            blocker_resources,
        ) in blockers
        if (
            blocker_assignment.work_center_id == work_center_id
            or required_resource_ids & blocker_resources
        )
        and slot_start < blocker_end
        and slot_end > blocker_start
    ]
    if not overlapping_ends:
        return None
    return max(overlapping_ends)


def _reanchor_against_frozen(
    assignments: list[Assignment],
    *,
    problem: ScheduleProblem,
    frozen_assignments: list[Assignment],
    ops_by_id: Mapping[Any, Any],
    op_positions: Mapping[Any, int],
    frozen_assignments_by_op: Mapping[Any, Assignment],
    frozen_predecessor_end_offsets: Mapping[Any, float],
    dispatch_context: Any,
) -> tuple[list[Assignment], int]:
    """Re-place free assignments against frozen timelines (Wave 9 extract)."""
    if not assignments or not frozen_assignments:
        return list(assignments), 0

    original_by_op = {assignment.operation_id: assignment for assignment in assignments}
    scheduled_assignments = [
        assignment for assignment in frozen_assignments if assignment.operation_id in ops_by_id
    ]
    external_frozen_blockers = sorted(
        [
            (
                assignment,
                (assignment.start_time - problem.planning_horizon_start).total_seconds() / 60.0,
                (assignment.end_time - problem.planning_horizon_start).total_seconds() / 60.0,
                set(assignment.aux_resource_ids),
            )
            for assignment in frozen_assignments
            if assignment.operation_id not in ops_by_id
        ],
        key=lambda blocker: blocker[1],
    )
    machine_index = MachineIndex(dispatch_context)
    for assignment in scheduled_assignments:
        machine_index.add(assignment)

    anchored_by_op = dict(frozen_assignments_by_op)
    pending_assignments = sorted(
        assignments,
        key=lambda assignment: (
            assignment.start_time,
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
            earliest_start = 0.0
            required_resource_ids = {
                requirement.aux_resource_id
                for requirement in dispatch_context.requirements_by_op.get(
                    operation.id,
                    [],
                )
            }
            if operation.predecessor_op_id is not None:
                predecessor_assignment = anchored_by_op.get(operation.predecessor_op_id)
                if predecessor_assignment is not None:
                    predecessor_end = (
                        predecessor_assignment.end_time - problem.planning_horizon_start
                    ).total_seconds() / 60.0
                    earliest_start = max(earliest_start, predecessor_end)
                elif operation.predecessor_op_id in original_by_op:
                    next_pending.append(assignment)
                    continue
                else:
                    if operation.id not in frozen_predecessor_end_offsets:
                        # Wave 14 / H14-5: never default missing floor to 0.0
                        return [], 0
                    earliest_start = max(
                        earliest_start,
                        float(frozen_predecessor_end_offsets[operation.id]),
                    )
            elif operation.id in frozen_predecessor_end_offsets:
                # Cleared pred edge — still enforce op-id offset floor (C14-1).
                earliest_start = max(
                    earliest_start,
                    float(frozen_predecessor_end_offsets[operation.id]),
                )

            slot = None
            current_earliest_start = earliest_start
            for _ in range(max(1, len(external_frozen_blockers) + 2)):
                slot = find_earliest_feasible_slot(
                    dispatch_context,
                    scheduled_assignments,
                    operation,
                    assignment.work_center_id,
                    current_earliest_start,
                    machine_index=machine_index,
                )
                if slot is None:
                    break
                conflict_end = _earliest_after_frozen_blockers(
                    slot_start=slot.start_offset,
                    slot_end=slot.end_offset,
                    work_center_id=assignment.work_center_id,
                    required_resource_ids=required_resource_ids,
                    blockers=external_frozen_blockers,
                )
                if conflict_end is None:
                    break
                nxt = max(current_earliest_start, conflict_end)
                if nxt <= current_earliest_start + 1e-9:
                    slot = None
                    break
                current_earliest_start = nxt
            else:
                slot = None
            if slot is None:
                next_pending.append(assignment)
                continue

            anchored_assignment = Assignment(
                operation_id=operation.id,
                work_center_id=assignment.work_center_id,
                start_time=problem.planning_horizon_start + timedelta(minutes=slot.start_offset),
                end_time=problem.planning_horizon_start + timedelta(minutes=slot.end_offset),
                setup_minutes=slot.setup_minutes,
                aux_resource_ids=slot.aux_resource_ids,
            )
            scheduled_assignments.append(anchored_assignment)
            machine_index.add(anchored_assignment)
            anchored_by_op[operation.id] = anchored_assignment
            reanchored_assignments.append(anchored_assignment)
            progress_made = True

        if not progress_made:
            return [], 0
        pending_assignments = next_pending

    if pending_assignments:
        return [], 0

    changed_assignment_count = sum(
        1
        for assignment in reanchored_assignments
        if original_by_op[assignment.operation_id].start_time != assignment.start_time
        or original_by_op[assignment.operation_id].end_time != assignment.end_time
        or original_by_op[assignment.operation_id].work_center_id != assignment.work_center_id
    )
    return sorted(
        reanchored_assignments,
        key=lambda assignment: assignment.start_time,
    ), changed_assignment_count


# ---------------------------------------------------------------------------
# Main ALNS solver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _AlnsRepairAttemptResult:
    """Outcome of one ALNS destroy→repair attempt (Wave 7 extract)."""

    assignments: list[Assignment] | None
    repair_used: str
    abort_iteration: bool
    cpsat_repair_attempts: int = 0
    cpsat_repair_ms_total: int = 0
    cpsat_repair_total_destroy_size: int = 0
    cpsat_repair_timeouts: int = 0
    cpsat_repairs: int = 0
    cpsat_repair_skips_large_destroy: int = 0
    greedy_repair_attempts: int = 0
    greedy_repair_ms_total: int = 0
    greedy_repair_total_destroy_size: int = 0
    greedy_repair_timeouts: int = 0
    greedy_repairs: int = 0
    rejection_reasons: Mapping[str, int] = field(default_factory=dict)


def _record_repair_reject(rejection_reasons: dict[str, int], outcome: RepairOutcome) -> None:
    if outcome.status == RepairStatus.FEASIBLE:
        return
    reason = outcome.reason or outcome.status.value
    rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1


def _try_cpsat_repair_lane(
    *,
    problem: ScheduleProblem,
    frozen: list[Assignment],
    frozen_by_op: Mapping[Any, Assignment],
    destroyed_ids: set[Any],
    ops_by_id: Mapping[Any, Any],
    op_positions: Mapping[Any, int],
    cpsat_max_destroy_ops: int,
    repair_time_limit_s: int,
    repair_num_workers: int,
    remaining_s: float,
    rejection_reasons: dict[str, int],
    frozen_predecessor_end_offsets: Mapping[Any, float] | None = None,
    frozen_context_operations: list[Any] | None = None,
    setup_minutes: Mapping[tuple[Any, Any, Any], int] | None = None,
) -> tuple[list[Assignment] | None, dict[str, int]]:
    """One CP-SAT micro-repair attempt; returns (assignments|None, counter deltas)."""
    stats = {
        "cpsat_repair_attempts": 0,
        "cpsat_repair_ms_total": 0,
        "cpsat_repair_total_destroy_size": 0,
        "cpsat_repair_timeouts": 0,
        "cpsat_repairs": 0,
        "cpsat_repair_skips_large_destroy": 0,
    }
    if len(destroyed_ids) > cpsat_max_destroy_ops:
        stats["cpsat_repair_skips_large_destroy"] = 1
        return None, stats
    # Wave 9 / D3: do not start a CP-SAT repair that already has no wall budget.
    if remaining_s < _ALNS_MIN_REPAIR_REMAINING_S:
        return None, stats

    stats["cpsat_repair_attempts"] = 1
    t0 = time.monotonic()
    outcome = _repair_cpsat_outcome(
        problem,
        frozen,
        destroyed_ids,
        time_limit_s=max(1, min(repair_time_limit_s, int(remaining_s))),
        num_workers=repair_num_workers,
        ops_by_id=ops_by_id,
        op_positions=op_positions,
        frozen_predecessor_end_offsets=frozen_predecessor_end_offsets,
        frozen_context_operations=frozen_context_operations,
    )
    stats["cpsat_repair_ms_total"] = int((time.monotonic() - t0) * 1000)
    stats["cpsat_repair_total_destroy_size"] = len(destroyed_ids)
    if outcome.status == RepairStatus.TIMEOUT:
        stats["cpsat_repair_timeouts"] = 1
    if outcome.status != RepairStatus.FEASIBLE:
        _record_repair_reject(rejection_reasons, outcome)
        return None, stats

    repaired = list(outcome.assignments)
    if _has_machine_overlap(
        frozen + repaired,
        ops_by_id=ops_by_id,
        setup_minutes=setup_minutes,
    ) or _violates_frozen_precedence(
        repaired,
        frozen_by_op,
        ops_by_id,
        frozen_predecessor_end_offsets=frozen_predecessor_end_offsets,
        horizon_start=problem.planning_horizon_start,
    ):
        _record_repair_reject(
            rejection_reasons,
            RepairOutcome(
                status=RepairStatus.INFEASIBLE,
                assignments=(),
                reason="cpsat_conflict_with_frozen",
            ),
        )
        return None, stats
    stats["cpsat_repairs"] = 1
    return repaired, stats


def _try_greedy_repair_lane(
    *,
    problem: ScheduleProblem,
    frozen: list[Assignment],
    frozen_by_op: Mapping[Any, Assignment],
    destroyed_ids: set[Any],
    ops_by_id: Mapping[Any, Any],
    rejection_reasons: dict[str, int],
    native_skip_reasons: list[str] | None = None,
    frozen_predecessor_end_offsets: Mapping[Any, float] | None = None,
    setup_minutes: Mapping[tuple[Any, Any, Any], int] | None = None,
) -> tuple[list[Assignment] | None, dict[str, int]]:
    """One greedy repair attempt; returns (assignments|None, counter deltas)."""
    stats = {
        "greedy_repair_attempts": 1,
        "greedy_repair_ms_total": 0,
        "greedy_repair_total_destroy_size": len(destroyed_ids),
        "greedy_repair_timeouts": 0,
        "greedy_repairs": 0,
    }
    t0 = time.monotonic()
    outcome = _repair_greedy_outcome(
        problem,
        frozen,
        destroyed_ids,
        native_skip_reasons=native_skip_reasons,
    )
    stats["greedy_repair_ms_total"] = int((time.monotonic() - t0) * 1000)
    if outcome.status == RepairStatus.TIMEOUT:
        stats["greedy_repair_timeouts"] = 1
    if outcome.status != RepairStatus.FEASIBLE:
        _record_repair_reject(rejection_reasons, outcome)
        return None, stats

    repaired = list(outcome.assignments)
    if _has_machine_overlap(
        frozen + repaired,
        ops_by_id=ops_by_id,
        setup_minutes=setup_minutes,
    ) or _violates_frozen_precedence(
        repaired,
        frozen_by_op,
        ops_by_id,
        frozen_predecessor_end_offsets=frozen_predecessor_end_offsets,
        horizon_start=problem.planning_horizon_start,
    ):
        _record_repair_reject(
            rejection_reasons,
            RepairOutcome(
                status=RepairStatus.INFEASIBLE,
                assignments=(),
                reason="greedy_conflict_with_frozen",
            ),
        )
        return None, stats
    stats["greedy_repairs"] = 1
    return repaired, stats


def _alns_repair_attempt_result(
    *,
    assignments: list[Assignment] | None,
    repair_used: str,
    abort_iteration: bool,
    rejection_reasons: dict[str, int],
    cpsat_stats: Mapping[str, int],
    greedy_stats: Mapping[str, int],
) -> _AlnsRepairAttemptResult:
    c, g = cpsat_stats.get, greedy_stats.get
    return _AlnsRepairAttemptResult(
        assignments=assignments,
        repair_used=repair_used,
        abort_iteration=abort_iteration,
        rejection_reasons=rejection_reasons,
        cpsat_repair_attempts=c("cpsat_repair_attempts", 0),
        cpsat_repair_ms_total=c("cpsat_repair_ms_total", 0),
        cpsat_repair_total_destroy_size=c("cpsat_repair_total_destroy_size", 0),
        cpsat_repair_timeouts=c("cpsat_repair_timeouts", 0),
        cpsat_repairs=c("cpsat_repairs", 0),
        cpsat_repair_skips_large_destroy=c("cpsat_repair_skips_large_destroy", 0),
        greedy_repair_attempts=g("greedy_repair_attempts", 0),
        greedy_repair_ms_total=g("greedy_repair_ms_total", 0),
        greedy_repair_total_destroy_size=g("greedy_repair_total_destroy_size", 0),
        greedy_repair_timeouts=g("greedy_repair_timeouts", 0),
        greedy_repairs=g("greedy_repairs", 0),
    )


def _attempt_alns_pair_repair(
    *,
    problem: ScheduleProblem,
    frozen: list[Assignment],
    frozen_by_op: Mapping[Any, Assignment],
    destroyed_ids: set[Any],
    ops_by_id: Mapping[Any, Any],
    op_positions: Mapping[Any, int],
    use_cpsat_repair: bool,
    forced_repair_mode: str | None,
    cpsat_max_destroy_ops: int,
    repair_time_limit_s: int,
    repair_num_workers: int,
    remaining_s: float,
    pair_bandit_active: bool,
    native_skip_reasons: list[str] | None = None,
    frozen_predecessor_end_offsets: Mapping[Any, float] | None = None,
    frozen_context_operations: list[Any] | None = None,
    setup_minutes: Mapping[tuple[Any, Any, Any], int] | None = None,
) -> _AlnsRepairAttemptResult:
    """CP-SAT then greedy repair for one ALNS iteration (extracted from ``_solve_core``)."""
    rejection_reasons: dict[str, int] = {}
    new_assignments: list[Assignment] | None = None
    repair_used = "none"
    cpsat_stats: dict[str, int] = {}
    greedy_stats: dict[str, int] = {}
    try_cpsat = use_cpsat_repair and forced_repair_mode in (None, "cpsat")
    try_greedy = forced_repair_mode in (None, "greedy")

    if try_cpsat:
        new_assignments, cpsat_stats = _try_cpsat_repair_lane(
            problem=problem,
            frozen=frozen,
            frozen_by_op=frozen_by_op,
            destroyed_ids=destroyed_ids,
            ops_by_id=ops_by_id,
            op_positions=op_positions,
            cpsat_max_destroy_ops=cpsat_max_destroy_ops,
            repair_time_limit_s=repair_time_limit_s,
            repair_num_workers=repair_num_workers,
            remaining_s=remaining_s,
            rejection_reasons=rejection_reasons,
            frozen_predecessor_end_offsets=frozen_predecessor_end_offsets,
            frozen_context_operations=frozen_context_operations,
            setup_minutes=setup_minutes,
        )
        if new_assignments is not None:
            repair_used = "cpsat"

    abort = new_assignments is None and forced_repair_mode == "cpsat" and pair_bandit_active
    if not abort and new_assignments is None and try_greedy:
        new_assignments, greedy_stats = _try_greedy_repair_lane(
            problem=problem,
            frozen=frozen,
            frozen_by_op=frozen_by_op,
            destroyed_ids=destroyed_ids,
            ops_by_id=ops_by_id,
            rejection_reasons=rejection_reasons,
            native_skip_reasons=native_skip_reasons,
            frozen_predecessor_end_offsets=frozen_predecessor_end_offsets,
            setup_minutes=setup_minutes,
        )
        if new_assignments is not None:
            repair_used = "greedy"

    return _alns_repair_attempt_result(
        assignments=None if abort else new_assignments,
        repair_used="none" if abort else repair_used,
        abort_iteration=abort,
        rejection_reasons=rejection_reasons,
        cpsat_stats=cpsat_stats,
        greedy_stats=greedy_stats,
    )


class AlnsSolver(BaseSolver):
    """Adaptive Large Neighborhood Search with Micro-CP-SAT repair.

    Designed for 5 000-50 000+ operation instances where monolithic CP-SAT
    and LBBD cannot converge in reasonable time.

    Architecture (Ropke & Pisinger 2006):
        1. Generate initial solution via greedy/beam heuristic
        2. Iteratively: destroy (remove k operations) → repair (micro CP-SAT)
        3. Accept/reject via Simulated Annealing
        4. Adapt operator selection probabilities based on success history

    Key parameters:
        max_iterations: Iteration CEILING (default 500). ``time_limit_s`` is a
            hard wall-clock deadline; whichever is hit first wins (D3/D4).
            ``min_iterations`` never overrides the deadline.
        destroy_fraction: Fraction of operations to destroy per iteration (default 0.05)
        min_destroy: Minimum destroy size (default 20)
        max_destroy: Maximum destroy size per iteration (default 300)
        repair_time_limit_s: Time limit for micro CP-SAT repair (default 10);
            clamped every iteration to the remaining wall-clock budget.
        sa_initial_temp: Starting temperature for SA (default 100.0)
        sa_cooling_rate: Geometric cooling factor (default 0.995)
        random_seed: For reproducibility (default 42)
    """

    @property
    def name(self) -> str:
        return "alns"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        # M2: virtualize max_parallel>1 work centers into disjunctive lanes so
        # the destroy/repair loop (which has no cumulative-capacity concept)
        # can run ops concurrently on a parallel machine instead of serializing
        # them and charging a phantom setup. lane_id is unrolled on the result.
        from synaps.solvers.greedy_dispatch import (
            _unroll_lane_assignments,
            _virtualize_parallel_lanes,
        )

        frozen_raw = kwargs.get("frozen_assignments") or []
        virtual_problem, virtual_to_original = _virtualize_parallel_lanes(problem)
        # Wave 14 / C14-2: under frozen, skip lane virtualization (serialize
        # parallel) instead of ERROR — ERROR forced RHC into silent greedy while
        # still branding RHC-ALNS.
        if frozen_raw and virtual_to_original:
            result = self._solve_core(problem, **kwargs)
            result.metadata["parallel_virtualization_skipped_due_to_frozen"] = True
            return stamp_honest_coverage(problem, result)
        result = self._solve_core(virtual_problem, **kwargs)
        _unroll_lane_assignments(result, virtual_to_original)
        return stamp_honest_coverage(problem, result)

    def _final_validate(
        self,
        problem: ScheduleProblem,
        best_assignments: list[Assignment],
        initial_assignments: list[Assignment],
        frozen_assignments: list[Assignment],
        frozen_prec_bad: Any,
        dispatch_context: Any,
        checker: Any,
        sdst: Any,
        ops_by_id: Any,
        objective_weights: Any,
    ) -> tuple[list[Assignment], Any, float, list[Any], list[Any], bool, bool, str | None]:
        """Final feasibility validation + recovery (extracted from _solve_core)."""
        recompute_assignment_setups(best_assignments, dispatch_context)
        final_obj = _evaluate_objective(problem, best_assignments, sdst, ops_by_id=ops_by_id)
        final_cost = _objective_cost(final_obj, objective_weights)

        # W16-P0-2: final claim must include frozen context. Otherwise an
        # incumbent that double-books frozen machine time is returned FEASIBLE
        # and RHC commits it, poisoning every later window.
        frozen_precedence_bad = bool(frozen_assignments) and frozen_prec_bad(best_assignments)
        final_check_assignments = (
            frozen_assignments + best_assignments if frozen_assignments else best_assignments
        )
        violations = _window_notary_violations(
            problem, final_check_assignments
        ) + _occupancy_conflict_violations(final_check_assignments, dispatch_context)
        violations_before_recovery = list(violations)
        recovery_attempted = len(violations_before_recovery) > 0
        recovered = False
        recovery_source: str | None = None

        if recovery_attempted:
            recovered_assignments = list(initial_assignments)
            recompute_assignment_setups(recovered_assignments, dispatch_context)
            recovered_check = (
                frozen_assignments + recovered_assignments
                if frozen_assignments
                else recovered_assignments
            )
            recovered_violations = _window_notary_violations(
                problem, recovered_check
            ) + _occupancy_conflict_violations(recovered_check, dispatch_context)
            if not recovered_violations and not (
                frozen_assignments and frozen_prec_bad(recovered_assignments)
            ):
                logger.warning(
                    "ALNS final incumbent had %d violations; recovering to initial solution",
                    len(violations_before_recovery),
                )
                best_assignments = recovered_assignments
                final_obj = _evaluate_objective(
                    problem, best_assignments, sdst, ops_by_id=ops_by_id
                )
                final_cost = _objective_cost(final_obj, objective_weights)
                violations = recovered_violations
                recovered = True
                recovery_source = "initial_solution"
            else:
                logger.warning(
                    "ALNS final incumbent had %d violations; "
                    "initial-solution recovery still has %d violations",
                    len(violations_before_recovery),
                    len(recovered_violations),
                )

        return (
            best_assignments,
            final_obj,
            final_cost,
            violations,
            violations_before_recovery,
            frozen_precedence_bad,
            recovered,
            recovery_source,
        )

    def _solve_core(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        """Run one ALNS search on *problem* (pipeline: see :class:`_AlnsRun`)."""
        return _AlnsRun(self, problem, kwargs).execute()


# ---------------------------------------------------------------------------
# ALNS run engine (2026-10 god-function decomposition)
# ---------------------------------------------------------------------------
#
# ``_AlnsRun`` is one search, executed as an explicit pipeline:
#
#     phase 1  initial solution  (warm start -> frozen seed -> native seed ->
#                                 list-schedule cover -> beam/greedy tournament)
#     phase 2  calibration       (warm-start skip, iteration budget, SA T0)
#     phase 3  operators         (roulette weights or UCB1 pairs, window bias)
#     phase 4  search loop       (destroy -> repair -> sanity -> accept -> adapt)
#     phase 5  final validation  (notary + recovery) and metadata
#
# The engine lives in this module on purpose: tests patch module globals
# (``DESTROY_OPERATORS``, ``_objective_cost``, ``_repair_greedy_outcome``,
# ``SdstMatrix``, ``FeasibilityChecker``, ``APPEND_GAP_SCAN_MIN_OPS``,
# ``time.monotonic`` ...) and the order of wall-clock and RNG draws is part of
# the reproducibility contract, so the decomposition preserves both exactly.


class _EarlyResult(Exception):  # noqa: N818 - control flow, never escapes _AlnsRun
    """Phase-1 abort carrying the ERROR result to return from ``execute``."""

    def __init__(self, result: ScheduleResult) -> None:
        super().__init__("alns phase-1 abort")
        self.result = result


@dataclass
class _AlnsRepairStats:
    """Repair-lane counters accumulated over the search loop."""

    cpsat_repair_attempts: int = 0
    cpsat_repairs: int = 0
    cpsat_repair_skips_large_destroy: int = 0
    cpsat_repair_timeouts: int = 0
    greedy_repair_attempts: int = 0
    greedy_repairs: int = 0
    greedy_repair_timeouts: int = 0
    cpsat_repair_ms_total: int = 0
    greedy_repair_ms_total: int = 0
    # R2 (EMA calibration): destroyed-op totals per lane so RHC can compute an
    # empirical mean repair time per destroyed op.
    cpsat_repair_total_destroy_size: int = 0
    greedy_repair_total_destroy_size: int = 0
    repair_rejection_reasons: dict[str, int] = field(default_factory=dict)

    def absorb(self, attempt: Any) -> None:
        self.cpsat_repair_attempts += attempt.cpsat_repair_attempts
        self.cpsat_repair_ms_total += attempt.cpsat_repair_ms_total
        self.cpsat_repair_total_destroy_size += attempt.cpsat_repair_total_destroy_size
        self.cpsat_repair_timeouts += attempt.cpsat_repair_timeouts
        self.cpsat_repairs += attempt.cpsat_repairs
        self.cpsat_repair_skips_large_destroy += attempt.cpsat_repair_skips_large_destroy
        self.greedy_repair_attempts += attempt.greedy_repair_attempts
        self.greedy_repair_ms_total += attempt.greedy_repair_ms_total
        self.greedy_repair_total_destroy_size += attempt.greedy_repair_total_destroy_size
        self.greedy_repair_timeouts += attempt.greedy_repair_timeouts
        self.greedy_repairs += attempt.greedy_repairs
        for reason, count in attempt.rejection_reasons.items():
            self.repair_rejection_reasons[reason] = (
                self.repair_rejection_reasons.get(reason, 0) + count
            )


@dataclass
class _AlnsSearchState:
    """Incumbent / current solution and loop counters."""

    current_assignments: list[Assignment]
    current_obj: ObjectiveValues
    current_cost: float
    current_cache: Any
    best_assignments: list[Assignment]
    best_obj: ObjectiveValues
    best_cost: float
    initial_cost: float
    temperature: float = 0.0
    improvements: int = 0
    feasibility_failures: int = 0
    sa_worsening_accepted: int = 0
    sa_worsening_rejected: int = 0
    iterations_completed: int = 0
    accepted_iterations: int = 0
    no_improve_streak: int = 0
    no_improve_early_stop: bool = False
    stagnation_iteration: int | None = None
    # P3.3: EMA repair-time tracker.
    ema_repair_ms: float = 0.0
    ema_repair_samples: int = 0


@dataclass
class _AlnsOperators:
    """Destroy-operator adaptation state (roulette wheel or UCB1 pairs)."""

    names: list[str]
    weights: list[float]
    scores: list[float]
    attempts: list[int]
    cumulative_attempts: list[int]
    cumulative_improvements: list[int]
    initial_weights_dict: dict[str, float]
    pair_bandit: Any = None
    mab_repair_modes: list[str] = field(default_factory=list)
    mab_pair_labels: list[str] = field(default_factory=list)
    cross_window_bias_applied: bool = False
    cross_window_bias_operator_deltas: dict[str, float] = field(default_factory=dict)


# Score rewards (Ropke & Pisinger 2006 §4.2).
_SIGMA_NEW_BEST = 33.0
_SIGMA_BETTER = 9.0
_SIGMA_ACCEPTED = 3.0


class _AlnsRun:
    """One ALNS search on one (sub-)problem."""

    initial_result: ScheduleResult
    initial_solution_t0: float
    phase1_deadline: float
    initial_solution_ms: int
    time_limit_exhausted_before_search: bool
    search: _AlnsSearchState
    ops: _AlnsOperators

    def __init__(self, solver: AlnsSolver, problem: ScheduleProblem, kwargs: dict[str, Any]):
        self.solver = solver
        self.problem = problem
        self.t0 = time.monotonic()
        self.cfg = cfg = AlnsRunConfig.from_kwargs(kwargs)
        self.objective_weights = _normalize_objective_weights(cfg.seeding.objective_weights_raw)
        self.frozen_assignments: list[Assignment] = list(cfg.seeding.frozen_assignments)
        self.frozen_assignments_by_op = {a.operation_id: a for a in self.frozen_assignments}
        self.frozen_predecessor_end_offsets = dict(cfg.seeding.frozen_predecessor_end_offsets)
        self.frozen_context_operations = list(
            cfg.seeding.frozen_context_operations_raw or problem.operations
        )
        # P3.1: variable fixing — exclude stable ops from destroy.
        self.fixed_op_ids: set[UUID] = set(cfg.seeding.fixed_op_ids)
        self._derive_search_parameters()
        self._init_context()
        # Native telemetry: initialized before any early ERROR can publish it.
        self.native_initial_seed_attempted = False
        self.native_initial_seed_used = False
        self.native_initial_seed_ms = 0
        self.native_initial_seed_fallback_reason: str | None = None
        self.native_greedy_repair_skip_reasons: list[str] = []
        self.warm_start_assignments: list[Assignment] = []
        self.warm_start_supplied_assignments = 0
        self.warm_start_completed_assignments = 0
        self.warm_start_used = False
        self.warm_start_rejected_reason: str | None = None
        self.initial_solver_name = "greedy"
        self.repair = _AlnsRepairStats()

    def _derive_search_parameters(self) -> None:
        """Stagnation patience, destroy size and the pressure-coupled SA schedule."""
        cfg, ad, an = self.cfg, self.cfg.adaptation, self.cfg.annealing
        base = ad.max_no_improve_base_iters
        self.max_no_improve_iters = base
        if ad.dynamic_no_improve_enabled and base > 0:
            scaled = round(
                base
                * (
                    1.0
                    + ad.no_improve_due_alpha * an.due_pressure
                    + ad.no_improve_candidate_beta * an.candidate_pressure
                )
            )
            self.max_no_improve_iters = min(
                ad.no_improve_max_iters, max(ad.no_improve_min_iters, scaled)
            )
        destroy_size = max(
            cfg.budget.min_destroy, int(len(self.problem.operations) * cfg.budget.destroy_fraction)
        )
        self.destroy_size = min(destroy_size, cfg.budget.max_destroy)
        self.adaptive_destroy_current = self.destroy_size
        self.max_iterations = cfg.budget.max_iterations
        self.original_max_iterations = cfg.budget.max_iterations
        self.sa_calibrated_base_temp = an.sa_initial_temp
        self.sa_calibration_samples = 0
        self.sa_temp_min = an.sa_temp_min
        self.sa_pressure_factor = 1.0
        if an.dynamic_sa_enabled:
            self.sa_pressure_factor += (
                an.sa_due_alpha * an.due_pressure + an.sa_candidate_beta * an.candidate_pressure
            )
        self.effective_sa_initial_temp = self._effective_temperature()
        self.effective_sa_cooling_rate = min(
            0.9999,
            max(
                0.90,
                an.sa_cooling_rate
                + (an.sa_pressure_cooling_gamma * max(0.0, self.sa_pressure_factor - 1.0)),
            ),
        )

    def _effective_temperature(self) -> float:
        an = self.cfg.annealing
        return _compute_effective_temperature(
            base_temp=self.sa_calibrated_base_temp,
            due_pressure=an.due_pressure,
            candidate_pressure=an.candidate_pressure,
            due_alpha=an.sa_due_alpha if an.dynamic_sa_enabled else 0.0,
            candidate_beta=an.sa_candidate_beta if an.dynamic_sa_enabled else 0.0,
            min_temp=self.sa_temp_min,
            max_temp=an.sa_temp_max,
        )

    def _init_context(self) -> None:
        problem = self.problem
        self.rng = random.Random(self.cfg.seeding.seed)
        self.n_ops = len(problem.operations)
        self.ops_by_id = {
            op.id: op for op in (*self.frozen_context_operations, *problem.operations)
        }
        self.problem_op_ids = {op.id for op in problem.operations}
        self.op_positions = {op.id: index for index, op in enumerate(problem.operations)}
        self.successors_by_op: dict[UUID, list[UUID]] = {}
        for op in problem.operations:
            if op.predecessor_op_id is not None:
                self.successors_by_op.setdefault(op.predecessor_op_id, []).append(op.id)
        self.sdst = SdstMatrix.from_problem(problem)
        self.checker = FeasibilityChecker()
        self.dispatch_context = build_dispatch_context(problem)
        self.lower_bound = compute_relaxed_makespan_lower_bound(problem)

    # ---------------------------------------------------------- orchestration

    def execute(self) -> ScheduleResult:
        try:
            self._phase1_initial_solution()
        except _EarlyResult as early:
            return early.result
        self.initial_solution_ms = int((time.monotonic() - self.initial_solution_t0) * 1000)
        self.time_limit_exhausted_before_search = (
            time.monotonic() - self.t0
        ) >= self.cfg.budget.time_limit_s
        self._init_search_state()
        skip_result = self._warm_start_skip_result()
        if skip_result is not None:
            return skip_result
        self._adjust_iteration_budget()
        self._calibrate_temperature()
        self._init_operators()
        self.search.temperature = self.effective_sa_initial_temp
        logger.info(
            "ALNS starting: %d ops, %d machines, destroy_size=%d, max_iter=%d, fixed_ops=%d",
            self.n_ops,
            len(self.problem.work_centers),
            self.destroy_size,
            self.max_iterations,
            len(self.fixed_op_ids),
        )
        # B3 (Task 7.3): bounded per-iteration trace (oldest records dropped).
        record = self.cfg.adaptation.record_iteration_metrics
        self.iteration_trace: deque[AlnsIterationRecord] = (
            deque(maxlen=self.cfg.adaptation.max_iteration_records) if record else deque(maxlen=0)
        )
        if self.time_limit_exhausted_before_search:
            logger.info(
                "ALNS time limit exhausted during initial solution generation (%d ms)",
                self.initial_solution_ms,
            )
        else:
            self._run_search_loop()
        return self._finalize()

    # ----------------------------------------------------- phase-1 helpers

    def _phase1_budget_exhausted(self) -> bool:
        return time.monotonic() >= self.phase1_deadline

    def _remaining_initial_seed_budget_s(self) -> float:
        return max(1.0, self.cfg.budget.time_limit_s - (time.monotonic() - self.t0))

    def _initial_seed_budget_s(self) -> float:
        """Seed budget that always leaves ``search_budget_reservation_s`` for search.

        ~0.5 ms/op (Python GreedyDispatch, capped at 30 s) vs 15 % of the
        remaining budget, floored at 3 s, never eating the search reservation.
        """
        time_limit_s = self.cfg.budget.time_limit_s
        remaining_budget_s = self._remaining_initial_seed_budget_s()
        repair_budget_s = max(1.0, float(self.cfg.budget.repair_time_limit_s))
        reserved = remaining_budget_s - self.cfg.seeding.search_budget_reservation_s
        if reserved < 1.0:
            return max(1.0, remaining_budget_s * 0.1)
        n_ops_budget = min(self.n_ops * 0.0005, 30.0)
        proportional = max(3.0, remaining_budget_s * 0.15)
        if time_limit_s <= 90.0:
            cap = max(1.0, min(3.0, repair_budget_s * 2.0))
        else:
            cap = max(5.0, min(max(n_ops_budget, proportional), reserved))
        return max(1.0, min(cap, reserved))

    @staticmethod
    def _initial_seed_timed_out(result: ScheduleResult) -> bool:
        metadata = result.metadata or {}
        return result.status == SolverStatus.TIMEOUT or bool(metadata.get("partial_schedule"))

    def _overlap(self, assignments: list[Assignment]) -> bool:
        return _has_machine_overlap(
            assignments,
            ops_by_id=self.ops_by_id,
            setup_minutes=self.dispatch_context.setup_minutes,
        ) or has_aux_capacity_violation(self.dispatch_context, assignments)

    def _frozen_prec_bad(self, assignments: list[Assignment]) -> bool:
        return _violates_frozen_precedence(
            assignments,
            self.frozen_assignments_by_op,
            self.ops_by_id,
            frozen_predecessor_end_offsets=self.frozen_predecessor_end_offsets,
            horizon_start=self.problem.planning_horizon_start,
        )

    def _is_valid_complete_schedule(self, assignments: list[Assignment]) -> bool:
        frozen = self.frozen_assignments
        combined = frozen + assignments if frozen else assignments
        return (
            len(assignments) == self.n_ops
            and len({assignment.operation_id for assignment in assignments}) == self.n_ops
            and not self._overlap(combined)
            and not _has_precedence_violation(assignments, self.ops_by_id)
            and not self._frozen_prec_bad(assignments)
            and not self.checker.check(self.problem, assignments)
        )

    def _seed_result(self, assignments: list[Assignment], solver_name: str) -> ScheduleResult:
        recompute_assignment_setups(assignments, self.dispatch_context)
        self.initial_solver_name = solver_name
        return ScheduleResult(
            solver_name=self.solver.name, status=SolverStatus.FEASIBLE, assignments=assignments
        )

    def _reanchor(self, assignments: list[Assignment]) -> list[Assignment]:
        reanchored, _ = _reanchor_against_frozen(
            assignments,
            problem=self.problem,
            frozen_assignments=self.frozen_assignments,
            ops_by_id=self.ops_by_id,
            op_positions=self.op_positions,
            frozen_assignments_by_op=self.frozen_assignments_by_op,
            frozen_predecessor_end_offsets=self.frozen_predecessor_end_offsets,
            dispatch_context=self.dispatch_context,
        )
        return reanchored

    def _error_result(
        self,
        error_message: str,
        *,
        reason_key: str | None = None,
        time_limit_exhausted_before_search: bool | None = None,
    ) -> _EarlyResult:
        """Build the phase-1 ERROR result (raise the returned exception)."""
        budget = self.cfg.budget
        elapsed_s = time.monotonic() - self.t0
        exhausted = (
            bool(time_limit_exhausted_before_search)
            if time_limit_exhausted_before_search is not None
            else elapsed_s > budget.time_limit_s
        )
        return _EarlyResult(
            ScheduleResult(
                solver_name=self.solver.name,
                status=SolverStatus.ERROR,
                duration_ms=int(elapsed_s * 1000),
                metadata={
                    "error": error_message,
                    "initial_seed_fallback_reason": reason_key or error_message,
                    "initial_solver": self.initial_solver_name,
                    **self._warm_start_meta(),
                    "initial_solution_ms": int(elapsed_s * 1000),
                    **self._native_seed_meta(),
                    "time_limit_exhausted_before_search": exhausted,
                    "iterations_completed": 0,
                    **_alns_wall_clock_honesty_meta(
                        budget.determinism,
                        exhausted,
                        0,
                        budget.max_iterations,
                        elapsed_s,
                        budget.time_limit_s,
                    ),
                },
            )
        )

    def _warm_start_meta(self) -> dict[str, Any]:
        # C1 (Task 9.4): `alns_warm_start_*` are ALNS-scoped mirrors for RHC
        # telemetry; coverage is the caller-supplied fraction before any fill.
        return {
            "warm_start_used": self.warm_start_used,
            "warm_start_supplied_assignments": self.warm_start_supplied_assignments,
            "warm_start_completed_assignments": self.warm_start_completed_assignments,
            "warm_start_rejected_reason": self.warm_start_rejected_reason,
            "alns_warm_start_used": self.warm_start_used,
            "alns_warm_start_coverage": round(
                self.warm_start_supplied_assignments / max(self.n_ops, 1), 6
            ),
        }

    def _native_seed_meta(self) -> dict[str, Any]:
        return {
            "native_initial_seed_attempted": self.native_initial_seed_attempted,
            "native_initial_seed_used": self.native_initial_seed_used,
            "native_initial_seed_ms": self.native_initial_seed_ms,
            "native_initial_seed_fallback_reason": self.native_initial_seed_fallback_reason,
            **_native_repair_meta_from_skips(self.native_greedy_repair_skip_reasons),
        }

    # ---------------------------------------------------- phase 1: seeding

    def _phase1_initial_solution(self) -> None:
        """Build a complete initial schedule or raise :class:`_EarlyResult`."""
        seeding = self.cfg.seeding
        self.initial_solution_t0 = time.monotonic()
        # Hard ceiling for seed+completion so RHC windows retain search (or
        # fall back to inline greedy) instead of burning the window on seeding.
        self.phase1_deadline = self.t0 + (
            self.cfg.budget.time_limit_s * seeding.phase1_wall_fraction
        )
        self._collect_warm_start()
        initial: ScheduleResult | None = None
        if self.warm_start_assignments:
            initial = self._try_warm_start_seed()
        if initial is None and self.frozen_assignments:
            # RHC inner windows: prefer a frozen-compatible constructive seed.
            initial = self._try_frozen_seed()
        if seeding.native_initial_seed_enabled and initial is None:
            initial = self._try_native_seed()
        if initial is None:
            initial = self._try_cover_seed()
        if initial is None:
            initial = self._constructive_seed()
        if self.frozen_assignments:
            initial = self._reanchor_initial(initial)
        initial = self._complete_initial(initial)
        if (
            self._phase1_budget_exhausted()
            and (time.monotonic() - self.t0) > self.cfg.budget.time_limit_s * 0.85
        ):
            # Seed consumed the Phase-1 ceiling: surface as pre-search timeout
            # so RHC prefers the inline greedy coverage path.
            raise self._error_result(
                "phase1_wall_budget_exhausted_after_seed", time_limit_exhausted_before_search=True
            )
        self.initial_result = initial

    def _collect_warm_start(self) -> None:
        raw = self.cfg.seeding.warm_start_assignments_raw
        if not isinstance(raw, list):
            return
        seen: set[UUID] = set()
        for assignment in raw:
            op_id = getattr(assignment, "operation_id", None)
            if op_id not in self.problem_op_ids or op_id in seen:
                continue
            self.warm_start_assignments.append(assignment)
            seen.add(op_id)
        self.warm_start_supplied_assignments = len(self.warm_start_assignments)

    def _try_warm_start_seed(self) -> ScheduleResult | None:
        candidate = sorted(self.warm_start_assignments, key=lambda a: a.start_time)
        missing_ids = self.problem_op_ids.difference(a.operation_id for a in candidate)
        if missing_ids:
            if self._phase1_budget_exhausted():
                self.warm_start_rejected_reason = "phase1_wall_budget_exhausted"
            else:
                outcome = _repair_greedy_outcome(
                    self.problem,
                    candidate,
                    missing_ids,
                    native_skip_reasons=self.native_greedy_repair_skip_reasons,
                )
                if outcome.status == RepairStatus.FEASIBLE:
                    candidate = sorted(
                        candidate + list(outcome.assignments), key=lambda a: a.start_time
                    )
                    self.warm_start_completed_assignments = len(outcome.assignments)
                else:
                    self.warm_start_rejected_reason = outcome.reason
        if self._is_valid_complete_schedule(candidate):
            self.warm_start_used = True
            return self._seed_result(candidate, "warm_start")
        if self.frozen_assignments:
            reanchored = self._reanchor(candidate)
            if self._is_valid_complete_schedule(reanchored):
                self.warm_start_used = True
                return self._seed_result(reanchored, "warm_start")
            if self.warm_start_rejected_reason is None:
                self.warm_start_rejected_reason = "warm_start_reanchored_infeasible"
        elif self.warm_start_rejected_reason is None:
            self.warm_start_rejected_reason = "warm_start_infeasible"
        return None

    def _set_rejected_reason_once(self, reason: str) -> None:
        if self.warm_start_rejected_reason is None:
            self.warm_start_rejected_reason = reason

    def _try_frozen_seed(self) -> ScheduleResult | None:
        seeding = self.cfg.seeding
        remaining_budget_s = max(0.0, self.cfg.budget.time_limit_s - (time.monotonic() - self.t0))
        if self._phase1_budget_exhausted():
            self._set_rejected_reason_once("phase1_wall_budget_exhausted")
            return None
        if not (
            self.n_ops <= seeding.frozen_initial_repair_max_ops
            and remaining_budget_s >= seeding.frozen_initial_repair_min_remaining_time_s
        ):
            self._set_rejected_reason_once("frozen_greedy_seed_skipped_budget_or_size")
            return None
        outcome = _repair_greedy_outcome(
            self.problem,
            self.frozen_assignments,
            set(self.problem_op_ids),
            native_skip_reasons=self.native_greedy_repair_skip_reasons,
        )
        if outcome.status != RepairStatus.FEASIBLE:
            self._set_rejected_reason_once(f"frozen_greedy_seed_{outcome.reason}")
            return None
        candidate = list(outcome.assignments)
        if self._is_valid_complete_schedule(candidate):
            return self._seed_result(candidate, "frozen_greedy_repair")
        self._set_rejected_reason_once("frozen_greedy_seed_infeasible")
        return None

    def _try_native_seed(self) -> ScheduleResult | None:
        """Task 24: fast complete packing via Rust ``greedy_repair_batch``.

        Validated with a RELAXED check (complete + no internal machine overlap):
        an ALNS initial solution need only be complete (Ropke & Pisinger 2006).
        Small instances still tournament against the Python greedy seed.
        """
        self.native_initial_seed_attempted = True
        t_native = time.monotonic()
        if _ops_have_machine_duration_overrides(list(self.ops_by_id.values())):
            self.native_initial_seed_ms = 0
            self.native_initial_seed_fallback_reason = "machine_duration_overrides"
            return None
        native = _try_native_initial_seed(
            self.problem,
            frozen_assignments=self.frozen_assignments,
            ops_by_id=self.ops_by_id,
            frozen_assignments_by_op=self.frozen_assignments_by_op,
        )
        self.native_initial_seed_ms = int((time.monotonic() - t_native) * 1000)
        if native is None:
            self.native_initial_seed_fallback_reason = "native_unavailable_or_failed"
            return None
        if not (
            len(native) == self.n_ops
            and len({a.operation_id for a in native}) == self.n_ops
            and not _has_machine_overlap(native)
        ):
            self.native_initial_seed_fallback_reason = "native_seed_infeasible"
            return None
        recompute_assignment_setups(native, self.dispatch_context)
        self.initial_solver_name, seed_assignments = _maybe_prefer_python_seed(
            self.problem,
            native,
            n_ops=self.n_ops,
            initial_beam_op_limit=self.cfg.seeding.initial_beam_op_limit,
            seed_budget_s=self._initial_seed_budget_s(),
            sdst=self.sdst,
            ops_by_id=self.ops_by_id,
            objective_weights=self.objective_weights,
            is_valid=self._is_valid_complete_schedule,
        )
        self.native_initial_seed_used = self.initial_solver_name == "native_greedy"
        return ScheduleResult(
            solver_name=self.solver.name, status=SolverStatus.FEASIBLE, assignments=seed_assignments
        )

    def _try_cover_seed(self) -> ScheduleResult | None:
        cover_seed = _try_unconstrained_list_schedule_seed(
            self.problem,
            dispatch_context=self.dispatch_context,
            n_ops=self.n_ops,
            frozen_assignments=self.frozen_assignments,
            deadline_exceeded=self._phase1_budget_exhausted,
        )
        if cover_seed is not None:
            self.initial_solver_name = "list_schedule_cover"
        return cover_seed

    def _constructive_seed(self) -> ScheduleResult:
        """Beam/greedy tournament (small n) or greedy; greedy retry on failure."""
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        if self.n_ops <= self.cfg.seeding.initial_beam_op_limit:
            result = self._beam_greedy_tournament()
        else:
            self.initial_solver_name = "greedy"
            result = GreedyDispatch().solve(
                self.problem, time_limit_s=self._initial_seed_budget_s()
            )
        self._accept_partial_seed_or_abort(result, "ALNS seed timed out")
        if self._is_valid_complete_schedule(list(result.assignments)):
            return result
        # Fall back to greedy if beam failed to cover the full instance.
        self.initial_solver_name = "greedy"
        result = GreedyDispatch().solve(self.problem, time_limit_s=self._initial_seed_budget_s())
        self._accept_partial_seed_or_abort(result, "ALNS fallback seed timed out")
        if not self._is_valid_complete_schedule(list(result.assignments)):
            # Proceed with partial coverage — completion + ALNS repair the
            # missing ops. Only bail out on zero coverage.
            if len(result.assignments) > 0:
                logger.info(
                    "ALNS seed incomplete (%d/%d ops), proceeding to "
                    "completion + search for repair",
                    len(result.assignments),
                    self.n_ops,
                )
            else:
                raise self._error_result("initial solution generation failed")
        return result

    def _accept_partial_seed_or_abort(self, result: ScheduleResult, label: str) -> None:
        """A timed-out seed with >0 coverage proceeds to completion + search."""
        if not self._initial_seed_timed_out(result):
            return
        seed_coverage = len(result.assignments) / max(self.n_ops, 1)
        if seed_coverage <= 0:
            raise self._error_result(
                "initial_seed_greedy_timed_out",
                reason_key="initial_seed_greedy_timed_out",
                time_limit_exhausted_before_search=True,
            )
        logger.info(
            "%s at %.1f%% coverage (%d/%d), proceeding to completion + search",
            label,
            seed_coverage * 100,
            len(result.assignments),
            self.n_ops,
        )

    def _beam_greedy_tournament(self) -> ScheduleResult:
        from synaps.solvers.greedy_dispatch import BeamSearchDispatch, GreedyDispatch

        seed_kw = {"time_limit_s": self._initial_seed_budget_s()}
        beam_result = BeamSearchDispatch(beam_width=3).solve(self.problem, **seed_kw)
        greedy_result = GreedyDispatch().solve(self.problem, **seed_kw)
        beam_valid = self._is_valid_complete_schedule(list(beam_result.assignments))
        greedy_valid = self._is_valid_complete_schedule(list(greedy_result.assignments))
        if beam_valid and greedy_valid:
            beam_cost = self._cost_of(list(beam_result.assignments))
            greedy_cost = self._cost_of(list(greedy_result.assignments))
            if greedy_cost < beam_cost:
                self.initial_solver_name = "greedy"
                return greedy_result
            self.initial_solver_name = "beam"
            return beam_result
        if beam_valid:
            self.initial_solver_name = "beam"
            return beam_result
        self.initial_solver_name = "greedy"
        return greedy_result

    def _cost_of(self, assignments: list[Assignment]) -> float:
        objective = _evaluate_objective(
            self.problem, assignments, self.sdst, ops_by_id=self.ops_by_id
        )
        return _objective_cost(objective, self.objective_weights)

    def _reanchor_initial(self, initial: ScheduleResult) -> ScheduleResult:
        reanchored = self._reanchor(list(initial.assignments))
        if not self._is_valid_complete_schedule(reanchored):
            raise self._error_result("initial solution generation failed")
        recompute_assignment_setups(reanchored, self.dispatch_context)
        return initial.model_copy(update={"assignments": reanchored})

    def _complete_initial(self, initial: ScheduleResult) -> ScheduleResult:
        """Greedy-complete a partial seed (hard stop at the Phase-1 ceiling)."""
        if not (len(initial.assignments) < self.n_ops and self.n_ops < APPEND_GAP_SCAN_MIN_OPS):
            return initial
        if self._phase1_budget_exhausted():
            raise self._error_result(
                "phase1_wall_budget_exhausted_before_completion",
                time_limit_exhausted_before_search=True,
            )
        covered_ids = {a.operation_id for a in initial.assignments}
        missing_ids = self.problem_op_ids - covered_ids
        if not missing_ids:
            return initial
        outcome = _repair_greedy_outcome(
            self.problem,
            list(initial.assignments),
            missing_ids,
            native_skip_reasons=self.native_greedy_repair_skip_reasons,
        )
        if outcome.status == RepairStatus.FEASIBLE:
            completed = list(initial.assignments) + list(outcome.assignments)
            completed.sort(key=lambda a: (a.start_time, self.op_positions.get(a.operation_id, 0)))
            logger.info(
                "ALNS completion phase repaired %d missing ops (now %d/%d)",
                len(missing_ids),
                len(completed),
                self.n_ops,
            )
            return initial.model_copy(update={"assignments": completed})
        if (
            self._phase1_budget_exhausted()
            or (time.monotonic() - self.t0) > self.cfg.budget.time_limit_s
        ):
            raise self._error_result(
                "phase1_wall_budget_exhausted_during_completion",
                time_limit_exhausted_before_search=True,
            )
        return initial

    # ------------------------------------------------ phase 2: calibration

    def _init_search_state(self) -> None:
        problem = self.problem
        current = list(self.initial_result.assignments)
        current_obj = _evaluate_objective(problem, current, self.sdst, ops_by_id=self.ops_by_id)
        current_cost = _objective_cost(current_obj, self.objective_weights)
        # P2.1: pre-compute order due offsets once (no datetime math per iteration).
        self.horizon_start = problem.planning_horizon_start
        self.order_due_offsets = {
            order.id: (order.due_date - self.horizon_start).total_seconds() / 60.0
            for order in problem.orders
        }
        current_cache = _build_machine_objective_cache(
            problem,
            current,
            self.sdst,
            ops_by_id=self.ops_by_id,
            horizon_start=self.horizon_start,
            order_due_offsets=self.order_due_offsets,
        )
        self.search = _AlnsSearchState(
            current_assignments=current,
            current_obj=current_obj,
            current_cost=current_cost,
            current_cache=current_cache,
            best_assignments=list(current),
            best_obj=current_obj,
            best_cost=current_cost,
            initial_cost=current_cost,
        )

    def _warm_start_skip_result(self) -> ScheduleResult | None:
        """Task 18.2: commit a warm start already within the gap threshold of the LB."""
        threshold = self.cfg.budget.warm_start_skip_threshold_gap
        if not (threshold > 0 and self.warm_start_used):
            return None
        lower = self.lower_bound.value
        ws_gap = (self.search.current_obj.makespan_minutes - lower) / max(lower, 1e-6)
        if ws_gap > threshold:
            return None
        elapsed_ms = int((time.monotonic() - self.t0) * 1000)
        best = self.search.best_assignments
        recompute_assignment_setups(best, self.dispatch_context)
        final_obj = _evaluate_objective(self.problem, best, self.sdst, ops_by_id=self.ops_by_id)
        return ScheduleResult(
            solver_name=self.solver.name,
            status=SolverStatus.FEASIBLE,
            assignments=best,
            objective=final_obj,
            duration_ms=elapsed_ms,
            random_seed=self.cfg.seeding.seed,
            metadata={
                "alns_skipped_warm_start_sufficient": True,
                "alns_skip_gap": round(ws_gap, 6),
                "iterations_completed": 0,
                "improvements": 0,
                "accepted_iterations": 0,
                "improved_iterations": 0,
                "stagnation_detected": False,
                "stagnation_iteration": None,
                **self._warm_start_meta(),
                "initial_solver": self.initial_solver_name,
                "initial_solution_ms": self.initial_solution_ms,
                **self._native_seed_meta(),
                "time_limit_exhausted_before_search": False,
                "max_iterations": self.max_iterations,
                "max_no_improve_iters": self.max_no_improve_iters,
                **self._lower_bound_meta(final_obj, include_upper=False),
            },
        )

    def _lower_bound_meta(
        self, final_obj: ObjectiveValues, *, include_upper: bool
    ) -> dict[str, Any]:
        lower = self.lower_bound.value
        makespan = final_obj.makespan_minutes
        meta: dict[str, Any] = {"lower_bound": round(lower, 4)}
        if include_upper:
            meta["upper_bound"] = round(makespan, 4)
            meta["gap"] = round(max(makespan - lower, 0.0) / max(makespan, 1e-9), 6)
            meta["lower_bound_method"] = "relaxed_precedence_capacity"
            meta["lower_bound_components"] = self.lower_bound.as_metadata()
        # Audit 6.2 / 6.3: ALNS-scoped LB + conventional relative gap vs the
        # makespan (never the weighted ALNS cost).
        meta["alns_lower_bound"] = round(lower, 4)
        meta["alns_gap_ratio"] = round(max(makespan - lower, 0.0) / max(lower, 1e-6), 6)
        if not include_upper:
            meta["lower_bound_components"] = self.lower_bound.as_metadata()
        return meta

    def _adjust_iteration_budget(self) -> None:
        """Task 18.1 / 18.3: shrink patience and iterations for good warm starts."""
        coverage = self.warm_start_supplied_assignments / max(self.n_ops, 1)
        if self.warm_start_used and coverage > 0.8 and self.max_no_improve_iters > 15:
            self.max_no_improve_iters = 15
        self.adaptive_iteration_scaling_applied = False
        if self.cfg.budget.adaptive_iteration_scaling and self.warm_start_used:
            scale_factor = max(0.1, 1.0 - coverage)
            self.max_iterations = max(5, int(self.max_iterations * scale_factor))
            self.adaptive_iteration_scaling_applied = True

    def _calibrate_temperature(self) -> None:
        an = self.cfg.annealing
        if not (an.sa_auto_calibration_enabled and self.n_ops < APPEND_GAP_SCAN_MIN_OPS):
            return
        self.sa_calibrated_base_temp, self.sa_calibration_samples = _calibrate_sa_temperature(
            self.problem,
            self.search.current_assignments,
            current_cost=self.search.current_cost,
            objective_weights=self.objective_weights,
            sdst=self.sdst,
            destroy_size=self.destroy_size,
            max_destroy=self.cfg.budget.max_destroy,
            ops_by_id=self.ops_by_id,
            successors_by_op=self.successors_by_op,
            trials=an.sa_calibration_trials,
            acceptance_probability=an.sa_initial_acceptance_probability,
            seed=self.cfg.seeding.seed,
            fallback_temperature=an.sa_initial_temp,
        )
        if self.sa_calibration_samples > 0:
            # R5: T_min as a fraction of the calibrated T_0 (Pepels 2014:
            # T_min = 0.01 T_0); an absolute floor degenerates SA into
            # hill-climbing on large-delta objectives.
            self.sa_temp_min = max(self.sa_temp_min, 0.01 * self.sa_calibrated_base_temp)
            self.effective_sa_initial_temp = self._effective_temperature()

    # -------------------------------------------------- phase 3: operators

    def _init_operators(self) -> None:
        ad = self.cfg.adaptation
        n_operators = len(DESTROY_OPERATORS)
        names = [name for name, _ in DESTROY_OPERATORS]
        # C2 (Task 12.1): dict keyed by operator name (robust to reordering).
        weights = list(_normalize_initial_operator_weights(ad.initial_operator_weights_raw, names))
        self.ops = _AlnsOperators(
            names=names,
            weights=weights,
            scores=[0.0] * n_operators,
            attempts=[0] * n_operators,
            cumulative_attempts=[0] * n_operators,
            cumulative_improvements=[0] * n_operators,
            initial_weights_dict={
                name: round(w, 6) for name, w in zip(names, weights, strict=True)
            },
            cross_window_bias_operator_deltas=dict.fromkeys(names, 0.0),
        )
        if ad.mab_pair_selection:
            from synaps.solvers._alns_mab import PairBandit

            # T-34 / Wave 6.3: UCB1 over the (destroy, repair) cartesian product.
            modes = ["cpsat", "greedy"] if self.cfg.budget.use_cpsat_repair else ["greedy"]
            self.ops.mab_repair_modes = modes
            self.ops.mab_pair_labels = [f"{d}|{r}" for d, _ in DESTROY_OPERATORS for r in modes]
            self.ops.pair_bandit = PairBandit(n_pairs=len(self.ops.mab_pair_labels))
        self._apply_cross_window_bias()

    def _apply_cross_window_bias(self) -> None:
        """C4 (Task 3b): bounded (<= 15 %) one-shot boost of setup-disrupting operators."""
        ad, ops = self.cfg.adaptation, self.ops
        hints = ad.cross_window_hints
        if not (ad.cross_window_operator_bias_enabled and hints and isinstance(hints, list)):
            return
        total_max_setup = 0.0
        valid_hint_count = 0
        for hint in hints:
            setup_by_machine = getattr(hint, "setup_cost_by_machine", None)
            if setup_by_machine and isinstance(setup_by_machine, dict):
                costs = [
                    v for v in setup_by_machine.values() if isinstance(v, int | float) and v > 0
                ]
                if costs:
                    total_max_setup += max(costs)
                    valid_hint_count += 1
        if valid_hint_count == 0:
            return
        # 100 minutes of setup concentration saturates the signal.
        signal = min(1.0, (total_max_setup / valid_hint_count) / 100.0)
        boost_factor = min(0.15, signal * 0.15)
        if boost_factor <= 0.0:
            return
        weights, n_operators = ops.weights, len(ops.names)
        pre_bias = list(weights)
        for idx, name in enumerate(ops.names):
            if name == "machine_segment":
                weights[idx] += boost_factor * weights[idx]
            elif name == "worst":
                weights[idx] += (boost_factor * 0.5) * weights[idx]
        # Floor: no operator below 10 % of the uniform weight.
        weight_floor = 1.0 / (n_operators * 10)
        for idx in range(n_operators):
            if weights[idx] < weight_floor:
                weights[idx] = weight_floor
        weight_sum = sum(weights)
        if weight_sum > 0.0:
            ops.weights = [w / weight_sum for w in weights]
        ops.cross_window_bias_applied = True
        ops.cross_window_bias_operator_deltas = {
            name: round(ops.weights[idx] - pre_bias[idx], 6) for idx, name in enumerate(ops.names)
        }

    # ------------------------------------------------ phase 4: search loop

    def _run_search_loop(self) -> None:
        for iteration in range(1, self.max_iterations + 1):
            # D3: time_limit_s is a HARD deadline (min_iterations never overrides it).
            if time.monotonic() - self.t0 >= self.cfg.budget.time_limit_s:
                logger.info("ALNS time limit reached at iteration %d", iteration)
                break
            self.search.iterations_completed = iteration
            if not self._search_iteration(iteration):
                break

    def _select_operator(self) -> tuple[int, int, str | None]:
        """Return ``(operator_idx, pair_idx, forced_repair_mode)``."""
        ops = self.ops
        if ops.pair_bandit is not None:
            pair_idx = int(ops.pair_bandit.select())
            n_modes = max(1, len(ops.mab_repair_modes))
            return pair_idx // n_modes, pair_idx, ops.mab_repair_modes[pair_idx % n_modes]
        r = self.rng.random() * sum(ops.weights)
        cumulative = 0.0
        selected = 0
        for idx, w in enumerate(ops.weights):
            cumulative += w
            if cumulative >= r:
                selected = idx
                break
        return selected, -1, None

    def _destroy(self, destroy_fn: Any) -> set[UUID]:
        budget = self.cfg.budget
        size = (
            self.adaptive_destroy_current if budget.adaptive_destroy_enabled else self.destroy_size
        )
        destroyed_ids: set[UUID] = destroy_fn(
            self.search.current_assignments,
            self.problem,
            self.sdst,
            size,
            self.rng,
            ops_by_id=self.ops_by_id,
            energy_weight=float(
                self.objective_weights.get("energy", self.objective_weights.get("energy_kwh", 0.0))
            ),
        )
        if self.fixed_op_ids:
            destroyed_ids -= self.fixed_op_ids
        if not destroyed_ids:
            return destroyed_ids
        destroyed_ids = _expand_successor_closure(destroyed_ids, self.successors_by_op)
        return _cap_destroy_set_preserving_successor_closure(
            destroyed_ids, self.ops_by_id, self.successors_by_op, budget.max_destroy, self.rng
        )

    def _search_iteration(self, iteration: int) -> bool:
        """One destroy/repair/accept step; False ends the loop."""
        from synaps.solvers._alns_mab import charge_pair_reject

        ops, search = self.ops, self.search
        op_idx, pair_idx, forced_repair_mode = self._select_operator()
        op_name, destroy_fn = DESTROY_OPERATORS[op_idx]
        destroyed_ids = self._destroy(destroy_fn)
        if not destroyed_ids:
            charge_pair_reject(ops.pair_bandit, pair_idx)
            return True
        internal_frozen = [
            a for a in search.current_assignments if a.operation_id not in destroyed_ids
        ]
        remaining_s = self.cfg.budget.time_limit_s - (time.monotonic() - self.t0)
        # Wave 9 / D3: never start a repair with essentially no wall budget left.
        if remaining_s < _ALNS_MIN_REPAIR_REMAINING_S:
            return False
        attempt = self._repair(
            destroyed_ids, internal_frozen, forced_repair_mode, pair_idx, remaining_s
        )
        self.repair.absorb(attempt)
        new_assignments = None if attempt.abort_iteration else attempt.assignments
        if new_assignments is None:
            charge_pair_reject(ops.pair_bandit, pair_idx)
            return True
        candidate = internal_frozen + new_assignments
        if not self._candidate_is_sane(candidate):
            charge_pair_reject(ops.pair_bandit, pair_idx)
            search.feasibility_failures += 1
            return True
        candidate_obj, candidate_cache = self._evaluate_candidate(
            candidate, destroyed_ids, new_assignments
        )
        candidate_cost = _objective_cost(candidate_obj, self.objective_weights)
        cost_before = search.current_cost
        reward = self._accept(candidate, candidate_obj, candidate_cache, candidate_cost)
        if reward >= _SIGMA_NEW_BEST:
            logger.debug(
                "ALNS iter %d: new best (cost=%.1f, makespan=%.1f, %s destroy, %s repair)",
                iteration,
                search.best_cost,
                search.best_obj.makespan_minutes,
                op_name,
                attempt.repair_used,
            )
        self._update_adaptation(iteration, op_idx, pair_idx, reward, cost_before, candidate_cost)
        self._record_iteration(iteration, op_name, destroyed_ids, candidate_cost, reward)
        self._update_ema_repair(attempt)
        self._update_adaptive_destroy(reward)
        search.temperature *= self.effective_sa_cooling_rate
        if self.max_no_improve_iters > 0 and search.no_improve_streak >= self.max_no_improve_iters:
            search.no_improve_early_stop = True
            search.stagnation_iteration = iteration
            logger.info(
                "ALNS early stop: no improvements for %d consecutive iterations",
                search.no_improve_streak,
            )
            return False
        return True

    def _repair(
        self,
        destroyed_ids: set[UUID],
        internal_frozen: list[Assignment],
        forced_repair_mode: str | None,
        pair_idx: int,
        remaining_s: float,
    ) -> Any:
        frozen = self.frozen_assignments + internal_frozen
        frozen_by_op = dict(self.frozen_assignments_by_op)
        frozen_by_op.update({a.operation_id: a for a in internal_frozen})
        budget = self.cfg.budget
        return _attempt_alns_pair_repair(
            problem=self.problem,
            frozen=frozen,
            frozen_by_op=frozen_by_op,
            destroyed_ids=destroyed_ids,
            ops_by_id=self.ops_by_id,
            op_positions=self.op_positions,
            use_cpsat_repair=budget.use_cpsat_repair,
            forced_repair_mode=forced_repair_mode,
            cpsat_max_destroy_ops=budget.cpsat_max_destroy_ops,
            repair_time_limit_s=budget.repair_time_limit_s,
            repair_num_workers=budget.repair_num_workers,
            remaining_s=remaining_s,
            pair_bandit_active=self.ops.pair_bandit is not None and pair_idx >= 0,
            native_skip_reasons=self.native_greedy_repair_skip_reasons,
            frozen_predecessor_end_offsets=self.frozen_predecessor_end_offsets,
            frozen_context_operations=self.frozen_context_operations,
            setup_minutes=self.dispatch_context.setup_minutes,
        )

    def _candidate_is_sane(self, candidate: list[Assignment]) -> bool:
        """Completeness, precedence, frozen precedence and occupancy sanity."""
        if len({a.operation_id for a in candidate}) != self.n_ops:
            return False
        if _has_precedence_violation(candidate, self.ops_by_id):
            return False
        if self._frozen_prec_bad(candidate):
            return False
        return not self._overlap(self.frozen_assignments + candidate)

    def _evaluate_candidate(
        self,
        candidate: list[Assignment],
        destroyed_ids: set[UUID],
        new_assignments: list[Assignment],
    ) -> tuple[ObjectiveValues, Any]:
        """Incremental evaluation: recompute only machines touched by the move."""
        affected_machine_ids: set[Any] = {
            a.work_center_id
            for a in self.search.current_assignments
            if a.operation_id in destroyed_ids
        }
        affected_machine_ids.update(a.work_center_id for a in new_assignments)
        candidate_obj, candidate_cache = _evaluate_objective_incremental(
            self.problem,
            candidate,
            self.sdst,
            ops_by_id=self.ops_by_id,
            horizon_start=self.horizon_start,
            affected_machine_ids=affected_machine_ids,
            base_cache=self.search.current_cache,
        )
        return candidate_obj, candidate_cache

    def _accept(
        self,
        candidate: list[Assignment],
        candidate_obj: ObjectiveValues,
        candidate_cache: Any,
        candidate_cost: float,
    ) -> float:
        """Global-best / SA acceptance; returns the Ropke-Pisinger score."""
        search = self.search
        delta = candidate_cost - search.current_cost
        if candidate_cost < search.best_cost:
            search.best_assignments = list(candidate)
            search.best_obj = candidate_obj
            search.best_cost = candidate_cost
            self._move_current(candidate, candidate_obj, candidate_cache, candidate_cost)
            search.improvements += 1
            search.no_improve_streak = 0
            return _SIGMA_NEW_BEST
        if _sa_accept(delta, search.temperature, self.rng):
            self._move_current(candidate, candidate_obj, candidate_cache, candidate_cost)
            if delta < 0:
                search.no_improve_streak = 0
                return _SIGMA_BETTER
            search.sa_worsening_accepted += 1
            search.no_improve_streak += 1
            return _SIGMA_ACCEPTED
        if delta > 0:
            search.sa_worsening_rejected += 1
        search.no_improve_streak += 1
        return 0.0

    def _move_current(
        self,
        candidate: list[Assignment],
        candidate_obj: ObjectiveValues,
        candidate_cache: Any,
        candidate_cost: float,
    ) -> None:
        search = self.search
        search.current_assignments = candidate
        search.current_obj = candidate_obj
        search.current_cost = candidate_cost
        search.current_cache = candidate_cache

    def _update_adaptation(
        self,
        iteration: int,
        op_idx: int,
        pair_idx: int,
        reward: float,
        cost_before: float,
        candidate_cost: float,
    ) -> None:
        ops = self.ops
        ops.scores[op_idx] += reward
        ops.attempts[op_idx] += 1
        if ops.pair_bandit is not None:
            from synaps.solvers._alns_mab import pair_reward

            ops.pair_bandit.update(
                pair_idx if pair_idx >= 0 else op_idx,
                pair_reward(
                    cost_before=cost_before, cost_after=candidate_cost, accepted=reward > 0.0
                ),
            )
        # B3 (Task 7.4): cumulative per-operator tracking (never reset).
        ops.cumulative_attempts[op_idx] += 1
        if reward >= _SIGMA_NEW_BEST:
            ops.cumulative_improvements[op_idx] += 1
        if reward > 0.0:
            self.search.accepted_iterations += 1
        # Segment boundary: refresh weights and reset the segment.
        if iteration % self.cfg.adaptation.operator_weight_segment_length == 0:
            ops.weights = _update_operator_weights_for_segment(
                ops.scores, ops.attempts, reset_mix=self.cfg.adaptation.operator_weight_reset_mix
            )
            ops.scores = [0.0] * len(ops.names)
            ops.attempts = [0] * len(ops.names)

    def _record_iteration(
        self,
        iteration: int,
        op_name: str,
        destroyed_ids: set[UUID],
        candidate_cost: float,
        reward: float,
    ) -> None:
        if not self.cfg.adaptation.record_iteration_metrics:
            return
        self.iteration_trace.append(
            AlnsIterationRecord(
                iteration=iteration,
                operator_name=op_name,
                destroy_size=len(destroyed_ids),
                repair_status="feasible",  # only reached when repair succeeded
                candidate_cost=candidate_cost,
                best_cost=self.search.best_cost,
                temperature=self.search.temperature,
                accepted=reward > 0.0,
                improved=reward >= _SIGMA_NEW_BEST,
            )
        )

    def _update_ema_repair(self, attempt: Any) -> None:
        """P3.3: EMA of the per-iteration repair time of the lane that succeeded.

        Audit 2026-10 (A-09): the EMA used to average the lane's CUMULATIVE
        total (``cpsat_repair_ms_total`` summed over all iterations), so it grew
        monotonically instead of estimating one repair. ``attempt`` carries the
        per-iteration lane timings.
        """
        search = self.search
        iter_repair_ms = 0
        if attempt.repair_used == "cpsat":
            iter_repair_ms = attempt.cpsat_repair_ms_total
        elif attempt.repair_used == "greedy":
            iter_repair_ms = attempt.greedy_repair_ms_total
        if iter_repair_ms <= 0:
            return
        alpha = self.cfg.budget.ema_repair_alpha
        if search.ema_repair_samples == 0:
            search.ema_repair_ms = float(iter_repair_ms)
        else:
            search.ema_repair_ms = alpha * iter_repair_ms + (1.0 - alpha) * search.ema_repair_ms
        search.ema_repair_samples += 1

    def _update_adaptive_destroy(self, reward: float) -> None:
        """P3.2: shrink on improvement (exploit), grow every 5-iteration plateau."""
        budget = self.cfg.budget
        if not budget.adaptive_destroy_enabled:
            return
        if reward >= _SIGMA_NEW_BEST:
            self.adaptive_destroy_current = max(
                budget.min_destroy,
                int(self.adaptive_destroy_current * budget.adaptive_destroy_shrink_rate),
            )
        elif self.search.no_improve_streak > 0 and self.search.no_improve_streak % 5 == 0:
            self.adaptive_destroy_current = min(
                budget.max_destroy,
                int(self.adaptive_destroy_current * budget.adaptive_destroy_grow_rate),
            )

    # ------------------------------------------- phase 5: final validation

    def _finalize(self) -> ScheduleResult:
        search, stats = self.search, self.repair
        (
            best_assignments,
            final_obj,
            final_cost,
            violations,
            violations_before_recovery,
            frozen_precedence_bad,
            recovered,
            recovery_source,
        ) = self.solver._final_validate(
            self.problem,
            search.best_assignments,
            list(self.initial_result.assignments),
            self.frozen_assignments,
            self._frozen_prec_bad,
            self.dispatch_context,
            self.checker,
            self.sdst,
            self.ops_by_id,
            self.objective_weights,
        )
        status = (
            SolverStatus.FEASIBLE
            if not violations and not frozen_precedence_bad
            else SolverStatus.ERROR
        )
        elapsed_ms = int((time.monotonic() - self.t0) * 1000)
        logger.info(
            "ALNS finished: %d iterations, %d improvements, cost=%.1f, "
            "makespan=%.1f min, %d cpsat repairs, %d greedy repairs, "
            "%d feasibility failures, %d violations, %d ms",
            search.iterations_completed,
            search.improvements,
            final_cost,
            final_obj.makespan_minutes,
            stats.cpsat_repairs,
            stats.greedy_repairs,
            search.feasibility_failures,
            len(violations),
            elapsed_ms,
        )
        recovery = {
            "final_violation_recovery_attempted": len(violations_before_recovery) > 0,
            "final_violation_recovered": recovered,
            "final_violation_recovery_source": recovery_source,
            "final_violations_before_recovery": len(violations_before_recovery),
            # Q4: the search incumbent was discarded and the seed returned.
            "quality_warning": "search_discarded_returned_seed" if recovered else None,
            "final_violations": len(violations),
        }
        metadata = {
            **self._meta_search_stats(),
            **self._meta_seed_and_budget(),
            **self._meta_annealing(),
            **self._meta_repair(recovery),
            **self._meta_quality(final_obj, final_cost),
        }
        return ScheduleResult(
            solver_name=self.solver.name,
            status=status,
            assignments=best_assignments,
            objective=final_obj,
            duration_ms=elapsed_ms,
            random_seed=self.cfg.seeding.seed,
            metadata=metadata,
        )

    def _meta_search_stats(self) -> dict[str, Any]:
        search, stats, ops = self.search, self.repair, self.ops
        destroy_names = [name for name, _ in DESTROY_OPERATORS]
        total_destroy = (
            stats.cpsat_repair_total_destroy_size + stats.greedy_repair_total_destroy_size
        )
        return {
            "iterations_completed": search.iterations_completed,
            "improvements": search.improvements,
            # B3 (Task 7.4): aggregate convergence metadata — always present.
            "accepted_iterations": search.accepted_iterations,
            "improved_iterations": search.improvements,
            "operator_attempt_counts": {
                name: ops.cumulative_attempts[i] for i, name in enumerate(destroy_names)
            },
            "operator_improvement_counts": {
                name: ops.cumulative_improvements[i] for i, name in enumerate(destroy_names)
            },
            "alns_final_operator_weights": {
                name: round(ops.weights[i], 6) for i, name in enumerate(destroy_names)
            },
            # C2 (Task 12.1): names + initial weights for cross-window persistence.
            "alns_operator_names": ops.names,
            "alns_initial_operator_weights": ops.initial_weights_dict,
            # C4 (Task 3b.4): always present, applied or not.
            "cross_window_bias_applied": ops.cross_window_bias_applied,
            "cross_window_bias_operator_deltas": ops.cross_window_bias_operator_deltas,
            "stagnation_detected": search.no_improve_early_stop,
            "stagnation_iteration": search.stagnation_iteration,
            "cpsat_repair_attempts": stats.cpsat_repair_attempts,
            "cpsat_repairs": stats.cpsat_repairs,
            "cpsat_repair_skips_large_destroy": stats.cpsat_repair_skips_large_destroy,
            "cpsat_repair_timeouts": stats.cpsat_repair_timeouts,
            "cpsat_repair_total_destroy_size": stats.cpsat_repair_total_destroy_size,
            "greedy_repair_attempts": stats.greedy_repair_attempts,
            "greedy_repairs": stats.greedy_repairs,
            "greedy_repair_timeouts": stats.greedy_repair_timeouts,
            "greedy_repair_total_destroy_size": stats.greedy_repair_total_destroy_size,
            # R2: empirical mean repair seconds per destroyed op (None on cold start).
            "observed_repair_s_per_destroyed_op": (
                (stats.cpsat_repair_ms_total + stats.greedy_repair_ms_total)
                / 1000.0
                / total_destroy
                if total_destroy > 0
                else None
            ),
            "repair_rejection_reasons": stats.repair_rejection_reasons,
        }

    def _meta_seed_and_budget(self) -> dict[str, Any]:
        cfg, seeding, budget = self.cfg, self.cfg.seeding, self.cfg.budget
        ops = self.ops
        return {
            "initial_solver": self.initial_solver_name,
            **self._warm_start_meta(),
            "initial_beam_op_limit": seeding.initial_beam_op_limit,
            "frozen_initial_repair_max_ops": seeding.frozen_initial_repair_max_ops,
            "phase1_wall_fraction": seeding.phase1_wall_fraction,
            "frozen_initial_repair_min_remaining_time_s": (
                seeding.frozen_initial_repair_min_remaining_time_s
            ),
            "cpsat_max_destroy_ops": budget.cpsat_max_destroy_ops,
            "mab_pair_selection": cfg.adaptation.mab_pair_selection,
            "mab_pair_count": len(ops.mab_pair_labels),
            "mab_repair_modes": list(ops.mab_repair_modes),
            "mab_pair_pulls": _pair_pulls(ops.pair_bandit, ops.mab_pair_labels),
            "repair_num_workers": budget.repair_num_workers,
            "initial_solution_ms": self.initial_solution_ms,
            **self._native_seed_meta(),
            **_alns_wall_clock_honesty_meta(
                budget.determinism,
                bool(self.time_limit_exhausted_before_search),
                self.search.iterations_completed,
                self.max_iterations,
                time.monotonic() - self.t0,
                budget.time_limit_s,
                no_improve=self.search.no_improve_early_stop,
            ),
            "time_limit_exhausted_before_search": self.time_limit_exhausted_before_search,
        }

    def _meta_annealing(self) -> dict[str, Any]:
        an, ad, search = self.cfg.annealing, self.cfg.adaptation, self.search
        worsening = search.sa_worsening_accepted + search.sa_worsening_rejected
        return {
            "max_no_improve_iters": self.max_no_improve_iters,
            "max_no_improve_base_iters": ad.max_no_improve_base_iters,
            "dynamic_no_improve_enabled": ad.dynamic_no_improve_enabled,
            "dynamic_sa_enabled": an.dynamic_sa_enabled,
            "sa_auto_calibration_enabled": an.sa_auto_calibration_enabled,
            "sa_calibration_trials": an.sa_calibration_trials,
            "sa_calibration_samples": self.sa_calibration_samples,
            "sa_initial_acceptance_probability": an.sa_initial_acceptance_probability,
            "due_pressure": round(an.due_pressure, 4),
            "candidate_pressure": round(an.candidate_pressure, 4),
            "sa_pressure_factor": round(self.sa_pressure_factor, 4),
            "sa_calibrated_base_temp": round(self.sa_calibrated_base_temp, 4),
            "effective_sa_initial_temp": round(self.effective_sa_initial_temp, 4),
            "effective_sa_cooling_rate": round(self.effective_sa_cooling_rate, 6),
            "operator_weight_segment_length": ad.operator_weight_segment_length,
            "operator_weight_reset_mix": ad.operator_weight_reset_mix,
            "sa_due_alpha": an.sa_due_alpha,
            "sa_candidate_beta": an.sa_candidate_beta,
            "sa_pressure_cooling_gamma": an.sa_pressure_cooling_gamma,
            "sa_temp_min": self.sa_temp_min,
            "sa_temp_max": an.sa_temp_max,
            "no_improve_due_alpha": ad.no_improve_due_alpha,
            "no_improve_candidate_beta": ad.no_improve_candidate_beta,
            "no_improve_min_iters": ad.no_improve_min_iters,
            "no_improve_max_iters": ad.no_improve_max_iters,
            "no_improve_early_stop": search.no_improve_early_stop,
            "no_improve_streak_final": search.no_improve_streak,
            "sa_worsening_accepted": search.sa_worsening_accepted,
            "sa_worsening_rejected": search.sa_worsening_rejected,
            "effective_sa_acceptance_rate": round(
                search.sa_worsening_accepted / max(1, worsening), 4
            ),
        }

    def _meta_repair(self, recovery: dict[str, Any]) -> dict[str, Any]:
        stats, search = self.repair, self.search
        return {
            "cpsat_repair_ms_total": stats.cpsat_repair_ms_total,
            "greedy_repair_ms_total": stats.greedy_repair_ms_total,
            "cpsat_repair_ms_mean": round(
                stats.cpsat_repair_ms_total / stats.cpsat_repair_attempts, 2
            )
            if stats.cpsat_repair_attempts > 0
            else 0.0,
            "greedy_repair_ms_mean": round(
                stats.greedy_repair_ms_total / stats.greedy_repair_attempts, 2
            )
            if stats.greedy_repair_attempts > 0
            else 0.0,
            "feasibility_failures": search.feasibility_failures,
            **recovery,
            "destroy_operators": {
                name: {"final_weight": round(self.ops.weights[i], 4)}
                for i, (name, _) in enumerate(DESTROY_OPERATORS)
            },
            "sdst_matrix_bytes": self.sdst.memory_bytes(),
        }

    def _meta_quality(self, final_obj: ObjectiveValues, final_cost: float) -> dict[str, Any]:
        search, budget = self.search, self.cfg.budget
        record = self.cfg.adaptation.record_iteration_metrics
        return {
            "initial_cost": round(search.initial_cost, 2),
            "final_cost": round(final_cost, 2),
            **self._lower_bound_meta(final_obj, include_upper=True),
            "improvement_pct": round((1 - final_cost / max(search.initial_cost, 1e-9)) * 100, 2),
            "fixed_ops_applied": len(self.fixed_op_ids),
            "adaptive_destroy_enabled": budget.adaptive_destroy_enabled,
            "adaptive_destroy_final_size": self.adaptive_destroy_current,
            "ema_repair_ms": round(search.ema_repair_ms, 2),
            "ema_repair_samples": search.ema_repair_samples,
            # Task 18: adaptive iteration budget.
            "alns_skipped_warm_start_sufficient": False,
            "adaptive_iteration_scaling": budget.adaptive_iteration_scaling,
            "adaptive_iteration_scaling_applied": self.adaptive_iteration_scaling_applied,
            "max_iterations": self.max_iterations,
            "original_max_iterations": self.original_max_iterations,
            # B3 (Task 7.3): per-iteration convergence trace (only when enabled).
            **(
                {"alns_iteration_trace": [r.to_dict() for r in self.iteration_trace]}
                if record
                else {}
            ),
        }


def _pair_pulls(bandit: Any, labels: list[str]) -> dict[str, int]:
    from synaps.solvers._alns_mab import pair_pulls

    return pair_pulls(bandit, labels)
