"""Greedy Dispatch solver — ATCS (Apparent Tardiness Cost with Setups) heuristic.

Includes:
    GreedyDispatch: single-trajectory ATCS constructive heuristic.
    BeamSearchDispatch: filtered beam search extension (width B=3..5) for
        improved solution quality on complex SDST matrices (Ow & Morton 1989).
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from synaps.accelerators import compute_atcs_log_scores_batch, get_acceleration_status
from synaps.model import (
    Assignment,
    ObjectiveValues,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
)
from synaps.precedence import DispatchPrecedence
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
from synaps.timegrain import duration_minutes_for, physical_processing_minutes_for

if TYPE_CHECKING:
    from collections.abc import Callable


def _edge_bound(
    edges: DispatchPrecedence, operation: Any, eligible: list[Any], wc_by_id: dict[Any, Any]
) -> float:
    """Earliest start implied by generalized precedence edges (0 when none)."""
    if operation.id not in edges.incoming:
        return 0.0
    durations = [
        duration_minutes_for(operation, wc_by_id[wc_id]) for wc_id in eligible if wc_id in wc_by_id
    ]
    return edges.earliest_start(operation.id, float(min(durations, default=0)))


def _gap_scan_for(n_ops: int, operation: Any | None = None) -> str:
    """KI-N1: full left-to-right gap walk is O(n^2*m). Large n appends only.

    Hard per-op windows keep a window-clipped interior scan so night leftovers
    are not appended after the last daytime job.
    """

    return gap_scan_for(n_ops, operation)


def _dispatch_timeout_result(
    *,
    solver_name: str,
    problem: ScheduleProblem,
    assignments: list[Assignment],
    t0: float,
    acceleration_status: object,
    time_limit_s: float | None,
    extra_metadata: dict[str, Any],
) -> ScheduleResult:
    """TIMEOUT + partial assignments. Uses ``evaluate`` so the ctor ratchet stays put."""

    from synaps.objective import evaluate

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return ScheduleResult(
        solver_name=solver_name,
        status=SolverStatus.TIMEOUT,
        assignments=list(assignments),
        objective=evaluate(problem, assignments),
        duration_ms=elapsed_ms,
        metadata={
            "acceleration": acceleration_status,
            "partial_schedule": True,
            "time_limit_s": time_limit_s,
            **extra_metadata,
        },
    )


def _dispatch_feasible_result(
    *,
    solver_name: str,
    assignments: list[Assignment],
    makespan: float | None,
    dispatch_context: Any,
    problem: ScheduleProblem,
    horizon_start: Any,
    t0: float,
    metadata: dict[str, Any],
) -> ScheduleResult:
    """FEASIBLE result with setups recomputed from the final machine sequences.

    Recomputing per-assignment setup from the final sequence corrects ghost
    setups after gap insertions. The objective here is solver telemetry; the
    BaseSolver boundary replaces it with the canonical ``evaluate``.
    """
    total_setup = recompute_assignment_setups(assignments, dispatch_context)
    total_material_loss = 0.0
    assignments_by_machine: dict[Any, list[Assignment]] = {}
    for assignment in assignments:
        assignments_by_machine.setdefault(assignment.work_center_id, []).append(assignment)
    for wc_id, machine_assignments in assignments_by_machine.items():
        machine_assignments.sort(key=lambda item: item.start_time)
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
    for assignment in assignments:
        operation = dispatch_context.ops_by_id[assignment.operation_id]
        end = (assignment.end_time - horizon_start).total_seconds() / 60.0
        if operation.order_id not in order_completion or end > order_completion[operation.order_id]:
            order_completion[operation.order_id] = end
    total_tardiness = 0.0
    for order in problem.orders:
        completion = order_completion.get(order.id, 0.0)
        due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
        total_tardiness += max(completion - due_offset, 0.0)
    if makespan is None:
        makespan = _makespan_of(assignments, horizon_start)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return ScheduleResult(
        solver_name=solver_name,
        status=SolverStatus.FEASIBLE,
        assignments=assignments,
        objective=ObjectiveValues(
            makespan_minutes=makespan,
            total_setup_minutes=total_setup,
            total_material_loss=total_material_loss,
            total_tardiness_minutes=total_tardiness,
        ),
        duration_ms=elapsed_ms,
        metadata=metadata,
    )


def _beam_partial_on_timeout(
    incumbent: list[Assignment] | None,
    beams: list[tuple[list[Assignment], set[Any], dict[Any, float], list[Any]]],
) -> list[Assignment]:
    """Best completed rollout, else the first live beam's assignments."""

    if incumbent is not None:
        return incumbent
    if not beams:
        return []
    return list(beams[0][0])


