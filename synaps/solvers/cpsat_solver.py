"""CP-SAT Solver — OR-Tools Constraint Programming solver for MO-FJSP-SDST."""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from ortools.sat.python import cp_model

from synaps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from synaps.solvers import BaseSolver


class CpSatSolver(BaseSolver):
    """Exact / time-boxed CP-SAT solver for flexible job-shop with SDST."""

    @property
    def name(self) -> str:
        return "cpsat"

    def _add_machine_order_and_adjacency(
        self,
        model: cp_model.CpModel,
        problem: ScheduleProblem,
        starts: dict[tuple[Any, Any], Any],
        ends: dict[tuple[Any, Any], Any],
        intervals: dict[tuple[Any, Any], Any],
        presences: dict[tuple[Any, Any], Any],
        setup_minutes_lookup: dict[tuple[Any, Any, Any], int],
        setup_material_lookup: dict[tuple[Any, Any, Any], int],
    ) -> tuple[list[Any], list[Any]]:
        """Model SDST via AddCircuit (O(N²) arcs per machine, not O(N³) booleans).

        Uses a virtual depot node per machine.  Self-loops model absent operations.
        Arc literals carry both the setup-time implication and the objective terms.

        Returns (setup_terms, material_terms, setup_intervals_by_op) where
        setup_intervals_by_op maps operation_id to a list of (optional_interval, arc_literal)
        for setup periods preceding that operation.  These are later included in
        auxiliary resource cumulative constraints.
        """
        setup_terms: list[Any] = []
        material_terms: list[Any] = []
        # Maps operation_id → [(setup_interval, arc_literal)] for aux resource tracking
        setup_intervals_by_op: dict[Any, list[tuple[Any, Any]]] = {}

        for work_center in problem.work_centers:
            machine_operations = [
                operation
                for operation in problem.operations
                if (operation.id, work_center.id) in intervals
            ]
            if not machine_operations:
                continue

            model.add_no_overlap(
                [intervals[(operation.id, work_center.id)] for operation in machine_operations]
            )

            n = len(machine_operations)
            op_index: dict[Any, int] = {op.id: idx for idx, op in enumerate(machine_operations)}
            depot = n  # virtual depot node

            arcs: list[tuple[int, int, Any]] = []

            # Depot → operation (operation is first on machine)
            for operation in machine_operations:
                lit = model.new_bool_var(f"arc_depot_{operation.id}_{work_center.id}")
                arcs.append((depot, op_index[operation.id], lit))
                model.add_implication(lit, presences[(operation.id, work_center.id)])

            # Operation → depot (operation is last on machine)
            for operation in machine_operations:
                lit = model.new_bool_var(f"arc_{operation.id}_depot_{work_center.id}")
                arcs.append((op_index[operation.id], depot, lit))
                model.add_implication(lit, presences[(operation.id, work_center.id)])

            # Operation → operation arcs (j directly follows i)
            for op_i in machine_operations:
                for op_j in machine_operations:
                    if op_i.id == op_j.id:
                        continue

                    lit = model.new_bool_var(
                        f"arc_{op_i.id}_{op_j.id}_{work_center.id}"
                    )
                    arcs.append((op_index[op_i.id], op_index[op_j.id], lit))

                    model.add_implication(lit, presences[(op_i.id, work_center.id)])
                    model.add_implication(lit, presences[(op_j.id, work_center.id)])

                    # Timing: j starts after i ends + setup from state(i) → state(j)
                    setup_minutes = setup_minutes_lookup.get(
                        (work_center.id, op_i.state_id, op_j.state_id), 0
                    )
                    model.add(
                        starts[(op_j.id, work_center.id)]
                        >= ends[(op_i.id, work_center.id)] + setup_minutes
                    ).only_enforce_if(lit)

                    if setup_minutes:
                        setup_terms.append(setup_minutes * lit)

                        # Create optional setup interval [end_i, start_j] for aux resource tracking
                        setup_start = ends[(op_i.id, work_center.id)]
                        setup_end = starts[(op_j.id, work_center.id)]
                        setup_interval = model.new_optional_interval_var(
                            setup_start,
                            setup_minutes,
                            setup_end,
                            lit,
                            f"setup_interval_{op_i.id}_{op_j.id}_{work_center.id}",
                        )
                        setup_intervals_by_op.setdefault(op_j.id, []).append(
                            (setup_interval, lit)
                        )

                    material_loss = setup_material_lookup.get(
                        (work_center.id, op_i.state_id, op_j.state_id), 0
                    )
                    if material_loss:
                        material_terms.append(material_loss * lit)

            # Self-loops for absent operations (not assigned to this machine)
            for operation in machine_operations:
                absent = presences[(operation.id, work_center.id)].negated()
                arcs.append((op_index[operation.id], op_index[operation.id], absent))

            # Self-loop for depot when machine is completely unused
            machine_presences = [
                presences[(operation.id, work_center.id)] for operation in machine_operations
            ]
            unused = model.new_bool_var(f"unused_{work_center.id}")
            model.add(sum(machine_presences) == 0).only_enforce_if(unused)
            model.add(sum(machine_presences) >= 1).only_enforce_if(unused.negated())
            arcs.append((depot, depot, unused))

            model.add_circuit(arcs)

        return setup_terms, material_terms, setup_intervals_by_op

    def _add_aux_resource_cumulative_constraints(
        self,
        model: cp_model.CpModel,
        problem: ScheduleProblem,
        eligible_by_op: dict[Any, list[Any]],
        intervals: dict[tuple[Any, Any], Any],
        setup_intervals_by_op: dict[Any, list[tuple[Any, Any]]],
    ) -> None:
        requirements_by_op: dict[Any, list[Any]] = {}
        for requirement in problem.aux_requirements:
            requirements_by_op.setdefault(requirement.operation_id, []).append(requirement)

        for resource in problem.auxiliary_resources:
            resource_intervals: list[Any] = []
            demands: list[int] = []
            for operation in problem.operations:
                demand = sum(
                    requirement.quantity_needed
                    for requirement in requirements_by_op.get(operation.id, [])
                    if requirement.aux_resource_id == resource.id
                )
                if demand <= 0:
                    continue
                # Processing intervals
                for work_center_id in eligible_by_op[operation.id]:
                    resource_intervals.append(intervals[(operation.id, work_center_id)])
                    demands.append(demand)

                # Setup intervals preceding this operation also reserve the resource
                for setup_interval, _arc_lit in setup_intervals_by_op.get(operation.id, []):
                    resource_intervals.append(setup_interval)
                    demands.append(demand)

            if resource_intervals:
                model.add_cumulative(resource_intervals, demands, resource.pool_size)

    def _build_weighted_objective(
        self,
        model: cp_model.CpModel,
        problem: ScheduleProblem,
        horizon: int,
        makespan: Any,
        setup_terms: list[Any],
        material_terms: list[Any],
        selected_ends: dict[Any, Any],
        objective_weights: dict[str, int],
        material_loss_scale: int,
        epsilon_constraints: dict[str, int] | None = None,
        objective_mode: str = "weighted_sum",
        primary_objective: str = "makespan",
    ) -> tuple[Any, Any, Any, int, dict[str, int], int]:
        max_setup = max((entry.setup_minutes for entry in problem.setup_matrix), default=0)
        max_material_scaled = max(
            (int(round(entry.material_loss * material_loss_scale)) for entry in problem.setup_matrix),
            default=0,
        )

        setup_ub = max(1, max_setup * max(len(problem.operations), 1))
        material_ub = max(1, max_material_scaled * max(len(problem.operations), 1))

        total_setup = model.new_int_var(0, setup_ub, "total_setup_minutes")
        total_material_scaled = model.new_int_var(0, material_ub, "total_material_loss_scaled")
        if setup_terms:
            model.add(total_setup == sum(setup_terms))
        else:
            model.add(total_setup == 0)
        if material_terms:
            model.add(total_material_scaled == sum(material_terms))
        else:
            model.add(total_material_scaled == 0)

        due_offsets = {
            order.id: int(
                (order.due_date - problem.planning_horizon_start).total_seconds() / 60.0
            )
            for order in problem.orders
        }

        tardiness_terms: list[Any] = []
        tardiness_ub = 0
        for order in problem.orders:
            order_operations = [operation for operation in problem.operations if operation.order_id == order.id]
            completion = model.new_int_var(0, horizon, f"completion_{order.id}")
            for operation in order_operations:
                model.add(completion >= selected_ends[operation.id])

            due_offset = due_offsets[order.id]
            order_tardiness_ub = max(0, horizon + max(0, -due_offset))
            tardiness = model.new_int_var(0, order_tardiness_ub, f"tardiness_{order.id}")
            model.add(tardiness >= completion - due_offset)
            tardiness_terms.append(tardiness)
            tardiness_ub += order_tardiness_ub

        total_tardiness = model.new_int_var(0, max(1, tardiness_ub), "total_tardiness_minutes")
        if tardiness_terms:
            model.add(total_tardiness == sum(tardiness_terms))
        else:
            model.add(total_tardiness == 0)

        weights = {
            "setup": int(objective_weights.get("setup", 1)),
            "material_loss": int(objective_weights.get("material_loss", 1)),
            "tardiness": int(objective_weights.get("tardiness", 1)),
        }
        secondary_bound = (
            weights["setup"] * setup_ub
            + weights["material_loss"] * material_ub
            + weights["tardiness"] * max(1, tardiness_ub)
            + 1
        )

        if epsilon_constraints:
            # ε-constraint scalarization (Geoffrion 1968 / Haimes et al. 1971):
            # constrain a subset of objectives and optimise a selected primary
            # objective directly.  This reaches Pareto regions that a pure
            # weighted-sum scalarization may miss in discrete spaces.
            if "max_makespan_minutes" in epsilon_constraints:
                model.add(makespan <= int(epsilon_constraints["max_makespan_minutes"]))
            if "max_setup_minutes" in epsilon_constraints:
                model.add(total_setup <= int(epsilon_constraints["max_setup_minutes"]))
            if "max_tardiness_minutes" in epsilon_constraints:
                model.add(total_tardiness <= int(epsilon_constraints["max_tardiness_minutes"]))
            if "max_material_loss_scaled" in epsilon_constraints:
                model.add(total_material_scaled <= int(epsilon_constraints["max_material_loss_scaled"]))
        
        if objective_mode == "epsilon_primary":
            objective_targets = {
                "makespan": makespan,
                "setup": total_setup,
                "material_loss": total_material_scaled,
                "tardiness": total_tardiness,
            }
            objective_bounds = {
                "makespan": horizon,
                "setup": setup_ub,
                "material_loss": material_ub,
                "tardiness": max(1, tardiness_ub),
            }
            try:
                primary_target = objective_targets[primary_objective]
            except KeyError as exc:
                supported = ", ".join(sorted(objective_targets))
                raise ValueError(
                    f"Unsupported primary_objective '{primary_objective}'. Expected one of: {supported}"
                ) from exc

            if primary_objective == "makespan":
                model.minimize(primary_target)
            else:
                # Lexicographic tie-break inside the selected Pareto slice:
                # once the primary objective is minimized, prefer the shortest
                # makespan still satisfying the epsilon caps.
                makespan_bound = objective_bounds["makespan"] + 1
                model.minimize(primary_target * makespan_bound + makespan)
        elif epsilon_constraints:
            model.minimize(makespan)
        else:
            # Default: hierarchical weighted-sum with makespan as primary
            model.minimize(
                makespan * secondary_bound
                + weights["setup"] * total_setup
                + weights["material_loss"] * total_material_scaled
                + weights["tardiness"] * total_tardiness
            )

        return total_setup, total_material_scaled, total_tardiness, secondary_bound, weights, material_loss_scale

    def _extract_solution_and_objective(
        self,
        problem: ScheduleProblem,
        solver: cp_model.CpSolver,
        result_status: SolverStatus,
        eligible_by_op: dict[Any, list[Any]],
        starts: dict[tuple[Any, Any], Any],
        ends: dict[tuple[Any, Any], Any],
        presences: dict[tuple[Any, Any], Any],
        makespan: Any,
        total_setup: Any,
        total_material_scaled: Any,
        total_tardiness: Any,
        weights: dict[str, int],
        material_loss_scale: int,
        secondary_bound: int,
    ) -> tuple[list[Assignment], ObjectiveValues, dict[str, Any]]:
        assignments: list[Assignment] = []
        metadata: dict[str, Any] = {
            "objective_weights": weights,
            "material_loss_scale": material_loss_scale,
            "makespan_secondary_bound": secondary_bound,
        }
        objective = ObjectiveValues()

        if result_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            requirements_by_op: dict[Any, list[Any]] = {}
            for requirement in problem.aux_requirements:
                requirements_by_op.setdefault(requirement.operation_id, []).append(requirement)

            for operation in problem.operations:
                for work_center_id in eligible_by_op[operation.id]:
                    if not solver.value(presences[(operation.id, work_center_id)]):
                        continue
                    start_offset = solver.value(starts[(operation.id, work_center_id)])
                    end_offset = solver.value(ends[(operation.id, work_center_id)])
                    assignments.append(
                        Assignment(
                            operation_id=operation.id,
                            work_center_id=work_center_id,
                            start_time=problem.planning_horizon_start + timedelta(minutes=start_offset),
                            end_time=problem.planning_horizon_start + timedelta(minutes=end_offset),
                            setup_minutes=0,
                            aux_resource_ids=[
                                requirement.aux_resource_id
                                for requirement in requirements_by_op.get(operation.id, [])
                            ],
                        )
                    )
                    break

            ops_by_id = {operation.id: operation for operation in problem.operations}
            setup_lookup = {
                (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
                for entry in problem.setup_matrix
            }
            assignments_by_machine: dict[Any, list[Assignment]] = {}
            for assignment in assignments:
                assignments_by_machine.setdefault(assignment.work_center_id, []).append(assignment)

            for machine_assignments in assignments_by_machine.values():
                machine_assignments.sort(key=lambda assignment: assignment.start_time)
                previous_assignment: Assignment | None = None
                for assignment in machine_assignments:
                    if previous_assignment is None:
                        assignment.setup_minutes = 0
                    else:
                        previous_state = ops_by_id[previous_assignment.operation_id].state_id
                        current_state = ops_by_id[assignment.operation_id].state_id
                        assignment.setup_minutes = setup_lookup.get(
                            (assignment.work_center_id, previous_state, current_state),
                            0,
                        )
                    previous_assignment = assignment

            objective = ObjectiveValues(
                makespan_minutes=float(solver.value(makespan)),
                total_setup_minutes=float(solver.value(total_setup)),
                total_material_loss=float(solver.value(total_material_scaled)) / material_loss_scale,
                total_tardiness_minutes=float(solver.value(total_tardiness)),
                weighted_sum=float(solver.objective_value),
            )
            metadata.update(
                {
                    "best_objective_bound": float(solver.best_objective_bound),
                    "objective_components": {
                        "makespan_minutes": objective.makespan_minutes,
                        "total_setup_minutes": objective.total_setup_minutes,
                        "total_material_loss": objective.total_material_loss,
                        "total_tardiness_minutes": objective.total_tardiness_minutes,
                    },
                }
            )

        return assignments, objective, metadata

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        time_limit_s = int(kwargs.get("time_limit_s", 30))
        random_seed = int(kwargs.get("random_seed", 42))
        num_workers = int(kwargs.get("num_workers", 8))
        objective_weights = dict(kwargs.get("objective_weights", {}))
        material_loss_scale = int(kwargs.get("material_loss_scale", 1000))
        epsilon_constraints: dict[str, int] | None = kwargs.get("epsilon_constraints", None)
        objective_mode = str(kwargs.get("objective_mode", "weighted_sum"))
        primary_objective = str(kwargs.get("primary_objective", "makespan"))

        t0 = time.monotonic()
        model = cp_model.CpModel()

        horizon = int(
            (problem.planning_horizon_end - problem.planning_horizon_start).total_seconds() / 60
        )

        wc_by_id = {work_center.id: work_center for work_center in problem.work_centers}
        eligible_by_op = {
            operation.id: (
                operation.eligible_wc_ids
                if operation.eligible_wc_ids
                else [work_center.id for work_center in problem.work_centers]
            )
            for operation in problem.operations
        }
        setup_minutes_lookup = {
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
            for entry in problem.setup_matrix
        }
        setup_material_lookup = {
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): int(
                round(entry.material_loss * material_loss_scale)
            )
            for entry in problem.setup_matrix
        }

        starts: dict[tuple[Any, Any], Any] = {}
        ends: dict[tuple[Any, Any], Any] = {}
        intervals: dict[tuple[Any, Any], Any] = {}
        presences: dict[tuple[Any, Any], Any] = {}
        selected_starts: dict[Any, Any] = {}
        selected_ends: dict[Any, Any] = {}

        for operation in problem.operations:
            selected_start = model.new_int_var(0, horizon, f"selected_start_{operation.id}")
            selected_end = model.new_int_var(0, horizon, f"selected_end_{operation.id}")
            selected_starts[operation.id] = selected_start
            selected_ends[operation.id] = selected_end

            presence_vars: list[Any] = []
            for work_center_id in eligible_by_op[operation.id]:
                work_center = wc_by_id[work_center_id]
                duration = max(1, int(round(operation.base_duration_min / work_center.speed_factor)))

                suffix = f"_{operation.id}_{work_center_id}"
                start_var = model.new_int_var(0, horizon, f"start{suffix}")
                end_var = model.new_int_var(0, horizon, f"end{suffix}")
                presence = model.new_bool_var(f"presence{suffix}")
                interval = model.new_optional_interval_var(
                    start_var,
                    duration,
                    end_var,
                    presence,
                    f"interval{suffix}",
                )

                starts[(operation.id, work_center_id)] = start_var
                ends[(operation.id, work_center_id)] = end_var
                intervals[(operation.id, work_center_id)] = interval
                presences[(operation.id, work_center_id)] = presence
                presence_vars.append(presence)

                model.add(selected_start == start_var).only_enforce_if(presence)
                model.add(selected_end == end_var).only_enforce_if(presence)

            model.add_exactly_one(presence_vars)

        for operation in problem.operations:
            if operation.predecessor_op_id is not None:
                model.add(selected_starts[operation.id] >= selected_ends[operation.predecessor_op_id])

        setup_terms, material_terms, setup_intervals_by_op = self._add_machine_order_and_adjacency(
            model,
            problem,
            starts,
            ends,
            intervals,
            presences,
            setup_minutes_lookup,
            setup_material_lookup,
        )
        self._add_aux_resource_cumulative_constraints(
            model, problem, eligible_by_op, intervals, setup_intervals_by_op
        )

        makespan = model.new_int_var(0, horizon, "makespan")
        for operation in problem.operations:
            model.add(makespan >= selected_ends[operation.id])

        total_setup, total_material_scaled, total_tardiness, secondary_bound, weights, scale = self._build_weighted_objective(
            model,
            problem,
            horizon,
            makespan,
            setup_terms,
            material_terms,
            selected_ends,
            objective_weights,
            material_loss_scale,
            epsilon_constraints=epsilon_constraints,
            objective_mode=objective_mode,
            primary_objective=primary_objective,
        )

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_s
        solver.parameters.random_seed = random_seed
        solver.parameters.num_workers = num_workers

        status_code = solver.solve(model)
        status_map = {
            cp_model.OPTIMAL: SolverStatus.OPTIMAL,
            cp_model.FEASIBLE: SolverStatus.FEASIBLE,
            cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
            cp_model.MODEL_INVALID: SolverStatus.ERROR,
        }
        result_status = status_map.get(status_code, SolverStatus.TIMEOUT)

        assignments, objective, metadata = self._extract_solution_and_objective(
            problem,
            solver,
            result_status,
            eligible_by_op,
            starts,
            ends,
            presences,
            makespan,
            total_setup,
            total_material_scaled,
            total_tardiness,
            weights,
            scale,
            secondary_bound,
        )
        metadata.update(
            {
                "objective_mode": objective_mode,
                "primary_objective": primary_objective,
                "epsilon_constraints": dict(epsilon_constraints or {}),
            }
        )

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return ScheduleResult(
            solver_name=self.name,
            status=result_status,
            assignments=assignments,
            objective=objective,
            duration_ms=elapsed_ms,
            random_seed=random_seed,
            metadata=metadata,
        )
