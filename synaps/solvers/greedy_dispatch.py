"""Greedy Dispatch solver — ATCS (Apparent Tardiness Cost with Setups) heuristic.

Includes:
    GreedyDispatch: single-trajectory ATCS constructive heuristic.
    BeamSearchDispatch: filtered beam search extension (width B=3..5) for
        improved solution quality on complex SDST matrices (Ow & Morton 1989).
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

from synaps.accelerators import compute_atcs_log_scores_batch, get_acceleration_status
from synaps.model import (
    Assignment,
    ObjectiveValues,
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
from synaps.solvers._time_windows import operation_earliest_offset_minutes
from synaps.solvers.coverage_outcome import stamp_honest_coverage
from synaps.timegrain import physical_processing_minutes_for


def _virtualize_parallel_lanes(
    problem: ScheduleProblem,
) -> tuple[ScheduleProblem, dict[Any, Any]]:
    """M2: expand every ``max_parallel > 1`` work center into disjunctive lanes.

    The dispatch layer has no cumulative-capacity concept, so the only way to
    let a machine run operations concurrently is to model each lane as its own
    ``max_parallel == 1`` work center (the same lane model CP-SAT uses via
    ``_virtualize_parallel_work_centers``). Unlike the CP-SAT variant this is
    NOT gated on setups: a parallel machine must allow concurrency regardless.
    Returns the transformed problem and a ``virtual_lane_id -> original_wc_id``
    map; the caller re-attaches ``lane_id`` and restores ``work_center_id`` on
    the resulting assignments. Returns ``({}, )`` unchanged when nothing to do.
    """
    from uuid import NAMESPACE_DNS, uuid5

    expandable = {wc.id: wc for wc in problem.work_centers if wc.max_parallel > 1}
    if not expandable:
        return problem, {}

    virtual_to_original: dict[Any, Any] = {}
    expanded_ids: dict[Any, list[Any]] = {}
    new_work_centers = []
    for wc in problem.work_centers:
        if wc.id not in expandable:
            new_work_centers.append(wc)
            continue
        lane_ids = []
        for lane in range(1, wc.max_parallel + 1):
            lane_id = uuid5(NAMESPACE_DNS, f"{wc.id}:lane:{lane}")
            lane_ids.append(lane_id)
            virtual_to_original[lane_id] = wc.id
            new_work_centers.append(
                wc.model_copy(
                    update={
                        "id": lane_id,
                        "code": f"{wc.code}::L{lane}",
                        "max_parallel": 1,
                    }
                )
            )
        expanded_ids[wc.id] = lane_ids

    default_eligible = [wc.id for wc in problem.work_centers]
    new_operations = []
    for op in problem.operations:
        base_eligible = list(op.eligible_wc_ids) if op.eligible_wc_ids else list(default_eligible)
        expanded_eligible: list[Any] = []
        for wc_id in base_eligible:
            expanded_eligible.extend(expanded_ids.get(wc_id, [wc_id]))
        new_operations.append(op.model_copy(update={"eligible_wc_ids": expanded_eligible}))

    new_setup_matrix = []
    for entry in problem.setup_matrix:
        entry_lane_ids = expanded_ids.get(entry.work_center_id)
        if not entry_lane_ids:
            new_setup_matrix.append(entry)
            continue
        for lane_id in entry_lane_ids:
            new_setup_matrix.append(entry.model_copy(update={"work_center_id": lane_id}))

    transformed = ScheduleProblem(
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
    return transformed, virtual_to_original


def _map_assignments_onto_virtual_lanes(
    assignments: list[Assignment],
    virtual_to_original: dict[Any, Any],
) -> list[Assignment]:
    """Map original-WC frozen assignments onto virtual lanes.

    Used by IncrementalRepair so ``max_parallel > 1`` is explicit lane
    virtualization rather than silent serialization or a hard ERROR.
    Overlapping frozen ops on the same WC pack onto distinct lanes when
    a free lane exists; leftover overlap stays on the earliest-free lane
    so the repair neighbourhood can still move the disrupted ops.
    """
    if not virtual_to_original or not assignments:
        return list(assignments)

    original_to_lanes: dict[Any, list[Any]] = {}
    for lane_id, original_id in virtual_to_original.items():
        original_to_lanes.setdefault(original_id, []).append(lane_id)
    for lane_ids in original_to_lanes.values():
        lane_ids.sort(key=str)

    lane_free_at: dict[Any, Any] = {}
    mapped_by_op: dict[Any, Assignment] = {}
    for assignment in sorted(
        assignments,
        key=lambda item: (item.start_time, item.end_time, str(item.operation_id)),
    ):
        lanes = original_to_lanes.get(assignment.work_center_id)
        if not lanes:
            mapped_by_op[assignment.operation_id] = assignment
            continue
        chosen = None
        if assignment.lane_id is not None and assignment.lane_id in virtual_to_original:
            chosen = assignment.lane_id
        else:
            for lane_id in lanes:
                free_at = lane_free_at.get(lane_id)
                if free_at is None or free_at <= assignment.start_time:
                    chosen = lane_id
                    break
            if chosen is None:
                chosen = min(
                    lanes,
                    key=lambda lane_id: lane_free_at.get(lane_id, assignment.start_time),
                )
        mapped = assignment.model_copy(update={"work_center_id": chosen, "lane_id": chosen})
        mapped_by_op[assignment.operation_id] = mapped
        lane_free_at[chosen] = max(lane_free_at.get(chosen, mapped.end_time), mapped.end_time)

    return [mapped_by_op.get(assignment.operation_id, assignment) for assignment in assignments]


def _unroll_lane_assignments(result: ScheduleResult, virtual_to_original: dict[Any, Any]) -> None:
    """M2: restore original work_center_id and expose the chosen lane_id in place."""
    if not virtual_to_original:
        return
    for assignment in result.assignments:
        original = virtual_to_original.get(assignment.work_center_id)
        if original is not None:
            assignment.lane_id = assignment.work_center_id
            assignment.work_center_id = original


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
        # M2: virtualize parallel lanes so a max_parallel>1 machine can run ops
        # concurrently; the core dispatch treats each lane as its own machine
        # (no phantom setup between concurrent lanes), then lane_id is unrolled.
        virtual_problem, virtual_to_original = _virtualize_parallel_lanes(problem)
        # Q5: a single ATCS rule is myopic on a NON-metric setup matrix (the
        # audit's 120-vs-32). Only then sweep several (k1,k2,k3) rules and keep
        # the best by the canonical objective; metric matrices (the common case,
        # and every warm-start consumer relies on the exact single trajectory)
        # keep the plain single-rule path unchanged.
        from synaps.validation import is_setup_matrix_metric

        if is_setup_matrix_metric(problem):
            result = self._solve_core(virtual_problem, **kwargs)
            result.metadata["priority_rule_sweep"] = False
            result.metadata["priority_rules_evaluated"] = 1
        else:
            result = self._solve_priority_rule_sweep(virtual_problem, **kwargs)
        _unroll_lane_assignments(result, virtual_to_original)
        return stamp_honest_coverage(problem, result)

    def _solve_priority_rule_sweep(
        self, virtual_problem: ScheduleProblem, **kwargs: Any
    ) -> ScheduleResult:
        """Q5: run several priority rules on a non-metric matrix, keep the best.

        Deterministic: a fixed candidate order and a strict ``<`` on the
        canonical objective sort key (coverage, then makespan, then weighted
        sum), so a fixed seed still yields one reproducible schedule. The
        configured rule is always among the candidates, so the sweep can never
        be worse than the plain single rule.
        """
        from synaps.objective import evaluate, objective_sort_key

        raw_weights = kwargs.get("objective_weights")
        weights = dict(raw_weights) if isinstance(raw_weights, dict) else None
        candidate_rules: list[tuple[float, float, float]] = []
        seen: set[tuple[float, float, float]] = set()
        for rule in (
            (self._k1, self._k2, self._k3),
            (5.0, 0.5, 0.5),
            (1.0, 1.0, 0.5),
            (2.0, 0.1, 0.5),
        ):
            if rule not in seen:
                seen.add(rule)
                candidate_rules.append(rule)

        best_result: ScheduleResult | None = None
        best_key: tuple[float, float, float] | None = None
        best_rule = candidate_rules[0]
        for k1, k2, k3 in candidate_rules:
            candidate_solver = GreedyDispatch(k1=k1, k2=k2, k3=k3)
            candidate_result = candidate_solver._solve_core(virtual_problem, **kwargs)
            candidate_key = objective_sort_key(
                evaluate(virtual_problem, candidate_result.assignments),
                weights,
            )
            if best_key is None or candidate_key < best_key:
                best_key = candidate_key
                best_result = candidate_result
                best_rule = (k1, k2, k3)

        assert best_result is not None  # candidate_rules is never empty
        best_result.metadata["priority_rule_sweep"] = True
        best_result.metadata["priority_rules_evaluated"] = len(candidate_rules)
        best_result.metadata["priority_rule_selected"] = list(best_rule)
        return best_result

    def _solve_core(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        t0 = time.monotonic()
        acceleration_status = get_acceleration_status()
        time_limit_s_raw = kwargs.get("time_limit_s")
        time_limit_s: float | None = None
        if time_limit_s_raw is not None:
            time_limit_s = max(0.1, float(time_limit_s_raw))

        # Precompute lookup tables
        orders_by_id = {o.id: o for o in problem.orders}
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        dispatch_context = build_dispatch_context(problem)

        horizon_start = problem.planning_horizon_start

        # Build operation queue (respecting precedence)
        all_ops = problem.operations
        n_total_ops = len(all_ops)
        scheduled_ops: set[Any] = set()
        op_end_offsets: dict[Any, float] = {}
        assignments: list[Assignment] = []
        machine_idx = MachineIndex(dispatch_context)

        while len(scheduled_ops) < n_total_ops:
            if time_limit_s is not None and (time.monotonic() - t0) > time_limit_s:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                partial_makespan = (
                    max(
                        (assignment.end_time - horizon_start).total_seconds() / 60.0
                        for assignment in assignments
                    )
                    if assignments
                    else 0.0
                )
                return ScheduleResult(
                    solver_name=self.name,
                    status=SolverStatus.TIMEOUT,
                    assignments=assignments,
                    objective=ObjectiveValues(makespan_minutes=partial_makespan),
                    duration_ms=elapsed_ms,
                    metadata={
                        "acceleration": acceleration_status,
                        "partial_schedule": True,
                        "scheduled_ops": len(assignments),
                        "remaining_ops": n_total_ops - len(scheduled_ops),
                        "time_limit_s": time_limit_s,
                    },
                )

            # Filter to ready operations (predecessor scheduled or none)
            ready = [
                op
                for op in all_ops
                if op.id not in scheduled_ops
                and (op.predecessor_op_id is None or op.predecessor_op_id in scheduled_ops)
            ]
            if not ready:
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
                    metadata={
                        "acceleration": acceleration_status,
                        "error": (
                            "no ready operations available; precedence graph may contain a cycle"
                        ),
                    },
                )

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
                pred_end = max(
                    pred_end,
                    operation_earliest_offset_minutes(op, order, horizon_start),
                )

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
                        machine_index=machine_idx,
                    )
                    if slot is None:
                        continue

                    work_center: Any = wc_by_id.get(wc_id)
                    if work_center is None:
                        from types import SimpleNamespace

                        work_center = SimpleNamespace(id=wc_id, speed_factor=1.0)
                    # F11: ATCS priority uses the physical (fractional) processing
                    # time via timegrain — not the integer reservation grain.
                    p_j = physical_processing_minutes_for(op, work_center)

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
                    metadata={
                        "acceleration": acceleration_status,
                        "error": "no feasible constructive slot found",
                    },
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
            # Score all candidates in one SoA-style batch call.
            # This keeps Python deterministic and lets optional PyO3/Rust
            # backends process the hot path with lower overhead.
            log_scores = compute_atcs_log_scores_batch(
                weights=[record["weight"] for record in candidate_records],
                processing_minutes=[record["processing_minutes"] for record in candidate_records],
                slack=[
                    max(
                        record["due_offset"]
                        - record["processing_minutes"]
                        - record["slot"].start_offset,
                        0.0,
                    )
                    for record in candidate_records
                ],
                ready_p_bar=ready_p_bar,
                setup_minutes=[record["slot"].setup_minutes for record in candidate_records],
                setup_scale=[
                    local_setup_scale_by_wc[record["work_center_id"]]
                    for record in candidate_records
                ],
                k1=self._k1,
                k2=self._k2,
                material_loss=[record["slot"].material_loss for record in candidate_records],
                material_scale=material_scale,
                k3=self._k3,
            )
            for record, log_score in zip(candidate_records, log_scores, strict=True):
                if log_score > best_log_score:
                    best_log_score = log_score
                    best_record = record

            best_op = best_record["operation"]
            # M2: ATCS decides WHICH operation to dispatch next; the work-center
            # choice for that op is then the earliest-completion feasible slot
            # among its candidates. This lets a max_parallel machine use an idle
            # lane instead of queuing behind a busy one (the ATCS composite,
            # dominated by the slack term at large due offsets, otherwise
            # preferred a much later start on the same lane, charging a phantom
            # setup). Deterministic tie-break: (end, setup, material, wc id) —
            # material_loss before wc id preserves the secondary preference for
            # a lower-material lane when completion and setup tie.
            best_op_candidates = [
                record for record in candidate_records if record["operation"].id == best_op.id
            ]
            best_record = min(
                best_op_candidates,
                key=lambda record: (
                    record["slot"].end_offset,
                    record["slot"].setup_minutes,
                    record["slot"].material_loss,
                    str(record["work_center_id"]),
                ),
            )
            best_wc_id = best_record["work_center_id"]
            best_slot = best_record["slot"]

            # Assign best
            work_center = wc_by_id.get(best_wc_id)
            end_offset = best_slot.end_offset

            new_assignment = Assignment(
                operation_id=best_op.id,
                work_center_id=best_wc_id,
                start_time=horizon_start + timedelta(minutes=best_slot.start_offset),
                end_time=horizon_start + timedelta(minutes=end_offset),
                setup_minutes=best_slot.setup_minutes,
                aux_resource_ids=best_slot.aux_resource_ids,
            )
            assignments.append(new_assignment)
            machine_idx.add(new_assignment)

            op_end_offsets[best_op.id] = end_offset
            scheduled_ops.add(best_op.id)

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
                previous_assignment = machine_assignments[index - 1]
                current_assignment = machine_assignments[index]
                previous_state = dispatch_context.ops_by_id[
                    previous_assignment.operation_id
                ].state_id
                current_state = dispatch_context.ops_by_id[current_assignment.operation_id].state_id
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
            metadata={"acceleration": acceleration_status},
        )


def _greedy_complete(
    dispatch_context: Any,
    orders_by_id: dict[Any, Any],
    horizon_start: Any,
    assignments: list[Assignment],
    scheduled_ops: set[Any],
    op_end_offsets: dict[Any, float],
    remaining: list[Any],
) -> tuple[list[Assignment], float] | None:
    """Q1: deterministic completion-to-go rollout (Ow & Morton second stage).

    Extends a partial schedule to a full one by repeatedly dispatching the
    (operation, work center) with the earliest feasible completion (ties broken
    deterministically), honoring precedence and release_date. Returns the full
    assignment list and its makespan, or None if it cannot be completed. This is
    a fixed function of the partial state, so a wider beam — which rolls out a
    superset of partial states — can only lower the global incumbent.
    """
    machine_idx = MachineIndex(dispatch_context)
    for assignment in assignments:
        machine_idx.add(assignment)
    out = list(assignments)
    scheduled = set(scheduled_ops)
    offsets = dict(op_end_offsets)
    todo = list(remaining)

    while todo:
        ready = [
            op for op in todo if op.predecessor_op_id is None or op.predecessor_op_id in scheduled
        ]
        if not ready:
            return None  # precedence cycle / dead partial
        best: tuple[Any, Any, Any] | None = None
        best_key: tuple[float, float, str, str] | None = None
        for op in ready:
            order = orders_by_id[op.order_id]
            pred_end = offsets.get(op.predecessor_op_id, 0.0)
            pred_end = max(
                pred_end,
                operation_earliest_offset_minutes(op, order, horizon_start),
            )
            eligible = (
                op.eligible_wc_ids if op.eligible_wc_ids else list(dispatch_context.wc_by_id.keys())
            )
            for wc_id in eligible:
                slot = find_earliest_feasible_slot(
                    dispatch_context, out, op, wc_id, pred_end, machine_index=machine_idx
                )
                if slot is None:
                    continue
                key = (slot.end_offset, float(slot.setup_minutes), str(wc_id), str(op.id))
                if best_key is None or key < best_key:
                    best_key = key
                    best = (op, wc_id, slot)
        if best is None:
            return None
        op, wc_id, slot = best
        assignment = Assignment(
            operation_id=op.id,
            work_center_id=wc_id,
            start_time=horizon_start + timedelta(minutes=slot.start_offset),
            end_time=horizon_start + timedelta(minutes=slot.end_offset),
            setup_minutes=slot.setup_minutes,
            aux_resource_ids=slot.aux_resource_ids,
        )
        out.append(assignment)
        machine_idx.add(assignment)
        offsets[op.id] = slot.end_offset
        scheduled.add(op.id)
        todo.remove(op)

    makespan = max((a.end_time - horizon_start).total_seconds() / 60.0 for a in out) if out else 0.0
    return out, makespan


class BeamSearchDispatch(BaseSolver):
    """Filtered Beam Search extension of ATCS dispatch (Ow & Morton 1989).

    Two-stage per the source method (Q1 fix): the cheap ATCS priority index is
    the first-stage filter that selects each beam's child expansions, and a
    completion-to-go greedy rollout of the actual objective is the second-stage
    ranking that decides which beams survive. A global incumbent is kept over
    every completed rollout (not only the last-step survivors), so makespan is
    non-increasing in the beam width.

    Memory: O(B · N) where N = number of operations.
    """

    def __init__(
        self,
        beam_width: int = 3,
        k1: float = 2.0,
        k2: float = 0.5,
        k3: float = 0.5,
    ) -> None:
        self._beam_width = max(1, beam_width)
        self._k1 = k1
        self._k2 = k2
        self._k3 = k3

    @property
    def name(self) -> str:
        return "beam_search"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        # M2: virtualize parallel lanes (see GreedyDispatch.solve).
        virtual_problem, virtual_to_original = _virtualize_parallel_lanes(problem)
        # Q1: beam search is not monotone in the beam width in general, so
        # return the best schedule over effective widths 1..B. This makes
        # makespan non-increasing in beam_width by construction (a wider beam
        # can never be worse than a narrower one) while still exploring the
        # full requested width. B is small (<= ~12), instances are small.
        best: ScheduleResult | None = None
        for width in range(1, self._beam_width + 1):
            candidate = self._solve_core(virtual_problem, width, **kwargs)
            if best is None or (
                candidate.objective.makespan_minutes < best.objective.makespan_minutes
            ):
                best = candidate
        assert best is not None
        _unroll_lane_assignments(best, virtual_to_original)
        return stamp_honest_coverage(problem, best)

    def _solve_core(
        self, problem: ScheduleProblem, beam_width: int, **kwargs: Any
    ) -> ScheduleResult:
        t0 = time.monotonic()
        acceleration_status = get_acceleration_status()

        orders_by_id = {o.id: o for o in problem.orders}
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        dispatch_context = build_dispatch_context(problem)
        horizon_start = problem.planning_horizon_start

        # Each beam is a tuple: (assignments, scheduled_ops, op_end_offsets, remaining)
        initial_remaining = list(problem.operations)
        beams: list[tuple[list[Assignment], set[Any], dict[Any, float], list[Any]]] = [
            ([], set(), {}, initial_remaining),
        ]

        total_ops = len(problem.operations)

        # Q1: global incumbent over EVERY completed rollout, not just the beams
        # that survive the last step. A wider beam rolls out a superset of
        # partial states, so this is non-increasing in the beam width.
        incumbent: list[Assignment] | None = None
        incumbent_makespan = float("inf")

        for _step in range(total_ops):
            candidates: list[
                tuple[
                    float,
                    tuple[tuple[str, float, str], ...],
                    list[Assignment],
                    set[Any],
                    dict[Any, float],
                    list[Any],
                ]
            ] = []

            for assignments, scheduled_ops, op_end_offsets, remaining in beams:
                machine_idx = MachineIndex(dispatch_context)
                for assignment in assignments:
                    machine_idx.add(assignment)

                if not remaining:
                    # Beam already complete — rank by its own makespan and let
                    # it update the incumbent.
                    completed_mk = (
                        max(
                            (a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments
                        )
                        if assignments
                        else 0.0
                    )
                    if completed_mk < incumbent_makespan:
                        # Snapshot: assignment objects are shared across beams and
                        # mutated in place by later steps, so copy to freeze it.
                        incumbent = [a.model_copy() for a in assignments]
                        incumbent_makespan = completed_mk
                    completed_fp = tuple(
                        sorted(
                            (
                                str(a.work_center_id),
                                (a.start_time - horizon_start).total_seconds(),
                                str(a.operation_id),
                            )
                            for a in assignments
                        )
                    )
                    candidates.append(
                        (
                            completed_mk,
                            completed_fp,
                            assignments,
                            scheduled_ops,
                            op_end_offsets,
                            remaining,
                        )
                    )
                    continue

                ready = [
                    op
                    for op in remaining
                    if op.predecessor_op_id is None or op.predecessor_op_id in scheduled_ops
                ]
                if not ready:
                    continue  # Dead beam — precedence cycle

                ready_p_bar = max(
                    sum(op.base_duration_min for op in ready) / max(len(ready), 1),
                    1.0,
                )

                candidate_records: list[dict[str, Any]] = []
                for op in ready:
                    order = orders_by_id[op.order_id]
                    due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
                    w_j = order.priority / 500.0
                    pred_end = op_end_offsets.get(op.predecessor_op_id, 0.0)
                    pred_end = max(
                        pred_end,
                        operation_earliest_offset_minutes(op, order, horizon_start),
                    )

                    eligible = (
                        op.eligible_wc_ids
                        if op.eligible_wc_ids
                        else [wc.id for wc in problem.work_centers]
                    )
                    for wc_id in eligible:
                        slot = find_earliest_feasible_slot(
                            dispatch_context,
                            assignments,
                            op,
                            wc_id,
                            pred_end,
                            machine_index=machine_idx,
                        )
                        if slot is None:
                            continue

                        work_center: Any = wc_by_id.get(wc_id)
                        if work_center is None:
                            from types import SimpleNamespace

                            work_center = SimpleNamespace(id=wc_id, speed_factor=1.0)
                        # F11: ATCS priority uses physical processing via timegrain.
                        p_j = physical_processing_minutes_for(op, work_center)

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
                    continue  # Dead beam

                # M2: collapse each operation's candidates to its earliest-
                # completion feasible slot before scoring, so a max_parallel
                # machine's idle lane is used instead of queuing behind a busy
                # lane (mirrors GreedyDispatch). Deterministic key (end, setup,
                # wc id). Beam then explores which OPERATION to place next.
                _best_by_op: dict[Any, dict[str, Any]] = {}
                for record in candidate_records:
                    op_id = record["operation"].id
                    existing_best = _best_by_op.get(op_id)
                    key = (
                        record["slot"].end_offset,
                        record["slot"].setup_minutes,
                        record["slot"].material_loss,
                        str(record["work_center_id"]),
                    )
                    if existing_best is None or key < (
                        existing_best["slot"].end_offset,
                        existing_best["slot"].setup_minutes,
                        existing_best["slot"].material_loss,
                        str(existing_best["work_center_id"]),
                    ):
                        _best_by_op[op_id] = record
                candidate_records = list(_best_by_op.values())

                # Compute setup and material scales
                local_setup_scale_by_wc: dict[Any, float] = {}
                for wc_id in {r["work_center_id"] for r in candidate_records}:
                    nonzero = [
                        r["slot"].setup_minutes
                        for r in candidate_records
                        if r["work_center_id"] == wc_id and r["slot"].setup_minutes > 0
                    ]
                    local_setup_scale_by_wc[wc_id] = max(
                        sum(nonzero) / max(len(nonzero), 1),
                        1.0,
                    )
                global_mat = [
                    r["slot"].material_loss
                    for r in candidate_records
                    if r["slot"].material_loss > 0
                ]
                material_scale = max(sum(global_mat) / max(len(global_mat), 1), 1.0)

                # Score all candidates and keep top-B
                scored: list[tuple[float, dict[str, Any]]] = []
                log_scores = compute_atcs_log_scores_batch(
                    weights=[record["weight"] for record in candidate_records],
                    processing_minutes=[
                        record["processing_minutes"] for record in candidate_records
                    ],
                    slack=[
                        max(
                            record["due_offset"]
                            - record["processing_minutes"]
                            - record["slot"].start_offset,
                            0.0,
                        )
                        for record in candidate_records
                    ],
                    ready_p_bar=ready_p_bar,
                    setup_minutes=[record["slot"].setup_minutes for record in candidate_records],
                    setup_scale=[
                        local_setup_scale_by_wc[record["work_center_id"]]
                        for record in candidate_records
                    ],
                    k1=self._k1,
                    k2=self._k2,
                    material_loss=[record["slot"].material_loss for record in candidate_records],
                    material_scale=material_scale,
                    k3=self._k3,
                )

                for record, log_score in zip(candidate_records, log_scores, strict=True):
                    scored.append((log_score, record))

                # Deterministic tie-break (op id, wc id) so the top-beam_width
                # child set is a prefix independent of the beam width — the key
                # to width-monotonicity: beams(B) then contains beams(B-1).
                scored.sort(
                    key=lambda x: (
                        -x[0],
                        str(x[1]["operation"].id),
                        str(x[1]["work_center_id"]),
                    )
                )
                # First stage (Ow & Morton): cheap ATCS priority filter selects
                # up to beam_width child expansions of this beam.
                top_candidates = scored[:beam_width]

                for _score, record in top_candidates:
                    new_assignments = list(assignments)
                    new_scheduled = set(scheduled_ops)
                    new_offsets = dict(op_end_offsets)

                    best_op = record["operation"]
                    best_slot = record["slot"]
                    end_offset = best_slot.end_offset

                    new_assignments.append(
                        Assignment(
                            operation_id=best_op.id,
                            work_center_id=record["work_center_id"],
                            start_time=horizon_start + timedelta(minutes=best_slot.start_offset),
                            end_time=horizon_start + timedelta(minutes=end_offset),
                            setup_minutes=best_slot.setup_minutes,
                            aux_resource_ids=best_slot.aux_resource_ids,
                        )
                    )
                    new_offsets[best_op.id] = end_offset
                    new_scheduled.add(best_op.id)
                    new_remaining = [op for op in remaining if op.id != best_op.id]

                    # Second stage: completion-to-go rollout ranks this beam by
                    # the ACTUAL objective and updates the global incumbent.
                    rollout = _greedy_complete(
                        dispatch_context,
                        orders_by_id,
                        horizon_start,
                        new_assignments,
                        new_scheduled,
                        new_offsets,
                        new_remaining,
                    )
                    if rollout is None:
                        continue
                    full_assignments, projected_mk = rollout
                    if projected_mk < incumbent_makespan:
                        # Snapshot: the rollout reuses assignment objects that
                        # later steps mutate in place, so copy to freeze it.
                        incumbent = [a.model_copy() for a in full_assignments]
                        incumbent_makespan = projected_mk
                    # Fingerprint is a deterministic function of the partial
                    # schedule (independent of the beam width), so the top-B
                    # beam set is a prefix and nests across widths.
                    fingerprint = tuple(
                        sorted(
                            (
                                str(a.work_center_id),
                                (a.start_time - horizon_start).total_seconds(),
                                str(a.operation_id),
                            )
                            for a in new_assignments
                        )
                    )
                    candidates.append(
                        (
                            projected_mk,
                            fingerprint,
                            new_assignments,
                            new_scheduled,
                            new_offsets,
                            new_remaining,
                        ),
                    )

            if not candidates:
                break

            # Second-stage ranking: keep the B beams with the best completion-
            # to-go projection (lower makespan is better), tie-broken by the
            # deterministic fingerprint so top-B nests across beam widths.
            candidates.sort(key=lambda x: (x[0], x[1]))
            beams = [(c[2], c[3], c[4], c[5]) for c in candidates[:beam_width]]

        # The incumbent is the best of every completed rollout. It is the
        # returned schedule; a wider beam can only lower it (Q1 monotonicity).
        if incumbent is None:
            # Fall back to standard greedy
            greedy = GreedyDispatch(k1=self._k1, k2=self._k2, k3=self._k3)
            return greedy.solve(problem, **kwargs)

        assignments, makespan = incumbent, incumbent_makespan

        # Recompute setups and objectives
        total_setup = recompute_assignment_setups(assignments, dispatch_context)

        total_material_loss = 0.0
        assignments_by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            assignments_by_machine.setdefault(a.work_center_id, []).append(a)
        for wc_id, machine_assignments in assignments_by_machine.items():
            machine_assignments.sort(key=lambda a: a.start_time)
            for idx in range(1, len(machine_assignments)):
                prev_op_id = machine_assignments[idx - 1].operation_id
                curr_op_id = machine_assignments[idx].operation_id
                prev_state = dispatch_context.ops_by_id[prev_op_id].state_id
                curr_state = dispatch_context.ops_by_id[curr_op_id].state_id
                total_material_loss += dispatch_context.material_loss.get(
                    (wc_id, prev_state, curr_state),
                    0.0,
                )

        order_completion: dict[Any, float] = {}
        for a in assignments:
            op = dispatch_context.ops_by_id[a.operation_id]
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
            assignments=assignments,
            objective=ObjectiveValues(
                makespan_minutes=makespan,
                total_setup_minutes=total_setup,
                total_material_loss=total_material_loss,
                total_tardiness_minutes=total_tardiness,
            ),
            duration_ms=elapsed_ms,
            metadata={
                "acceleration": acceleration_status,
                "beam_width": self._beam_width,
            },
        )
