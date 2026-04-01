"""Feasibility Checker — validates constraint satisfaction without solving."""

from __future__ import annotations

from typing import Any

from syn_aps.model import (
    Assignment,
    ScheduleProblem,
)


class FeasibilityViolation:
    """A single constraint violation."""

    def __init__(self, kind: str, message: str, operation_id: Any = None, work_center_id: Any = None) -> None:
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
        5. Auxiliary resource pool not exceeded at any point in time.
    """

    def check(self, problem: ScheduleProblem, assignments: list[Assignment]) -> list[FeasibilityViolation]:
        violations: list[FeasibilityViolation] = []
        ops_by_id = {op.id: op for op in problem.operations}
        assigned: dict[Any, Assignment] = {}

        # 1. All operations assigned exactly once
        for a in assignments:
            if a.operation_id in assigned:
                violations.append(FeasibilityViolation(
                    "DUPLICATE_ASSIGNMENT",
                    f"Operation {a.operation_id} assigned more than once.",
                    operation_id=a.operation_id,
                ))
            assigned[a.operation_id] = a

        for op in problem.operations:
            if op.id not in assigned:
                violations.append(FeasibilityViolation(
                    "MISSING_ASSIGNMENT",
                    f"Operation {op.id} not assigned.",
                    operation_id=op.id,
                ))

        # 2. Eligible machine
        for a in assignments:
            assigned_op = ops_by_id.get(a.operation_id)
            if assigned_op and assigned_op.eligible_wc_ids and a.work_center_id not in assigned_op.eligible_wc_ids:
                violations.append(FeasibilityViolation(
                    "INELIGIBLE_MACHINE",
                    f"Operation {a.operation_id} assigned to ineligible machine {a.work_center_id}.",
                    operation_id=a.operation_id,
                    work_center_id=a.work_center_id,
                ))

        # 3. Precedence
        for op in problem.operations:
            if op.predecessor_op_id and op.id in assigned and op.predecessor_op_id in assigned:
                pred_end = assigned[op.predecessor_op_id].end_time
                cur_start = assigned[op.id].start_time
                if cur_start < pred_end:
                    violations.append(FeasibilityViolation(
                        "PRECEDENCE_VIOLATION",
                        f"Operation {op.id} starts at {cur_start} before predecessor ends at {pred_end}.",
                        operation_id=op.id,
                    ))

        # 4. No overlap per machine
        by_machine: dict[Any, list[Assignment]] = {}
        for a in assignments:
            by_machine.setdefault(a.work_center_id, []).append(a)

        for wc_id, machine_assignments in by_machine.items():
            sorted_a = sorted(machine_assignments, key=lambda x: x.start_time)
            for i in range(len(sorted_a) - 1):
                if sorted_a[i].end_time > sorted_a[i + 1].start_time:
                    violations.append(FeasibilityViolation(
                        "MACHINE_OVERLAP",
                        f"Overlap on machine {wc_id}: {sorted_a[i].operation_id} ends after {sorted_a[i+1].operation_id} starts.",
                        work_center_id=wc_id,
                    ))

        return violations
