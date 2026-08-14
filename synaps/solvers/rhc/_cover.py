"""Constructive coverage kernels for RHC greedy fill.

At ≥10k ops GREEDY_COVER uses a non-delay list-schedule (append after each
machine's ready time). Rolling windows and full gap insertion remain for
search inners and residual fill.

Academic basis:
    - Pinedo (2016): list scheduling / non-delay dispatch.
    - Residual RHC fill keeps gap insertion for leftover ops that need holes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from heapq import heappop, heappush
from typing import TYPE_CHECKING, Any

from synaps.accelerators import resource_capacity_window_is_feasible
from synaps.model import Assignment
from synaps.solvers._dispatch_support import find_earliest_feasible_slot
from synaps.timegrain import duration_minutes_for

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from datetime import datetime
    from uuid import UUID

    from synaps.model import Operation
    from synaps.solvers._dispatch_support import DispatchContext, MachineIndex, SlotCandidate

_GLOBAL_GREEDY_COVER_MIN_OPS_DEFAULT = 10_000


@dataclass(frozen=True)
class GreedyCoverStats:
    """Counters from one constructive coverage fill."""

    placed: int
    clipped: int
    passes: int
    time_limited: bool


def should_use_global_greedy_cover(
    *,
    inner_solver_name: str,
    n_ops: int,
    min_ops: int = _GLOBAL_GREEDY_COVER_MIN_OPS_DEFAULT,
) -> bool:
    """True when RHC should skip rolling windows and list-schedule in one pass."""

    return inner_solver_name == "greedy" and n_ops >= min_ops


def select_earliest_horizon_slot(
    *,
    dispatch_context: DispatchContext,
    assignments: list[Assignment],
    operation: Operation,
    eligible_wc_ids: Sequence[UUID],
    earliest_start: float,
    horizon_minutes: float,
    machine_index: MachineIndex,
) -> tuple[SlotCandidate | None, UUID | None, int]:
    """Pick the feasible slot with the earliest completion inside the horizon."""

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

    remaining = sorted(operations, key=lambda op: (op.seq_in_order, str(op.id)))
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
            earliest_start=max(pred_end, op_earliest.get(op.id, 0.0)),
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
) -> GreedyCoverStats:
    """Non-delay list schedule over the ready queue (earliest floor first).

    Placing every seq=0 before any seq=1 parks late-release first-ops on
    machines and starves early chains. The ready heap keeps early successors
    eligible as soon as their predecessor finishes.
    """

    heap, successors = _ready_heap(operations, op_earliest)
    tails: dict[UUID, tuple[float, UUID | None]] = {
        wc_id: (0.0, None) for wc_id in default_wc_ids
    }
    aux_windows: dict[UUID, list[tuple[float, float, int]]] = {}
    clipped = 0
    placed = 0
    time_limited = False
    ops_by_id = dispatch_context.ops_by_id
    while heap:
        if deadline_exceeded is not None and deadline_exceeded():
            time_limited = True
            break
        _floor, _seq, _sid, op_id = heappop(heap)
        op = ops_by_id[op_id]
        pred_end = 0.0
        if op.predecessor_op_id:
            pred_assignment = assignment_by_op.get(op.predecessor_op_id)
            if pred_assignment is None:
                continue
            pred_end = (pred_assignment.end_time - horizon_start).total_seconds() / 60.0
        floor = max(pred_end, op_earliest.get(op.id, 0.0))
        slot = _best_list_schedule_slot(
            op=op,
            dispatch_context=dispatch_context,
            tails=tails,
            aux_windows=aux_windows,
            floor=floor,
            default_wc_ids=default_wc_ids,
            horizon_minutes=horizon_minutes,
        )
        if slot is None:
            clipped += 1
            continue
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
        )
        placed += 1
        for succ in successors[op.id]:
            succ_floor = max(end, op_earliest.get(succ.id, 0.0))
            heappush(heap, (succ_floor, succ.seq_in_order, str(succ.id), succ.id))
    return GreedyCoverStats(
        placed=placed, clipped=clipped, passes=1, time_limited=time_limited
    )


def _ready_heap(
    operations: Sequence[Operation],
    op_earliest: Mapping[UUID, float],
) -> tuple[list[tuple[float, int, str, UUID]], dict[UUID, list[Operation]]]:
    successors: dict[UUID, list[Operation]] = defaultdict(list)
    heap: list[tuple[float, int, str, UUID]] = []
    for op in operations:
        if op.predecessor_op_id:
            successors[op.predecessor_op_id].append(op)
        else:
            heappush(
                heap,
                (op_earliest.get(op.id, 0.0), op.seq_in_order, str(op.id), op.id),
            )
    return heap, successors


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
) -> None:
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
    tails[wc_id] = (end, op.state_id)
    aux_start = start - setup
    for requirement in dispatch_context.requirements_by_op.get(op.id, []):
        aux_windows.setdefault(requirement.aux_resource_id, []).append(
            (aux_start, end, int(requirement.quantity_needed))
        )


def _best_list_schedule_slot(
    *,
    op: Operation,
    dispatch_context: DispatchContext,
    tails: dict[UUID, tuple[float, UUID | None]],
    aux_windows: dict[UUID, list[tuple[float, float, int]]],
    floor: float,
    default_wc_ids: Sequence[UUID],
    horizon_minutes: float,
) -> tuple[float, float, int, UUID, list[UUID]] | None:
    """Return (start, end, setup, wc_id, aux_ids) with earliest completion."""

    eligible = op.eligible_wc_ids if op.eligible_wc_ids else default_wc_ids
    requirements = dispatch_context.requirements_by_op.get(op.id, [])
    aux_ids = [requirement.aux_resource_id for requirement in requirements]
    best: tuple[float, float, int, UUID, list[UUID]] | None = None
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
        delayed = _delay_start_for_aux(
            start=start,
            duration=duration,
            setup=setup,
            requirements=requirements,
            aux_windows=aux_windows,
            resources_by_id=dispatch_context.resources_by_id,
            horizon_minutes=horizon_minutes,
        )
        if delayed is None:
            continue
        end = delayed + duration
        if best is None or end < best[1] or (end == best[1] and str(wc_id) < str(best[3])):
            best = (delayed, end, setup, wc_id, aux_ids)
    return best
