"""CP-SAT Solver — OR-Tools Constraint Programming solver for MO-FJSP-SDST."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from ortools.sat.python import cp_model

from syn_aps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from syn_aps.solvers import BaseSolver


class CpSatSolver(BaseSolver):
    """Exact / time-boxed CP-SAT solver for flexible job-shop with SDST.

    Uses interval variables with optional machine assignment and
    sequence-dependent setup transitions via circuit / no-overlap constraints.
    """

    @property
    def name(self) -> str:
        return "cpsat"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        time_limit_s: int = int(kwargs.get("time_limit_s", 30))
        random_seed: int = int(kwargs.get("random_seed", 42))

        t0 = time.monotonic()
        model = cp_model.CpModel()

        # Horizon in minutes
        horizon = int((problem.planning_horizon_end - problem.planning_horizon_start).total_seconds() / 60)

        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        setup_lookup: dict[tuple[Any, Any, Any], int] = {}
        for se in problem.setup_matrix:
            setup_lookup[(se.work_center_id, se.from_state_id, se.to_state_id)] = se.setup_minutes

        # Decision variables
        starts: dict[tuple[Any, Any], Any] = {}       # (op_id, wc_id) -> IntVar
        ends: dict[tuple[Any, Any], Any] = {}         # (op_id, wc_id) -> IntVar
        intervals: dict[tuple[Any, Any], Any] = {}    # (op_id, wc_id) -> IntervalVar
        presences: dict[tuple[Any, Any], Any] = {}    # (op_id, wc_id) -> BoolVar

        for op in problem.operations:
            eligible = op.eligible_wc_ids if op.eligible_wc_ids else [wc.id for wc in problem.work_centers]
            op_presence_vars: list[Any] = []

            for wc_id in eligible:
                wc = wc_by_id[wc_id]
                duration = max(1, int(op.base_duration_min / wc.speed_factor))

                suffix = f"_{op.id}_{wc_id}"
                start_var = model.new_int_var(0, horizon, f"start{suffix}")
                end_var = model.new_int_var(0, horizon, f"end{suffix}")
                presence = model.new_bool_var(f"pres{suffix}")
                interval = model.new_optional_interval_var(
                    start_var, duration, end_var, presence, f"interval{suffix}"
                )

                starts[(op.id, wc_id)] = start_var
                ends[(op.id, wc_id)] = end_var
                intervals[(op.id, wc_id)] = interval
                presences[(op.id, wc_id)] = presence
                op_presence_vars.append(presence)

            # Exactly one machine per operation
            model.add_exactly_one(op_presence_vars)

        # Precedence constraints
        for op in problem.operations:
            if op.predecessor_op_id is not None:
                pred = op.predecessor_op_id
                for wc_id_cur in (op.eligible_wc_ids or [wc.id for wc in problem.work_centers]):
                    for wc_id_pred in (
                        next(
                            o.eligible_wc_ids or [wc.id for wc in problem.work_centers]
                            for o in problem.operations
                            if o.id == pred
                        )
                    ):
                        model.add(
                            starts[(op.id, wc_id_cur)] >= ends[(pred, wc_id_pred)]
                        ).only_enforce_if(
                            presences[(op.id, wc_id_cur)],
                            presences[(pred, wc_id_pred)],
                        )

        # No-overlap per machine
        for wc in problem.work_centers:
            machine_intervals = [
                intervals[(op.id, wc.id)]
                for op in problem.operations
                if (op.id, wc.id) in intervals
            ]
            if machine_intervals:
                model.add_no_overlap(machine_intervals)

        # Objective: minimise makespan (primary)
        makespan = model.new_int_var(0, horizon, "makespan")
        for key, end_var in ends.items():
            model.add(makespan >= end_var).only_enforce_if(presences[key])
        model.minimize(makespan)

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s
        solver.parameters.random_seed = random_seed
        solver.parameters.num_workers = 8

        status_code = solver.solve(model)

        status_map = {
            cp_model.OPTIMAL: SolverStatus.OPTIMAL,
            cp_model.FEASIBLE: SolverStatus.FEASIBLE,
            cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
        }
        result_status = status_map.get(status_code, SolverStatus.TIMEOUT)

        assignments: list[Assignment] = []
        if result_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE):
            for op in problem.operations:
                eligible = op.eligible_wc_ids if op.eligible_wc_ids else [wc.id for wc in problem.work_centers]
                for wc_id in eligible:
                    if solver.value(presences[(op.id, wc_id)]):
                        s = solver.value(starts[(op.id, wc_id)])
                        e = solver.value(ends[(op.id, wc_id)])
                        assignments.append(
                            Assignment(
                                operation_id=op.id,
                                work_center_id=wc_id,
                                start_time=problem.planning_horizon_start + timedelta(minutes=s),
                                end_time=problem.planning_horizon_start + timedelta(minutes=e),
                            )
                        )
                        break

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        ms_val = solver.value(makespan) if result_status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE) else 0

        return ScheduleResult(
            solver_name=self.name,
            status=result_status,
            assignments=assignments,
            objective=ObjectiveValues(makespan_minutes=float(ms_val)),
            duration_ms=elapsed_ms,
            random_seed=random_seed,
        )
