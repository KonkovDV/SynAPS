"""Shared constructive scheduling helpers for greedy and repair solvers."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from synaps.accelerators import resource_capacity_window_is_feasible

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from synaps.model import (
        Assignment,
        AuxiliaryResource,
        Operation,
        OperationAuxRequirement,
        ScheduleProblem,
        WorkCenter,
    )


@dataclass(frozen=True)
class DispatchContext:
    horizon_start: datetime
    ops_by_id: dict[UUID, Operation]
    wc_by_id: dict[UUID, WorkCenter]
    setup_minutes: dict[tuple[UUID, UUID, UUID], int]
    material_loss: dict[tuple[UUID, UUID, UUID], float]
    requirements_by_op: dict[UUID, list[OperationAuxRequirement]]
    resources_by_id: dict[UUID, AuxiliaryResource]


class MachineIndex:
    """Incremental per-machine sorted assignment index with lazy caching.

    Avoids O(A) filter+sort on every ``find_earliest_feasible_slot`` call
    by maintaining per-machine buckets via ``bisect.insort``.  Derived data
    (setup-window starts, resource-capacity windows) is computed lazily and
    invalidated on each ``add()``.
    """

    __slots__ = (
        "_context",
        "_by_machine",
        "_all",
        "_setup_window_starts",
        "_resource_windows_cache",
    )

    def __init__(self, context: DispatchContext) -> None:
        self._context = context
        self._by_machine: dict[Any, list[Assignment]] = {}
        self._all: list[Assignment] = []
        self._setup_window_starts: dict[Any, float] | None = None
        self._resource_windows_cache: dict[
            frozenset[Any],
            dict[Any, ResourceWindowSeries],
        ] = {}

    # -- mutators ---------------------------------------------------------

    def add(self, assignment: Assignment) -> None:
        bucket = self._by_machine.setdefault(assignment.work_center_id, [])
        bisect.insort(bucket, assignment, key=lambda a: a.start_time)
        self._all.append(assignment)
        self._setup_window_starts = None
        self._resource_windows_cache.clear()

    # -- queries ----------------------------------------------------------

    def get_machine_assignments(self, work_center_id: Any) -> list[Assignment]:
        return self._by_machine.get(work_center_id, [])

    @property
    def all_assignments(self) -> list[Assignment]:
        return self._all

    def get_setup_window_starts(self) -> dict[Any, float]:
        if self._setup_window_starts is None:
            self._setup_window_starts = self._compute_setup_window_starts()
        return self._setup_window_starts

    def get_resource_windows(
        self, required_resource_ids: set[Any],
    ) -> dict[Any, ResourceWindowSeries]:
        key = frozenset(required_resource_ids)
        if key not in self._resource_windows_cache:
            self._resource_windows_cache[key] = _resource_windows_by_resource(
                self._context,
                self._all,
                self.get_setup_window_starts(),
                required_resource_ids,
            )
        return self._resource_windows_cache[key]

    # -- internal ---------------------------------------------------------

    def _compute_setup_window_starts(self) -> dict[Any, float]:
        ctx = self._context
        result: dict[Any, float] = {}
        for machine_assignments in self._by_machine.values():
            previous: Assignment | None = None
            for assignment in machine_assignments:
                start_offset = _offset_minutes(ctx, assignment, end=False)
                if previous is None:
                    result[assignment.operation_id] = start_offset
                else:
                    prev_state = _assignment_state_id(ctx, previous)
                    cur_state = _assignment_state_id(ctx, assignment)
                    setup_before = (
                        ctx.setup_minutes.get(
                            (assignment.work_center_id, prev_state, cur_state),
                            0,
                        )
                        if prev_state is not None and cur_state is not None
                        else 0
                    )
                    result[assignment.operation_id] = start_offset - setup_before
                previous = assignment
        return result


@dataclass(frozen=True)
class SlotCandidate:
    start_offset: float
    end_offset: float
    setup_minutes: int
    material_loss: float
    aux_resource_ids: list[UUID]


@dataclass(frozen=True)
class ResourceWindowSeries:
    windows: list[tuple[float, float, int]]
    start_offsets: list[float]
    end_offsets: list[float]
    quantities: list[int]


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
                prev_state = _assignment_state_id(context, previous)
                cur_state = _assignment_state_id(context, assignment)
                assignment.setup_minutes = (
                    context.setup_minutes.get(
                        (assignment.work_center_id, prev_state, cur_state),
                        0,
                    )
                    if prev_state is not None and cur_state is not None
                    else 0
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
        material_loss={
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.material_loss
            for entry in problem.setup_matrix
        },
        requirements_by_op=requirements_by_op,
        resources_by_id={resource.id: resource for resource in problem.auxiliary_resources},
    )


def _offset_minutes(context: DispatchContext, assignment: Assignment, *, end: bool) -> float:
    anchor = assignment.end_time if end else assignment.start_time
    return float((anchor - context.horizon_start).total_seconds() / 60.0)


def _assignment_state_id(
    context: DispatchContext,
    assignment: Assignment | None,
) -> Any | None:
    if assignment is None:
        return None
    operation = context.ops_by_id.get(assignment.operation_id)
    return operation.state_id if operation is not None else None


def _assignment_setup_window_starts(
    context: DispatchContext,
    scheduled_assignments: list[Assignment],
) -> dict[Any, float]:
    setup_window_starts: dict[Any, float] = {}
    by_machine: dict[Any, list[Assignment]] = {}
    for assignment in scheduled_assignments:
        by_machine.setdefault(assignment.work_center_id, []).append(assignment)

    for machine_assignments in by_machine.values():
        machine_assignments.sort(key=lambda assignment: assignment.start_time)
        previous_assignment: Assignment | None = None
        for assignment in machine_assignments:
            start_offset = _offset_minutes(context, assignment, end=False)
            if previous_assignment is None:
                setup_window_starts[assignment.operation_id] = start_offset
            else:
                previous_state = _assignment_state_id(context, previous_assignment)
                current_state = _assignment_state_id(context, assignment)
                setup_before = (
                    context.setup_minutes.get(
                        (assignment.work_center_id, previous_state, current_state),
                        0,
                    )
                    if previous_state is not None and current_state is not None
                    else 0
                )
                setup_window_starts[assignment.operation_id] = start_offset - setup_before
            previous_assignment = assignment

    return setup_window_starts


def _resource_is_feasible(
    context: DispatchContext,
    resource_windows_by_resource: dict[UUID, ResourceWindowSeries],
    operation_id: UUID,
    start_offset: float,
    end_offset: float,
    setup_minutes: int,
) -> bool:
    requirements = context.requirements_by_op.get(operation_id, [])
    candidate_window_start = start_offset - setup_minutes

    for requirement in requirements:
        resource = context.resources_by_id.get(requirement.aux_resource_id)
        if resource is None:
            continue
        resource_windows = resource_windows_by_resource.get(requirement.aux_resource_id)
        if resource_windows is None:
            continue
        if not resource_capacity_window_is_feasible(
            window_starts=resource_windows.start_offsets,
            window_ends=resource_windows.end_offsets,
            window_quantities=resource_windows.quantities,
            candidate_start=candidate_window_start,
            candidate_end=end_offset,
            requested_quantity=requirement.quantity_needed,
            pool_size=resource.pool_size,
        ):
            return False

    return True


def _resource_windows_by_resource(
    context: DispatchContext,
    scheduled_assignments: list[Assignment],
    setup_window_starts: dict[Any, float],
    required_resource_ids: set[UUID],
) -> dict[UUID, ResourceWindowSeries]:
    resource_windows: dict[UUID, list[tuple[float, float, int]]] = {
        resource_id: [] for resource_id in required_resource_ids
    }

    for assignment in scheduled_assignments:
        assignment_requirements = context.requirements_by_op.get(assignment.operation_id, [])
        if not assignment_requirements:
            continue

        start_offset = setup_window_starts.get(
            assignment.operation_id,
            _offset_minutes(context, assignment, end=False),
        )
        end_offset = _offset_minutes(context, assignment, end=True)
        for requirement in assignment_requirements:
            if requirement.aux_resource_id not in required_resource_ids:
                continue
            resource_windows.setdefault(requirement.aux_resource_id, []).append(
                (start_offset, end_offset, requirement.quantity_needed)
            )

    return {
        resource_id: ResourceWindowSeries(
            windows=windows,
            start_offsets=[window[0] for window in windows],
            end_offsets=[window[1] for window in windows],
            quantities=[window[2] for window in windows],
        )
        for resource_id, windows in resource_windows.items()
    }


def _candidate_starts(
    context: DispatchContext,
    scheduled_assignments: list[Assignment],
    operation_id: UUID,
    gap_start: float,
    latest_start: float,
    setup_minutes: int,
    resource_windows_by_resource: dict[UUID, ResourceWindowSeries] | None = None,
) -> list[float]:
    starts = {gap_start}
    required_resource_ids = {
        requirement.aux_resource_id
        for requirement in context.requirements_by_op.get(operation_id, [])
    }
    if not required_resource_ids:
        return [gap_start]

    if resource_windows_by_resource is not None:
        for resource_windows in resource_windows_by_resource.values():
            for _other_start, other_end, _quantity in resource_windows.windows:
                release_offset = other_end + setup_minutes
                if gap_start <= release_offset <= latest_start:
                    starts.add(release_offset)
        return sorted(starts)

    for assignment in scheduled_assignments:
        for requirement in context.requirements_by_op.get(assignment.operation_id, []):
            if requirement.aux_resource_id not in required_resource_ids:
                continue
            release_offset = _offset_minutes(context, assignment, end=True) + setup_minutes
            if gap_start <= release_offset <= latest_start:
                starts.add(release_offset)
            break

    return sorted(starts)


def find_earliest_feasible_slot(
    context: DispatchContext,
    scheduled_assignments: list[Assignment],
    operation: Operation,
    work_center_id: UUID,
    earliest_start: float,
    machine_index: MachineIndex | None = None,
) -> SlotCandidate | None:
    work_center = context.wc_by_id.get(work_center_id)
    speed_factor = work_center.speed_factor if work_center is not None else 1.0
    duration = operation.base_duration_min / speed_factor
    aux_resource_ids = [
        requirement.aux_resource_id
        for requirement in context.requirements_by_op.get(operation.id, [])
    ]
    required_resource_ids = set(aux_resource_ids)

    if machine_index is not None:
        setup_window_starts = machine_index.get_setup_window_starts()
        resource_windows_by_resource = machine_index.get_resource_windows(required_resource_ids)
        machine_assignments = machine_index.get_machine_assignments(work_center_id)
    else:
        setup_window_starts = _assignment_setup_window_starts(context, scheduled_assignments)
        resource_windows_by_resource = _resource_windows_by_resource(
            context,
            scheduled_assignments,
            setup_window_starts,
            required_resource_ids,
        )
        machine_assignments = sorted(
            [
                assignment
                for assignment in scheduled_assignments
                if assignment.work_center_id == work_center_id
            ],
            key=lambda assignment: assignment.start_time,
        )

    def evaluate_gap(
        previous: Assignment | None, following: Assignment | None
    ) -> SlotCandidate | None:
        previous_end = _offset_minutes(context, previous, end=True) if previous is not None else 0.0
        previous_state = _assignment_state_id(context, previous)
        setup_before = (
            context.setup_minutes.get((work_center_id, previous_state, operation.state_id), 0)
            if previous_state is not None
            else 0
        )
        material_loss_before = (
            context.material_loss.get((work_center_id, previous_state, operation.state_id), 0.0)
            if previous_state is not None
            else 0.0
        )
        gap_start = max(earliest_start, previous_end + setup_before)

        if following is not None:
            following_start = _offset_minutes(context, following, end=False)
            following_state = _assignment_state_id(context, following)
            setup_after = (
                context.setup_minutes.get(
                    (work_center_id, operation.state_id, following_state),
                    0,
                )
                if following_state is not None
                else 0
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
            setup_before,
            resource_windows_by_resource=resource_windows_by_resource,
        ):
            end_offset = candidate_start + duration
            if candidate_start < gap_start - 1e-9 or candidate_start > latest_start + 1e-9:
                continue
            if _resource_is_feasible(
                context,
                resource_windows_by_resource,
                operation.id,
                candidate_start,
                end_offset,
                setup_before,
            ):
                return SlotCandidate(
                    start_offset=candidate_start,
                    end_offset=end_offset,
                    setup_minutes=setup_before,
                    material_loss=material_loss_before,
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
