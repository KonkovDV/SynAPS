"""Cable schedule functionals that the kernel does not search (C2/C4).

``D_max`` is WIP drum count: a reel occupies a drum from first-stage start to
last-stage end, unlike Cumulative aux which frees the token when the op ends.
Hamming R is canonical schedule stability from ``02_CANONICAL_FORM.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from synaps.model import Assignment, ScheduleProblem
from synaps.objective import evaluate


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


def peak_wip_drums(problem: ScheduleProblem, assignments: list[Assignment]) -> int:
    """Sweep-line peak of overlapping reel spans (WIP drums, not processing aux)."""

    events: list[tuple[datetime, int]] = []
    for start, end in _reel_spans(problem, assignments):
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], item[1]))
    peak = 0
    live = 0
    for _when, delta in events:
        live += delta
        if live > peak:
            peak = live
    return peak


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
        "reel_count": len(_reel_spans(problem, assignments)),
    }
    if baseline is not None:
        payload["stability_hamming"] = assignment_hamming(baseline, assignments)
    return payload
