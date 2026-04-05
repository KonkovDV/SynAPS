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
        5. Auxiliary resource pool not exceeded at any point in time across setup + processing windows.
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
                        f"Operation {a.operation_id} assigned to ineligible machine {a.work_center_id}.",
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
                            f"Operation {op.id} starts at {cur_start} before predecessor ends at {pred_end}.",
                            operation_id=op.id,
                        )
                    )

        # 4. No overlap per machine
        by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            by_machine.setdefault(a.work_center_id, []).append(a)

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
                                    f"Machine {wc_id} exceeds max_parallel={max_parallel} at {timestamp}: "
                                    f"usage is {in_use}."
                                ),
                                operation_id=operation_id,
                                work_center_id=wc_id,
                            )
                        )
                        break
                continue

            sorted_a = sorted(machine_assignments, key=lambda x: x.start_time)
            for i in range(len(sorted_a) - 1):
                current = sorted_a[i]
                following = sorted_a[i + 1]

                if current.end_time > following.start_time:
                    violations.append(
                        FeasibilityViolation(
                            "MACHINE_OVERLAP",
                            f"Overlap on machine {wc_id}: {current.operation_id} ends after {following.operation_id} starts.",
                            work_center_id=wc_id,
                        )
                    )
                    continue

                current_op = ops_by_id.get(current.operation_id)
                following_op = ops_by_id.get(following.operation_id)
                if current_op is None or following_op is None:
                    continue

                required_setup = setup_lookup.get(
                    (wc_id, current_op.state_id, following_op.state_id), 0
                )
                actual_gap_minutes = (
                    following.start_time - current.end_time
                ).total_seconds() / 60.0
                if actual_gap_minutes < required_setup:
                    violations.append(
                        FeasibilityViolation(
                            "SETUP_GAP_VIOLATION",
                            (
                                f"Machine {wc_id} requires {required_setup} minutes of setup between "
                                f"{current.operation_id} and {following.operation_id}, but only "
                                f"{actual_gap_minutes:.1f} minutes are available."
                            ),
                            operation_id=following.operation_id,
                            work_center_id=wc_id,
                        )
                    )

        setup_window_start_by_op: dict[Any, Any] = {}
        for wc_id, machine_assignments in by_machine.items():
            sorted_assignments = sorted(machine_assignments, key=lambda assignment: assignment.start_time)
            previous_assignment: Assignment | None = None
            for assignment in sorted_assignments:
                if previous_assignment is None:
                    setup_window_start_by_op[assignment.operation_id] = assignment.start_time
                else:
                    previous_op = ops_by_id.get(previous_assignment.operation_id)
                    current_op = ops_by_id.get(assignment.operation_id)
                    required_setup = 0
                    if previous_op is not None and current_op is not None:
                        required_setup = setup_lookup.get(
                            (wc_id, previous_op.state_id, current_op.state_id),
                            0,
                        )
                    setup_window_start_by_op[assignment.operation_id] = assignment.start_time - timedelta(minutes=required_setup)
                previous_assignment = assignment

        # 5. Auxiliary resource pools
        for resource_id, resource in resources_by_id.items():
            events: list[tuple[Any, int, Any]] = []
            for assignment in assignments:
                for requirement in requirements_by_op.get(assignment.operation_id, []):
                    if requirement.aux_resource_id != resource_id:
                        continue
                    events.append(
                        (
                            setup_window_start_by_op.get(assignment.operation_id, assignment.start_time),
                            requirement.quantity_needed,
                            assignment.operation_id,
                        )
                    )
                    events.append(
                        (assignment.end_time, -requirement.quantity_needed, assignment.operation_id)
                    )

            in_use = 0
            for timestamp, delta, operation_id in sorted(
                events, key=lambda item: (item[0], 0 if item[1] < 0 else 1)
            ):
                in_use += delta
                if in_use > resource.pool_size:
                    violations.append(
                        FeasibilityViolation(
                            "AUX_RESOURCE_CAPACITY_VIOLATION",
                            (
                                f"Auxiliary resource {resource.code} exceeds pool size {resource.pool_size} "
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
