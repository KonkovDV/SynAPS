"""Feasibility Checker — validates constraint satisfaction without solving."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from synaps.model import (
        Assignment,
        ScheduleProblem,
    )


class FeasibilityViolation:
    """A single constraint violation."""

    def __init__(
        self, kind: str, message: str, operation_id: Any = None, work_center_id: Any = None
    ) -> None:
        self.kind = kind
        self.message = message
        self.operation_id = operation_id
        self.work_center_id = work_center_id

    def __repr__(self) -> str:
        return f"Violation({self.kind}: {self.message})"


class FeasibilityChecker:
    """Check a set of assignments against the problem constraints.

    Checks performed:
        1. All operations assigned exactly once.
        2. Assigned machine is in eligible set.
        3. Precedence constraints respected (predecessor ends before successor starts).
        4. No time overlap on same machine.
        5. Auxiliary resource pool not exceeded at any point in time across setup
           + processing windows.
    """

    def check(
        self, problem: ScheduleProblem, assignments: list[Assignment]
    ) -> list[FeasibilityViolation]:
        violations: list[FeasibilityViolation] = []
        ops_by_id = {op.id: op for op in problem.operations}
        work_centers_by_id = {work_center.id: work_center for work_center in problem.work_centers}
        setup_lookup = {
            (entry.work_center_id, entry.from_state_id, entry.to_state_id): entry.setup_minutes
            for entry in problem.setup_matrix
        }
        resources_by_id = {resource.id: resource for resource in problem.auxiliary_resources}
        requirements_by_op: dict[Any, list[Any]] = {}
        for requirement in problem.aux_requirements:
            requirements_by_op.setdefault(requirement.operation_id, []).append(requirement)
        assigned: dict[Any, Assignment] = {}

        # 1. All operations assigned exactly once
        for a in assignments:
            if a.operation_id in assigned:
                violations.append(
                    FeasibilityViolation(
                        "DUPLICATE_ASSIGNMENT",
                        f"Operation {a.operation_id} assigned more than once.",
                        operation_id=a.operation_id,
                    )
                )
            assigned[a.operation_id] = a

        for op in problem.operations:
            if op.id not in assigned:
                violations.append(
                    FeasibilityViolation(
                        "MISSING_ASSIGNMENT",
                        f"Operation {op.id} not assigned.",
                        operation_id=op.id,
                    )
                )

        # 2. Eligible machine
        for a in assignments:
            assigned_op = ops_by_id.get(a.operation_id)
            if (
                assigned_op
                and assigned_op.eligible_wc_ids
                and a.work_center_id not in assigned_op.eligible_wc_ids
            ):
                violations.append(
                    FeasibilityViolation(
                        "INELIGIBLE_MACHINE",
                        "Operation "
                        f"{a.operation_id} assigned to ineligible machine {a.work_center_id}.",
                        operation_id=a.operation_id,
                        work_center_id=a.work_center_id,
                    )
                )

        # 3. Precedence
        for op in problem.operations:
            if op.predecessor_op_id and op.id in assigned and op.predecessor_op_id in assigned:
                pred_end = assigned[op.predecessor_op_id].end_time
                cur_start = assigned[op.id].start_time
                if cur_start < pred_end:
                    violations.append(
                        FeasibilityViolation(
                            "PRECEDENCE_VIOLATION",
                            "Operation "
                            f"{op.id} starts at {cur_start} before predecessor ends at {pred_end}.",
                            operation_id=op.id,
                        )
                    )

        # 4. No overlap per machine
        by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            by_machine.setdefault(a.work_center_id, []).append(a)

        setup_window_start_by_op: dict[Any, Any] = {}

        for wc_id, machine_assignments in by_machine.items():
            work_center = work_centers_by_id.get(wc_id)
            max_parallel = work_center.max_parallel if work_center is not None else 1

            if max_parallel > 1:
                events: list[tuple[Any, int, Any]] = []
                for assignment in machine_assignments:
                    events.append((assignment.start_time, 1, assignment.operation_id))
                    events.append((assignment.end_time, -1, assignment.operation_id))

                in_use = 0
                for timestamp, delta, operation_id in sorted(
                    events, key=lambda item: (item[0], 0 if item[1] < 0 else 1)
                ):
                    in_use += delta
                    if in_use > max_parallel:
                        violations.append(
                            FeasibilityViolation(
                                "MACHINE_CAPACITY_VIOLATION",
                                (
                                    f"Machine {wc_id} exceeds max_parallel={max_parallel} "
                                    f"at {timestamp}: "
                                    f"usage is {in_use}."
                                ),
                                operation_id=operation_id,
                                work_center_id=wc_id,
                            )
                        )
                        break
                explicit_lane_metadata = all(
                    assignment.lane_id is not None for assignment in machine_assignments
                )
                lane_sequences: list[list[Assignment]] = []
                if explicit_lane_metadata:
                    assignments_by_lane: dict[Any, list[Assignment]] = {}
                    for assignment in machine_assignments:
                        assignments_by_lane.setdefault(assignment.lane_id, []).append(assignment)
                    if len(assignments_by_lane) > max_parallel:
                        violations.append(
                            FeasibilityViolation(
                                "MACHINE_CAPACITY_VIOLATION",
                                (
                                    f"Machine {wc_id} exposes {len(assignments_by_lane)} lanes, "
                                    f"exceeding max_parallel={max_parallel}."
                                ),
                                work_center_id=wc_id,
                            )
                        )
                    lane_sequences = list(assignments_by_lane.values())
                else:
                    for assignment in sorted(
                        machine_assignments,
                        key=lambda item: (item.start_time, item.end_time),
                    ):
                        current_op = ops_by_id.get(assignment.operation_id)
                        if current_op is None:
                            continue

                        chosen_lane_index: int | None = None
                        chosen_available_at = None
                        for lane_index, lane_assignments in enumerate(lane_sequences):
                            lane_previous_assignment = lane_assignments[-1]
                            previous_op = ops_by_id.get(lane_previous_assignment.operation_id)
                            if previous_op is None:
                                continue
                            required_setup = setup_lookup.get(
                                (wc_id, previous_op.state_id, current_op.state_id),
                                0,
                            )
                            available_at = lane_previous_assignment.end_time + timedelta(
                                minutes=required_setup
                            )
                            if available_at <= assignment.start_time and (
                                chosen_available_at is None or available_at > chosen_available_at
                            ):
                                chosen_lane_index = lane_index
                                chosen_available_at = available_at

                        if chosen_lane_index is None:
                            if len(lane_sequences) < max_parallel:
                                lane_sequences.append([assignment])
                                continue
                            violations.append(
                                FeasibilityViolation(
                                    "SETUP_GAP_VIOLATION",
                                    (
                                        f"Machine {wc_id} cannot place operation "
                                        f"{assignment.operation_id} within max_parallel="
                                        f"{max_parallel} while respecting setup gaps."
                                    ),
                                    operation_id=assignment.operation_id,
                                    work_center_id=wc_id,
                                )
                            )
                            break

                        lane_sequences[chosen_lane_index].append(assignment)

                for lane_assignments in lane_sequences:
                    sorted_assignments = sorted(lane_assignments, key=lambda item: item.start_time)
                    previous_assignment: Assignment | None = None
                    for assignment in sorted_assignments:
                        if previous_assignment is None:
                            setup_window_start_by_op[assignment.operation_id] = (
                                assignment.start_time
                            )
                            previous_assignment = assignment
                            continue

                        if previous_assignment.end_time > assignment.start_time:
                            violations.append(
                                FeasibilityViolation(
                                    "MACHINE_OVERLAP",
                                    "Overlap on machine "
                                    f"{wc_id}: {previous_assignment.operation_id} ends after "
                                    f"{assignment.operation_id} starts.",
                                    work_center_id=wc_id,
                                )
                            )
                            previous_assignment = assignment
                            continue

                        previous_op = ops_by_id.get(previous_assignment.operation_id)
                        current_op = ops_by_id.get(assignment.operation_id)
                        required_setup = 0
                        if previous_op is not None and current_op is not None:
                            required_setup = setup_lookup.get(
                                (wc_id, previous_op.state_id, current_op.state_id),
                                0,
                            )

                        actual_gap_minutes = (
                            assignment.start_time - previous_assignment.end_time
                        ).total_seconds() / 60.0
                        if actual_gap_minutes < required_setup:
                            violations.append(
                                FeasibilityViolation(
                                    "SETUP_GAP_VIOLATION",
                                    (
                                        f"Machine {wc_id} requires {required_setup} minutes of "
                                        f"setup between {previous_assignment.operation_id} and "
                                        f"{assignment.operation_id}, but only "
                                        f"{actual_gap_minutes:.1f} minutes are available."
                                    ),
                                    operation_id=assignment.operation_id,
                                    work_center_id=wc_id,
                                )
                            )

                        setup_window_start_by_op[assignment.operation_id] = (
                            assignment.start_time - timedelta(minutes=required_setup)
                        )
                        previous_assignment = assignment
                continue

            sorted_assignments = sorted(machine_assignments, key=lambda item: item.start_time)
            serial_previous_assignment: Assignment | None = None
            for assignment in sorted_assignments:
                if serial_previous_assignment is None:
                    setup_window_start_by_op[assignment.operation_id] = assignment.start_time
                    serial_previous_assignment = assignment
                    continue

                if serial_previous_assignment.end_time > assignment.start_time:
                    violations.append(
                        FeasibilityViolation(
                            "MACHINE_OVERLAP",
                            "Overlap on machine "
                            f"{wc_id}: {serial_previous_assignment.operation_id} ends after "
                            f"{assignment.operation_id} starts.",
                            work_center_id=wc_id,
                        )
                    )
                    serial_previous_assignment = assignment
                    continue

                previous_op = ops_by_id.get(serial_previous_assignment.operation_id)
                current_op = ops_by_id.get(assignment.operation_id)
                required_setup = 0
                if previous_op is not None and current_op is not None:
                    required_setup = setup_lookup.get(
                        (wc_id, previous_op.state_id, current_op.state_id),
                        0,
                    )
                actual_gap_minutes = (
                    assignment.start_time - serial_previous_assignment.end_time
                ).total_seconds() / 60.0
                if actual_gap_minutes < required_setup:
                    violations.append(
                        FeasibilityViolation(
                            "SETUP_GAP_VIOLATION",
                            (
                                f"Machine {wc_id} requires {required_setup} minutes of "
                                "setup between "
                                f"{serial_previous_assignment.operation_id} and "
                                f"{assignment.operation_id}, "
                                f"but only {actual_gap_minutes:.1f} minutes are available."
                            ),
                            operation_id=assignment.operation_id,
                            work_center_id=wc_id,
                        )
                    )

                setup_window_start_by_op[assignment.operation_id] = (
                    assignment.start_time - timedelta(minutes=required_setup)
                )
                serial_previous_assignment = assignment

        # 5. Auxiliary resource pools
        for resource_id, resource in resources_by_id.items():
            resource_events: list[tuple[Any, int, Any]] = []
            for assignment in assignments:
                for requirement in requirements_by_op.get(assignment.operation_id, []):
                    if requirement.aux_resource_id != resource_id:
                        continue
                    resource_events.append(
                        (
                            setup_window_start_by_op.get(
                                assignment.operation_id, assignment.start_time
                            ),
                            requirement.quantity_needed,
                            assignment.operation_id,
                        )
                    )
                    resource_events.append(
                        (assignment.end_time, -requirement.quantity_needed, assignment.operation_id)
                    )

            in_use = 0
            for timestamp, delta, operation_id in sorted(
                resource_events, key=lambda item: (item[0], 0 if item[1] < 0 else 1)
            ):
                in_use += delta
                if in_use > resource.pool_size:
                    violations.append(
                        FeasibilityViolation(
                            "AUX_RESOURCE_CAPACITY_VIOLATION",
                            (
                                f"Auxiliary resource {resource.code} exceeds pool size "
                                f"{resource.pool_size} "
                                f"at {timestamp}: usage is {in_use}."
                            ),
                            operation_id=operation_id,
                        )
                    )
                    break

        # 6. Horizon bounds
        for a in assignments:
            if a.start_time < problem.planning_horizon_start:
                violations.append(
                    FeasibilityViolation(
                        "HORIZON_BOUND_VIOLATION",
                        (
                            f"Operation {a.operation_id} starts at {a.start_time}, "
                            f"before planning horizon start {problem.planning_horizon_start}."
                        ),
                        operation_id=a.operation_id,
                    )
                )
            if a.end_time > problem.planning_horizon_end:
                violations.append(
                    FeasibilityViolation(
                        "HORIZON_BOUND_VIOLATION",
                        (
                            f"Operation {a.operation_id} ends at {a.end_time}, "
                            f"after planning horizon end {problem.planning_horizon_end}."
                        ),
                        operation_id=a.operation_id,
                    )
                )

        return violations