def _beam_deadline_result(
    *,
    time_limit_s: float | None,
    t0: float,
    incumbent: list[Assignment] | None,
    beams: list[tuple[list[Assignment], set[Any], dict[Any, float], list[Any]]],
    solver_name: str,
    problem: ScheduleProblem,
    acceleration_status: object,
    beam_width: int,
) -> ScheduleResult | None:
    if time_limit_s is None or (time.monotonic() - t0) <= time_limit_s:
        return None
    partial = _beam_partial_on_timeout(incumbent, beams)
    return _dispatch_timeout_result(
        solver_name=solver_name,
        problem=problem,
        assignments=partial,
        t0=t0,
        acceleration_status=acceleration_status,
        time_limit_s=time_limit_s,
        extra_metadata={"beam_width": beam_width, "scheduled_ops": len(partial)},
    )


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
        precedence_edges=problem.precedence_edges,
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


def _dispatch_time_limit(kwargs: dict[str, Any]) -> float | None:
    raw = kwargs.get("time_limit_s")
    return max(0.1, float(raw)) if raw is not None else None


def _ready_p_bar(ready: list[Any]) -> float:
    """Mean BASE duration of the ready set (ATCS look-ahead scale, >= 1)."""
    total = float(sum(op.base_duration_min for op in ready))
    return max(total / max(len(ready), 1), 1.0)


def _collect_atcs_records(
    *,
    problem: ScheduleProblem,
    dispatch_context: Any,
    orders_by_id: dict[Any, Any],
    wc_by_id: dict[Any, Any],
    ready: list[Any],
    assignments: list[Assignment],
    op_end_offsets: dict[Any, float],
    machine_idx: MachineIndex,
    n_total_ops: int,
    edges: DispatchPrecedence | None = None,
    check_timeout: Callable[[], ScheduleResult | None] | None = None,
) -> tuple[list[dict[str, Any]], ScheduleResult | None]:
    """Feasible (operation, machine) slots of the ready set with ATCS inputs.

    Returns ``(records, timeout_result)``; ``check_timeout`` (beam search) is
    polled before every slot search and aborts with its result.
    """
    horizon_start = problem.planning_horizon_start
    records: list[dict[str, Any]] = []
    for op in ready:
        order = orders_by_id[op.order_id]
        due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
        w_j = order.priority / 500.0  # normalise around default priority
        pred_end = op_end_offsets.get(op.predecessor_op_id, 0.0)
        pred_end = max(pred_end, operation_earliest_offset_minutes(op, order, horizon_start))
        eligible = (
            op.eligible_wc_ids
            if op.eligible_wc_ids
            else [work_center.id for work_center in problem.work_centers]
        )
        if edges is not None:
            pred_end = max(pred_end, _edge_bound(edges, op, eligible, wc_by_id))
        for wc_id in eligible:
            if check_timeout is not None and (timed_out := check_timeout()) is not None:
                return records, timed_out
            slot = find_earliest_feasible_slot(
                dispatch_context,
                assignments,
                op,
                wc_id,
                pred_end,
                machine_index=machine_idx,
                gap_scan=_gap_scan_for(n_total_ops, op),
            )
            if slot is None:
                continue
            work_center: Any = wc_by_id.get(wc_id)
            if work_center is None:
                from types import SimpleNamespace

                work_center = SimpleNamespace(id=wc_id, speed_factor=1.0)
            records.append(
                {
                    "operation": op,
                    "work_center_id": wc_id,
                    "slot": slot,
                    "due_offset": due_offset,
                    "weight": w_j,
                    # F11: ATCS uses the physical (fractional) processing time.
                    "processing_minutes": physical_processing_minutes_for(op, work_center),
                }
            )
    return records, None


