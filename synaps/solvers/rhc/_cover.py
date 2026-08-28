"""Constructive coverage kernels for RHC greedy fill.

Unconstrained COVER at ≥10k ops uses a non-delay list-schedule (append
after each machine's ready time). Windowed and calendar instances at
n≥2000 use the same one-pass cover (`global_greedy_cover_min_ops` stays
10_000). If the tail is infeasible, insert into the earliest idle gap
(active / insertion SGS). Windowed ops are not bound by the 64-insert
cap. Residual gap-fill remains a safety net.

Academic basis:
    - Pinedo (2016): list scheduling / non-delay dispatch.
    - Kolisch (1996): serial SGS = earliest feasible insertion.
    - Artigues, Lopez, Ayache (Ann. OR 2005, arXiv:cs/0606043): appending
      SGS is not active under SDST; insertion SGS is required.
    - Zhang et al. (Processes 2019): first-fit idle-period / extrusion insert.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from heapq import heappop, heappush
from typing import TYPE_CHECKING, Any

from synaps.accelerators import compute_atcs_log_score, resource_capacity_window_is_feasible
from synaps.calendar import delay_start_to_open_shift, work_centers_have_calendar
from synaps.model import Assignment
from synaps.solvers._dispatch_support import (
    APPEND_GAP_SCAN_MIN_OPS,
    MachineIndex,
    find_earliest_feasible_slot,
    operation_has_hard_windows,
)
from synaps.solvers._time_windows import (
    operation_earliest_offset_minutes,
    operation_latest_finish_offset_minutes,
)
from synaps.timegrain import duration_minutes_for

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from uuid import UUID

    from synaps.model import Operation
    from synaps.solvers._dispatch_support import DispatchContext, SlotCandidate

    _CoverReadyKey = float | tuple[float, str]
    _CoverHeapItem = tuple[_CoverReadyKey, int, str, UUID]

_GLOBAL_GREEDY_COVER_MIN_OPS_DEFAULT = 10_000
_NATIVE_LIST_SCHEDULE_MIN_OPS = 10_000
_MAX_LIST_SCHEDULE_GAP_INSERTS = 64
# Above this, in-pass insertion fragments the calendar; residual one-shot
# gap-fill on an append-only timeline is cheaper (measured 100k hang).
_MAX_LIST_SCHEDULE_GAP_OPS = 80_000
_COVER_ATCS_K1 = 2.0
_COVER_ATCS_K2 = 0.5
_COVER_ATCS_K3 = 0.5
# Non-delay window: ATCS may not jump a ready op whose floor is later
# than min(ready floors) + window. Window 0 is Kolisch parallel SGS
# (non-delay). Unbounded ATCS collapsed month coverage (2026-08-14).
# Nervous month uses one colour SMED (240 min) as a bounded delay
# (Artigues 2005: non-delay is not dominant under SDST; Lee-Pinedo k2
# look-ahead is a wait/setup tradeoff at setup-duration scale).
_COVER_ATCS_FLOOR_WINDOW = 0.0


@dataclass(frozen=True)
class GreedyCoverStats:
    """Counters from one constructive coverage fill."""

    placed: int
    clipped: int
    passes: int
    time_limited: bool
    gap_inserted: int = 0


def should_use_global_greedy_cover(
    *,
    inner_solver_name: str,
    n_ops: int,
    min_ops: int = _GLOBAL_GREEDY_COVER_MIN_OPS_DEFAULT,
    has_hard_windows: bool = False,
    has_machine_calendar: bool = False,
) -> bool:
    """True when RHC should skip rolling windows and list-schedule in one pass.

    ``min_ops`` stays 10_000 for unconstrained COVER. Windowed and calendar
    instances at the leftover-scan scale (n>=2000) list-schedule in one
    pass: rolling 8 h windows from midnight split a 22:00-06:00 night
    and exhaust the 120 s box before residual fill. This is not a
    retune of ``global_greedy_cover_min_ops``.
    """

    if inner_solver_name != "greedy":
        return False
    if n_ops >= min_ops:
        return True
    return (has_hard_windows or has_machine_calendar) and n_ops >= APPEND_GAP_SCAN_MIN_OPS


def _cover_gap_scan_for(n_timeline: int, operation: Any | None = None) -> str:
    """Append-only when the packed timeline is already at the large-n threshold.

    Residual fill against 100k packed assignments used the default full gap
    walk (O(n^2*m)). Windowed leftovers use a clipped interior scan.
    """

    if operation is not None and operation_has_hard_windows(operation):
        return "window" if n_timeline >= APPEND_GAP_SCAN_MIN_OPS else "all"
    return "append" if n_timeline >= APPEND_GAP_SCAN_MIN_OPS else "all"


def _allow_list_schedule_gap(
    *,
    operation: Operation,
    n_ops: int,
    gap_attempts: int,
) -> bool:
    """Windowed ops always insertion-SGS; unconstrained keeps the 64/80k cap.

    A 5k night analog with a 64-insert cap left ~25% of ops on the tail
    after their 8 h window closed. Window-clipped scan is O(gaps in the
    window), not the 100k full-timeline walk.
    """

    if operation_has_hard_windows(operation):
        return True
    return gap_attempts < _MAX_LIST_SCHEDULE_GAP_INSERTS and n_ops < _MAX_LIST_SCHEDULE_GAP_OPS


def _cover_ready_sort_key(
    op: Operation,
    *,
    floor: float,
    horizon_start: datetime,
    cover_ready_rule: str,
) -> float | tuple[float, str]:
    """EDD by latest_finish for fifo windowed ops; ATCS keeps the ready floor."""

    if cover_ready_rule == "atcs":
        return floor
    latest = operation_latest_finish_offset_minutes(op, horizon_start)
    due = float(latest) if latest is not None else floor
    family = str(op.state_id) if operation_has_hard_windows(op) else ""
    return (due, family)


def _cover_placement_floor(
    op: Operation,
    *,
    pred_end: float,
    op_earliest: Mapping[UUID, float],
    horizon_start: datetime,
) -> float:
    """Ready floor: actual pred end plus the published window, not chain-LB.

    RHC ``_propagate_earliest_starts_with_release_and_duration`` adds
    ``pred.earliest + p_min`` into successor earliest. When that p_min is
    larger than the grain actually placed, the successor floor sits past
    ``pred_end`` and closes an 8 h night that still had slack. Windowed
    cover uses the published window and the realized predecessor end.
    """

    if operation_has_hard_windows(op):
        return max(pred_end, operation_earliest_offset_minutes(op, None, horizon_start))
    return max(pred_end, op_earliest.get(op.id, 0.0))


def select_earliest_horizon_slot(
    *,
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    operation: Operation,
    eligible_wc_ids: Sequence[UUID],
    earliest_start: float,
    horizon_minutes: float,
    machine_index: MachineIndex,
    gap_scan: str | None = None,
) -> tuple[SlotCandidate | None, UUID | None, int]:
    """Pick the feasible slot with the earliest completion inside the horizon."""

    scan = gap_scan if gap_scan is not None else _cover_gap_scan_for(len(assignments), operation)
    best_slot: SlotCandidate | None = None
    best_wc: UUID | None = None
    clipped = 0
    for wc_id in eligible_wc_ids:
        slot = find_earliest_feasible_slot(
            dispatch_context,
            assignments,
            operation,
            wc_id,
            earliest_start,
            machine_index=machine_index,
            gap_scan=scan,
        )
        if slot is None:
            continue
        if slot.end_offset > horizon_minutes + 1e-9:
            clipped += 1
            continue
        if best_slot is None or slot.end_offset < best_slot.end_offset:
            best_slot = slot
            best_wc = wc_id
    return best_slot, best_wc, clipped


def place_operations_greedy(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    machine_index: MachineIndex,
    horizon_start: datetime,
    horizon_minutes: float,
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    deadline_exceeded: Callable[[], bool] | None = None,
    max_passes: int | None = None,
) -> GreedyCoverStats:
    """Insert unscheduled ops by earliest feasible completion, in place.

    Operations whose predecessors are not yet scheduled are deferred to a
    later pass. Horizon overflow is counted, not placed. Returns stats; the
    caller owns logging and claim/notary.
    """

    remaining = sorted(
        operations,
        key=lambda op: (
            _cover_ready_sort_key(
                op,
                floor=float(op.seq_in_order),
                horizon_start=horizon_start,
                cover_ready_rule="fifo",
            ),
            op.seq_in_order,
            str(op.id),
        ),
    )
    pass_limit = max_passes if max_passes is not None else max(len(remaining) * 3, 1)
    clipped = 0
    placed = 0
    passes = 0
    time_limited = False
    while remaining and passes < pass_limit:
        if deadline_exceeded is not None and deadline_exceeded():
            time_limited = True
            break
        passes += 1
        still, pass_placed, pass_clipped, hit_deadline = _place_ready_ops_once(
            remaining,
            dispatch_context=dispatch_context,
            assignments=assignments,
            assignment_by_op=assignment_by_op,
            scheduled_ids=scheduled_ids,
            machine_index=machine_index,
            horizon_start=horizon_start,
            horizon_minutes=horizon_minutes,
            op_earliest=op_earliest,
            default_wc_ids=default_wc_ids,
            deadline_exceeded=deadline_exceeded,
        )
        clipped += pass_clipped
        placed += pass_placed
        remaining = still
        if hit_deadline:
            time_limited = True
            break
        if pass_placed == 0:
            break
    return GreedyCoverStats(
        placed=placed,
        clipped=clipped,
        passes=passes,
        time_limited=time_limited,
    )


def _place_ready_ops_once(
    remaining: Sequence[Operation],
    *,
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    machine_index: MachineIndex,
    horizon_start: datetime,
    horizon_minutes: float,
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    deadline_exceeded: Callable[[], bool] | None,
) -> tuple[list[Operation], int, int, bool]:
    """One list-scheduling pass. Returns (still, placed, clipped, time_limited)."""

    still: list[Operation] = []
    placed = 0
    clipped = 0
    for index, op in enumerate(remaining):
        if deadline_exceeded is not None and deadline_exceeded():
            still.extend(remaining[index:])
            return still, placed, clipped, True
        if op.predecessor_op_id and op.predecessor_op_id not in scheduled_ids:
            still.append(op)
            continue
        pred_end = 0.0
        if op.predecessor_op_id:
            pred_assignment = assignment_by_op.get(op.predecessor_op_id)
            if pred_assignment is not None:
                pred_end = (pred_assignment.end_time - horizon_start).total_seconds() / 60.0
        eligible = op.eligible_wc_ids if op.eligible_wc_ids else default_wc_ids
        slot, wc_id, slot_clips = select_earliest_horizon_slot(
            dispatch_context=dispatch_context,
            assignments=assignments,
            operation=op,
            eligible_wc_ids=eligible,
            earliest_start=_cover_placement_floor(
                op,
                pred_end=pred_end,
                op_earliest=op_earliest,
                horizon_start=horizon_start,
            ),
            horizon_minutes=horizon_minutes,
            machine_index=machine_index,
        )
        clipped += slot_clips
        if slot is None or wc_id is None:
            still.append(op)
            continue
        assignment = Assignment(
            operation_id=op.id,
            work_center_id=wc_id,
            start_time=horizon_start + timedelta(minutes=slot.start_offset),
            end_time=horizon_start + timedelta(minutes=slot.end_offset),
            setup_minutes=slot.setup_minutes,
            aux_resource_ids=slot.aux_resource_ids,
        )
        assignments.append(assignment)
        assignment_by_op[op.id] = assignment
        scheduled_ids.add(op.id)
        machine_index.add(assignment)
        placed += 1
    return still, placed, clipped, False


def _tail_start_and_setup(
    *,
    last_end: float,
    last_state: UUID | None,
    op_state: UUID,
    work_center_id: UUID,
    earliest_start: float,
    setup_minutes: Mapping[tuple[UUID, UUID, UUID], int],
) -> tuple[float, int]:
    setup = 0
    if last_state is not None:
        setup = int(setup_minutes.get((work_center_id, last_state, op_state), 0))
    return max(earliest_start, last_end + setup), setup


def _delay_start_for_aux(
    *,
    start: float,
    duration: float,
    setup: int,
    requirements: Sequence[Any],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    resources_by_id: Mapping[UUID, Any],
    horizon_minutes: float,
) -> float | None:
    """Bump a tail start until aux pools fit, or None if the horizon is exceeded."""

    if not requirements:
        return start if start + duration <= horizon_minutes + 1e-9 else None
    for _ in range(256):
        end = start + duration
        if end > horizon_minutes + 1e-9:
            return None
        aux_start = start - setup
        blocked_until = start
        feasible = True
        for requirement in requirements:
            resource = resources_by_id.get(requirement.aux_resource_id)
            if resource is None:
                continue
            windows = aux_windows.get(requirement.aux_resource_id, [])
            if resource_capacity_window_is_feasible(
                window_starts=[window[0] for window in windows],
                window_ends=[window[1] for window in windows],
                window_quantities=[window[2] for window in windows],
                candidate_start=aux_start,
                candidate_end=end,
                requested_quantity=int(requirement.quantity_needed),
                pool_size=int(resource.pool_size),
            ):
                continue
            feasible = False
            overlap_ends = [
                window[1]
                for window in windows
                if window[0] < end + 1e-9 and window[1] > aux_start - 1e-9
            ]
            if overlap_ends:
                blocked_until = max(blocked_until, min(overlap_ends))
        if feasible:
            return start
        if blocked_until <= start + 1e-9:
            return None
        start = blocked_until
    return None


def place_operations_list_schedule(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    deadline_exceeded: Callable[[], bool] | None = None,
    cover_ready_rule: str = "fifo",
    order_priority_by_id: Mapping[UUID, int] | None = None,
    cover_atcs_floor_window: float = _COVER_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float = 0.0,
) -> GreedyCoverStats:
    """Ready-queue non-delay append; insertion SGS on a failed tail (capped)."""

    native_stats = _try_native_list_schedule(
        operations=operations,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        op_earliest=op_earliest,
        default_wc_ids=default_wc_ids,
        cover_ready_rule=cover_ready_rule,
        order_priority_by_id=order_priority_by_id,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    if native_stats is not None:
        return native_stats
    return _place_operations_list_schedule_python(
        operations=operations,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        op_earliest=op_earliest,
        default_wc_ids=default_wc_ids,
        deadline_exceeded=deadline_exceeded,
        cover_ready_rule=cover_ready_rule,
        order_priority_by_id=order_priority_by_id,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )


def _place_operations_list_schedule_python(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    deadline_exceeded: Callable[[], bool] | None = None,
    cover_ready_rule: str = "fifo",
    order_priority_by_id: Mapping[UUID, int] | None = None,
    cover_atcs_floor_window: float = _COVER_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float = 0.0,
) -> GreedyCoverStats:
    """Python parallel SGS with capped insertion into idle gaps."""

    heap, successors = _ready_heap(
        operations,
        op_earliest,
        scheduled_ids,
        horizon_start=horizon_start,
        cover_ready_rule=cover_ready_rule,
    )
    tails, aux_windows = _seed_list_schedule_state(
        assignments, dispatch_context, default_wc_ids, horizon_start
    )
    homes = _build_window_family_homes(operations, dispatch_context, default_wc_ids)
    stats = _run_python_cover_loop(
        heap=heap,
        successors=successors,
        tails=tails,
        aux_windows=aux_windows,
        operations=operations,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        op_earliest=op_earliest,
        default_wc_ids=default_wc_ids,
        deadline_exceeded=deadline_exceeded,
        cover_ready_rule=cover_ready_rule,
        order_priority_by_id=order_priority_by_id,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        window_family_homes=homes,
    )
    extra_placed, extra_gap = _recover_windowed_leftovers(
        operations=operations,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        tails=tails,
        aux_windows=aux_windows,
        op_earliest=op_earliest,
        default_wc_ids=default_wc_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        window_family_homes=homes,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    return GreedyCoverStats(
        placed=stats.placed + extra_placed,
        clipped=max(0, stats.clipped - extra_placed),
        passes=stats.passes,
        time_limited=stats.time_limited,
        gap_inserted=stats.gap_inserted + extra_gap,
    )


def _recover_windowed_leftovers(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    tails: dict[UUID, tuple[float, UUID | None]],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None,
    cover_atcs_exhaust_window: float,
) -> tuple[int, int]:
    placed, gap = _retry_windowed_leftovers(
        operations=operations,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        tails=tails,
        aux_windows=aux_windows,
        op_earliest=op_earliest,
        default_wc_ids=default_wc_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        window_family_homes=window_family_homes,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    ejected, eject_gap = _eject_windowed_leftovers(
        operations=operations,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        op_earliest=op_earliest,
        default_wc_ids=default_wc_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        window_family_homes=window_family_homes,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    return placed + ejected, gap + eject_gap


def _retry_windowed_leftovers(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    tails: dict[UUID, tuple[float, UUID | None]],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None,
    cover_atcs_exhaust_window: float,
) -> tuple[int, int]:
    """Second pass: gap-insert windowed leftovers after the packed timeline exists."""

    machine_index = MachineIndex(dispatch_context)
    machine_index.extend(assignments)
    extra_placed = extra_gap = 0
    pending = [
        op for op in operations if op.id not in scheduled_ids and operation_has_hard_windows(op)
    ]
    for _ in range(len(pending) + 1):
        progress = 0
        for op in pending:
            if op.id in scheduled_ids:
                continue
            if op.predecessor_op_id and op.predecessor_op_id not in scheduled_ids:
                continue
            pred_end = 0.0
            if op.predecessor_op_id:
                pred_asg = assignment_by_op[op.predecessor_op_id]
                pred_end = (pred_asg.end_time - horizon_start).total_seconds() / 60.0
            placed_one, inserted, _end = _place_ready_list_operation(
                op=op,
                floor=_cover_placement_floor(
                    op,
                    pred_end=pred_end,
                    op_earliest=op_earliest,
                    horizon_start=horizon_start,
                ),
                dispatch_context=dispatch_context,
                assignments=assignments,
                assignment_by_op=assignment_by_op,
                scheduled_ids=scheduled_ids,
                tails=tails,
                aux_windows=aux_windows,
                default_wc_ids=default_wc_ids,
                horizon_start=horizon_start,
                horizon_minutes=horizon_minutes,
                allow_gap=True,
                cover_atcs_exhaust_window=cover_atcs_exhaust_window,
                machine_index=machine_index,
                window_family_homes=window_family_homes,
            )
            if not placed_one:
                continue
            extra_placed += 1
            extra_gap += int(inserted)
            progress += 1
        if progress == 0:
            break
    return extra_placed, extra_gap


def _pop_cover_assignment(
    assignment: Assignment,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
) -> None:
    assignments.remove(assignment)
    del assignment_by_op[assignment.operation_id]
    scheduled_ids.discard(assignment.operation_id)


def _eject_windowed_leftovers(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None,
    cover_atcs_exhaust_window: float,
) -> tuple[int, int]:
    """Eject a blocking tail so a windowed leftover and the victim both re-place."""

    extra_placed = extra_gap = 0
    pending = [
        op for op in operations if op.id not in scheduled_ids and operation_has_hard_windows(op)
    ]
    for op in pending:
        if op.id in scheduled_ids:
            continue
        if op.predecessor_op_id and op.predecessor_op_id not in scheduled_ids:
            continue
        gained = _eject_one_windowed_leftover(
            op,
            dispatch_context=dispatch_context,
            assignments=assignments,
            assignment_by_op=assignment_by_op,
            scheduled_ids=scheduled_ids,
            op_earliest=op_earliest,
            default_wc_ids=default_wc_ids,
            horizon_start=horizon_start,
            horizon_minutes=horizon_minutes,
            window_family_homes=window_family_homes,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        )
        extra_placed += int(gained)
        extra_gap += int(gained)
    return extra_placed, extra_gap


def _pred_end_minutes(
    op: Operation,
    assignment_by_op: Mapping[UUID, Assignment],
    horizon_start: datetime,
) -> float:
    if not op.predecessor_op_id:
        return 0.0
    pred_asg = assignment_by_op.get(op.predecessor_op_id)
    if pred_asg is None:
        return 0.0
    return (pred_asg.end_time - horizon_start).total_seconds() / 60.0


def _place_windowed_with_rebuild(
    op: Operation,
    *,
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    default_wc_ids: Sequence[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    op_earliest: Mapping[UUID, float],
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None,
    cover_atcs_exhaust_window: float,
) -> bool:
    tails, aux_windows = _seed_list_schedule_state(
        assignments, dispatch_context, default_wc_ids, horizon_start
    )
    index = MachineIndex(dispatch_context)
    index.extend(assignments)
    placed, _, _ = _place_ready_list_operation(
        op=op,
        floor=_cover_placement_floor(
            op,
            pred_end=_pred_end_minutes(op, assignment_by_op, horizon_start),
            op_earliest=op_earliest,
            horizon_start=horizon_start,
        ),
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        tails=tails,
        aux_windows=aux_windows,
        default_wc_ids=default_wc_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        allow_gap=True,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        machine_index=index,
        window_family_homes=window_family_homes,
    )
    return placed


def _eject_one_windowed_leftover(
    op: Operation,
    *,
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None,
    cover_atcs_exhaust_window: float,
) -> bool:
    if op.earliest_start is None or op.latest_finish is None:
        return False
    eligible = set(op.eligible_wc_ids or default_wc_ids)
    victims = [
        row
        for row in assignments
        if row.work_center_id in eligible
        and op.earliest_start <= row.start_time < op.latest_finish
        and row.operation_id != op.predecessor_op_id
    ]
    victims.sort(key=lambda row: row.start_time, reverse=True)

    def place(target: Operation) -> bool:
        return _place_windowed_with_rebuild(
            target,
            dispatch_context=dispatch_context,
            assignments=assignments,
            assignment_by_op=assignment_by_op,
            scheduled_ids=scheduled_ids,
            default_wc_ids=default_wc_ids,
            horizon_start=horizon_start,
            horizon_minutes=horizon_minutes,
            op_earliest=op_earliest,
            window_family_homes=window_family_homes,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        )

    for victim in victims[:12]:
        victim_op = dispatch_context.ops_by_id.get(victim.operation_id)
        if victim_op is None:
            continue
        _pop_cover_assignment(victim, assignments, assignment_by_op, scheduled_ids)
        if not place(op):
            assignments.append(victim)
            assignment_by_op[victim.operation_id] = victim
            scheduled_ids.add(victim.operation_id)
            continue
        if place(victim_op):
            return True
        leftover_asg = assignment_by_op[op.id]
        _pop_cover_assignment(leftover_asg, assignments, assignment_by_op, scheduled_ids)
        assignments.append(victim)
        assignment_by_op[victim.operation_id] = victim
        scheduled_ids.add(victim.operation_id)
    return False


def _run_python_cover_loop(
    *,
    heap: list[_CoverHeapItem],
    successors: dict[UUID, list[Operation]],
    tails: dict[UUID, tuple[float, UUID | None]],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    deadline_exceeded: Callable[[], bool] | None,
    cover_ready_rule: str,
    order_priority_by_id: Mapping[UUID, int] | None,
    cover_atcs_floor_window: float,
    cover_atcs_exhaust_window: float,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None = None,
) -> GreedyCoverStats:
    clipped = placed = gap_inserted = gap_attempts = 0
    time_limited = False
    ops_by_id = dispatch_context.ops_by_id
    machine_index = MachineIndex(dispatch_context)
    if assignments:
        machine_index.extend(assignments)
    while heap:
        if deadline_exceeded is not None and deadline_exceeded():
            time_limited = True
            break
        _floor, _seq, _sid, op_id = _pop_cover_ready(
            heap,
            cover_ready_rule=cover_ready_rule,
            tails=tails,
            dispatch_context=dispatch_context,
            ops_by_id=ops_by_id,
            horizon_start=horizon_start,
            horizon_minutes=horizon_minutes,
            order_priority_by_id=order_priority_by_id,
            cover_atcs_floor_window=cover_atcs_floor_window,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        )
        step = _place_cover_heap_item(
            op=ops_by_id[op_id],
            operations=operations,
            dispatch_context=dispatch_context,
            assignments=assignments,
            assignment_by_op=assignment_by_op,
            scheduled_ids=scheduled_ids,
            tails=tails,
            aux_windows=aux_windows,
            successors=successors,
            heap=heap,
            horizon_start=horizon_start,
            horizon_minutes=horizon_minutes,
            op_earliest=op_earliest,
            default_wc_ids=default_wc_ids,
            cover_ready_rule=cover_ready_rule,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
            gap_attempts=gap_attempts,
            machine_index=machine_index,
            window_family_homes=window_family_homes,
        )
        if step is None:
            continue
        gap_inserted += step[0]
        gap_attempts += step[1]
        clipped += step[2]
        placed += step[3]
    return GreedyCoverStats(
        placed=placed,
        clipped=clipped,
        passes=1,
        time_limited=time_limited,
        gap_inserted=gap_inserted,
    )


def _place_cover_heap_item(
    *,
    op: Operation,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    tails: dict[UUID, tuple[float, UUID | None]],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    successors: dict[UUID, list[Operation]],
    heap: list[_CoverHeapItem],
    horizon_start: datetime,
    horizon_minutes: float,
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    cover_ready_rule: str,
    cover_atcs_exhaust_window: float,
    gap_attempts: int,
    machine_index: MachineIndex,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None = None,
) -> tuple[int, int, int, int] | None:
    pred_end = 0.0
    if op.predecessor_op_id:
        pred_assignment = assignment_by_op.get(op.predecessor_op_id)
        if pred_assignment is None:
            return None
        pred_end = (pred_assignment.end_time - horizon_start).total_seconds() / 60.0
    allow_gap = _allow_list_schedule_gap(
        operation=op, n_ops=len(operations), gap_attempts=gap_attempts
    )
    placed_one, inserted, end = _place_ready_list_operation(
        op=op,
        floor=_cover_placement_floor(
            op,
            pred_end=pred_end,
            op_earliest=op_earliest,
            horizon_start=horizon_start,
        ),
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        tails=tails,
        aux_windows=aux_windows,
        default_wc_ids=default_wc_ids,
        horizon_start=horizon_start,
        horizon_minutes=horizon_minutes,
        allow_gap=allow_gap,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        machine_index=machine_index,
        window_family_homes=window_family_homes,
    )
    gap_ins = 1 if inserted else 0
    gap_att = 1 if allow_gap and (inserted or not placed_one) else 0
    if not placed_one:
        return (gap_ins, gap_att, 1, 0)
    _enqueue_cover_successors(
        heap,
        successors[op.id],
        end=end,
        op_earliest=op_earliest,
        as_list=cover_ready_rule == "atcs",
        horizon_start=horizon_start,
        cover_ready_rule=cover_ready_rule,
    )
    return (gap_ins, gap_att, 0, 1)


def _enqueue_cover_successors(
    heap: list[_CoverHeapItem],
    successors: Sequence[Operation],
    *,
    end: float,
    op_earliest: Mapping[UUID, float],
    as_list: bool,
    horizon_start: datetime,
    cover_ready_rule: str,
) -> None:
    for succ in successors:
        floor = _cover_placement_floor(
            succ,
            pred_end=end,
            op_earliest=op_earliest,
            horizon_start=horizon_start,
        )
        item = (
            _cover_ready_sort_key(
                succ,
                floor=floor,
                horizon_start=horizon_start,
                cover_ready_rule=cover_ready_rule,
            ),
            succ.seq_in_order,
            str(succ.id),
            succ.id,
        )
        if as_list:
            heap.append(item)
        else:
            heappush(heap, item)


def _ensure_list_schedule_index(
    machine_index: MachineIndex | None,
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
) -> MachineIndex:
    if machine_index is None:
        machine_index = MachineIndex(dispatch_context)
        machine_index.extend(assignments)
    return machine_index


def _best_gap_cover_slot(
    *,
    op: Operation,
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    machine_index: MachineIndex,
    floor: float,
    default_wc_ids: Sequence[UUID],
    horizon_minutes: float,
) -> tuple[float, float, int, UUID, list[UUID]] | None:
    eligible = op.eligible_wc_ids if op.eligible_wc_ids else default_wc_ids
    best_slot, best_wc, _clipped = select_earliest_horizon_slot(
        dispatch_context=dispatch_context,
        assignments=assignments,
        operation=op,
        eligible_wc_ids=eligible,
        earliest_start=floor,
        horizon_minutes=horizon_minutes,
        machine_index=machine_index,
    )
    if best_slot is None or best_wc is None:
        return None
    return (
        best_slot.start_offset,
        best_slot.end_offset,
        best_slot.setup_minutes,
        best_wc,
        list(best_slot.aux_resource_ids),
    )


def _place_ready_list_operation(
    *,
    op: Operation,
    floor: float,
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    tails: dict[UUID, tuple[float, UUID | None]],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    default_wc_ids: Sequence[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    allow_gap: bool = True,
    cover_atcs_exhaust_window: float = 0.0,
    machine_index: MachineIndex | None = None,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None = None,
) -> tuple[bool, bool, float]:
    """Place one ready op. Returns (placed, gap_inserted, end)."""

    slot = _best_list_schedule_slot(
        op=op,
        dispatch_context=dispatch_context,
        tails=tails,
        aux_windows=aux_windows,
        floor=floor,
        default_wc_ids=default_wc_ids,
        horizon_minutes=horizon_minutes,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        window_family_homes=window_family_homes,
    )
    inserted = False
    if slot is None and allow_gap:
        index = _ensure_list_schedule_index(machine_index, dispatch_context, assignments)
        slot = _best_gap_cover_slot(
            op=op,
            dispatch_context=dispatch_context,
            assignments=assignments,
            machine_index=index,
            floor=floor,
            default_wc_ids=default_wc_ids,
            horizon_minutes=horizon_minutes,
        )
        inserted = slot is not None
        machine_index = index
    if slot is None:
        return False, False, 0.0
    start, end, setup, wc_id, aux_ids = slot
    _commit_list_schedule_assignment(
        op=op,
        start=start,
        end=end,
        setup=setup,
        wc_id=wc_id,
        aux_ids=aux_ids,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        tails=tails,
        aux_windows=aux_windows,
        horizon_start=horizon_start,
        machine_index=machine_index,
    )
    return True, inserted, end


def _ready_heap(
    operations: Sequence[Operation],
    op_earliest: Mapping[UUID, float],
    scheduled_ids: set[UUID] | None = None,
    *,
    horizon_start: datetime,
    cover_ready_rule: str = "fifo",
) -> tuple[list[_CoverHeapItem], dict[UUID, list[Operation]]]:
    locked = scheduled_ids or set()
    successors: dict[UUID, list[Operation]] = defaultdict(list)
    heap: list[_CoverHeapItem] = []
    for op in operations:
        if op.predecessor_op_id:
            successors[op.predecessor_op_id].append(op)
    for op in operations:
        if op.id in locked:
            continue
        pred = op.predecessor_op_id
        if pred is not None and pred not in locked:
            continue
        floor = _cover_placement_floor(
            op,
            pred_end=0.0,
            op_earliest=op_earliest,
            horizon_start=horizon_start,
        )
        heappush(
            heap,
            (
                _cover_ready_sort_key(
                    op,
                    floor=floor,
                    horizon_start=horizon_start,
                    cover_ready_rule=cover_ready_rule,
                ),
                op.seq_in_order,
                str(op.id),
                op.id,
            ),
        )
    return heap, successors


def _seed_list_schedule_state(
    assignments: Sequence[Assignment],
    dispatch_context: DispatchContext,
    default_wc_ids: Sequence[UUID],
    horizon_start: datetime,
) -> tuple[dict[UUID, tuple[float, UUID | None]], dict[UUID, list[tuple[float, float, int]]]]:
    tails: dict[UUID, tuple[float, UUID | None]] = dict.fromkeys(default_wc_ids, (0.0, None))
    aux_windows: dict[UUID, list[tuple[float, float, int]]] = {}
    for assignment in assignments:
        end = (assignment.end_time - horizon_start).total_seconds() / 60.0
        start = (assignment.start_time - horizon_start).total_seconds() / 60.0
        last_end, _state = tails.get(assignment.work_center_id, (0.0, None))
        operation = dispatch_context.ops_by_id.get(assignment.operation_id)
        if end + 1e-9 >= last_end:
            tails[assignment.work_center_id] = (
                end,
                operation.state_id if operation is not None else None,
            )
        aux_start = start - float(assignment.setup_minutes)
        for requirement in dispatch_context.requirements_by_op.get(assignment.operation_id, []):
            aux_windows.setdefault(requirement.aux_resource_id, []).append(
                (aux_start, end, int(requirement.quantity_needed))
            )
    return tails, aux_windows


def _pop_cover_ready(
    heap: list[_CoverHeapItem],
    *,
    cover_ready_rule: str,
    tails: dict[UUID, tuple[float, UUID | None]],
    dispatch_context: DispatchContext,
    ops_by_id: Mapping[UUID, Operation],
    horizon_start: datetime,
    horizon_minutes: float,
    order_priority_by_id: Mapping[UUID, int] | None,
    cover_atcs_floor_window: float = _COVER_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float = 0.0,
) -> _CoverHeapItem:
    if cover_ready_rule != "atcs":
        return heappop(heap)
    if len(heap) <= 1:
        return heap.pop()
    return heap.pop(
        _atcs_pick_index(
            heap,
            tails=tails,
            dispatch_context=dispatch_context,
            ops_by_id=ops_by_id,
            horizon_start=horizon_start,
            horizon_minutes=horizon_minutes,
            order_priority_by_id=order_priority_by_id,
            cover_atcs_floor_window=cover_atcs_floor_window,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        )
    )


def _min_cover_setup_and_p(
    operation: Operation,
    tails: dict[UUID, tuple[float, UUID | None]],
    dispatch_context: DispatchContext,
) -> tuple[float, float, float]:
    eligible = operation.eligible_wc_ids or list(tails)
    min_setup = float("inf")
    p_min = float(operation.base_duration_min)
    material = 0.0
    for wc_id in eligible:
        work_center = dispatch_context.wc_by_id.get(wc_id)
        if work_center is None:
            continue
        _last_end, last_state = tails.get(wc_id, (0.0, None))
        setup = 0
        scrap = 0.0
        if last_state is not None:
            setup = int(
                dispatch_context.setup_minutes.get((wc_id, last_state, operation.state_id), 0)
            )
            scrap = float(
                dispatch_context.material_loss.get((wc_id, last_state, operation.state_id), 0.0)
            )
        duration = float(duration_minutes_for(operation, work_center))
        if setup < min_setup:
            min_setup = float(setup)
            p_min = duration
            material = scrap
    if min_setup == float("inf"):
        return 0.0, p_min, 0.0
    return min_setup, p_min, material


def _atcs_pick_index(
    heap: list[_CoverHeapItem],
    *,
    tails: dict[UUID, tuple[float, UUID | None]],
    dispatch_context: DispatchContext,
    ops_by_id: Mapping[UUID, Operation],
    horizon_start: datetime,
    horizon_minutes: float,
    order_priority_by_id: Mapping[UUID, int] | None,
    cover_atcs_floor_window: float = _COVER_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float = 0.0,
) -> int:
    p_sum = setup_sum = setup_n = mat_sum = mat_n = 0.0
    stats: list[tuple[float, float, float, float]] = []
    for item in heap:
        operation = ops_by_id[item[3]]
        setup, processing, material = _min_cover_setup_and_p(operation, tails, dispatch_context)
        p_sum += processing
        if setup > 0:
            setup_sum += setup
            setup_n += 1
        if material > 0:
            mat_sum += material
            mat_n += 1
        stats.append((item[0], setup, processing, material))
    p_bar = max(p_sum / len(heap), 0.1)
    s_bar = max(setup_sum / setup_n, 1.0) if setup_n else 1.0
    m_bar = max(mat_sum / mat_n, 1.0) if mat_n else 1.0
    eligible = _atcs_window_indices(stats, cover_atcs_floor_window, cover_atcs_exhaust_window)
    best_i = eligible[0]
    best_numeric = (float("-inf"), float("inf"), 0)
    best_sid = ""
    for index in eligible:
        item = heap[index]
        operation = ops_by_id[item[3]]
        floor, setup, processing, material = stats[index]
        latest = operation_latest_finish_offset_minutes(operation, horizon_start)
        cap = horizon_minutes if latest is None else min(horizon_minutes, latest)
        score = compute_atcs_log_score(
            weight=max(float((order_priority_by_id or {}).get(operation.order_id, 1)), 1e-9),
            processing_minutes=processing,
            slack=max(cap - processing - floor, 0.0),
            ready_p_bar=p_bar,
            setup_minutes=setup,
            setup_scale=s_bar,
            k1=_COVER_ATCS_K1,
            k2=_COVER_ATCS_K2,
            material_loss=material,
            material_scale=m_bar,
            k3=_COVER_ATCS_K3,
        )
        numeric = (score, -floor, -item[1])
        if numeric > best_numeric or (numeric == best_numeric and item[2] < best_sid):
            best_numeric = numeric
            best_sid = item[2]
            best_i = index
    return best_i


def _atcs_window_indices(
    stats: list[tuple[float, float, float, float]],
    floor_window: float = _COVER_ATCS_FLOOR_WINDOW,
    exhaust_window: float = 0.0,
) -> list[int]:
    """Keep ATCS inside a floor class; exhaust zero-setup runs when asked.

    Mahmoodi/Dooley exhaustive group scheduling: do not switch family while a
    continuation is already in the queue. Pfund ATCSR allows a bounded idle
    for that continuation. A general ATCS floor window (any job, not just
    setup 0) collapsed 16-stage coverage (2026-08-15).
    """

    min_floor = min(row[0] for row in stats)
    if exhaust_window > 0.0:
        cap = min_floor + exhaust_window
        continuations = [
            index for index, row in enumerate(stats) if row[0] <= cap + 1e-9 and row[1] <= 1e-9
        ]
        if continuations:
            return continuations
    cap = min_floor + max(0.0, floor_window)
    return [index for index, row in enumerate(stats) if row[0] <= cap + 1e-9]


def _window_night_key(op: Operation) -> object | None:
    if not operation_has_hard_windows(op) or op.earliest_start is None:
        return None
    return op.earliest_start.date()


def _op_window_minutes(op: Operation) -> float:
    if op.earliest_start is None or op.latest_finish is None:
        return 8 * 60.0
    span = (op.latest_finish - op.earliest_start).total_seconds() / 60.0
    return max(span, 1.0)


def _min_eligible_duration(
    op: Operation,
    dispatch_context: DispatchContext,
    default_wc_ids: Sequence[UUID],
) -> float:
    eligible = op.eligible_wc_ids or list(default_wc_ids)
    best = float("inf")
    for wc_id in eligible:
        work_center = dispatch_context.wc_by_id.get(wc_id)
        if work_center is None:
            continue
        best = min(best, float(duration_minutes_for(op, work_center)))
    return 1.0 if best == float("inf") else best


def _build_window_family_homes(
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    default_wc_ids: Sequence[UUID],
) -> dict[tuple[object, UUID], tuple[UUID, ...]]:
    """FFD: give each (night, state) family the fewest machines that fit the load."""

    grouped: dict[object, dict[UUID, list[Operation]]] = defaultdict(lambda: defaultdict(list))
    for op in operations:
        night = _window_night_key(op)
        if night is None:
            continue
        grouped[night][op.state_id].append(op)
    homes: dict[tuple[object, UUID], tuple[UUID, ...]] = {}
    for night, by_state in grouped.items():
        remaining: dict[UUID, float] = {}
        loads: list[tuple[float, UUID, list[Operation]]] = []
        for state, ops in by_state.items():
            load = sum(_min_eligible_duration(op, dispatch_context, default_wc_ids) for op in ops)
            loads.append((load, state, ops))
        loads.sort(key=lambda row: (-row[0], str(row[1])))
        for load, state, ops in loads:
            width = min(_op_window_minutes(op) for op in ops)
            elig: set[UUID] = set()
            for op in ops:
                elig.update(op.eligible_wc_ids or default_wc_ids)
            chosen: list[UUID] = []
            leftover = load
            ordered = sorted(
                elig,
                key=lambda wc_id: (-remaining.get(wc_id, width), str(wc_id)),
            )
            for wc_id in ordered:
                if leftover <= 1e-9:
                    break
                cap = remaining.setdefault(wc_id, width)
                if cap <= 1e-9:
                    continue
                take = min(cap, leftover)
                remaining[wc_id] = cap - take
                leftover -= take
                chosen.append(wc_id)
            homes[(night, state)] = tuple(chosen)
    return homes


def _windowed_list_slot_key(
    *,
    preferred: bool,
    last_state: UUID | None,
    last_end: float,
    op_state: UUID,
    floor: float,
    setup: int,
    end: float,
    wc_id: UUID,
) -> tuple[int, int, int, int, float, str]:
    """Pack a night by home family, then continuation, before opening another machine."""

    continues = last_state is not None and last_state == op_state
    opens_night = last_end <= floor + 1e-9
    return (
        0 if preferred else 1,
        0 if continues else 1,
        0 if opens_night else 1,
        int(setup),
        end,
        str(wc_id),
    )


def _family_home_wcs(
    op: Operation,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None,
) -> Sequence[UUID]:
    night = _window_night_key(op)
    if night is None or not window_family_homes:
        return ()
    return window_family_homes.get((night, op.state_id), ())


def _cover_slot_beats_best(
    *,
    op: Operation,
    last_state: UUID | None,
    last_end: float,
    floor: float,
    setup: int,
    end: float,
    wc_id: UUID,
    home_wcs: Sequence[UUID],
    best: tuple[float, float, int, UUID, list[UUID]] | None,
    best_last_state: UUID | None,
    best_last_end: float,
    cover_atcs_exhaust_window: float,
) -> bool:
    """Windowed nights use family homes then continuation; unconstrained keeps earliest end."""

    if best is None:
        return True
    if operation_has_hard_windows(op):
        return _windowed_list_slot_key(
            preferred=wc_id in home_wcs,
            last_state=last_state,
            last_end=last_end,
            op_state=op.state_id,
            floor=floor,
            setup=setup,
            end=end,
            wc_id=wc_id,
        ) < _windowed_list_slot_key(
            preferred=best[3] in home_wcs,
            last_state=best_last_state,
            last_end=best_last_end,
            op_state=op.state_id,
            floor=floor,
            setup=best[2],
            end=best[1],
            wc_id=best[3],
        )
    continuation = cover_atcs_exhaust_window > 0.0 and setup <= 1e-9
    best_cont = best[2] <= 1e-9
    if cover_atcs_exhaust_window > 0.0 and continuation != best_cont:
        return continuation
    return end < best[1] or (end == best[1] and str(wc_id) < str(best[3]))


def _commit_list_schedule_assignment(
    *,
    op: Operation,
    start: float,
    end: float,
    setup: int,
    wc_id: UUID,
    aux_ids: list[UUID],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    tails: dict[UUID, tuple[float, UUID | None]],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    horizon_start: datetime,
    machine_index: MachineIndex | None = None,
) -> Assignment:
    assignment = Assignment(
        operation_id=op.id,
        work_center_id=wc_id,
        start_time=horizon_start + timedelta(minutes=start),
        end_time=horizon_start + timedelta(minutes=end),
        setup_minutes=setup,
        aux_resource_ids=aux_ids,
    )
    assignments.append(assignment)
    assignment_by_op[op.id] = assignment
    scheduled_ids.add(op.id)
    last_end, _last_state = tails.get(wc_id, (0.0, None))
    if end + 1e-9 >= last_end:
        tails[wc_id] = (end, op.state_id)
    aux_start = start - setup
    for requirement in dispatch_context.requirements_by_op.get(op.id, []):
        aux_windows.setdefault(requirement.aux_resource_id, []).append(
            (aux_start, end, int(requirement.quantity_needed))
        )
    if machine_index is not None:
        machine_index.add(assignment)
    return assignment


def _best_list_schedule_slot(
    *,
    op: Operation,
    dispatch_context: DispatchContext,
    tails: dict[UUID, tuple[float, UUID | None]],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    floor: float,
    default_wc_ids: Sequence[UUID],
    horizon_minutes: float,
    cover_atcs_exhaust_window: float = 0.0,
    window_family_homes: Mapping[tuple[object, UUID], Sequence[UUID]] | None = None,
) -> tuple[float, float, int, UUID, list[UUID]] | None:
    """Return (start, end, setup, wc_id, aux_ids). Exhaust prefers setup 0."""

    eligible = op.eligible_wc_ids if op.eligible_wc_ids else default_wc_ids
    requirements = dispatch_context.requirements_by_op.get(op.id, [])
    aux_ids = [requirement.aux_resource_id for requirement in requirements]
    home_wcs = _family_home_wcs(op, window_family_homes)
    best: tuple[float, float, int, UUID, list[UUID]] | None = None
    best_last_state: UUID | None = None
    best_last_end = 0.0
    for wc_id in eligible:
        work_center = dispatch_context.wc_by_id.get(wc_id)
        if work_center is None:
            continue
        duration = float(duration_minutes_for(op, work_center))
        last_end, last_state = tails.get(wc_id, (0.0, None))
        start, setup = _tail_start_and_setup(
            last_end=last_end,
            last_state=last_state,
            op_state=op.state_id,
            work_center_id=wc_id,
            earliest_start=floor,
            setup_minutes=dispatch_context.setup_minutes,
        )
        if work_center.calendar:
            occupancy_earliest = start - float(setup)
            cal_occupancy = delay_start_to_open_shift(
                occupancy_earliest,
                duration + float(setup),
                work_center.calendar,
                dispatch_context.horizon_start,
            )
            if cal_occupancy is None:
                continue
            start = cal_occupancy + float(setup)
        latest = operation_latest_finish_offset_minutes(op, dispatch_context.horizon_start)
        cap = horizon_minutes if latest is None else min(horizon_minutes, latest)
        delayed = _delay_start_for_aux(
            start=start,
            duration=duration,
            setup=setup,
            requirements=requirements,
            aux_windows=aux_windows,
            resources_by_id=dispatch_context.resources_by_id,
            horizon_minutes=cap,
        )
        if delayed is None:
            continue
        end = delayed + duration
        if _cover_slot_beats_best(
            op=op,
            last_state=last_state,
            last_end=last_end,
            floor=floor,
            setup=setup,
            end=end,
            wc_id=wc_id,
            home_wcs=home_wcs,
            best=best,
            best_last_state=best_last_state,
            best_last_end=best_last_end,
            cover_atcs_exhaust_window=cover_atcs_exhaust_window,
        ):
            best = (delayed, end, setup, wc_id, aux_ids)
            best_last_state = last_state
            best_last_end = last_end
    return best


def _try_native_list_schedule(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    horizon_start: datetime,
    horizon_minutes: float,
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    cover_ready_rule: str = "fifo",
    order_priority_by_id: Mapping[UUID, int] | None = None,
    cover_atcs_floor_window: float = _COVER_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float = 0.0,
) -> GreedyCoverStats | None:
    """SoA parallel SGS via Rust. None means use the Python cover."""

    import os

    from synaps.accelerators import _native_list_schedule_cover, list_schedule_cover_native

    if os.getenv("SYNAPS_DISABLE_LIST_SCHEDULE_NATIVE") == "1":
        return None
    if assignments or len(operations) < _NATIVE_LIST_SCHEDULE_MIN_OPS:
        return None
    if _native_list_schedule_cover is None:
        return None
    if any(op.machine_duration_overrides for op in operations):
        return None
    packed = _pack_list_schedule_native(
        operations=operations,
        dispatch_context=dispatch_context,
        op_earliest=op_earliest,
        default_wc_ids=default_wc_ids,
        horizon_minutes=horizon_minutes,
        cover_ready_rule=cover_ready_rule,
        order_priority_by_id=order_priority_by_id,
        cover_atcs_floor_window=cover_atcs_floor_window,
        cover_atcs_exhaust_window=cover_atcs_exhaust_window,
    )
    if packed is None:
        return None
    arrays, idx_to_wc = packed
    result = list_schedule_cover_native(**arrays)
    if result is None:
        return None
    starts, ends, machines, setups = result
    placed, clipped = _materialize_native_cover(
        operations=operations,
        dispatch_context=dispatch_context,
        assignments=assignments,
        assignment_by_op=assignment_by_op,
        scheduled_ids=scheduled_ids,
        horizon_start=horizon_start,
        idx_to_wc=idx_to_wc,
        starts=starts,
        ends=ends,
        machines=machines,
        setups=setups,
    )
    return GreedyCoverStats(
        placed=placed,
        clipped=clipped,
        passes=1,
        time_limited=False,
        gap_inserted=0,
    )


def _pack_list_schedule_native(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    op_earliest: Mapping[UUID, float],
    default_wc_ids: Sequence[UUID],
    horizon_minutes: float,
    cover_ready_rule: str = "fifo",
    order_priority_by_id: Mapping[UUID, int] | None = None,
    cover_atcs_floor_window: float = _COVER_ATCS_FLOOR_WINDOW,
    cover_atcs_exhaust_window: float = 0.0,
) -> tuple[dict[str, Any], list[Any]] | None:
    """Pack SoA arrays for ``list_schedule_cover``. Returns None on skip."""

    import numpy as np

    n = len(operations)
    if n == 0 or not default_wc_ids:
        return None
    idx_to_wc = list(default_wc_ids)
    maps: dict[str, Any] = {
        "wc": {wc_id: idx for idx, wc_id in enumerate(idx_to_wc)},
        "op": {op.id: i for i, op in enumerate(operations)},
        "state": {},
        "aux": {res_id: idx for idx, res_id in enumerate(dispatch_context.resources_by_id)},
        "all_wc": idx_to_wc,
    }
    rows = _empty_native_cover_rows(n)
    id_strings = _fill_native_cover_rows(operations, dispatch_context, op_earliest, maps, rows)
    n_wc = len(idx_to_wc)
    n_states = max(len(maps["state"]), 1)
    uuid_rank = np.empty(n, dtype=np.int32)
    for rank, idx in enumerate(sorted(range(n), key=id_strings.__getitem__)):
        uuid_rank[idx] = rank
    speeds = np.array(
        [float(dispatch_context.wc_by_id[wc_id].speed_factor) for wc_id in idx_to_wc],
        dtype=np.float64,
    )
    pools = np.array(
        [int(resource.pool_size) for resource in dispatch_context.resources_by_id.values()],
        dtype=np.int32,
    )
    sdst = _sdst_flat_from_context(
        dispatch_context.setup_minutes, maps["wc"], maps["state"], n_wc, n_states
    )
    arrays = _native_cover_array_dict(
        rows, uuid_rank, speeds, pools, n_wc, n_states, horizon_minutes, sdst
    )
    if cover_ready_rule == "atcs":
        arrays["ready_rule"] = 1
        arrays["weights"] = np.array(
            [float((order_priority_by_id or {}).get(op.order_id, 1)) for op in operations],
            dtype=np.float64,
        )
        arrays["material_loss"] = np.array(
            [float(getattr(op, "material_loss", 0.0) or 0.0) for op in operations],
            dtype=np.float64,
        )
        arrays["floor_window"] = float(max(0.0, cover_atcs_floor_window))
        arrays["exhaust_window"] = float(max(0.0, cover_atcs_exhaust_window))
    calendars = _pack_native_calendars(dispatch_context, idx_to_wc)
    if calendars is not None:
        arrays.update(calendars)
    return arrays, idx_to_wc


def _empty_native_cover_rows(n: int) -> dict[str, Any]:
    import numpy as np

    elig_off = np.empty(n + 1, dtype=np.int64)
    aux_off = np.empty(n + 1, dtype=np.int64)
    elig_off[0] = 0
    aux_off[0] = 0
    return {
        "durations": np.empty(n, dtype=np.float64),
        "preds": np.full(n, -1, dtype=np.int64),
        "seq": np.empty(n, dtype=np.int32),
        "earliest": np.empty(n, dtype=np.float64),
        "latest": np.empty(n, dtype=np.float64),
        "states": np.empty(n, dtype=np.int64),
        "elig_off": elig_off,
        "elig_flat": [],
        "aux_off": aux_off,
        "aux_res_flat": [],
        "aux_qty_flat": [],
    }


def _fill_native_cover_rows(
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    op_earliest: Mapping[UUID, float],
    maps: dict[str, Any],
    rows: dict[str, Any],
) -> list[str]:
    import math

    id_strings: list[str] = []
    wc_id_to_idx = maps["wc"]
    for i, op in enumerate(operations):
        rows["durations"][i] = float(op.base_duration_min)
        rows["seq"][i] = int(op.seq_in_order)
        rows["earliest"][i] = float(op_earliest.get(op.id, 0.0))
        finish = operation_latest_finish_offset_minutes(op, dispatch_context.horizon_start)
        rows["latest"][i] = math.inf if finish is None else float(finish)
        rows["states"][i] = maps["state"].setdefault(op.state_id, len(maps["state"]))
        if op.predecessor_op_id is not None:
            rows["preds"][i] = int(maps["op"].get(op.predecessor_op_id, -1))
        eligible = op.eligible_wc_ids if op.eligible_wc_ids else maps["all_wc"]
        rows["elig_flat"].extend(wc_id_to_idx[wc_id] for wc_id in eligible if wc_id in wc_id_to_idx)
        rows["elig_off"][i + 1] = len(rows["elig_flat"])
        for requirement in dispatch_context.requirements_by_op.get(op.id, []):
            aux_idx = maps["aux"].get(requirement.aux_resource_id)
            if aux_idx is None:
                continue
            rows["aux_res_flat"].append(aux_idx)
            rows["aux_qty_flat"].append(int(requirement.quantity_needed))
        rows["aux_off"][i + 1] = len(rows["aux_res_flat"])
        id_strings.append(str(op.id))
    return id_strings


def _sdst_flat_from_context(
    setup_minutes: Mapping[Any, int],
    wc_id_to_idx: Mapping[Any, int],
    state_to_idx: Mapping[Any, int],
    n_wc: int,
    n_states: int,
) -> Any:
    import numpy as np

    sdst = np.zeros(n_wc * n_states * n_states, dtype=np.float64)
    for (wc_id, from_state, to_state), minutes in setup_minutes.items():
        wi = wc_id_to_idx.get(wc_id)
        fi = state_to_idx.get(from_state)
        ti = state_to_idx.get(to_state)
        if wi is None or fi is None or ti is None:
            continue
        sdst[wi * n_states * n_states + fi * n_states + ti] = float(minutes)
    return sdst


def _pack_native_calendars(
    dispatch_context: DispatchContext,
    idx_to_wc: Sequence[Any],
) -> dict[str, Any] | None:
    """CSR shift spans per machine. None means every work center is 24/7."""

    import numpy as np

    if not work_centers_have_calendar(list(dispatch_context.wc_by_id.values())):
        return None
    opens: list[float] = []
    closes: list[float] = []
    offsets = [0]
    horizon_start = dispatch_context.horizon_start
    for wc_id in idx_to_wc:
        work_center = dispatch_context.wc_by_id.get(wc_id)
        calendar = getattr(work_center, "calendar", None) or []
        for interval in calendar:
            open_m = (interval.start - horizon_start).total_seconds() / 60.0
            close_m = (interval.end - horizon_start).total_seconds() / 60.0
            if close_m > open_m:
                opens.append(open_m)
                closes.append(close_m)
        offsets.append(len(opens))
    return {
        "calendar_offsets": np.asarray(offsets, dtype=np.int64),
        "calendar_open": np.asarray(opens, dtype=np.float64),
        "calendar_close": np.asarray(closes, dtype=np.float64),
    }


def _native_cover_array_dict(
    rows: dict[str, Any],
    uuid_rank: Any,
    speeds: Any,
    pools: Any,
    n_wc: int,
    n_states: int,
    horizon_minutes: float,
    sdst: Any,
) -> dict[str, Any]:
    import numpy as np

    return {
        "base_durations": rows["durations"],
        "predecessor_indices": rows["preds"],
        "seq_in_order": rows["seq"],
        "uuid_rank": uuid_rank,
        "earliest": rows["earliest"],
        "latest_finish": rows["latest"],
        "eligible_offsets": rows["elig_off"],
        "eligible_indices": np.asarray(rows["elig_flat"], dtype=np.int64),
        "state_ids": rows["states"],
        "sdst_setup_flat": sdst,
        "n_wc": n_wc,
        "n_states": n_states,
        "speed_factors": speeds,
        "horizon_minutes": float(horizon_minutes),
        "aux_offsets": rows["aux_off"],
        "aux_resource_indices": np.asarray(rows["aux_res_flat"], dtype=np.int64),
        "aux_quantities": np.asarray(rows["aux_qty_flat"], dtype=np.int32),
        "aux_pool_sizes": pools,
    }


def _materialize_native_cover(
    *,
    operations: Sequence[Operation],
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    assignment_by_op: dict[UUID, Assignment],
    scheduled_ids: set[UUID],
    horizon_start: datetime,
    idx_to_wc: Sequence[Any],
    starts: Any,
    ends: Any,
    machines: Any,
    setups: Any,
) -> tuple[int, int]:
    """Commit native placements with model_construct (skip per-row validation)."""

    placed = 0
    clipped = 0
    n_wc = len(idx_to_wc)
    for i, op in enumerate(operations):
        machine = int(machines[i])
        if machine < 0 or machine >= n_wc:
            clipped += 1
            continue
        start = float(starts[i])
        end = float(ends[i])
        aux_ids = [
            requirement.aux_resource_id
            for requirement in dispatch_context.requirements_by_op.get(op.id, [])
        ]
        assignment = Assignment.model_construct(
            operation_id=op.id,
            work_center_id=idx_to_wc[machine],
            start_time=horizon_start + timedelta(minutes=start),
            end_time=horizon_start + timedelta(minutes=end),
            setup_minutes=int(setups[i]),
            aux_resource_ids=aux_ids,
            lane_id=None,
        )
        assignments.append(assignment)
        assignment_by_op[op.id] = assignment
        scheduled_ids.add(op.id)
        placed += 1
    return placed, clipped
