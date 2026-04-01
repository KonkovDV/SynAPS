"""Greedy Dispatch solver — ATCS (Apparent Tardiness Cost with Setups) heuristic."""

from __future__ import annotations

import time
from datetime import timedelta
from math import exp
from typing import Any

from syn_aps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from syn_aps.solvers import BaseSolver


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

    def __init__(self, k1: float = 2.0, k2: float = 0.5) -> None:
        self._k1 = k1
        self._k2 = k2

    @property
    def name(self) -> str:
        return "greedy_dispatch"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()

        # Precompute lookup tables
        orders_by_id = {o.id: o for o in problem.orders}
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        setup_lookup: dict[tuple[Any, Any, Any], int] = {}
        for se in problem.setup_matrix:
            setup_lookup[(se.work_center_id, se.from_state_id, se.to_state_id)] = se.setup_minutes

        # Mean processing & setup times for ATCS normalisation
        p_bar = max(
            sum(op.base_duration_min for op in problem.operations) / max(len(problem.operations), 1),
            1.0,
        )
        s_bar = max(
            sum(se.setup_minutes for se in problem.setup_matrix) / max(len(problem.setup_matrix), 1),
            1.0,
        )

        # Work center state tracking: (available_time, last_state_id)
        wc_state: dict[Any, tuple[float, Any]] = {}
        horizon_start = problem.planning_horizon_start
        for wc in problem.work_centers:
            wc_state[wc.id] = (0.0, None)  # offset in minutes from horizon_start

        # Build operation queue (respecting precedence)
        remaining = list(problem.operations)
        scheduled_ops: set[Any] = set()
        op_end_offsets: dict[Any, float] = {}
        assignments: list[Assignment] = []
        total_setup = 0.0
        total_tardiness = 0.0

        while remaining:
            # Filter to ready operations (predecessor scheduled or none)
            ready = [
                op
                for op in remaining
                if op.predecessor_op_id is None or op.predecessor_op_id in scheduled_ops
            ]
            if not ready:
                break  # deadlock — should not happen with valid input

            best_score = -1.0
            best_op = ready[0]
            best_wc_id = ready[0].eligible_wc_ids[0] if ready[0].eligible_wc_ids else problem.work_centers[0].id
            best_start = 0.0
            best_setup = 0

            for op in ready:
                order = orders_by_id[op.order_id]
                due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
                w_j = order.priority / 500.0  # normalise around default priority
                pred_end = op_end_offsets.get(op.predecessor_op_id, 0.0)

                eligible = op.eligible_wc_ids if op.eligible_wc_ids else [wc.id for wc in problem.work_centers]
                for wc_id in eligible:
                    avail, last_state = wc_state[wc_id]
                    work_center = wc_by_id.get(wc_id)
                    speed = work_center.speed_factor if work_center is not None else 1.0
                    p_j = op.base_duration_min / speed

                    s_jk = setup_lookup.get((wc_id, last_state, op.state_id), 0) if last_state else 0
                    start = max(avail + s_jk, pred_end)

                    # ATCS index
                    slack = max(due_offset - p_j - start, 0.0)
                    tardiness_factor = exp(-slack / (self._k1 * p_bar))
                    setup_factor = exp(-s_jk / (self._k2 * s_bar)) if s_jk > 0 else 1.0
                    score = (w_j / max(p_j, 0.1)) * tardiness_factor * setup_factor

                    if score > best_score:
                        best_score = score
                        best_op = op
                        best_wc_id = wc_id
                        best_start = start
                        best_setup = s_jk

            # Assign best
            work_center = wc_by_id.get(best_wc_id)
            speed = work_center.speed_factor if work_center is not None else 1.0
            duration = best_op.base_duration_min / speed
            end_offset = best_start + duration

            assignments.append(
                Assignment(
                    operation_id=best_op.id,
                    work_center_id=best_wc_id,
                    start_time=horizon_start + timedelta(minutes=best_start),
                    end_time=horizon_start + timedelta(minutes=end_offset),
                    setup_minutes=best_setup,
                )
            )

            wc_state[best_wc_id] = (end_offset, best_op.state_id)
            op_end_offsets[best_op.id] = end_offset
            scheduled_ops.add(best_op.id)
            remaining.remove(best_op)
            total_setup += best_setup

            # Tardiness
            order = orders_by_id[best_op.order_id]
            due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
            tardiness = max(end_offset - due_offset, 0.0)
            total_tardiness += tardiness

        # Compute objective
        makespan = max((a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments) if assignments else 0.0

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        return ScheduleResult(
            solver_name=self.name,
            status=SolverStatus.FEASIBLE,
            assignments=assignments,
            objective=ObjectiveValues(
                makespan_minutes=makespan,
                total_setup_minutes=total_setup,
                total_tardiness_minutes=total_tardiness,
            ),
            duration_ms=elapsed_ms,
        )
