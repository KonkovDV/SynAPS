"""CP-SAT Solver — OR-Tools Constraint Programming solver for MO-FJSP-SDST."""

from __future__ import annotations

import itertools
import math
import time
from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from ortools.sat.python import cp_model

from synaps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from synaps.solvers import BaseSolver
from synaps.timegrain import duration_minutes

# N3 (audit v3): time limits are owned by ``time_limit_s`` and may not be set
# through ``sat_parameters`` — doing so silently defeats the timebox (D3).
_TIMEBOX_PARAMETERS = frozenset({"max_time_in_seconds", "max_deterministic_time"})

# F9 (audit v4): in strict determinism the single-worker invariant is what makes
# a fixed seed reproducible; overriding the worker count via ``sat_parameters``
# silently re-enables the multi-threaded portfolio race that N1 removed. Reject
# worker-count overrides in strict mode, same as the timebox keys (N3).
_STRICT_MODE_DENIED_PARAMETERS = frozenset({"num_workers", "num_search_workers"})

# N1 (audit v3, ADR-0001): strict determinism runs CP-SAT single-threaded and
# stops on MACHINE-INDEPENDENT deterministic time — the SOLE binding limit — so
# a fixed seed yields a byte-identical schedule regardless of host speed or CPU
# load. The wall clock is only a loose runaway safety (2x the budget); if it,
# rather than the deterministic stop, ends the search, metadata records
# determinism_violated. The deterministic budget is a fraction of time_limit_s
# so that, at the measured single-thread wall/deterministic ratio (~1.1-1.5,
# rising under load), the run still finishes within ~1.2x the wall budget; 0.5
# holds for ratios up to ~2.4. The lost ~50% of the search budget is the
# documented price of reproducibility. A pure wall-clock stop, or a wall cap
# tight enough to pre-empt the deterministic stop, is inherently
# non-reproducible under variable load (the original D1/D3 collision).
_STRICT_DETERMINISTIC_FRACTION = 0.5
_STRICT_WALL_SAFETY_FACTOR = 2.0

# P1-1: the default hierarchical objective is a big-M scalarization
# ``makespan * secondary_bound + secondary_terms``. At the model's stated scale
# (MAX_SCHEDULE_OPERATIONS = 200_000) ``(horizon + 1) * secondary_bound`` can
# exceed the CP-SAT int64 objective domain, corrupting the solve. When the big-M
# would overflow this safe ceiling we degrade to a PURE lexicographic objective
# (minimize makespan alone — the dominant term — leaving the secondary terms as a
# reported, non-minimized residual) rather than overflowing silently. 2**62
# leaves headroom below the int64 max (2**63 - 1) for CP-SAT's internal sums.
_SAFE_OBJECTIVE_MAX = 2**62


def _objective_product_overflows(term_bound: int, multiplier_bound: int) -> bool:
    """True if ``term * (multiplier_bound + 1)`` can exceed the safe int64 ceiling.

    Unified guard (audit v4, F5): the same product shape appears in the default
    big-M objective (``makespan * secondary_bound``, makespan ≤ horizon) and in
    ``epsilon_primary`` with a non-makespan primary
    (``primary * (horizon + 1)``, primary ≤ primary_bound).
    """
    return term_bound * (multiplier_bound + 1) > _SAFE_OBJECTIVE_MAX


def _bigm_objective_overflows(horizon: int, secondary_bound: int) -> bool:
    """True if the big-M objective coefficient product exceeds the safe int64 ceiling."""
    return _objective_product_overflows(secondary_bound, horizon)


def _build_tardiness_terms(
    model: cp_model.CpModel,
    problem: ScheduleProblem,
    horizon: int,
    selected_ends: dict[Any, Any],
) -> tuple[Any, int]:
    """Per-order completion/tardiness vars and the total tardiness var."""
    # F8 (audit v4): due offsets deliberately FLOOR to the integer-minute
    # grid. Operation ends are integral on this grid, so floor is exact for
    # the feasibility question: an integer end e is tardy vs a real due d
    # iff e > floor(d). (Contrast with release offsets, which must CEIL —
    # a floor there would admit starts before the release.)
    due_offsets = {
        order.id: int((order.due_date - problem.planning_horizon_start).total_seconds() / 60.0)
        for order in problem.orders
    }

    tardiness_terms: list[Any] = []
    tardiness_ub = 0
    for order in problem.orders:
        order_operations = [
            operation for operation in problem.operations if operation.order_id == order.id
        ]
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
    return total_tardiness, tardiness_ub


