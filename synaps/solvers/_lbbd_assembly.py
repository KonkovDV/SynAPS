"""Shared LBBD post-assembly lane helpers (F3, audit v4).

Used by both ``lbbd_solver`` and ``lbbd_hd_solver`` so parallel machines are
never serialized into a single pseudo-lane when ``lane_id`` metadata is absent.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_DNS, uuid5

from synaps.solvers.feasibility_checker import FeasibilityChecker

if TYPE_CHECKING:
    from uuid import UUID

    from synaps.model import Assignment, Operation, ScheduleProblem, WorkCenter


class LaneGroupResolver:
    """Per-machine lane grouping for post-assembly.

    Lanes come from ``lane_id`` metadata (CP-SAT virtualizes parallel machines
    and tags lanes) or from the same exact lane inference the FeasibilityChecker
    uses; the resolved lane is written back onto each assignment.
    """

    def __init__(
        self,
        wc_by_id: dict[UUID, WorkCenter],
        ops_by_id: dict[UUID, Operation],
        setup_minutes_lookup: dict[tuple[UUID, UUID, UUID], float],
        *,
        lane_tag_prefix: str = "lbbd-lane",
    ) -> None:
        self._wc_by_id = wc_by_id
        self._ops_by_id = ops_by_id
        self._setup_minutes_lookup = setup_minutes_lookup
        self._lane_tag_prefix = lane_tag_prefix
        self._checker: FeasibilityChecker | None = None

    def groups(
        self, work_center_id: UUID, machine_assignments: list[Assignment]
    ) -> list[list[Assignment]]:
        wc = self._wc_by_id.get(work_center_id)
        if wc is None or wc.max_parallel <= 1 or len(machine_assignments) <= 1:
            return [machine_assignments]
        if all(a.lane_id is not None for a in machine_assignments):
            groups: dict[UUID, list[Assignment]] = {}
            for a in machine_assignments:
                groups.setdefault(a.lane_id, []).append(a)  # type: ignore[arg-type]
            return list(groups.values())
        if self._checker is None:
            self._checker = FeasibilityChecker()
        ordered = sorted(machine_assignments, key=lambda a: (a.start_time, a.end_time))
        inferred, _budget_exhausted = self._checker._assign_lanes_exact(
            wc_id=work_center_id,
            ordered=ordered,
            max_parallel=wc.max_parallel,
            ops_by_id=self._ops_by_id,
            setup_lookup=self._setup_minutes_lookup,
            strict_setup_matrix=False,
        )
        if inferred is None:
            return [machine_assignments]
        for lane_index, lane in enumerate(inferred):
            lane_tag = uuid5(
                NAMESPACE_DNS, f"{self._lane_tag_prefix}:{work_center_id}:{lane_index}"
            )
            for a in lane:
                a.lane_id = lane_tag
        return inferred


def stamp_parallel_lane_ids(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Operation],
    *,
    lane_tag_prefix: str = "lbbd-lane",
) -> None:
    """Mutate assignments: infer and write ``lane_id`` on parallel WCs (F3)."""
    if not assignments:
        return
    setup_minutes_lookup = {
        (e.work_center_id, e.from_state_id, e.to_state_id): float(e.setup_minutes)
        for e in problem.setup_matrix
    }
    resolver = LaneGroupResolver(
        wc_by_id={wc.id: wc for wc in problem.work_centers},
        ops_by_id=ops_by_id,
        setup_minutes_lookup=setup_minutes_lookup,
        lane_tag_prefix=lane_tag_prefix,
    )
    by_machine: dict[UUID, list[Assignment]] = {}
    for assignment in assignments:
        by_machine.setdefault(assignment.work_center_id, []).append(assignment)
    for work_center_id, machine_assignments in by_machine.items():
        resolver.groups(work_center_id, machine_assignments)


def enforce_lane_gaps(
    work_center_id: UUID,
    lane: list[Assignment],
    ops_by_id: dict[UUID, Operation],
    setup_lookup: dict[tuple[UUID, UUID, UUID], timedelta],
) -> bool:
    """Shift a serial lane so consecutive pairs respect the setup gap."""
    lane.sort(key=lambda assignment: assignment.start_time)
    changed = False
    previous_assignment: Assignment | None = None
    for assignment in lane:
        if previous_assignment is None:
            assignment.setup_minutes = 0
        else:
            prev_state = ops_by_id[previous_assignment.operation_id].state_id
            next_state = ops_by_id[assignment.operation_id].state_id
            required_setup = setup_lookup.get(
                (work_center_id, prev_state, next_state),
                timedelta(0),
            )
            assignment.setup_minutes = int(required_setup.total_seconds() // 60)
            earliest_next_start = previous_assignment.end_time + required_setup
            if assignment.start_time < earliest_next_start:
                shift = earliest_next_start - assignment.start_time
                assignment.start_time = assignment.start_time + shift
                assignment.end_time = assignment.end_time + shift
                changed = True
        previous_assignment = assignment
    return changed


__all__ = [
    "LaneGroupResolver",
    "enforce_lane_gaps",
    "stamp_parallel_lane_ids",
]
