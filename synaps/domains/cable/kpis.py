"""Cable schedule functionals that the kernel does not search (C2/C4).

Three drum peaks (C-R2). They are not interchangeable:

* ``peak_wip_drums`` — reel span from first-stage start to last-stage end
  (plant WIP / Dmax). Not a Cumulative constraint.
* ``peak_processing_drums`` — drum aux on ``[start, end)``. Setup-hold omitted.
* ``peak_aux_hold_drums`` — drum aux on ``[start - setup, end)`` using the
  assignment setup stamp (checker F1 / CP-SAT Cumulative window). Still not
  hold-until-successor (C5a, gated).

Hamming R is canonical schedule stability from ``02_CANONICAL_FORM.md``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from synaps.objective import evaluate

if TYPE_CHECKING:
    from synaps.model import Assignment, ScheduleProblem


def _reel_id_for(operation: Any) -> str:
    attrs = getattr(operation, "domain_attributes", None) or {}
    reel = attrs.get("reel_id")
    if reel:
        return str(reel)
    return str(operation.order_id)


def _reel_spans(
    problem: ScheduleProblem,
    assignments: list[Assignment],
) -> list[tuple[datetime, datetime]]:
    ops_by_id = {operation.id: operation for operation in problem.operations}
    spans: dict[str, tuple[datetime, datetime]] = {}
    for assignment in assignments:
        operation = ops_by_id.get(assignment.operation_id)
        if operation is None:
            continue
        key = _reel_id_for(operation)
        current = spans.get(key)
        if current is None:
            spans[key] = (assignment.start_time, assignment.end_time)
            continue
        start, end = current
        spans[key] = (min(start, assignment.start_time), max(end, assignment.end_time))
    return list(spans.values())


def _peak_from_events(events: list[tuple[datetime, int]]) -> int:
    events.sort(key=lambda item: (item[0], item[1]))
    peak = 0
    live = 0
    for _when, delta in events:
        live += delta
        if live > peak:
            peak = live
    return peak


def _drum_aux_op_ids(problem: ScheduleProblem) -> set[Any]:
    return {item.operation_id for item in problem.aux_requirements}


def peak_processing_drums(problem: ScheduleProblem, assignments: list[Assignment]) -> int:
    """Sweep-line peak of drum aux on ``[start, end)``. Setup-hold is not included."""

    needed = _drum_aux_op_ids(problem)
    events: list[tuple[datetime, int]] = []
    for assignment in assignments:
        if assignment.operation_id not in needed:
            continue
        events.append((assignment.start_time, 1))
        events.append((assignment.end_time, -1))
    return _peak_from_events(events)


def peak_aux_hold_drums(problem: ScheduleProblem, assignments: list[Assignment]) -> int:
    """Sweep-line peak of drum aux on ``[start - setup, end)`` (stamp, F1 window)."""

    needed = _drum_aux_op_ids(problem)
    events: list[tuple[datetime, int]] = []
    for assignment in assignments:
        if assignment.operation_id not in needed:
            continue
        occupancy_start = assignment.start_time - timedelta(minutes=assignment.setup_minutes)
        events.append((occupancy_start, 1))
        events.append((assignment.end_time, -1))
    return _peak_from_events(events)


def peak_wip_drums(problem: ScheduleProblem, assignments: list[Assignment]) -> int:
    """Sweep-line peak of overlapping reel spans (WIP drums, not processing aux)."""

    events: list[tuple[datetime, int]] = []
    for start, end in _reel_spans(problem, assignments):
        events.append((start, 1))
        events.append((end, -1))
    return _peak_from_events(events)


def assignment_hamming(
    baseline: list[Assignment],
    candidate: list[Assignment],
) -> float:
    """Share of baseline ops whose (work_center, start) changed. In [0, 1]."""

    old_by_op = {
        assignment.operation_id: (assignment.work_center_id, assignment.start_time)
        for assignment in baseline
    }
    if not old_by_op:
        return 0.0
    new_by_op = {
        assignment.operation_id: (assignment.work_center_id, assignment.start_time)
        for assignment in candidate
    }
    moved = 0
    for operation_id, key in old_by_op.items():
        if new_by_op.get(operation_id) != key:
            moved += 1
    return moved / len(old_by_op)


def cable_kpis(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    *,
    baseline: list[Assignment] | None = None,
) -> dict[str, float | int]:
    """Bundle kernel objective plus cable functionals for a named profile."""

    objective = evaluate(problem, assignments)
    payload: dict[str, float | int] = {
        "coverage": objective.coverage,
        "unscheduled_operations": objective.unscheduled_operations,
        "makespan_minutes": objective.makespan_minutes,
        "total_setup_minutes": objective.total_setup_minutes,
        "total_material_loss": objective.total_material_loss,
        "total_tardiness_minutes": objective.total_tardiness_minutes,
        "total_energy_kwh": objective.total_energy_kwh,
        "peak_wip_drums": peak_wip_drums(problem, assignments),
        "peak_processing_drums": peak_processing_drums(problem, assignments),
        "peak_aux_hold_drums": peak_aux_hold_drums(problem, assignments),
        "reel_count": len(_reel_spans(problem, assignments)),
    }
    if baseline is not None:
        payload["stability_hamming"] = assignment_hamming(baseline, assignments)
    return payload