def _minimize_scalarized_objective(
    model: cp_model.CpModel,
    *,
    objective_mode: str,
    epsilon_constraints: dict[str, int] | None,
    primary_objective: str,
    makespan: Any,
    total_setup: Any,
    total_material_scaled: Any,
    total_tardiness: Any,
    horizon: int,
    setup_ub: int,
    material_ub: int,
    tardiness_ub: int,
    weights: dict[str, int],
    secondary_bound: int,
) -> bool:
    """Install the scalarized objective; returns True when overflow-degraded.

    F5 (audit v4): BOTH scalarized objectives can overflow — the default big-M
    branch and epsilon_primary with a non-makespan primary grow with the same
    law — so the overflow guard is applied per-branch.
    """
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
                "Unsupported primary_objective "
                f"'{primary_objective}'. Expected one of: {supported}"
            ) from exc

        if primary_objective == "makespan":
            model.minimize(primary_target)
        elif _objective_product_overflows(
            objective_bounds[primary_objective], objective_bounds["makespan"]
        ):
            # F5: ``primary * (horizon + 1)`` would overflow the int64 objective
            # domain at this scale — degrade to makespan, same policy as the
            # big-M branch, instead of corrupting the solve silently.
            model.minimize(makespan)
            return True
        # Lexicographic tie-break inside the selected Pareto slice: once the
        # primary objective is minimized, prefer the shortest makespan still
        # satisfying the epsilon caps.
        makespan_bound = objective_bounds["makespan"] + 1
        model.minimize(primary_target * makespan_bound + makespan)
        return False

    if epsilon_constraints:
        model.minimize(makespan)
        return False

    # Default: hierarchical weighted-sum with makespan as primary. P1-1: guard
    # the big-M against int64 overflow at the model's stated scale; when the
    # coefficient product exceeds the safe ceiling, degrade to makespan-only
    # rather than overflow the CP-SAT objective domain.
    if _bigm_objective_overflows(horizon, secondary_bound):
        model.minimize(makespan)
        return True
    model.minimize(
        makespan * secondary_bound
        + weights["setup"] * total_setup
        + weights["material_loss"] * total_material_scaled
        + weights["tardiness"] * total_tardiness
    )
    return False


