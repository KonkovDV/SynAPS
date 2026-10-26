"""Incremental Repair Engine — localised neighbourhood repair for schedule disruptions."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

from synaps.model import (
    Assignment,
    ObjectiveValues,
    Operation,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from synaps.planning_policy import frozen_ids_for_repair
from synaps.solvers import BaseSolver
from synaps.solvers._dispatch_support import (
    MachineIndex,
    build_dispatch_context,
    find_earliest_feasible_slot,
    gap_scan_for,
    recompute_assignment_setups,
)
from synaps.solvers._time_windows import operation_earliest_offset_minutes
from synaps.solvers.coverage_outcome import stamp_honest_coverage
from synaps.solvers.delta_notary import notarize_repair

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


def _total_tardiness(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[Any, Operation],
    horizon_start: datetime,
) -> float:
    """Per-order tardiness; F10-consistent with ``objective.evaluate``: an
    order with no scheduled operations completes at the horizon END."""
    order_completion: dict[Any, float] = {}
    for assignment in assignments:
        operation = ops_by_id.get(assignment.operation_id)
        if operation is None:
            continue
        end = (assignment.end_time - horizon_start).total_seconds() / 60.0
        order_completion[operation.order_id] = max(
            order_completion.get(operation.order_id, 0.0), end
        )
    horizon_span = (problem.planning_horizon_end - horizon_start).total_seconds() / 60.0
    return sum(
        max(
            order_completion.get(order.id, horizon_span)
            - (order.due_date - horizon_start).total_seconds() / 60.0,
            0.0,
        )
        for order in problem.orders
    )


def _publish_repair_result(
    *,
    solver_name: str,
    problem: ScheduleProblem,
    all_assignments: list[Assignment],
    remaining_repair: list[Operation],
    neighbourhood: set[Any],
    frozen: list[Assignment],
    repaired: list[Assignment],
    used_cpsat_fallback: bool,
    cpsat_fallback_num_workers: int,
    t0: float,
    base_assignments: list[Assignment],
    notary_mode: str,
    freeze_horizon_end: Any,
    total_setup: float,
    total_material_loss: float,
    makespan: float,
    total_tardiness: float,
) -> ScheduleResult:
    """Final notary + ScheduleResult. Default notary is exhaustive (S4)."""

    unrepaired_ids = [operation.id for operation in remaining_repair]
    # Wave 11 / C2: never claim FEASIBLE while neighbourhood ops remain unrepaired.
    # W16-P1: never claim FEASIBLE without a final notary pass — a timed-out
    # CP-SAT fallback incumbent can overlap greedy-placed ops.
    notary = notarize_repair(
        problem,
        all_assignments,
        mode=notary_mode,
        baseline=base_assignments,
        freeze_horizon_end=freeze_horizon_end,
    )
    status = (
        SolverStatus.FEASIBLE
        if not unrepaired_ids and not notary.violations
        else SolverStatus.INFEASIBLE
    )
    return ScheduleResult(
        solver_name=solver_name,
        status=status,
        assignments=all_assignments,
        objective=ObjectiveValues(
            makespan_minutes=makespan,
            total_setup_minutes=total_setup,
            total_material_loss=total_material_loss,
            total_tardiness_minutes=total_tardiness,
        ),
        duration_ms=int((time.monotonic() - t0) * 1000),
        metadata={
            "neighbourhood_size": len(neighbourhood),
            "frozen_count": len(frozen),
            "repaired_count": len(repaired),
            "unrepaired_count": len(unrepaired_ids),
            "cpsat_fallback_num_workers": cpsat_fallback_num_workers,
            "used_cpsat_fallback": used_cpsat_fallback,
            "notary_mode": notary.mode,
            "notary_mismatch": notary.mismatch,
            "notary_ms": notary.elapsed_ms,
            "notary_delta_ops": notary.dirty_operations,
            "notary_delta_machines": notary.dirty_machines,
        },
    )


class IncrementalRepair(BaseSolver):
    """Repair a disrupted schedule by re-dispatching operations within a
    configurable neighbourhood radius, keeping all other assignments frozen.

    Radius policy:
        BREAKDOWN  → 2 x setup_count downstream
        RUSH_ORDER → affected machine ± 30 min window
        MATERIAL   → same state group
        DEFAULT    → 5 operations forward
    """

    def _cpsat_fallback(
        self,
        problem: ScheduleProblem,
        frozen_assignments: list[Assignment],
        remaining_op_ids: set[Any],
        already_scheduled_ids: set[Any],
        *,
        num_workers: int = 1,
    ) -> list[Assignment] | None:
        """Use a micro CP-SAT solve when constructive repair cannot place the remainder.

        Frozen work stays fixed: machine no-overlap via ``frozen_assignments``,
        and precedence via ``frozen_predecessor_end_offsets`` (Wave 11 / C1).
        Only ``remaining_op_ids`` are free decision variables — predecessors that
        are already scheduled must not be re-timed inside the subproblem.
        """
        import math

        from synaps.solvers.cpsat_solver import CpSatSolver

        op_positions = {operation.id: index for index, operation in enumerate(problem.operations)}
        ops_by_id = {operation.id: operation for operation in problem.operations}
        frozen_by_op = {assignment.operation_id: assignment for assignment in frozen_assignments}
        _ = already_scheduled_ids  # reserved for future readiness diagnostics

        sub_operations = [
            operation for operation in problem.operations if operation.id in remaining_op_ids
        ]
        if not sub_operations:
            return None

        horizon_start = problem.planning_horizon_start
        frozen_predecessor_end_offsets: dict[Any, int] = {}
        free_operations: list[Operation] = []
        for operation in sub_operations:
            pred_id = operation.predecessor_op_id
            if pred_id is not None and pred_id not in remaining_op_ids:
                # Pred outside free set: must be frozen (Wave 12 / C12-3). Never
                # clear the edge without an offset — that was fail-open.
                frozen_pred = frozen_by_op.get(pred_id)
                if frozen_pred is None:
                    return None
                frozen_predecessor_end_offsets[operation.id] = math.ceil(
                    (frozen_pred.end_time - horizon_start).total_seconds() / 60.0
                )
                free_operations.append(operation.model_copy(update={"predecessor_op_id": None}))
            else:
                free_operations.append(operation)

        sub_problem = ScheduleProblem(
            states=problem.states,
            orders=problem.orders,
            operations=free_operations,
            work_centers=problem.work_centers,
            setup_matrix=problem.setup_matrix,
            auxiliary_resources=problem.auxiliary_resources,
            aux_requirements=[
                requirement
                for requirement in problem.aux_requirements
                if requirement.operation_id in remaining_op_ids
            ],
            planning_horizon_start=problem.planning_horizon_start,
            planning_horizon_end=problem.planning_horizon_end,
        )

        try:
            result = CpSatSolver().solve(
                sub_problem,
                time_limit_s=5,
                num_workers=max(1, int(num_workers)),
                auto_greedy_warm_start=False,
                enable_symmetry_breaking=False,
                frozen_assignments=list(frozen_assignments),
                frozen_predecessor_end_offsets=frozen_predecessor_end_offsets,
                frozen_context_operations=list(problem.operations),
                frozen_aux_requirements=list(problem.aux_requirements),
            )
        except ValueError:
            return None

        if (
            result.status in (SolverStatus.INFEASIBLE, SolverStatus.ERROR, SolverStatus.TIMEOUT)
            and not result.assignments
        ):
            return None

        fallback_assignments = [
            assignment
            for assignment in result.assignments
            if assignment.operation_id in remaining_op_ids
        ]
        # Reject incomplete CP-SAT returns: missing remaining ops must not look repaired.
        if {a.operation_id for a in fallback_assignments} != set(remaining_op_ids):
            return None
        fallback_assignments.sort(key=lambda assignment: op_positions[assignment.operation_id])
        # Defensive precedence check vs frozen predecessors (C1 fail-closed).
        for assignment in fallback_assignments:
            scheduled_op = ops_by_id.get(assignment.operation_id)
            if scheduled_op is None or scheduled_op.predecessor_op_id is None:
                continue
            if scheduled_op.predecessor_op_id in remaining_op_ids:
                continue
            frozen_pred = frozen_by_op.get(scheduled_op.predecessor_op_id)
            if frozen_pred is not None and assignment.start_time < frozen_pred.end_time:
                return None
        return fallback_assignments

    @property
    def name(self) -> str:
        return "incremental_repair"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        from synaps.solvers.greedy_dispatch import (
            _map_assignments_onto_virtual_lanes,
            _unroll_lane_assignments,
            _virtualize_parallel_lanes,
        )

        virtual_problem, virtual_to_original = _virtualize_parallel_lanes(problem)
        if not virtual_to_original:
            return stamp_honest_coverage(problem, self._solve_core(problem, **kwargs))
        mapped_kwargs = dict(kwargs)
        mapped_kwargs["base_assignments"] = _map_assignments_onto_virtual_lanes(
            list(kwargs.get("base_assignments") or []),
            virtual_to_original,
        )
        result = self._solve_core(virtual_problem, **mapped_kwargs)
        _unroll_lane_assignments(result, virtual_to_original)
        result.metadata["parallel_virtualization"] = True
        return stamp_honest_coverage(problem, result)

    def _finish_with_cpsat(
        self,
        problem: ScheduleProblem,
        frozen: list[Assignment],
        loop: _GreedyRepairLoop,
        remaining_repair: list[Operation],
        num_workers: int,
    ) -> bool:
        """A ready operation fit nowhere: let CP-SAT place every remaining one."""
        cpsat_result = self._cpsat_fallback(
            problem,
            frozen + loop.repaired,
            {operation.id for operation in remaining_repair},
            loop.scheduled_ids,
            num_workers=num_workers,
        )
        if cpsat_result is None:
            return False
        loop.repaired.extend(cpsat_result)
        loop.scheduled_ids.update(assignment.operation_id for assignment in cpsat_result)
        remaining_repair.clear()
        return True

    def _solve_core(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()

        # Required kwargs
        base_assignments = cast("list[Assignment]", kwargs.get("base_assignments", []))
        disrupted_op_ids = set(cast("list[Any]", kwargs.get("disrupted_op_ids", [])))
        radius: int = int(kwargs.get("radius", 5))
        cpsat_fallback_num_workers: int = max(
            1,
            int(kwargs.get("cpsat_fallback_num_workers", kwargs.get("num_workers", 1))),
        )

        if not base_assignments:
            return ScheduleResult(
                solver_name=self.name,
                status=SolverStatus.ERROR,
                metadata={"error": "base_assignments required"},
            )

        ops_by_id = {op.id: op for op in problem.operations}
        op_positions = {op.id: index for index, op in enumerate(problem.operations)}
        dispatch_context = build_dispatch_context(problem)

        # Neighbourhood: disrupted ops + `radius` downstream successors, minus frozen.
        neighbourhood = _repair_neighbourhood(problem, disrupted_op_ids, radius)
        neighbourhood -= frozen_ids_for_repair(base_assignments, kwargs)

        # Separate frozen vs. repaired assignments
        frozen = [a for a in base_assignments if a.operation_id not in neighbourhood]
        to_repair = [
            ops_by_id[operation_id]
            for operation_id in sorted(neighbourhood, key=op_positions.__getitem__)
            if operation_id in ops_by_id
        ]
        loop = _GreedyRepairLoop(problem, dispatch_context, frozen, op_positions)
        remaining_repair, slot_missing = loop.run(to_repair)
        repaired = loop.repaired
        used_cpsat_fallback = slot_missing and self._finish_with_cpsat(
            problem, frozen, loop, remaining_repair, cpsat_fallback_num_workers
        )

        all_assignments = frozen + repaired

        # Recompute per-assignment setup_minutes from the final machine
        # sequence — prevents ghost setups when a repaired op is inserted
        # between two frozen ops.
        total_setup = recompute_assignment_setups(all_assignments, dispatch_context)
        horizon_start = problem.planning_horizon_start
        makespan = (
            max((a.end_time - horizon_start).total_seconds() / 60.0 for a in all_assignments)
            if all_assignments
            else 0.0
        )

        # Per-order tardiness (F10-consistent with objective.evaluate)
        total_tardiness = _total_tardiness(problem, all_assignments, ops_by_id, horizon_start)
        return _publish_repair_result(
            solver_name=self.name,
            problem=problem,
            all_assignments=all_assignments,
            remaining_repair=remaining_repair,
            neighbourhood=neighbourhood,
            frozen=frozen,
            repaired=repaired,
            used_cpsat_fallback=used_cpsat_fallback,
            cpsat_fallback_num_workers=cpsat_fallback_num_workers,
            t0=t0,
            base_assignments=base_assignments,
            notary_mode=str(kwargs.get("notary", "exhaustive")),
            freeze_horizon_end=kwargs.get("freeze_horizon_end"),
            total_setup=total_setup,
            total_material_loss=_total_material_loss(all_assignments, ops_by_id, dispatch_context),
            makespan=makespan,
            total_tardiness=total_tardiness,
        )


def _repair_neighbourhood(
    problem: ScheduleProblem, disrupted_op_ids: set[Any], radius: int
) -> set[Any]:
    """Disrupted operations plus up to ``radius`` layers of chain successors."""
    neighbourhood: set[Any] = set(disrupted_op_ids)
    for _ in range(radius):
        new_layer: set[Any] = set()
        for op in problem.operations:
            if op.predecessor_op_id in neighbourhood and op.id not in neighbourhood:
                new_layer.add(op.id)
        if not new_layer:
            break
        neighbourhood.update(new_layer)
    return neighbourhood


_RepairCandidate = tuple[int, float, float, float, int, int, str, "Operation", "UUID", Any]


class _GreedyRepairLoop:
    """Priority-aware greedy re-insertion of the neighbourhood after the frozen set."""

    def __init__(
        self,
        problem: ScheduleProblem,
        dispatch_context: Any,
        frozen: list[Assignment],
        op_positions: dict[Any, int],
    ) -> None:
        self.dispatch_context = dispatch_context
        self.op_positions = op_positions
        self.orders_by_id = {o.id: o for o in problem.orders}
        self.horizon_start = problem.planning_horizon_start
        self.all_wc_ids = [work_center.id for work_center in problem.work_centers]
        self.repaired: list[Assignment] = []
        self.scheduled_ids: set[Any] = {a.operation_id for a in frozen}
        self.scheduled_by_op: dict[Any, Assignment] = {
            assignment.operation_id: assignment for assignment in frozen
        }
        self.machine_idx = MachineIndex(dispatch_context)
        self.machine_idx.extend(frozen)
        self.n_scan = len(problem.operations)

    def run(self, to_repair: list[Operation]) -> tuple[list[Operation], bool]:
        """Insert until done or stuck: ``(remaining, a ready op had no slot)``."""
        # Sort by descending priority first (higher priority = more urgent),
        # then by sequence within order for stable tie-breaking.
        remaining_repair = sorted(
            to_repair,
            key=lambda operation: (
                -self.orders_by_id[operation.order_id].priority,
                operation.seq_in_order,
                self.op_positions[operation.id],
            ),
        )
        while remaining_repair:
            ready = [
                operation
                for operation in remaining_repair
                if operation.predecessor_op_id is None
                or operation.predecessor_op_id in self.scheduled_ids
            ]
            if not ready:
                return remaining_repair, False
            best_candidate = self._best_candidate(ready)
            if best_candidate is None:
                return remaining_repair, True
            _, _, _, _, _, _, _, operation, work_center_id, slot = best_candidate
            self.repaired.append(
                Assignment(
                    operation_id=operation.id,
                    work_center_id=work_center_id,
                    start_time=self.horizon_start + timedelta(minutes=slot.start_offset),
                    end_time=self.horizon_start + timedelta(minutes=slot.end_offset),
                    setup_minutes=slot.setup_minutes,
                    aux_resource_ids=slot.aux_resource_ids,
                )
            )
            self.scheduled_by_op[operation.id] = self.repaired[-1]
            self.machine_idx.add(self.repaired[-1])
            self.scheduled_ids.add(operation.id)
            remaining_repair.remove(operation)
        return remaining_repair, False

    def _best_candidate(self, ready: list[Operation]) -> _RepairCandidate | None:
        best_candidate: _RepairCandidate | None = None
        scheduled_assignments = self.machine_idx.all_assignments
        for operation in ready:
            predecessor_end = 0.0
            if operation.predecessor_op_id is not None:
                predecessor_assignment = self.scheduled_by_op.get(operation.predecessor_op_id)
                if predecessor_assignment is not None:
                    predecessor_end = (
                        predecessor_assignment.end_time - self.horizon_start
                    ).total_seconds() / 60.0
            earliest_start = max(
                predecessor_end,
                operation_earliest_offset_minutes(
                    operation,
                    self.orders_by_id[operation.order_id],
                    self.horizon_start,
                ),
            )
            eligible = operation.eligible_wc_ids if operation.eligible_wc_ids else self.all_wc_ids
            for work_center_id in eligible:
                slot = find_earliest_feasible_slot(
                    self.dispatch_context,
                    scheduled_assignments,
                    operation,
                    work_center_id,
                    earliest_start,
                    machine_index=self.machine_idx,
                    gap_scan=gap_scan_for(self.n_scan, operation),
                )
                if slot is None:
                    continue
                # Priority-aware candidate key: high-priority operations (higher
                # number) are preferred even if they start later. Negative
                # priority ensures descending sort. Within the same priority
                # class, prefer earlier end_offset to minimise makespan impact,
                # then lower material loss.
                candidate: _RepairCandidate = (
                    -self.orders_by_id[operation.order_id].priority,
                    slot.end_offset,
                    slot.material_loss,
                    slot.start_offset,
                    operation.seq_in_order,
                    self.op_positions[operation.id],
                    str(work_center_id),
                    operation,
                    work_center_id,
                    slot,
                )
                if best_candidate is None or candidate[:7] < best_candidate[:7]:
                    best_candidate = candidate
        return best_candidate


def _total_material_loss(
    all_assignments: list[Assignment], ops_by_id: dict[Any, Operation], dispatch_context: Any
) -> float:
    """Material loss of the consecutive transitions on every machine sequence."""
    total_material_loss = 0.0
    by_machine: dict[Any, list[Assignment]] = {}
    for assignment in all_assignments:
        by_machine.setdefault(assignment.work_center_id, []).append(assignment)
    for work_center_id, machine_assignments in by_machine.items():
        machine_assignments.sort(key=lambda assignment: assignment.start_time)
        for index in range(1, len(machine_assignments)):
            previous_operation = ops_by_id.get(machine_assignments[index - 1].operation_id)
            current_operation = ops_by_id.get(machine_assignments[index].operation_id)
            if previous_operation is None or current_operation is None:
                continue
            total_material_loss += dispatch_context.material_loss.get(
                (work_center_id, previous_operation.state_id, current_operation.state_id),
                0.0,
            )
    return total_material_loss
