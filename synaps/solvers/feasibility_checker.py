"""Feasibility Checker — validates constraint satisfaction without solving."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from synaps.timegrain import duration_minutes

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
        4. No time overlap on same machine (covers machine capacity, lane setup gaps,
           and serial SETUP_GAP_VIOLATION checks).
        5. Auxiliary resource pool not exceeded at any point in time across setup
           + processing windows.
        6. Horizon bounds: no assignment starts before planning_horizon_start or ends
           after planning_horizon_end.
        7. Cross-state SDST entries must exist in setup_matrix (same-state may default
           to 0 minutes when the cell is absent).
    """

    @staticmethod
    def _lookup_required_setup(
        setup_lookup: dict[tuple[Any, Any, Any], int],
        *,
        work_center_id: Any,
        from_state_id: Any,
        to_state_id: Any,
        operation_id: Any,
        violations: list[FeasibilityViolation],
        exhaustive: bool,
        strict_setup_matrix: bool,
    ) -> int | None:
        """Return required setup minutes, or None when a blocking violation was recorded.

        Contract: absent setup cells default to 0 minutes (sparse SDST). When
        ``strict_setup_matrix`` is enabled, a missing *cross-state* cell is a
        hard ``MISSING_SETUP_ENTRY`` violation instead of a silent zero.
        """

        key = (work_center_id, from_state_id, to_state_id)
        if key in setup_lookup:
            return setup_lookup[key]
        if from_state_id == to_state_id or not strict_setup_matrix:
            return 0

        violations.append(
            FeasibilityViolation(
                "MISSING_SETUP_ENTRY",
                (
                    f"Machine {work_center_id} has no setup_matrix entry from state "
                    f"{from_state_id} to {to_state_id} for operation {operation_id}."
                ),
                operation_id=operation_id,
                work_center_id=work_center_id,
            )
        )
        if not exhaustive:
            return None
        return 10**9

    def check(
        self,
        problem: ScheduleProblem,
        assignments: list[Assignment],
        *,
        exhaustive: bool = False,
        strict_setup_matrix: bool = False,
    ) -> list[FeasibilityViolation]:
        violations: list[FeasibilityViolation] = []
        ops_by_id = {op.id: op for op in problem.operations}
        orders_by_id = {order.id: order for order in problem.orders}
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
                        if not exhaustive:
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
                            required_setup = self._lookup_required_setup(
                                setup_lookup,
                                work_center_id=wc_id,
                                from_state_id=previous_op.state_id,
                                to_state_id=current_op.state_id,
                                operation_id=assignment.operation_id,
                                violations=violations,
                                exhaustive=exhaustive,
                                strict_setup_matrix=strict_setup_matrix,
                            )
                            if required_setup is None:
                                return violations
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
                            if not exhaustive:
                                break
                            continue

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
                            looked_up = self._lookup_required_setup(
                                setup_lookup,
                                work_center_id=wc_id,
                                from_state_id=previous_op.state_id,
                                to_state_id=current_op.state_id,
                                operation_id=assignment.operation_id,
                                violations=violations,
                                exhaustive=exhaustive,
                                strict_setup_matrix=strict_setup_matrix,
                            )
                            if looked_up is None:
                                return violations
                            required_setup = looked_up

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
                    looked_up = self._lookup_required_setup(
                        setup_lookup,
                        work_center_id=wc_id,
                        from_state_id=previous_op.state_id,
                        to_state_id=current_op.state_id,
                        operation_id=assignment.operation_id,
                        violations=violations,
                        exhaustive=exhaustive,
                        strict_setup_matrix=strict_setup_matrix,
                    )
                    if looked_up is None:
                        return violations
                    required_setup = looked_up
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
                    if not exhaustive:
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

        # 7. Release dates (M1): an operation may not start before its order's
        # release_date (production meaning: material not available before it).
        for a in assignments:
            checked_op = ops_by_id.get(a.operation_id)
            if checked_op is None:
                continue
            order = orders_by_id.get(checked_op.order_id)
            release = getattr(order, "release_date", None) if order is not None else None
            if release is not None and a.start_time < release:
                violations.append(
                    FeasibilityViolation(
                        "RELEASE_DATE_VIOLATION",
                        (
                            f"Operation {a.operation_id} starts at {a.start_time}, "
                            f"before order release_date {release}."
                        ),
                        operation_id=a.operation_id,
                    )
                )
                if not exhaustive:
                    break

        # 8. Operation durations (P0-3): the assignment span must give the
        # operation enough time to process. ``timegrain.duration_minutes``
        # (ceil(base/speed)) is the canonical RESERVATION target (P0-4), but a
        # solver that legitimately reserved ``round(base/speed)`` is at most
        # ~1 min under ceil and is still physically adequate (round/ceil are
        # both >= the real processing time base/speed to within a minute). We
        # therefore keep a 1-minute inter-solver tolerance: since ceil-1 <
        # base/speed, flagging ``actual < ceil-1`` never false-positives a
        # physically sufficient span, yet still catches a MATERIAL underrun
        # (the repro: 1 min for a ceil-4 op -> 1 < 4-1). Removing this tolerance
        # wrongly rejected round-based schedules (e.g. ALNS' internal validity
        # gate). Setup is a separate leading window, so the span is pure
        # processing.
        for a in assignments:
            checked_op = ops_by_id.get(a.operation_id)
            if checked_op is None:
                continue
            work_center = work_centers_by_id.get(a.work_center_id)
            speed = work_center.speed_factor if work_center is not None else 1.0
            if speed <= 0:
                continue
            expected = duration_minutes(checked_op.base_duration_min, speed)
            actual = (a.end_time - a.start_time).total_seconds() / 60.0
            if actual < expected - 1.0 - 1e-6:
                violations.append(
                    FeasibilityViolation(
                        "DURATION_MISMATCH",
                        (
                            f"Operation {a.operation_id} span {actual:.4f} min is shorter than "
                            f"its canonical processing time {expected} min "
                            f"(ceil(base_duration_min/speed_factor)) beyond the 1-min "
                            f"inter-solver rounding tolerance."
                        ),
                        operation_id=a.operation_id,
                        work_center_id=a.work_center_id,
                    )
                )
                if not exhaustive:
                    break

        return violations
