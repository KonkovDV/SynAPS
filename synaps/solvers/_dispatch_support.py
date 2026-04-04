"""Shared constructive scheduling helpers for greedy and repair solvers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from synaps.model import Assignment, ScheduleProblem


@dataclass(frozen=True)
class DispatchContext:
    horizon_start: Any
    ops_by_id: dict[Any, Any]
    wc_by_id: dict[Any, Any]
    setup_minutes: dict[tuple[Any, Any, Any], int]
    requirements_by_op: dict[Any, list[Any]]
    resources_by_id: dict[Any, Any]


@dataclass(frozen=True)
class SlotCandidate:
    start_offset: float
    end_offset: float
    setup_minutes: int
    aux_resource_ids: list[Any]


def recompute_assignment_setups(
    assignments: list[Assignment],
    context: DispatchContext,
) -> float:
    """Recompute each Assignment.setup_minutes based on actual machine sequence.

    After constructive insertion or gap-filling, the *following* operation's
    setup_minutes may still reflect the old predecessor.  This post-hoc pass
    rebuilds setup costs from scratch, matching the CP-SAT solver's
    ``_extract_solution_and_objective`` logic.

    Returns the recomputed aggregate total_setup (sum of all setup_minutes).
    """
    by_machine: dict[Any, list[Assignment]] = {}
    for assignment in assignments:
        by_machine.setdefault(assignment.work_center_id, []).append(assignment)

    total_setup = 0.0
    for machine_assignments in by_machine.values():
        machine_assignments.sort(key=lambda a: a.start_time)
        previous: Assignment | None = None
        for assignment in machine_assignments:
            if previous is None:
                assignment.setup_minutes = 0
            else:
                prev_state = context.ops_by_id[previous.operation_id].state_id
                cur_state = context.ops_by_id[assignment.operation_id].state_id
                assignment.setup_minutes = context.setup_minutes.get(
                    (assignment.work_center_id, prev_state, cur_state), 0
                )
            total_setup += assignment.setup_minutes
            previous = assignment

    return total_setup


def build_dispatch_context(problem: ScheduleProblem) -> DispatchContext:
    requirements_by_op: dict[Any, list[Any]] = {}
    for requirement in problem.aux_requirements:
        requirements_by_op.setdefault(requirement.operation_id, []).append(requirement)

    return DispatchContext(
        horizon_start=problem.planning_horizon_start,
        ops_by_id={operation.id: operation for operation in problem.operations},
        wc_by_id={work_center.id: work_center for work_center in problem.work_centers},
        setup_minutes={
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
            for entry in problem.setup_matrix
        },
        requirements_by_op=requirements_by_op,
        resources_by_id={resource.id: resource for resource in problem.auxiliary_resources},
    )


def _offset_minutes(context: DispatchContext, assignment: Assignment, *, end: bool) -> float:
    anchor = assignment.end_time if end else assignment.start_time
    return (anchor - context.horizon_start).total_seconds() / 60.0


def _resource_is_feasible(
    context: DispatchContext,
    scheduled_assignments: list[Assignment],
    operation_id: Any,
    start_offset: float,
    end_offset: float,
) -> bool:
    requirements = context.requirements_by_op.get(operation_id, [])
    for requirement in requirements:
        resource = context.resources_by_id.get(requirement.aux_resource_id)
        if resource is None:
            continue

        active_demand = 0
        events: list[tuple[float, int]] = []
        for assignment in scheduled_assignments:
            for other_requirement in context.requirements_by_op.get(assignment.operation_id, []):
                if other_requirement.aux_resource_id != requirement.aux_resource_id:
                    continue

                other_start = _offset_minutes(context, assignment, end=False)
                other_end = _offset_minutes(context, assignment, end=True)
                if other_start >= end_offset or other_end <= start_offset:
                    continue

                if other_start <= start_offset < other_end:
                    active_demand += other_requirement.quantity_needed
                else:
                    events.append((other_start, other_requirement.quantity_needed))

                if start_offset < other_end < end_offset:
                    events.append((other_end, -other_requirement.quantity_needed))

        if active_demand + requirement.quantity_needed > resource.pool_size:
            return False

        for _, delta in sorted(events, key=lambda item: (item[0], 0 if item[1] < 0 else 1)):
            active_demand += delta
            if active_demand + requirement.quantity_needed > resource.pool_size:
                return False

    return True


def _candidate_starts(
    context: DispatchContext,
    scheduled_assignments: list[Assignment],
    operation_id: Any,
    gap_start: float,
    latest_start: float,
) -> list[float]:
    starts = {gap_start}
    required_resource_ids = {
        requirement.aux_resource_id
        for requirement in context.requirements_by_op.get(operation_id, [])
    }
    if not required_resource_ids:
        return [gap_start]

    for assignment in scheduled_assignments:
        for requirement in context.requirements_by_op.get(assignment.operation_id, []):
            if requirement.aux_resource_id not in required_resource_ids:
                continue
            release_offset = _offset_minutes(context, assignment, end=True)
            if gap_start <= release_offset <= latest_start:
                starts.add(release_offset)
            break

    return sorted(starts)


def find_earliest_feasible_slot(
    context: DispatchContext,
    scheduled_assignments: list[Assignment],
    operation: Any,
    work_center_id: Any,
    earliest_start: float,
) -> SlotCandidate | None:
    work_center = context.wc_by_id.get(work_center_id)
    speed_factor = work_center.speed_factor if work_center is not None else 1.0
    duration = operation.base_duration_min / speed_factor
    aux_resource_ids = [
        requirement.aux_resource_id
        for requirement in context.requirements_by_op.get(operation.id, [])
    ]

    machine_assignments = sorted(
        [assignment for assignment in scheduled_assignments if assignment.work_center_id == work_center_id],
        key=lambda assignment: assignment.start_time,
    )

    def evaluate_gap(previous: Assignment | None, following: Assignment | None) -> SlotCandidate | None:
        previous_end = _offset_minutes(context, previous, end=True) if previous is not None else 0.0
        previous_state = (
            context.ops_by_id[previous.operation_id].state_id if previous is not None else None
        )
        setup_before = (
            context.setup_minutes.get((work_center_id, previous_state, operation.state_id), 0)
            if previous_state is not None
            else 0
        )
        gap_start = max(earliest_start, previous_end + setup_before)

        if following is not None:
            following_start = _offset_minutes(context, following, end=False)
            following_state = context.ops_by_id[following.operation_id].state_id
            setup_after = context.setup_minutes.get(
                (work_center_id, operation.state_id, following_state),
                0,
            )
            latest_start = following_start - setup_after - duration
        else:
            latest_start = float("inf")

        if gap_start > latest_start + 1e-9:
            return None

        for candidate_start in _candidate_starts(
            context,
            scheduled_assignments,
            operation.id,
            gap_start,
            latest_start,
        ):
            end_offset = candidate_start + duration
            if candidate_start < gap_start - 1e-9 or candidate_start > latest_start + 1e-9:
                continue
            if _resource_is_feasible(
                context,
                scheduled_assignments,
                operation.id,
                candidate_start,
                end_offset,
            ):
                return SlotCandidate(
                    start_offset=candidate_start,
                    end_offset=end_offset,
                    setup_minutes=setup_before,
                    aux_resource_ids=aux_resource_ids,
                )

        return None

    previous_assignment: Assignment | None = None
    for assignment in machine_assignments:
        candidate = evaluate_gap(previous_assignment, assignment)
        if candidate is not None:
            return candidate
        previous_assignment = assignment

    return evaluate_gap(previous_assignment, None)