def _atcs_log_scores(
    records: list[dict[str, Any]], *, ready_p_bar: float, k1: float, k2: float, k3: float
) -> list[float]:
    """Batch log-ATCS scores with per-machine setup and global material scales."""
    local_setup_scale_by_wc: dict[Any, float] = {}
    for wc_id in {record["work_center_id"] for record in records}:
        nonzero = [
            record["slot"].setup_minutes
            for record in records
            if record["work_center_id"] == wc_id and record["slot"].setup_minutes > 0
        ]
        local_setup_scale_by_wc[wc_id] = max(sum(nonzero) / max(len(nonzero), 1), 1.0)
    nonzero_material = [
        record["slot"].material_loss for record in records if record["slot"].material_loss > 0
    ]
    material_scale = max(sum(nonzero_material) / max(len(nonzero_material), 1), 1.0)
    # One SoA batch call: deterministic in Python, PyO3/Rust when available.
    return compute_atcs_log_scores_batch(
        weights=[record["weight"] for record in records],
        processing_minutes=[record["processing_minutes"] for record in records],
        slack=[
            max(
                record["due_offset"] - record["processing_minutes"] - record["slot"].start_offset,
                0.0,
            )
            for record in records
        ],
        ready_p_bar=ready_p_bar,
        setup_minutes=[record["slot"].setup_minutes for record in records],
        setup_scale=[local_setup_scale_by_wc[record["work_center_id"]] for record in records],
        k1=k1,
        k2=k2,
        material_loss=[record["slot"].material_loss for record in records],
        material_scale=material_scale,
        k3=k3,
    )


def _slot_preference_key(record: dict[str, Any]) -> tuple[float, float, float, str]:
    """Deterministic machine preference: (end, setup, material, wc id)."""
    slot = record["slot"]
    return (slot.end_offset, slot.setup_minutes, slot.material_loss, str(record["work_center_id"]))


def _assignment_from_record(record: dict[str, Any], horizon_start: Any) -> Assignment:
    slot = record["slot"]
    return Assignment(
        operation_id=record["operation"].id,
        work_center_id=record["work_center_id"],
        start_time=horizon_start + timedelta(minutes=slot.start_offset),
        end_time=horizon_start + timedelta(minutes=slot.end_offset),
        setup_minutes=slot.setup_minutes,
        aux_resource_ids=slot.aux_resource_ids,
    )


def _makespan_of(assignments: list[Assignment], horizon_start: Any) -> float:
    return max(
        ((a.end_time - horizon_start).total_seconds() / 60.0 for a in assignments), default=0.0
    )


