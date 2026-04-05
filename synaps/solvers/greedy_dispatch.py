"""Greedy Dispatch solver — ATCS (Apparent Tardiness Cost with Setups) heuristic."""

from __future__ import annotations

import time
from datetime import timedelta
from math import log
from typing import Any

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


class GreedyDispatch(BaseSolver):
    """Single-pass priority dispatch using the ATCS composite index.

    ATCS(j) = (w_j / p_j) · exp(-max(d_j - p_j - t, 0) / (K1 · p̄))
                            · exp(-s_jk / (K2 · s̄))

    where:
        w_j = priority weight of operation j
        p_j = processing time of operation j
        d_j = due date of the parent order
        t   = current time
        K1  = tardiness look-ahead scaling (default 2.0)
        K2  = setup scaling (default 0.5)
        p̄   = mean processing time
        s̄   = mean setup time
    """

    def __init__(self, k1: float = 2.0, k2: float = 0.5, k3: float = 0.5) -> None:
        self._k1 = k1
        self._k2 = k2
        self._k3 = k3

    @property
    def name(self) -> str:
        return "greedy_dispatch"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()

        # Precompute lookup tables
        orders_by_id = {o.id: o for o in problem.orders}
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        dispatch_context = build_dispatch_context(problem)

        horizon_start = problem.planning_horizon_start

        # Build operation queue (respecting precedence)
        remaining = list(problem.operations)
        scheduled_ops: set[Any] = set()
        op_end_offsets: dict[Any, float] = {}
        assignments: list[Assignment] = []

        while remaining:
            # Filter to ready operations (predecessor scheduled or none)
            ready = [
                op
                for op in remaining
                if op.predecessor_op_id is None or op.predecessor_op_id in scheduled_ops
            ]
            if not ready:
                break  # deadlock — should not happen with valid input

            ready_p_bar = max(
                sum(op.base_duration_min for op in ready) / max(len(ready), 1),
                1.0,
            )
            candidate_records: list[dict[str, Any]] = []

            for op in ready:
                order = orders_by_id[op.order_id]
                due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
                w_j = order.priority / 500.0  # normalise around default priority
                pred_end = op_end_offsets.get(op.predecessor_op_id, 0.0)

                eligible = (
                    op.eligible_wc_ids
                    if op.eligible_wc_ids
                    else [work_center.id for work_center in problem.work_centers]
                )
                for wc_id in eligible:
                    slot = find_earliest_feasible_slot(
                        dispatch_context,
                        assignments,
                        op,
                        wc_id,
                        pred_end,
                    )
                    if slot is None:
                        continue

                    work_center = wc_by_id.get(wc_id)
                    speed = work_center.speed_factor if work_center is not None else 1.0
                    p_j = op.base_duration_min / speed

                    candidate_records.append(
                        {
                            "operation": op,
                            "work_center_id": wc_id,
                            "slot": slot,
                            "due_offset": due_offset,
                            "weight": w_j,
                            "processing_minutes": p_j,
                        }
                    )

            if not candidate_records:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                return ScheduleResult(
                    solver_name=self.name,
                    status=SolverStatus.ERROR,
                    assignments=assignments,
                    objective=ObjectiveValues(
                        makespan_minutes=max(
                            (
                                (assignment.end_time - horizon_start).total_seconds() / 60.0
                                for assignment in assignments
                            ),
                            default=0.0,
                        ),
                    ),
                    duration_ms=elapsed_ms,
                    metadata={"error": "no feasible constructive slot found"},
                )

            local_setup_scale_by_wc: dict[Any, float] = {}
            for wc_id in {record["work_center_id"] for record in candidate_records}:
                nonzero_machine_setups = [
                    record["slot"].setup_minutes
                    for record in candidate_records
                    if record["work_center_id"] == wc_id and record["slot"].setup_minutes > 0
                ]
                local_setup_scale_by_wc[wc_id] = max(
                    sum(nonzero_machine_setups) / max(len(nonzero_machine_setups), 1),
                    1.0,
                )
            global_nonzero_material_losses = [
                record["slot"].material_loss
                for record in candidate_records
                if record["slot"].material_loss > 0
            ]
            material_scale = max(
                sum(global_nonzero_material_losses) / max(len(global_nonzero_material_losses), 1),
                1.0,
            )

            best_log_score = float("-inf")
            best_record = candidate_records[0]
            for record in candidate_records:
                slot = record["slot"]
                p_j = record["processing_minutes"]
                slack = max(record["due_offset"] - p_j - slot.start_offset, 0.0)
                setup_scale = local_setup_scale_by_wc[record["work_center_id"]]
                setup_penalty = (
                    slot.setup_minutes / (self._k2 * setup_scale)
                    if slot.setup_minutes > 0
                    else 0.0
                )
                material_penalty = (
                    slot.material_loss / (self._k3 * material_scale)
                    if slot.material_loss > 0
                    else 0.0
                )

                # Compare in log-space to avoid exp() underflow on sparse or
                # heavy-tailed SDST matrices while preserving ATCS ranking.
                # Extended ATCS: material-loss penalty reduces the attractiveness
                # of transitions with equal setup time but higher material waste.
                log_score = (
                    log(max(record["weight"], 1e-9))
                    - log(max(p_j, 0.1))
                    - (slack / (self._k1 * ready_p_bar))
                    - setup_penalty
                    - material_penalty
                )
                if log_score > best_log_score:
                    best_log_score = log_score
                    best_record = record

            best_op = best_record["operation"]
            best_wc_id = best_record["work_center_id"]
            best_slot = best_record["slot"]

            # Assign best
            work_center = wc_by_id.get(best_wc_id)
            speed = work_center.speed_factor if work_center is not None else 1.0
            end_offset = best_slot.end_offset

            assignments.append(
                Assignment(
                    operation_id=best_op.id,
                    work_center_id=best_wc_id,
                    start_time=horizon_start + timedelta(minutes=best_slot.start_offset),
                    end_time=horizon_start + timedelta(minutes=end_offset),
                    setup_minutes=best_slot.setup_minutes,
                    aux_resource_ids=best_slot.aux_resource_ids,
                )
            )

            op_end_offsets[best_op.id] = end_offset
            scheduled_ops.add(best_op.id)
            remaining.remove(best_op)

        # Recompute per-assignment setup_minutes and aggregate total from the
        # final machine sequence — corrects ghost setups after gap insertions.
        total_setup = recompute_assignment_setups(assignments, dispatch_context)

        total_material_loss = 0.0
        assignments_by_machine: dict[Any, list[Assignment]] = {}
        for assignment in assignments:
            assignments_by_machine.setdefault(assignment.work_center_id, []).append(assignment)
        for work_center_id, machine_assignments in assignments_by_machine.items():
            machine_assignments.sort(key=lambda assignment: assignment.start_time)
            for index in range(1, len(machine_assignments)):
                previous_state = dispatch_context.ops_by_id[machine_assignments[index - 1].operation_id].state_id
                current_state = dispatch_context.ops_by_id[machine_assignments[index].operation_id].state_id
                total_material_loss += dispatch_context.material_loss.get(
                    (work_center_id, previous_state, current_state),
                    0.0,
                )

        # Compute per-order tardiness (last operation per order determines tardiness)
        order_completion: dict[Any, float] = {}
        for assignment in assignments:
            op = dispatch_context.ops_by_id[assignment.operation_id]
            end = (assignment.end_time - horizon_start).total_seconds() / 60.0
            if op.order_id not in order_completion or end > order_completion[op.order_id]:
                order_completion[op.order_id] = end

        total_tardiness = 0.0
        for order in problem.orders:
            completion = order_completion.get(order.id, 0.0)
            due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
            total_tardiness += max(completion - due_offset, 0.0)

        # Compute objective
        makespan = (
            max((a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments)
            if assignments
            else 0.0
        )

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        return ScheduleResult(
            solver_name=self.name,
            status=SolverStatus.FEASIBLE,
            assignments=assignments,
            objective=ObjectiveValues(
                makespan_minutes=makespan,
                total_setup_minutes=total_setup,
                total_material_loss=total_material_loss,
                total_tardiness_minutes=total_tardiness,
            ),
            duration_ms=elapsed_ms,
        )
