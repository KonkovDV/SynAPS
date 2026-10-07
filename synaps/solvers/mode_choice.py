"""Exactly-one execution mode as optional intervals.

An operation with an empty ``modes`` list is unchanged. A non-empty list is one
optional interval per (machine, mode); exactly one of them is present. Resource
demand is the selected mode's demand, not a single demand copied onto every
alternative.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from synaps.model import Assignment, ScheduleProblem

if TYPE_CHECKING:
    from ortools.sat.python import cp_model
from synaps.timegrain import duration_minutes_for


def build_presence_intervals(
    model: cp_model.CpModel,
    problem: ScheduleProblem,
    eligible_by_op: dict[Any, list[Any]],
    wc_by_id: dict[Any, Any],
    horizon: int,
    starts: dict[tuple[Any, Any], Any],
    ends: dict[tuple[Any, Any], Any],
    intervals: dict[tuple[Any, Any], Any],
    presences: dict[tuple[Any, Any], Any],
    selected_starts: dict[Any, Any],
    selected_ends: dict[Any, Any],
) -> tuple[dict[Any, list[tuple[str, Any]]], dict[Any, list[tuple[Any, list[tuple[Any, int]]]]]]:
    """One optional interval per machine, or per mode when the operation has modes."""

    mode_vars: dict[Any, list[tuple[str, Any]]] = {}
    mode_load: dict[Any, list[tuple[Any, list[tuple[Any, int]]]]] = {}
    for operation in problem.operations:
        selected_start = model.new_int_var(0, horizon, f"selected_start_{operation.id}")
        selected_end = model.new_int_var(0, horizon, f"selected_end_{operation.id}")
        selected_starts[operation.id] = selected_start
        selected_ends[operation.id] = selected_end
        if operation.modes:
            add_mode_choice(
                model,
                operation,
                eligible_by_op[operation.id],
                horizon,
                selected_start,
                selected_end,
                starts,
                ends,
                intervals,
                presences,
                mode_vars,
                mode_load,
            )
            continue
        _add_machine_intervals(
            model,
            operation,
            eligible_by_op[operation.id],
            wc_by_id,
            horizon,
            selected_start,
            selected_end,
            starts,
            ends,
            intervals,
            presences,
        )
    return mode_vars, mode_load


def _add_machine_intervals(
    model: cp_model.CpModel,
    operation: Any,
    eligible_ids: list[Any],
    wc_by_id: dict[Any, Any],
    horizon: int,
    selected_start: Any,
    selected_end: Any,
    starts: dict[tuple[Any, Any], Any],
    ends: dict[tuple[Any, Any], Any],
    intervals: dict[tuple[Any, Any], Any],
    presences: dict[tuple[Any, Any], Any],
) -> None:
    presence_vars: list[Any] = []
    for work_center_id in eligible_ids:
        duration = duration_minutes_for(operation, wc_by_id[work_center_id])
        suffix = f"_{operation.id}_{work_center_id}"
        start_var = model.new_int_var(0, horizon, f"start{suffix}")
        end_var = model.new_int_var(0, horizon, f"end{suffix}")
        presence = model.new_bool_var(f"presence{suffix}")
        interval = model.new_optional_interval_var(
            start_var, duration, end_var, presence, f"interval{suffix}"
        )
        starts[(operation.id, work_center_id)] = start_var
        ends[(operation.id, work_center_id)] = end_var
        intervals[(operation.id, work_center_id)] = interval
        presences[(operation.id, work_center_id)] = presence
        presence_vars.append(presence)
        model.add(selected_start == start_var).only_enforce_if(presence)
        model.add(selected_end == end_var).only_enforce_if(presence)
    model.add_exactly_one(presence_vars)


def add_mode_choice(
    model: cp_model.CpModel,
    operation: Any,
    eligible_ids: list[Any],
    horizon: int,
    selected_start: Any,
    selected_end: Any,
    starts: dict[tuple[Any, Any], Any],
    ends: dict[tuple[Any, Any], Any],
    intervals: dict[tuple[Any, Any], Any],
    presences: dict[tuple[Any, Any], Any],
    mode_vars: dict[Any, list[tuple[str, Any]]],
    mode_load: dict[Any, list[tuple[Any, list[tuple[Any, int]]]]],
) -> None:
    """Bridge one (operation, machine) interval and one optional interval per mode."""

    durations = [mode.duration_min for mode in operation.modes]
    low, high = min(durations), max(durations)
    chosen: list[Any] = []
    loads: list[tuple[Any, list[tuple[Any, int]]]] = []
    recorded = mode_vars.setdefault(operation.id, [])
    for work_center_id in eligible_ids:
        suffix = f"_{operation.id}_{work_center_id}"
        start_var = model.new_int_var(0, horizon, f"start{suffix}")
        end_var = model.new_int_var(0, horizon, f"end{suffix}")
        presence = model.new_bool_var(f"presence{suffix}")
        duration = model.new_int_var(low, high, f"dur{suffix}")
        interval = model.new_optional_interval_var(
            start_var, duration, end_var, presence, f"interval{suffix}"
        )
        starts[(operation.id, work_center_id)] = start_var
        ends[(operation.id, work_center_id)] = end_var
        intervals[(operation.id, work_center_id)] = interval
        presences[(operation.id, work_center_id)] = presence
        model.add(selected_start == start_var).only_enforce_if(presence)
        model.add(selected_end == end_var).only_enforce_if(presence)
        on_machine: list[Any] = []
        for mode in operation.modes:
            flag = model.new_bool_var(f"mode{suffix}_{mode.code}")
            recorded.append((mode.code, flag))
            on_machine.append(flag)
            chosen.append(flag)
            model.add(duration == mode.duration_min).only_enforce_if(flag)
            mode_interval = model.new_optional_interval_var(
                start_var, mode.duration_min, end_var, flag, f"mspan{suffix}_{mode.code}"
            )
            loads.append(
                (
                    mode_interval,
                    [(item.aux_resource_id, item.quantity_needed) for item in mode.requirements],
                )
            )
        model.add(sum(on_machine) == 1).only_enforce_if(presence)
        model.add(sum(on_machine) == 0).only_enforce_if(presence.negated())
    model.add_exactly_one(chosen)
    mode_load[operation.id] = loads


def mode_assignment(
    problem: Any,
    operation: Any,
    work_center_id: Any,
    start_offset: int,
    end_offset: int,
    requirements_by_op: dict[Any, list[Any]],
    solver: cp_model.CpSolver,
    mode_vars: dict[Any, list[tuple[str, Any]]],
) -> Assignment:
    """One assignment, with the mode CP-SAT actually turned on."""

    code: str | None = None
    for candidate, flag in mode_vars.get(operation.id, []):
        if solver.value(flag):
            code = candidate
            break
    if code is None:
        aux_ids = [item.aux_resource_id for item in requirements_by_op.get(operation.id, [])]
    else:
        mode = next(item for item in operation.modes if item.code == code)
        aux_ids = [item.aux_resource_id for item in mode.requirements]
    origin = problem.planning_horizon_start
    return Assignment(
        operation_id=operation.id,
        work_center_id=work_center_id,
        start_time=origin + timedelta(minutes=start_offset),
        end_time=origin + timedelta(minutes=end_offset),
        setup_minutes=0,
        aux_resource_ids=aux_ids,
        mode_code=code,
    )