def _partial_fingerprint(
    assignments: list[Assignment], horizon_start: Any
) -> tuple[tuple[str, float, str], ...]:
    """Width-independent identity of a partial schedule (beam nesting key)."""
    return tuple(
        sorted(
            (
                str(a.work_center_id),
                (a.start_time - horizon_start).total_seconds(),
                str(a.operation_id),
            )
            for a in assignments
        )
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

    supports_precedence_edges = True

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
        deadline: float | None = None
        time_limit_s_raw = kwargs.get("time_limit_s")
        if time_limit_s_raw is not None:
            deadline = time.monotonic() + max(0.1, float(time_limit_s_raw))
        evaluated = 0
        for k1, k2, k3 in candidate_rules:
            if evaluated and deadline is not None and time.monotonic() >= deadline:
                break
            inner_kwargs = dict(kwargs)
            if deadline is not None:
                inner_kwargs["time_limit_s"] = max(0.1, deadline - time.monotonic())
            candidate_solver = GreedyDispatch(k1=k1, k2=k2, k3=k3)
            candidate_result = candidate_solver._solve_core(virtual_problem, **inner_kwargs)
            evaluated += 1
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
        best_result.metadata["priority_rules_evaluated"] = evaluated
        best_result.metadata["priority_rule_selected"] = list(best_rule)
        return best_result

    def _solve_core(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        """Serial schedule generation: ATCS picks the op, earliest completion the machine."""
        t0 = time.monotonic()
        acceleration_status = get_acceleration_status()
        time_limit_s = _dispatch_time_limit(kwargs)
        orders_by_id = {o.id: o for o in problem.orders}
        wc_by_id = {wc.id: wc for wc in problem.work_centers}
        dispatch_context = build_dispatch_context(problem)
        horizon_start = problem.planning_horizon_start
        n_total_ops = len(problem.operations)
        scheduled_ops: set[Any] = set()
        op_end_offsets: dict[Any, float] = {}
        assignments: list[Assignment] = []
        machine_idx = MachineIndex(dispatch_context)
        edges = DispatchPrecedence.build(problem.precedence_edges)
        while len(scheduled_ops) < n_total_ops:
            if time_limit_s is not None and (time.monotonic() - t0) > time_limit_s:
                return self._timeout_result(
                    assignments,
                    horizon_start,
                    t0,
                    acceleration_status,
                    time_limit_s,
                    n_total_ops,
                    len(scheduled_ops),
                )
            ready = [
                op
                for op in problem.operations
                if op.id not in scheduled_ops
                and (op.predecessor_op_id is None or op.predecessor_op_id in scheduled_ops)
                and edges.ready(op.id, scheduled_ops)
            ]
            if not ready:
                return self._error_result(
                    assignments,
                    horizon_start,
                    t0,
                    acceleration_status,
                    "no ready operations available; precedence graph may contain a cycle",
                )
            records, _ = _collect_atcs_records(
                problem=problem,
                dispatch_context=dispatch_context,
                orders_by_id=orders_by_id,
                wc_by_id=wc_by_id,
                ready=ready,
                assignments=assignments,
                op_end_offsets=op_end_offsets,
                machine_idx=machine_idx,
                n_total_ops=n_total_ops,
                edges=edges,
            )
            if not records:
                return self._error_result(
                    assignments,
                    horizon_start,
                    t0,
                    acceleration_status,
                    "no feasible constructive slot found",
                )
            best_record = self._select_record(records, _ready_p_bar(ready))
            new_assignment = _assignment_from_record(best_record, horizon_start)
            assignments.append(new_assignment)
            machine_idx.add(new_assignment)
            end_offset = best_record["slot"].end_offset
            op_end_offsets[new_assignment.operation_id] = end_offset
            edges.record(new_assignment.operation_id, best_record["slot"].start_offset, end_offset)
            scheduled_ops.add(new_assignment.operation_id)
        return _dispatch_feasible_result(
            solver_name=self.name,
            assignments=assignments,
            makespan=None,
            dispatch_context=dispatch_context,
            problem=problem,
            horizon_start=horizon_start,
            t0=t0,
            metadata={"acceleration": acceleration_status},
        )

    def _select_record(self, records: list[dict[str, Any]], ready_p_bar: float) -> dict[str, Any]:
        """ATCS chooses WHICH operation; earliest completion chooses its machine.

        M2: picking the machine by earliest completion lets a max_parallel
        machine use an idle lane instead of queuing behind a busy one (the ATCS
        slack term otherwise preferred a much later start on the same lane,
        charging a phantom setup). Tie-break (end, setup, material, wc id).
        """
        log_scores = _atcs_log_scores(
            records, ready_p_bar=ready_p_bar, k1=self._k1, k2=self._k2, k3=self._k3
        )
        best_log_score = float("-inf")
        best_record = records[0]
        for record, log_score in zip(records, log_scores, strict=True):
            if log_score > best_log_score:
                best_log_score = log_score
                best_record = record
        best_op_id = best_record["operation"].id
        return min(
            (record for record in records if record["operation"].id == best_op_id),
            key=_slot_preference_key,
        )

    def _timeout_result(
        self,
        assignments: list[Assignment],
        horizon_start: Any,
        t0: float,
        acceleration_status: object,
        time_limit_s: float,
        n_total_ops: int,
        n_scheduled: int,
    ) -> ScheduleResult:
        return ScheduleResult(
            solver_name=self.name,
            status=SolverStatus.TIMEOUT,
            assignments=assignments,
            objective=ObjectiveValues(makespan_minutes=_makespan_of(assignments, horizon_start)),
            duration_ms=int((time.monotonic() - t0) * 1000),
            metadata={
                "acceleration": acceleration_status,
                "partial_schedule": True,
                "scheduled_ops": len(assignments),
                "remaining_ops": n_total_ops - n_scheduled,
                "time_limit_s": time_limit_s,
            },
        )

    def _error_result(
        self,
        assignments: list[Assignment],
        horizon_start: Any,
        t0: float,
        acceleration_status: object,
        error: str,
    ) -> ScheduleResult:
        return ScheduleResult(
            solver_name=self.name,
            status=SolverStatus.ERROR,
            assignments=assignments,
            objective=ObjectiveValues(makespan_minutes=_makespan_of(assignments, horizon_start)),
            duration_ms=int((time.monotonic() - t0) * 1000),
            metadata={"acceleration": acceleration_status, "error": error},
        )


def _greedy_complete(
    dispatch_context: Any,
    orders_by_id: dict[Any, Any],
    horizon_start: Any,
    assignments: list[Assignment],
    scheduled_ops: set[Any],
    op_end_offsets: dict[Any, float],
    remaining: list[Any],
    *,
    time_limit_s: float | None = None,
    t0: float | None = None,
) -> tuple[list[Assignment], float] | None:
    """Completion-to-go rollout; None if the partial cannot be completed."""
    machine_idx = MachineIndex(dispatch_context)
    for assignment in assignments:
        machine_idx.add(assignment)
    out = list(assignments)
    scheduled = set(scheduled_ops)
    offsets = dict(op_end_offsets)
    todo = list(remaining)
    n_scan = len(out) + len(todo)
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
                if t0 is not None and (time.monotonic() - t0) > (time_limit_s or 1e18):
                    return None
                slot = find_earliest_feasible_slot(
                    dispatch_context,
                    out,
                    op,
                    wc_id,
                    pred_end,
                    machine_index=machine_idx,
                    gap_scan=_gap_scan_for(n_scan, op),
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
        deadline: float | None = None
        time_limit_s_raw = kwargs.get("time_limit_s")
        if time_limit_s_raw is not None:
            deadline = time.monotonic() + max(0.1, float(time_limit_s_raw))
        best: ScheduleResult | None = None
        # Always finish width=1 so a zero-remaining budget cannot skip solve().
        for width in range(1, self._beam_width + 1):
            if best is not None and deadline is not None and time.monotonic() >= deadline:
                break
            inner_kwargs = dict(kwargs)
            if deadline is not None:
                inner_kwargs["time_limit_s"] = max(0.1, deadline - time.monotonic())
            candidate = self._solve_core(virtual_problem, width, **inner_kwargs)
            if best is None or (
                candidate.objective.makespan_minutes < best.objective.makespan_minutes
            ):
                best = candidate
            if candidate.status is SolverStatus.TIMEOUT:
                break
        assert best is not None
        _unroll_lane_assignments(best, virtual_to_original)
        return stamp_honest_coverage(problem, best)

    def _solve_core(
        self, problem: ScheduleProblem, beam_width: int, **kwargs: Any
    ) -> ScheduleResult:
        """One filtered beam search of width ``beam_width`` (see :class:`_BeamRun`)."""
        return _BeamRun(self, problem, beam_width, kwargs).execute()


_BeamState = tuple[list[Assignment], set[Any], dict[Any, float], list[Any]]
_BeamCandidate = tuple[
    float,
    tuple[tuple[str, float, str], ...],
    list[Assignment],
    set[Any],
    dict[Any, float],
    list[Any],
]


class _BeamRun:
    """One filtered beam search (Ow & Morton 1989) with a global incumbent.

    Each step expands every live beam: the cheap ATCS index selects up to
    ``beam_width`` children (first stage), a completion-to-go greedy rollout
    ranks them by the ACTUAL makespan (second stage), and the ``beam_width``
    best survive. The incumbent is the best of EVERY completed rollout, so
    makespan is non-increasing in the beam width (Q1).
    """

    def __init__(
        self,
        solver: BeamSearchDispatch,
        problem: ScheduleProblem,
        beam_width: int,
        kwargs: dict[str, Any],
    ) -> None:
        self.solver = solver
        self.problem = problem
        self.beam_width = beam_width
        self.kwargs = kwargs
        self.t0 = time.monotonic()
        self.acceleration_status = get_acceleration_status()
        self.time_limit_s = _dispatch_time_limit(kwargs)
        self.orders_by_id = {o.id: o for o in problem.orders}
        self.wc_by_id = {wc.id: wc for wc in problem.work_centers}
        self.dispatch_context = build_dispatch_context(problem)
        self.horizon_start = problem.planning_horizon_start
        self.total_ops = len(problem.operations)
        self.beams: list[_BeamState] = [([], set(), {}, list(problem.operations))]
        self.incumbent: list[Assignment] | None = None
        self.incumbent_makespan = float("inf")

    def _timeout(self) -> ScheduleResult | None:
        return _beam_deadline_result(
            time_limit_s=self.time_limit_s,
            t0=self.t0,
            incumbent=self.incumbent,
            beams=self.beams,
            solver_name=self.solver.name,
            problem=self.problem,
            acceleration_status=self.acceleration_status,
            beam_width=self.solver._beam_width,
        )

    def execute(self) -> ScheduleResult:
        for _step in range(self.total_ops):
            timed_out = self._timeout()
            if timed_out is not None:
                return timed_out
            candidates: list[_BeamCandidate] = []
            for beam in self.beams:
                timed_out = self._expand(beam, candidates)
                if timed_out is not None:
                    return timed_out
            if not candidates:
                break
            # Keep the B best completion-to-go projections; the deterministic
            # fingerprint tie-break makes top-B nest across beam widths.
            candidates.sort(key=lambda c: (c[0], c[1]))
            self.beams = [(c[2], c[3], c[4], c[5]) for c in candidates[: self.beam_width]]
        if self.incumbent is None:
            # Fall back to standard greedy.
            solver = self.solver
            greedy = GreedyDispatch(k1=solver._k1, k2=solver._k2, k3=solver._k3)
            return greedy.solve(self.problem, **self.kwargs)
        return _dispatch_feasible_result(
            solver_name=self.solver.name,
            assignments=self.incumbent,
            makespan=self.incumbent_makespan,
            dispatch_context=self.dispatch_context,
            problem=self.problem,
            horizon_start=self.horizon_start,
            t0=self.t0,
            metadata={
                "acceleration": self.acceleration_status,
                "beam_width": self.solver._beam_width,
            },
        )

    def _offer_incumbent(self, assignments: list[Assignment], makespan: float) -> None:
        if makespan < self.incumbent_makespan:
            # Snapshot: assignment objects are shared across beams and mutated
            # in place by later steps, so copy to freeze the incumbent.
            self.incumbent = [a.model_copy() for a in assignments]
            self.incumbent_makespan = makespan

    def _expand(self, beam: _BeamState, candidates: list[_BeamCandidate]) -> ScheduleResult | None:
        """Expand one beam into ranked children (or re-rank a completed beam)."""
        assignments, scheduled_ops, op_end_offsets, remaining = beam
        machine_idx = MachineIndex(self.dispatch_context)
        for assignment in assignments:
            machine_idx.add(assignment)
        if not remaining:
            completed = _makespan_of(assignments, self.horizon_start)
            self._offer_incumbent(assignments, completed)
            fingerprint = _partial_fingerprint(assignments, self.horizon_start)
            candidates.append((completed, fingerprint, *beam))
            return None
        ready = [
            op
            for op in remaining
            if op.predecessor_op_id is None or op.predecessor_op_id in scheduled_ops
        ]
        if not ready:
            return None  # Dead beam — precedence cycle
        records, timed_out = _collect_atcs_records(
            problem=self.problem,
            dispatch_context=self.dispatch_context,
            orders_by_id=self.orders_by_id,
            wc_by_id=self.wc_by_id,
            ready=ready,
            assignments=assignments,
            op_end_offsets=op_end_offsets,
            machine_idx=machine_idx,
            n_total_ops=self.total_ops,
            check_timeout=self._timeout,
        )
        if timed_out is not None:
            return timed_out
        if not records:
            return None  # Dead beam
        for record in self._top_children(records, _ready_p_bar(ready)):
            timed_out = self._rollout_child(record, beam, candidates)
            if timed_out is not None:
                return timed_out
        return None

    def _top_children(
        self, records: list[dict[str, Any]], ready_p_bar: float
    ) -> list[dict[str, Any]]:
        """First stage: per-op earliest-completion slot, then the top-B by ATCS.

        M2: collapsing each operation to its earliest-completion slot lets a
        max_parallel machine use an idle lane (mirrors GreedyDispatch). The
        (op id, wc id) tie-break makes the top-B a width-independent prefix,
        so beams(B) contains beams(B-1).
        """
        best_by_op: dict[Any, dict[str, Any]] = {}
        for record in records:
            op_id = record["operation"].id
            existing = best_by_op.get(op_id)
            if existing is None or _slot_preference_key(record) < _slot_preference_key(existing):
                best_by_op[op_id] = record
        collapsed = list(best_by_op.values())
        solver = self.solver
        log_scores = _atcs_log_scores(
            collapsed, ready_p_bar=ready_p_bar, k1=solver._k1, k2=solver._k2, k3=solver._k3
        )
        scored = list(zip(log_scores, collapsed, strict=True))
        scored.sort(key=lambda x: (-x[0], str(x[1]["operation"].id), str(x[1]["work_center_id"])))
        return [record for _score, record in scored[: self.beam_width]]

    def _rollout_child(
        self, record: dict[str, Any], beam: _BeamState, candidates: list[_BeamCandidate]
    ) -> ScheduleResult | None:
        """Second stage: completion-to-go rollout ranks the child by makespan."""
        assignments, scheduled_ops, op_end_offsets, remaining = beam
        best_op = record["operation"]
        new_assignments = [*assignments, _assignment_from_record(record, self.horizon_start)]
        new_offsets = dict(op_end_offsets)
        new_offsets[best_op.id] = record["slot"].end_offset
        new_scheduled = set(scheduled_ops)
        new_scheduled.add(best_op.id)
        new_remaining = [op for op in remaining if op.id != best_op.id]
        timed_out = self._timeout()
        if timed_out is not None:
            return timed_out
        rollout = _greedy_complete(
            self.dispatch_context,
            self.orders_by_id,
            self.horizon_start,
            new_assignments,
            new_scheduled,
            new_offsets,
            new_remaining,
            time_limit_s=self.time_limit_s,
            t0=self.t0,
        )
        if rollout is None:
            return self._timeout()
        full_assignments, projected_mk = rollout
        self._offer_incumbent(full_assignments, projected_mk)
        candidates.append(
            (
                projected_mk,
                _partial_fingerprint(new_assignments, self.horizon_start),
                new_assignments,
                new_scheduled,
                new_offsets,
                new_remaining,
            )
        )
        return None