def _apply_sat_parameter_overrides(
    solver: cp_model.CpSolver,
    *,
    time_limit_s: int,
    random_seed: int,
    num_workers: int,
    determinism: str,
    overrides: Any,
) -> dict[str, Any]:
    """Apply explicit SatParameters overrides and return the effective audit snapshot.

    ``determinism`` (D1):

    * ``"strict"`` (default) makes a fixed ``random_seed`` reproducible. OR-Tools
      portfolio workers race under a wall-clock limit, and a wall stop is
      inherently non-deterministic, so ``strict`` runs SINGLE-THREADED and stops
      on ``max_deterministic_time`` (machine-independent) as the sole binding
      limit; the wall clock is only a loose runaway safety. See ADR-0001.
    * ``"fast"`` keeps the multi-threaded wall-clock portfolio, which is faster
      but not reproducible with more than one worker.

    Explicit ``overrides`` win for every parameter EXCEPT the time limits
    (``max_time_in_seconds`` / ``max_deterministic_time``): those are owned by
    ``time_limit_s`` and raise ``ValueError`` if overridden, so the timebox
    cannot be bypassed through ``sat_parameters`` (audit v3, N3).
    """

    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.random_seed = random_seed
    solver.parameters.num_workers = num_workers

    if determinism == "strict":
        # N1 (audit v3, ADR-0001): single-threaded search has a deterministic
        # order; stopping on deterministic time (machine-independent) as the
        # SOLE binding limit makes a fixed seed reproducible regardless of host
        # speed or CPU load. The original fix left max_time_in_seconds at the
        # budget, so under load (where the wall/deterministic ratio rises) the
        # wall cap cut before the deterministic stop and reproducibility was
        # lost (measured: 4/4 distinct schedules). The wall clock is therefore
        # relaxed to a loose runaway safety; the deterministic stop binds first.
        # determinism="fast" keeps the multi-threaded portfolio for throughput.
        num_workers = 1
        solver.parameters.num_workers = 1
        deterministic_stop = float(time_limit_s) * _STRICT_DETERMINISTIC_FRACTION
        solver.parameters.max_deterministic_time = deterministic_stop
        solver.parameters.max_time_in_seconds = float(time_limit_s) * _STRICT_WALL_SAFETY_FACTOR

    effective_parameters: dict[str, Any] = {
        "max_time_in_seconds": float(solver.parameters.max_time_in_seconds),
        "random_seed": int(solver.parameters.random_seed),
        "num_workers": int(solver.parameters.num_workers),
        "determinism": determinism,
    }
    if determinism == "strict":
        # Recorded only in strict mode, where it is the binding stop (N1).
        effective_parameters["max_deterministic_time"] = float(
            solver.parameters.max_deterministic_time
        )
    if not isinstance(overrides, Mapping):
        return effective_parameters

    for key, raw_value in overrides.items():
        if key in _TIMEBOX_PARAMETERS:
            # N3 (audit v3): the timebox is set solely through ``time_limit_s``.
            # Allowing a caller to raise ``max_time_in_seconds`` /
            # ``max_deterministic_time`` via ``sat_parameters`` let a solve run
            # ~3x its budget (8s budget -> 24s wall), silently defeating D3.
            raise ValueError(
                f"Cannot override CP-SAT time limit {key!r} via sat_parameters; "
                f"the search budget is controlled only by time_limit_s."
            )
        if determinism == "strict" and key in _STRICT_MODE_DENIED_PARAMETERS:
            # F9 (audit v4): strict mode is reproducible BECAUSE it is
            # single-threaded; a num_workers override would silently re-enable
            # the racing portfolio. Use determinism="fast" to opt out.
            raise ValueError(
                f"Cannot override CP-SAT worker count {key!r} via sat_parameters "
                f"in determinism='strict' (single-threading is the reproducibility "
                f"invariant, see ADR-0001); use determinism='fast' to opt out."
            )
        if not hasattr(solver.parameters, key):
            raise ValueError(f"Unknown CP-SAT parameter override: {key}")
        try:
            setattr(solver.parameters, key, raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid CP-SAT parameter override {key}={raw_value!r}") from exc

        applied_value = getattr(solver.parameters, key)
        if isinstance(applied_value, bool | int | float | str):
            effective_parameters[key] = applied_value
        elif isinstance(raw_value, bool | int | float | str):
            effective_parameters[key] = raw_value
        else:
            effective_parameters[key] = str(applied_value)

    effective_parameters["max_time_in_seconds"] = float(solver.parameters.max_time_in_seconds)
    effective_parameters["random_seed"] = int(solver.parameters.random_seed)
    effective_parameters["num_workers"] = int(solver.parameters.num_workers)
    return effective_parameters


class CpSatSolver(BaseSolver):
    """Exact / time-boxed CP-SAT solver for flexible job-shop with SDST."""

    def _virtualize_parallel_work_centers(
        self,
        problem: ScheduleProblem,
    ) -> tuple[ScheduleProblem, dict[UUID, UUID]]:
        """Expand parallel work centers into exact disjunctive lanes when ordering matters.

        `AddCircuit` models sequence-dependent transitions exactly only for
        disjunctive resources. When a work center has `max_parallel > 1` and any
        non-zero sequence-dependent transition cost (setup time, material loss,
        or energy) is present, we split it into identical virtual lanes, each
        with `max_parallel = 1`. This preserves exact lane sequencing while
        still allowing the original amount of concurrency overall.
        """
        setup_by_work_center: dict[UUID, bool] = {}
        for entry in problem.setup_matrix:
            if entry.setup_minutes > 0 or entry.material_loss > 0 or entry.energy_kwh > 0:
                setup_by_work_center[entry.work_center_id] = True

        expandable = {
            work_center.id: work_center
            for work_center in problem.work_centers
            if work_center.max_parallel > 1 and setup_by_work_center.get(work_center.id, False)
        }
        if not expandable:
            return problem, {}

        virtual_to_original: dict[UUID, UUID] = {}
        expanded_ids: dict[UUID, list[UUID]] = {}
        new_work_centers = []
        for work_center in problem.work_centers:
            if work_center.id not in expandable:
                new_work_centers.append(work_center)
                continue

            lane_ids: list[UUID] = []
            for lane in range(1, work_center.max_parallel + 1):
                lane_id = uuid5(NAMESPACE_DNS, f"{work_center.id}:lane:{lane}")
                lane_ids.append(lane_id)
                virtual_to_original[lane_id] = work_center.id
                new_work_centers.append(
                    work_center.model_copy(
                        update={
                            "id": lane_id,
                            "code": f"{work_center.code}::L{lane}",
                            "max_parallel": 1,
                            "domain_attributes": {
                                **work_center.domain_attributes,
                                "virtualized_from": str(work_center.id),
                                "virtual_lane": lane,
                            },
                        }
                    )
                )
            expanded_ids[work_center.id] = lane_ids

        default_eligible = [work_center.id for work_center in problem.work_centers]
        new_operations = []
        for operation in problem.operations:
            base_eligible = (
                list(operation.eligible_wc_ids)
                if operation.eligible_wc_ids
                else list(default_eligible)
            )
            expanded_eligible: list[UUID] = []
            for work_center_id in base_eligible:
                expanded_eligible.extend(expanded_ids.get(work_center_id, [work_center_id]))
            new_operations.append(
                operation.model_copy(update={"eligible_wc_ids": expanded_eligible})
            )

        new_setup_matrix = []
        for entry in problem.setup_matrix:
            entry_lane_ids = expanded_ids.get(entry.work_center_id)
            if not entry_lane_ids:
                new_setup_matrix.append(entry)
                continue
            for lane_id in entry_lane_ids:
                new_setup_matrix.append(entry.model_copy(update={"work_center_id": lane_id}))

        transformed_problem = ScheduleProblem(
            states=problem.states,
            orders=problem.orders,
            operations=new_operations,
            work_centers=new_work_centers,
            setup_matrix=new_setup_matrix,
            auxiliary_resources=problem.auxiliary_resources,
            aux_requirements=problem.aux_requirements,
            planning_horizon_start=problem.planning_horizon_start,
            planning_horizon_end=problem.planning_horizon_end,
        )
        return transformed_problem, virtual_to_original

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
        *,
        planning_horizon_start: Any,
        horizon: int,
        frozen_assignments: list[Assignment] | None = None,
    ) -> tuple[list[Any], list[Any], dict[Any, list[tuple[Any, Any]]]]:
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
        frozen_assignments_by_machine: dict[Any, list[Assignment]] = {}
        if frozen_assignments:
            for assignment in frozen_assignments:
                frozen_assignments_by_machine.setdefault(
                    assignment.work_center_id,
                    [],
                ).append(assignment)

        for work_center in problem.work_centers:
            machine_operations = [
                operation
                for operation in problem.operations
                if (operation.id, work_center.id) in intervals
            ]
            if not machine_operations:
                continue

            machine_intervals = [
                intervals[(operation.id, work_center.id)] for operation in machine_operations
            ]
            frozen_machine_intervals: list[Any] = []
            for frozen_index, frozen_assignment in enumerate(
                sorted(
                    frozen_assignments_by_machine.get(work_center.id, []),
                    key=lambda assignment: assignment.start_time,
                )
            ):
                start_offset = round(
                    (frozen_assignment.start_time - planning_horizon_start).total_seconds() / 60.0
                )
                end_offset = round(
                    (frozen_assignment.end_time - planning_horizon_start).total_seconds() / 60.0
                )
                start_offset = max(0, min(start_offset, horizon))
                end_offset = max(0, min(end_offset, horizon))
                if end_offset <= start_offset:
                    continue

                frozen_start = model.new_int_var(
                    start_offset,
                    start_offset,
                    f"frozen_start_{work_center.id}_{frozen_index}",
                )
                frozen_end = model.new_int_var(
                    end_offset,
                    end_offset,
                    f"frozen_end_{work_center.id}_{frozen_index}",
                )
                frozen_machine_intervals.append(
                    model.new_interval_var(
                        frozen_start,
                        end_offset - start_offset,
                        frozen_end,
                        f"frozen_interval_{work_center.id}_{frozen_index}",
                    )
                )

            constrained_machine_intervals = machine_intervals + frozen_machine_intervals

            if work_center.max_parallel <= 1:
                model.add_no_overlap(constrained_machine_intervals)
            else:
                model.add_cumulative(
                    constrained_machine_intervals,
                    [1] * len(constrained_machine_intervals),
                    work_center.max_parallel,
                )

            if work_center.max_parallel > 1:
                continue

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

                    lit = model.new_bool_var(f"arc_{op_i.id}_{op_j.id}_{work_center.id}")
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

                        # Reserve setup as an optional window ending exactly at
                        # op_j's start: [start_j - setup, start_j], with its own
                        # start var constrained only under `lit`. The previous
                        # form passed ends[i] as the interval start, which — since
                        # a CP-SAT IntervalVar enforces start + size == end —
                        # welded start_j == end_i + setup and forbade machine
                        # idle, right-shifting op_i and cutting the true optimum
                        # (P0-1). This still feeds the aux-resource cumulative
                        # below and matches FeasibilityChecker's setup-window
                        # semantics (start - setup).
                        su_start = model.new_int_var(
                            0, horizon, f"su_start_{op_i.id}_{op_j.id}_{work_center.id}"
                        )
                        model.add(
                            su_start == starts[(op_j.id, work_center.id)] - setup_minutes
                        ).only_enforce_if(lit)
                        model.add(
                            su_start >= ends[(op_i.id, work_center.id)]
                        ).only_enforce_if(lit)
                        setup_interval = model.new_optional_interval_var(
                            su_start,
                            setup_minutes,
                            starts[(op_j.id, work_center.id)],
                            lit,
                            f"setup_interval_{op_i.id}_{op_j.id}_{work_center.id}",
                        )
                        setup_intervals_by_op.setdefault(op_j.id, []).append((setup_interval, lit))

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
    ) -> tuple[Any, Any, Any, int, dict[str, int], int, bool]:
        max_setup = max((entry.setup_minutes for entry in problem.setup_matrix), default=0)
        max_material_scaled = max(
            (round(entry.material_loss * material_loss_scale) for entry in problem.setup_matrix),
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

        total_tardiness, tardiness_ub = _build_tardiness_terms(
            model, problem, horizon, selected_ends
        )

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
                model.add(
                    total_material_scaled <= int(epsilon_constraints["max_material_loss_scaled"])
                )

        bigm_degraded = _minimize_scalarized_objective(
            model,
            objective_mode=objective_mode,
            epsilon_constraints=epsilon_constraints,
            primary_objective=primary_objective,
            makespan=makespan,
            total_setup=total_setup,
            total_material_scaled=total_material_scaled,
            total_tardiness=total_tardiness,
            horizon=horizon,
            setup_ub=setup_ub,
            material_ub=material_ub,
            tardiness_ub=tardiness_ub,
            weights=weights,
            secondary_bound=secondary_bound,
        )

        return (
            total_setup,
            total_material_scaled,
            total_tardiness,
            secondary_bound,
            weights,
            material_loss_scale,
            bigm_degraded,
        )

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
        makespan_bound_divisor: float = 1.0,
        bound_is_makespan: bool = True,
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
                            start_time=problem.planning_horizon_start
                            + timedelta(minutes=start_offset),
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
                total_material_loss=float(solver.value(total_material_scaled))
                / material_loss_scale,
                total_tardiness_minutes=float(solver.value(total_tardiness)),
                weighted_sum=float(solver.objective_value),
            )
            # Q3: solver.best_objective_bound is the dual bound of the scalarized
            # (big-M) objective, in big-M units. Publish it verbatim under its
            # own key, and report best_objective_bound in makespan minutes by
            # dividing out the makespan coefficient (secondary_bound for the
            # default weighted-sum objective; 1 when makespan is minimized
            # directly). This is a valid makespan lower bound (<= achieved).
            scalarized_bound = float(solver.best_objective_bound)
            divisor = makespan_bound_divisor if makespan_bound_divisor > 0 else 1.0
            # Floor: in the weighted-sum objective C_max*S + secondary (with
            # 0 <= secondary < S), floor(bound / S) is a valid makespan lower
            # bound (integer minutes); the fractional part is the secondary
            # terms, which must not inflate the makespan bound above C_max.
            makespan_bound = (
                float(math.floor(scalarized_bound / divisor)) if divisor > 1.0 else scalarized_bound
            )
            # Q3: only claim makespan-minute units when the minimized objective
            # actually bounds makespan (weighted-sum, or makespan minimized
            # directly). In epsilon_primary mode with a non-makespan primary the
            # objective is primary*(H+1)+makespan, so the dual bound is in
            # scalarized units, not minutes — label it honestly and do not
            # expose a spurious best_objective_bound as a makespan bound.
            metadata["objective_components"] = {
                "makespan_minutes": objective.makespan_minutes,
                "total_setup_minutes": objective.total_setup_minutes,
                "total_material_loss": objective.total_material_loss,
                "total_tardiness_minutes": objective.total_tardiness_minutes,
            }
            metadata["scalarized_objective_bound"] = scalarized_bound
            if bound_is_makespan:
                metadata["best_objective_bound"] = makespan_bound
                metadata["objective_bound_units"] = "makespan_minutes"
            else:
                metadata["best_objective_bound"] = scalarized_bound
                metadata["objective_bound_units"] = "scalarized_objective"

        return assignments, objective, metadata

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        time_limit_s = int(kwargs.get("time_limit_s", 30))
        random_seed = int(kwargs.get("random_seed", 42))
        num_workers = int(kwargs.get("num_workers", 8))
        # D1: default to reproducible multi-threaded search. "fast" opts back
        # into the non-deterministic wall-clock portfolio.
        determinism = str(kwargs.get("determinism", "strict"))
        if determinism not in ("strict", "fast"):
            raise ValueError(f"determinism must be 'strict' or 'fast', got {determinism!r}")
        sat_parameter_overrides = kwargs.get("sat_parameters")
        auto_greedy_warm_start = bool(kwargs.get("auto_greedy_warm_start", True))
        objective_weights = dict(kwargs.get("objective_weights", {}))
        material_loss_scale = int(kwargs.get("material_loss_scale", 1000))
        epsilon_constraints: dict[str, int] | None = kwargs.get("epsilon_constraints")
        objective_mode = str(kwargs.get("objective_mode", "weighted_sum"))
        primary_objective = str(kwargs.get("primary_objective", "makespan"))
        warm_start_assignments: list[Assignment] | None = kwargs.get("warm_start_assignments")
        frozen_assignments_raw = kwargs.get("frozen_assignments")
        frozen_assignments: list[Assignment] = list(frozen_assignments_raw or [])
        frozen_predecessor_end_offsets = {
            op_id: int(offset)
            for op_id, offset in dict(kwargs.get("frozen_predecessor_end_offsets", {})).items()
        }
        enable_symmetry_breaking = bool(kwargs.get("enable_symmetry_breaking", False))

        t0 = time.monotonic()
        model = cp_model.CpModel()

        solve_problem, virtual_to_original = self._virtualize_parallel_work_centers(problem)

        # P1-4: frozen assignments are defined on the ORIGINAL work centers, not
        # the virtual lanes created for max_parallel > 1. Silently dropping them
        # (the prior behavior) let a repair overlap frozen work with no signal.
        # Fail loudly instead; a proper lane mapping is a future enhancement.
        if frozen_assignments and virtual_to_original:
            raise ValueError(
                "frozen_assignments are not supported together with max_parallel>1 "
                "work-center lane virtualization: the frozen intervals reference the "
                "original work centers, not the virtual lanes. Provide a single-lane "
                "instance or omit frozen_assignments (P1-4)."
            )

        # F8 (audit v4): floor here is the CONSERVATIVE direction — all
        # start/end vars are bounded by `horizon`, so a sub-minute remainder is
        # simply lost as schedulable space; extracted datetimes therefore never
        # exceed planning_horizon_end (the checker's HORIZON_BOUND is safe).
        horizon = int(
            (
                solve_problem.planning_horizon_end - solve_problem.planning_horizon_start
            ).total_seconds()
            / 60
        )

        wc_by_id = {work_center.id: work_center for work_center in solve_problem.work_centers}
        eligible_by_op = {
            operation.id: (
                operation.eligible_wc_ids
                if operation.eligible_wc_ids
                else [work_center.id for work_center in solve_problem.work_centers]
            )
            for operation in solve_problem.operations
        }
        setup_minutes_lookup = {
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
            for entry in solve_problem.setup_matrix
        }
        setup_material_lookup = {
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): round(
                entry.material_loss * material_loss_scale
            )
            for entry in solve_problem.setup_matrix
        }

        starts: dict[tuple[Any, Any], Any] = {}
        ends: dict[tuple[Any, Any], Any] = {}
        intervals: dict[tuple[Any, Any], Any] = {}
        presences: dict[tuple[Any, Any], Any] = {}
        selected_starts: dict[Any, Any] = {}
        selected_ends: dict[Any, Any] = {}

        for operation in solve_problem.operations:
            selected_start = model.new_int_var(0, horizon, f"selected_start_{operation.id}")
            selected_end = model.new_int_var(0, horizon, f"selected_end_{operation.id}")
            selected_starts[operation.id] = selected_start
            selected_ends[operation.id] = selected_end

            presence_vars: list[Any] = []
            for work_center_id in eligible_by_op[operation.id]:
                work_center = wc_by_id[work_center_id]
                duration = duration_minutes(operation.base_duration_min, work_center.speed_factor)

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

        # M1: release_date lower bound on the start time. An operation may not
        # start before its order becomes available (material release).
        # F8 (audit v4): the offset must CEIL, not truncate — the model works on
        # an integer-minute grid while the FeasibilityChecker compares exact
        # datetimes. int() admitted starts up to 59.999s before the release
        # (release at H0+1.5min -> offset 1 -> start at H0+1:00, a
        # RELEASE_DATE_VIOLATION). ceil lands on the first grid point that is
        # not before the release.
        orders_by_id = {order.id: order for order in solve_problem.orders}
        release_offset_by_op: dict[Any, int] = {}
        for operation in solve_problem.operations:
            order = orders_by_id.get(operation.order_id)
            release = getattr(order, "release_date", None) if order is not None else None
            if release is not None:
                offset = math.ceil(
                    (release - solve_problem.planning_horizon_start).total_seconds() / 60.0
                )
                if offset > 0:
                    release_offset_by_op[operation.id] = offset

        for operation in solve_problem.operations:
            if operation.predecessor_op_id is not None:
                model.add(
                    selected_starts[operation.id] >= selected_ends[operation.predecessor_op_id]
                )
            frozen_predecessor_end_offset = frozen_predecessor_end_offsets.get(operation.id)
            if frozen_predecessor_end_offset is not None:
                model.add(selected_starts[operation.id] >= frozen_predecessor_end_offset)
            release_offset = release_offset_by_op.get(operation.id)
            if release_offset is not None:
                model.add(selected_starts[operation.id] >= release_offset)

        setup_terms, material_terms, setup_intervals_by_op = self._add_machine_order_and_adjacency(
            model,
            solve_problem,
            starts,
            ends,
            intervals,
            presences,
            setup_minutes_lookup,
            setup_material_lookup,
            planning_horizon_start=solve_problem.planning_horizon_start,
            horizon=horizon,
            frozen_assignments=frozen_assignments,
        )
        self._add_aux_resource_cumulative_constraints(
            model, solve_problem, eligible_by_op, intervals, setup_intervals_by_op
        )

        makespan = model.new_int_var(0, horizon, "makespan")
        for operation in solve_problem.operations:
            model.add(makespan >= selected_ends[operation.id])

        (
            total_setup,
            total_material_scaled,
            total_tardiness,
            secondary_bound,
            weights,
            scale,
            bigm_degraded,
        ) = self._build_weighted_objective(
            model,
            solve_problem,
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

        if enable_symmetry_breaking:
            # A capacity-ordering symmetry cut is sound only between genuinely
            # interchangeable machines: any schedule of A must be transferable
            # wholesale onto B. That requires identical capability_group,
            # speed_factor, max_parallel, setup matrix, AND identical eligible-
            # operation sets. The old form grouped only by (capability_group,
            # speed_factor) and summed over "shared" ops, cutting the optimum
            # whenever an op was eligible on A but not B (P0-2).
            setup_rows_by_wc: dict[Any, list[tuple[Any, Any, int, float, float]]] = {}
            for entry in solve_problem.setup_matrix:
                setup_rows_by_wc.setdefault(entry.work_center_id, []).append(
                    (
                        entry.from_state_id,
                        entry.to_state_id,
                        entry.setup_minutes,
                        entry.material_loss,
                        entry.energy_kwh,
                    )
                )
            eligible_ops_by_wc: dict[Any, frozenset[Any]] = {
                work_center.id: frozenset(
                    operation.id
                    for operation in solve_problem.operations
                    if work_center.id in eligible_by_op[operation.id]
                )
                for work_center in solve_problem.work_centers
            }
            # Machines carrying frozen (fixed) intervals are not interchangeable
            # with unfrozen peers even when all other attributes match: the
            # frozen blocks differ per machine, so a wholesale A<->B swap need
            # not preserve feasibility. Exclude them from symmetry classes.
            frozen_wc_ids = {assignment.work_center_id for assignment in frozen_assignments}
            symmetry_classes: dict[tuple[Any, ...], list[Any]] = {}
            for work_center in solve_problem.work_centers:
                if work_center.id in frozen_wc_ids:
                    continue
                setup_signature = tuple(
                    sorted(
                        setup_rows_by_wc.get(work_center.id, []),
                        key=lambda row: (str(row[0]), str(row[1])),
                    )
                )
                class_key = (
                    work_center.capability_group,
                    work_center.speed_factor,
                    work_center.max_parallel,
                    setup_signature,
                    eligible_ops_by_wc[work_center.id],
                )
                symmetry_classes.setdefault(class_key, []).append(work_center)
            for class_work_centers in symmetry_classes.values():
                if len(class_work_centers) < 2:
                    continue
                for work_center_a, work_center_b in itertools.pairwise(class_work_centers):
                    # Eligible sets are identical within a class, so summing over
                    # A's ops covers exactly the same operations as B's.
                    presences_a = [
                        presences[(op_id, work_center_a.id)]
                        for op_id in eligible_ops_by_wc[work_center_a.id]
                        if (op_id, work_center_a.id) in presences
                    ]
                    presences_b = [
                        presences[(op_id, work_center_b.id)]
                        for op_id in eligible_ops_by_wc[work_center_b.id]
                        if (op_id, work_center_b.id) in presences
                    ]
                    if presences_a and presences_b:
                        model.add(sum(presences_a) >= sum(presences_b))

        if (
            auto_greedy_warm_start
            and warm_start_assignments is None
            and time_limit_s >= 5
            and not virtual_to_original
        ):
            from synaps.solvers.greedy_dispatch import GreedyDispatch

            greedy_result = GreedyDispatch().solve(problem)
            if greedy_result.assignments:
                warm_start_assignments = greedy_result.assignments

        hint_count = 0
        if warm_start_assignments and not virtual_to_original:
            hint_by_operation = {
                assignment.operation_id: assignment for assignment in warm_start_assignments
            }
            for operation in solve_problem.operations:
                hint = hint_by_operation.get(operation.id)
                if hint is None:
                    continue
                start_offset = int(
                    (hint.start_time - problem.planning_horizon_start).total_seconds() / 60.0
                )
                start_offset = max(0, min(start_offset, horizon))
                for work_center_id in eligible_by_op[operation.id]:
                    is_assigned = work_center_id == hint.work_center_id
                    model.add_hint(presences[(operation.id, work_center_id)], int(is_assigned))
                    hint_count += 1
                    if is_assigned:
                        model.add_hint(starts[(operation.id, work_center_id)], start_offset)
                        hint_count += 1

        solver = cp_model.CpSolver()
        effective_sat_parameters = _apply_sat_parameter_overrides(
            solver,
            time_limit_s=time_limit_s,
            random_seed=random_seed,
            num_workers=num_workers,
            determinism=determinism,
            overrides=sat_parameter_overrides,
        )
        random_seed = int(effective_sat_parameters["random_seed"])
        num_workers = int(effective_sat_parameters["num_workers"])

        status_code = solver.solve(model)
        status_map = {
            cp_model.OPTIMAL: SolverStatus.OPTIMAL,
            cp_model.FEASIBLE: SolverStatus.FEASIBLE,
            cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
            cp_model.MODEL_INVALID: SolverStatus.ERROR,
        }
        result_status = status_map.get(status_code, SolverStatus.TIMEOUT)

        # N1 (audit v3): under strict determinism the search must stop on the
        # machine-independent deterministic-time budget, not on the wall cap.
        # If the result was not proven (OPTIMAL/INFEASIBLE) yet the solver
        # consumed less than its deterministic budget, the wall cap ended the
        # search first, so the schedule is NOT guaranteed reproducible on this
        # host. Surface that rather than implying determinism silently.
        determinism_violated = False
        if determinism == "strict" and result_status not in (
            SolverStatus.OPTIMAL,
            SolverStatus.INFEASIBLE,
        ):
            deterministic_stop = float(effective_sat_parameters["max_deterministic_time"])
            deterministic_time_used = float(solver.deterministic_time)
            determinism_violated = deterministic_time_used < deterministic_stop * 0.99

        assignments, objective, metadata = self._extract_solution_and_objective(
            solve_problem,
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
            makespan_bound_divisor=(
                # Q3: the default weighted-sum objective scales makespan by
                # secondary_bound; the epsilon modes minimize makespan (or the
                # primary) directly, so the bound is already in its own units.
                float(secondary_bound)
                if objective_mode == "weighted_sum" and not epsilon_constraints
                else 1.0
            ),
            bound_is_makespan=(
                # The dual bound is a makespan bound only when the minimized
                # objective is makespan (weighted-sum, epsilon-constraint, or
                # epsilon_primary with primary==makespan). With a non-makespan
                # primary the objective is scalarized, so the bound is not.
                objective_mode != "epsilon_primary" or primary_objective == "makespan"
            ),
        )
        if virtual_to_original:
            for assignment in assignments:
                assignment.lane_id = assignment.work_center_id
                assignment.work_center_id = virtual_to_original.get(
                    assignment.work_center_id,
                    assignment.work_center_id,
                )
        metadata.update(
            {
                "objective_mode": objective_mode,
                "primary_objective": primary_objective,
                "epsilon_constraints": dict(epsilon_constraints or {}),
                "auto_greedy_warm_start": auto_greedy_warm_start,
                "warm_started": warm_start_assignments is not None and not virtual_to_original,
                "hint_count": hint_count,
                "symmetry_breaking": enable_symmetry_breaking,
                "determinism": determinism,
                "determinism_violated": determinism_violated,
                "objective_bigm_overflow_degraded": bigm_degraded,
                "sat_parameters": effective_sat_parameters,
                "parallel_virtualization": {
                    "enabled": bool(virtual_to_original),
                    "virtual_lane_count": len(virtual_to_original),
                    "original_parallel_work_centers": len(set(virtual_to_original.values())),
                },
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
