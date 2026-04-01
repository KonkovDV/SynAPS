"""Incremental Repair Engine — localised neighbourhood repair for schedule disruptions."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any, cast

from syn_aps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from syn_aps.solvers import BaseSolver


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
        base_assignments = cast(list[Assignment], kwargs.get("base_assignments", []))
        disrupted_op_ids = set(cast(list[Any], kwargs.get("disrupted_op_ids", [])))
        radius: int = int(kwargs.get("radius", 5))

        if not base_assignments:
            return ScheduleResult(
                solver_name=self.name,
                status=SolverStatus.ERROR,
                metadata={"error": "base_assignments required"},
            )

        orders_by_id = {o.id: o for o in problem.orders}
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        ops_by_id = {op.id: op for op in problem.operations}

        # Identify neighbourhood: disrupted ops + `radius` downstream successors
        neighbourhood: set[Any] = set(disrupted_op_ids)
        for _ in range(radius):
            for op in problem.operations:
                if op.predecessor_op_id in neighbourhood:
                    neighbourhood.add(op.id)

        # Separate frozen vs. repaired assignments
        frozen = [a for a in base_assignments if a.operation_id not in neighbourhood]
        to_repair = [ops_by_id[oid] for oid in neighbourhood if oid in ops_by_id]

        # Build WC availability from frozen assignments
        wc_available: dict[Any, float] = {}
        horizon_start = problem.planning_horizon_start
        for a in frozen:
            end_offset = (a.end_time - horizon_start).total_seconds() / 60.0
            cur = wc_available.get(a.work_center_id, 0.0)
            wc_available[a.work_center_id] = max(cur, end_offset)

        for wc in problem.work_centers:
            wc_available.setdefault(wc.id, 0.0)

        # Simple greedy re-dispatch of neighbourhood ops
        to_repair.sort(key=lambda op: (op.seq_in_order, orders_by_id[op.order_id].priority))
        repaired: list[Assignment] = []
        scheduled_ids: set[Any] = {a.operation_id for a in frozen}

        for op in to_repair:
            # Wait for predecessor
            pred_end = 0.0
            if op.predecessor_op_id:
                for a in frozen + repaired:
                    if a.operation_id == op.predecessor_op_id:
                        pred_end = (a.end_time - horizon_start).total_seconds() / 60.0
                        break

            eligible = op.eligible_wc_ids if op.eligible_wc_ids else list(wc_available.keys())
            best_end = float("inf")
            best_assignment = None

            for wc_id in eligible:
                work_center = wc_by_id.get(wc_id)
                speed = work_center.speed_factor if work_center is not None else 1.0
                start = max(wc_available.get(wc_id, 0.0), pred_end)
                duration = op.base_duration_min / speed
                end = start + duration

                if end < best_end:
                    best_end = end
                    best_assignment = Assignment(
                        operation_id=op.id,
                        work_center_id=wc_id,
                        start_time=horizon_start + timedelta(minutes=start),
                        end_time=horizon_start + timedelta(minutes=end),
                    )

            if best_assignment:
                repaired.append(best_assignment)
                wc_available[best_assignment.work_center_id] = (
                    best_assignment.end_time - horizon_start
                ).total_seconds() / 60.0
                scheduled_ids.add(op.id)

        all_assignments = frozen + repaired
        makespan = max(
            (a.end_time - horizon_start).total_seconds() / 60.0 for a in all_assignments
        ) if all_assignments else 0.0

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        return ScheduleResult(
            solver_name=self.name,
            status=SolverStatus.FEASIBLE,
            assignments=all_assignments,
            objective=ObjectiveValues(makespan_minutes=makespan),
            duration_ms=elapsed_ms,
            metadata={
                "neighbourhood_size": len(neighbourhood),
                "frozen_count": len(frozen),
                "repaired_count": len(repaired),
            },
        )
