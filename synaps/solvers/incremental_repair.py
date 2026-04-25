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
from synaps.solvers import BaseSolver
from synaps.solvers._dispatch_support import (
    MachineIndex,
    build_dispatch_context,
    find_earliest_feasible_slot,
    recompute_assignment_setups,
)

if TYPE_CHECKING:
    from uuid import UUID


class IncrementalRepair(BaseSolver):
    """Repair a disrupted schedule by re-dispatching operations within a
    configurable neighbourhood radius, keeping all other assignments frozen.

    Radius policy:
        BREAKDOWN  → 2 × setup_count downstream
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
        """Use a micro CP-SAT solve when constructive repair cannot place the remainder."""
        from synaps.solvers.cpsat_solver import CpSatSolver

        ops_by_id = {operation.id: operation for operation in problem.operations}
        op_positions = {operation.id: index for index, operation in enumerate(problem.operations)}
        needed_ids = set(remaining_op_ids)
        for op_id in sorted(remaining_op_ids, key=op_positions.__getitem__):
            operation = ops_by_id.get(op_id)
            if operation and operation.predecessor_op_id:
                needed_ids.add(operation.predecessor_op_id)

        sub_operations = [
            operation for operation in problem.operations if operation.id in needed_ids
        ]
        if not sub_operations:
            return None

        sub_problem = ScheduleProblem(
            states=problem.states,
            orders=problem.orders,
            operations=sub_operations,
            work_centers=problem.work_centers,
            setup_matrix=problem.setup_matrix,
            auxiliary_resources=problem.auxiliary_resources,
            aux_requirements=[
                requirement
                for requirement in problem.aux_requirements
                if requirement.operation_id in needed_ids
            ],
            planning_horizon_start=problem.planning_horizon_start,
            planning_horizon_end=problem.planning_horizon_end,
        )

        result = CpSatSolver().solve(
            sub_problem,
            time_limit_s=5,
            num_workers=max(1, int(num_workers)),
            auto_greedy_warm_start=False,
            enable_symmetry_breaking=False,
        )

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
        fallback_assignments.sort(key=lambda assignment: op_positions[assignment.operation_id])
        return fallback_assignments

    @property
    def name(self) -> str:
        return "incremental_repair"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
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

        orders_by_id = {o.id: o for o in problem.orders}
        ops_by_id = {op.id: op for op in problem.operations}
        op_positions = {op.id: index for index, op in enumerate(problem.operations)}
        dispatch_context = build_dispatch_context(problem)

        # Identify neighbourhood: disrupted ops + `radius` downstream successors
        neighbourhood: set[Any] = set(disrupted_op_ids)
        for _ in range(radius):
            new_layer: set[Any] = set()
            for op in problem.operations:
                if op.predecessor_op_id in neighbourhood and op.id not in neighbourhood:
                    new_layer.add(op.id)
            if not new_layer:
                break
            neighbourhood.update(new_layer)

        # Separate frozen vs. repaired assignments
        frozen = [a for a in base_assignments if a.operation_id not in neighbourhood]
        to_repair = [
            ops_by_id[operation_id]
            for operation_id in sorted(neighbourhood, key=op_positions.__getitem__)
            if operation_id in ops_by_id
        ]
        horizon_start = problem.planning_horizon_start
        used_cpsat_fallback = False

        repaired: list[Assignment] = []
        scheduled_ids: set[Any] = {a.operation_id for a in frozen}
        scheduled_by_op: dict[Any, Assignment] = {assignment.operation_id: assignment for assignment in frozen}
        machine_idx = MachineIndex(dispatch_context)
        for assignment in frozen:
            machine_idx.add(assignment)
        # Sort by descending priority first (higher priority = more urgent),
        # then by sequence within order for stable tie-breaking.
        remaining_repair = sorted(
            to_repair,
            key=lambda operation: (
                -orders_by_id[operation.order_id].priority,
                operation.seq_in_order,
                op_positions[operation.id],
            ),
        )

        while remaining_repair:
            ready = [
                operation
                for operation in remaining_repair
                if operation.predecessor_op_id is None
                or operation.predecessor_op_id in scheduled_ids
            ]
            if not ready:
                break

            best_candidate: (
                tuple[
                    int,
                    float,
                    float,
                    float,
                    int,
                    int,
                    str,
                    Operation,
                    UUID,
                    Any,
                ]
                | None
            ) = None
            scheduled_assignments = frozen + repaired

            for operation in ready:
                predecessor_end = 0.0
                if operation.predecessor_op_id is not None:
                    predecessor_assignment = scheduled_by_op.get(operation.predecessor_op_id)
                    if predecessor_assignment is not None:
                        predecessor_end = (
                            predecessor_assignment.end_time - horizon_start
                        ).total_seconds() / 60.0

                eligible = (
                    operation.eligible_wc_ids
                    if operation.eligible_wc_ids
                    else [work_center.id for work_center in problem.work_centers]
                )
                for work_center_id in eligible:
                    slot = find_earliest_feasible_slot(
                        dispatch_context,
                        scheduled_assignments,
                        operation,
                        work_center_id,
                        predecessor_end,
                        machine_index=machine_idx,
                    )
                    if slot is None:
                        continue
                    # Priority-aware candidate key: high-priority operations (higher number)
                    # are preferred even if they start later.  Negative priority ensures
                    # descending sort.  Within the same priority class, prefer earlier
                    # end_offset to minimise makespan impact, then lower material loss.
                    op_priority = orders_by_id[operation.order_id].priority
                    candidate_key = (
                        -op_priority,
                        slot.end_offset,
                        slot.material_loss,
                        slot.start_offset,
                        operation.seq_in_order,
                        op_positions[operation.id],
                        str(work_center_id),
                    )
                    if best_candidate is None or candidate_key < best_candidate[:7]:
                        best_candidate = (
                            -op_priority,
                            slot.end_offset,
                            slot.material_loss,
                            slot.start_offset,
                            operation.seq_in_order,
                            op_positions[operation.id],
                            str(work_center_id),
                            operation,
                            work_center_id,
                            slot,
                        )

            if best_candidate is None:
                remaining_ids = {operation.id for operation in remaining_repair}
                cpsat_result = self._cpsat_fallback(
                    problem,
                    frozen + repaired,
                    remaining_ids,
                    scheduled_ids,
                    num_workers=cpsat_fallback_num_workers,
                )
                if cpsat_result is not None:
                    repaired.extend(cpsat_result)
                    scheduled_ids.update(assignment.operation_id for assignment in cpsat_result)
                    remaining_repair.clear()
                    used_cpsat_fallback = True
                break

            _, _, _, _, _, _, _, operation, work_center_id, slot = best_candidate
            repaired.append(
                Assignment(
                    operation_id=operation.id,
                    work_center_id=work_center_id,
                    start_time=horizon_start + timedelta(minutes=slot.start_offset),
                    end_time=horizon_start + timedelta(minutes=slot.end_offset),
                    setup_minutes=slot.setup_minutes,
                    aux_resource_ids=slot.aux_resource_ids,
                )
            )
            scheduled_by_op[operation.id] = repaired[-1]
            machine_idx.add(repaired[-1])
            scheduled_ids.add(operation.id)
            remaining_repair.remove(operation)

        all_assignments = frozen + repaired

        # Recompute per-assignment setup_minutes from the final machine
        # sequence — prevents ghost setups when a repaired op is inserted
        # between two frozen ops.
        total_setup = recompute_assignment_setups(all_assignments, dispatch_context)

        total_material_loss = 0.0
        by_machine: dict[Any, list[Assignment]] = {}
        for assignment in all_assignments:
            by_machine.setdefault(assignment.work_center_id, []).append(assignment)
        for work_center_id, machine_assignments in by_machine.items():
            machine_assignments.sort(key=lambda assignment: assignment.start_time)
            for index in range(1, len(machine_assignments)):
                previous_operation = ops_by_id.get(
                    machine_assignments[index - 1].operation_id
                )
                current_operation = ops_by_id.get(machine_assignments[index].operation_id)
                if previous_operation is None or current_operation is None:
                    continue
                previous_state = previous_operation.state_id
                current_state = current_operation.state_id
                total_material_loss += dispatch_context.material_loss.get(
                    (work_center_id, previous_state, current_state),
                    0.0,
                )

        makespan = (
            max((a.end_time - horizon_start).total_seconds() / 60.0 for a in all_assignments)
            if all_assignments
            else 0.0
        )

        # Per-order tardiness
        order_completion: dict[Any, float] = {}
        for a in all_assignments:
            assigned_operation = ops_by_id.get(a.operation_id)
            if assigned_operation is None:
                continue
            end = (a.end_time - horizon_start).total_seconds() / 60.0
            if (
                assigned_operation.order_id not in order_completion
                or end > order_completion[assigned_operation.order_id]
            ):
                order_completion[assigned_operation.order_id] = end

        total_tardiness = 0.0
        for order in problem.orders:
            completion = order_completion.get(order.id, 0.0)
            due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
            total_tardiness += max(completion - due_offset, 0.0)

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        return ScheduleResult(
            solver_name=self.name,
            status=SolverStatus.FEASIBLE,
            assignments=all_assignments,
            objective=ObjectiveValues(
                makespan_minutes=makespan,
                total_setup_minutes=total_setup,
                total_material_loss=total_material_loss,
                total_tardiness_minutes=total_tardiness,
            ),
            duration_ms=elapsed_ms,
            metadata={
                "neighbourhood_size": len(neighbourhood),
                "frozen_count": len(frozen),
                "repaired_count": len(repaired),
                "cpsat_fallback_num_workers": cpsat_fallback_num_workers,
                "used_cpsat_fallback": used_cpsat_fallback,
            },
        )
