"""Incremental Repair Engine — localised neighbourhood repair for schedule disruptions."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, cast

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
    find_earliest_feasible_slot,
    recompute_assignment_setups,
)


class IncrementalRepair(BaseSolver):
    """Repair a disrupted schedule by re-dispatching operations within a
    configurable neighbourhood radius, keeping all other assignments frozen.

    Radius policy:
        BREAKDOWN  → 2 × setup_count downstream
        RUSH_ORDER → affected machine ± 30 min window
        MATERIAL   → same state group
        DEFAULT    → 5 operations forward
    """

    @property
    def name(self) -> str:
        return "incremental_repair"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()

        # Required kwargs
        base_assignments = cast("list[Assignment]", kwargs.get("base_assignments", []))
        disrupted_op_ids = set(cast("list[Any]", kwargs.get("disrupted_op_ids", [])))
        radius: int = int(kwargs.get("radius", 5))

        if not base_assignments:
            return ScheduleResult(
                solver_name=self.name,
                status=SolverStatus.ERROR,
                metadata={"error": "base_assignments required"},
            )

        orders_by_id = {o.id: o for o in problem.orders}
        ops_by_id = {op.id: op for op in problem.operations}
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
        to_repair = [ops_by_id[oid] for oid in neighbourhood if oid in ops_by_id]
        horizon_start = problem.planning_horizon_start

        repaired: list[Assignment] = []
        scheduled_ids: set[Any] = {a.operation_id for a in frozen}
        # Sort by descending priority first (higher priority = more urgent),
        # then by sequence within order for stable tie-breaking.
        remaining_repair = sorted(
            to_repair,
            key=lambda operation: (-orders_by_id[operation.order_id].priority, operation.seq_in_order),
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

            best_candidate: tuple[float, Any, Any, Any] | None = None
            scheduled_assignments = frozen + repaired

            for operation in ready:
                predecessor_end = 0.0
                if operation.predecessor_op_id is not None:
                    for assignment in scheduled_assignments:
                        if assignment.operation_id == operation.predecessor_op_id:
                            predecessor_end = (
                                assignment.end_time - horizon_start
                            ).total_seconds() / 60.0
                            break

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
                    )
                    if slot is None:
                        continue
                    # Priority-aware candidate key: high-priority operations (higher number)
                    # are preferred even if they start later.  Negative priority ensures
                    # descending sort.  Within the same priority class, prefer earlier
                    # end_offset to minimise makespan impact.
                    op_priority = orders_by_id[operation.order_id].priority
                    candidate_key = (-op_priority, slot.end_offset, slot.start_offset, operation.seq_in_order)
                    if best_candidate is None or candidate_key < best_candidate[:4]:
                        best_candidate = (-op_priority, slot.end_offset, slot.start_offset, operation, work_center_id, slot)

            if best_candidate is None:
                break

            _, _, _, operation, work_center_id, slot = best_candidate
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
            scheduled_ids.add(operation.id)
            remaining_repair.remove(operation)

        all_assignments = frozen + repaired

        # Recompute per-assignment setup_minutes from the final machine
        # sequence — prevents ghost setups when a repaired op is inserted
        # between two frozen ops.
        total_setup = recompute_assignment_setups(all_assignments, dispatch_context)

        makespan = max(
            (a.end_time - horizon_start).total_seconds() / 60.0 for a in all_assignments
        ) if all_assignments else 0.0

        # Per-order tardiness
        order_completion: dict[Any, float] = {}
        for a in all_assignments:
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

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        return ScheduleResult(
            solver_name=self.name,
            status=SolverStatus.FEASIBLE,
            assignments=all_assignments,
            objective=ObjectiveValues(
                makespan_minutes=makespan,
                total_setup_minutes=total_setup,
                total_tardiness_minutes=total_tardiness,
            ),
            duration_ms=elapsed_ms,
            metadata={
                "neighbourhood_size": len(neighbourhood),
                "frozen_count": len(frozen),
                "repaired_count": len(repaired),
            },
        )
