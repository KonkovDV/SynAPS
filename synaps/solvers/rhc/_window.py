"""Per-window scheduling kernels for the RHC solver.

This module hosts the four largest pure-functional kernels of the RHC
window loop, decomposed from `synaps/solvers/rhc/_solver.py` as part of
the R7 subpackage split (see AGENTS.md Wave 4 / R7 roadmap):

* `collect_commit_candidates` — pick a precedence-closed subset of inner
  assignments that fully completes inside the active horizon and the
  rolling commit boundary.
* `reanchor_inner_assignments` — replay an inner solver's assignment
  bundle on top of the frozen schedule, finding earliest feasible slots
  while preserving precedence and machine/setup constraints.
* `select_backtracking_assignments` — when bounded backtracking is on,
  rewind a tail of recent commits whose end time falls into the
  next-window backtracking horizon.
* `stabilize_temporal_consistency` — bounded forward-only pass that
  repairs residual precedence and machine/setup conflicts in an
  assignment list before final objective evaluation.

Academic basis:

* The "commit set must be precedence-closed" invariant in
  `collect_commit_candidates` mirrors the standard rolling-horizon
  freeze policy from receding-horizon control (Rawlings & Mayne 2009):
  partial precedence closures across the horizon boundary cause
  reanchoring failures in the next window.
* `reanchor_inner_assignments` follows the slot-search reanchor pattern
  described in Pernas-Alvarez et al. (2025, IJPR) for CP-based
  decomposition of large shipbuilding schedules: the inner solver's
  output is replayed against the frozen baseline, accepting only
  slot-feasible reassignments and rolling back atomically on failure.
* The topological-stabilizer pass implements the standard "as-early-as-
  possible repair" used in scheduling literature (e.g., Pinedo 2016):
  forward-only shifts respecting precedence and setup transitions
  cannot create new conflicts and converge in at most O(passes * |ops|)
  steps.

All functions in this module are side-effect-free with respect to
solver-owned state: they may mutate only the ``Assignment`` objects in
their input list (the temporal-consistency stabilizer is by design an
in-place repair).
"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from synaps.model import Assignment

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from uuid import UUID

    from synaps.model import Operation
    from synaps.solvers._dispatch_support import DispatchContext


# ---------------------------------------------------------------------------
# Commit candidate selection
# ---------------------------------------------------------------------------


def collect_commit_candidates(
    assignments: list[Assignment],
    *,
    commit_boundary: float,
    commit_all: bool,
    frozen_ids: set[UUID],
    eligible_ids: set[UUID] | None,
    horizon_start: datetime,
    horizon_minutes: float,
    ops_by_id: Mapping[UUID, Operation],
) -> tuple[dict[UUID, Assignment], int]:
    """Pick the precedence-closed set of inner assignments to freeze.

    Returns ``(candidates, horizon_clipped_count)``:
    the caller is expected to fold the clipped count into its own
    `horizon_clipped_assignments` counter.

    Selection rules (preserved from the original closure):

    * Drop assignments whose ``operation_id`` is already in
      ``frozen_ids`` (already committed in a previous window).
    * Drop assignments not in ``eligible_ids`` if that set is provided
      (used by the rewind path to limit the eligible scope).
    * Drop assignments ending past ``horizon_minutes`` (count them as
      clipped) — they cannot be committed.
    * Keep only assignments ending no later than ``commit_boundary``
      unless ``commit_all`` is True; the rest survive as the overlap
      tail for the next window.
    * Iteratively drop any candidate whose direct predecessor is neither
      already frozen nor present in the candidate set; repeat until
      stable. This precedence closure is required so the next window
      can extend the frozen schedule without orphaned operations.

    Pure function: does not mutate any of its inputs.
    """
    candidates: dict[UUID, Assignment] = {}
    horizon_clipped_count = 0

    for assignment in assignments:
        op_id = assignment.operation_id
        if op_id in frozen_ids:
            continue
        if eligible_ids is not None and op_id not in eligible_ids:
            continue

        end_offset = (assignment.end_time - horizon_start).total_seconds() / 60.0
        if end_offset > horizon_minutes + 1e-9:
            horizon_clipped_count += 1
            continue

        # Freeze only work that fully completes inside the active horizon.
        # Assignments crossing the rolling boundary survive as overlap tail
        # so they can seed the next window.
        if end_offset <= commit_boundary + 1e-9 or commit_all:
            candidates[op_id] = assignment

    # Commit set must be precedence-closed: drop ops whose predecessors
    # are neither already frozen nor in the candidate set itself.
    changed = True
    while changed:
        changed = False
        for op_id in list(candidates.keys()):
            operation = ops_by_id.get(op_id)
            predecessor_op_id = (
                operation.predecessor_op_id if operation is not None else None
            )
            if predecessor_op_id is None:
                continue
            if (
                predecessor_op_id not in frozen_ids
                and predecessor_op_id not in candidates
            ):
                del candidates[op_id]
                changed = True

    return candidates, horizon_clipped_count


# ---------------------------------------------------------------------------
# Reanchor inner assignments on the frozen baseline
# ---------------------------------------------------------------------------


def reanchor_inner_assignments(
    assignments: list[Assignment],
    *,
    frozen_assignments: list[Assignment],
    frozen_assignment_by_op: dict[UUID, Assignment],
    dispatch_context: DispatchContext,
    machine_index_factory: Any,
    find_earliest_feasible_slot: Any,
    ops_by_id: Mapping[UUID, Operation],
    op_earliest: Mapping[UUID, float],
    op_positions: Mapping[UUID, int],
    horizon_start: datetime,
) -> tuple[list[Assignment], int]:
    """Replay ``assignments`` on top of ``frozen_assignments``.

    Each pending assignment is reassigned to the earliest feasible slot
    on its work center, respecting:

    * its operation's predecessor end time (if assigned),
    * its operation's release/earliest-start (``op_earliest``), and
    * the existing scheduled assignments on that work center.

    The procedure is monotone: each pass either anchors at least one
    pending assignment or aborts. If a full pass makes no progress, or
    any assignment is left unanchored after the bounded number of
    passes, the original assignments are returned untouched and the
    changed-count is reported as zero (atomic rollback).

    ``machine_index_factory`` is ``MachineIndex`` (the constructor; we
    cannot import it directly from this module without creating a
    runtime cycle), and ``find_earliest_feasible_slot`` is the matching
    slot finder. Both are passed as parameters to keep the dependency
    direction Solver -> Window helpers (and never the other way).

    Returns ``(reanchored_assignments, changed_count)`` where
    ``changed_count`` is the number of assignments whose start, end, or
    work center differ from the original assignment.

    Pure function: does not mutate inputs except by appending to
    locally-allocated lists.
    """
    if not assignments or not frozen_assignments:
        return list(assignments), 0

    original_by_op = {
        assignment.operation_id: assignment for assignment in assignments
    }
    scheduled_assignments = list(frozen_assignments)
    machine_index = machine_index_factory(dispatch_context)
    for assignment in scheduled_assignments:
        machine_index.add(assignment)

    anchored_by_op = dict(frozen_assignment_by_op)
    pending_assignments = sorted(
        assignments,
        key=lambda assignment: (
            assignment.start_time,
            ops_by_id[assignment.operation_id].seq_in_order,
            op_positions[assignment.operation_id],
        ),
    )
    reanchored_assignments: list[Assignment] = []

    for _ in range(len(pending_assignments) + 1):
        if not pending_assignments:
            break
        progress_made = False
        next_pending: list[Assignment] = []

        for assignment in pending_assignments:
            operation = ops_by_id[assignment.operation_id]
            earliest_start = op_earliest.get(operation.id, 0.0)
            if operation.predecessor_op_id is not None:
                predecessor_assignment = anchored_by_op.get(operation.predecessor_op_id)
                if predecessor_assignment is None:
                    next_pending.append(assignment)
                    continue
                predecessor_end = (
                    predecessor_assignment.end_time - horizon_start
                ).total_seconds() / 60.0
                earliest_start = max(earliest_start, predecessor_end)

            slot = find_earliest_feasible_slot(
                dispatch_context,
                scheduled_assignments,
                operation,
                assignment.work_center_id,
                earliest_start,
                machine_index=machine_index,
            )
            if slot is None:
                next_pending.append(assignment)
                continue

            anchored_assignment = Assignment(
                operation_id=operation.id,
                work_center_id=assignment.work_center_id,
                start_time=horizon_start + timedelta(minutes=slot.start_offset),
                end_time=horizon_start + timedelta(minutes=slot.end_offset),
                setup_minutes=slot.setup_minutes,
                aux_resource_ids=slot.aux_resource_ids,
            )
            scheduled_assignments.append(anchored_assignment)
            machine_index.add(anchored_assignment)
            anchored_by_op[operation.id] = anchored_assignment
            reanchored_assignments.append(anchored_assignment)
            progress_made = True

        if not progress_made:
            return list(assignments), 0
        pending_assignments = next_pending

    if pending_assignments:
        return list(assignments), 0

    changed_assignment_count = sum(
        1
        for assignment in reanchored_assignments
        if original_by_op[assignment.operation_id].start_time != assignment.start_time
        or original_by_op[assignment.operation_id].end_time != assignment.end_time
        or original_by_op[assignment.operation_id].work_center_id
        != assignment.work_center_id
    )
    return sorted(
        reanchored_assignments,
        key=lambda assignment: assignment.start_time,
    ), changed_assignment_count


# ---------------------------------------------------------------------------
# Backtracking selection
# ---------------------------------------------------------------------------


def select_backtracking_assignments(
    *,
    window_start_offset: float,
    backtracking_enabled: bool,
    backtracking_tail_minutes: float,
    backtracking_max_ops: int,
    committed_assignments: list[Assignment],
    committed_assignment_by_op: Mapping[UUID, Assignment],
    ops_by_id: Mapping[UUID, Operation],
    horizon_start: datetime,
) -> list[Assignment]:
    """Return the assignments to rewind into the next window.

    Selection rules (preserved from the original closure):

    * If backtracking is disabled, the tail size is non-positive, the
      max-ops cap is non-positive, or there are no commits yet, return
      an empty list.
    * Otherwise compute the rewind boundary
      ``max(0, window_start_offset - backtracking_tail_minutes)`` and
      take every committed assignment whose end offset is strictly
      after the rewind boundary.
    * Close that set under successors: an op whose predecessor is being
      rewound must also be rewound.
    * If the closure exceeds ``backtracking_max_ops``, abort and return
      an empty list (the caller will not rewind anything).

    Pure function.
    """
    if (
        not backtracking_enabled
        or backtracking_tail_minutes <= 0.0
        or backtracking_max_ops <= 0
        or not committed_assignments
    ):
        return []

    rewind_boundary = max(0.0, window_start_offset - backtracking_tail_minutes)
    rewound_ids = {
        assignment.operation_id
        for assignment in committed_assignments
        if (
            (assignment.end_time - horizon_start).total_seconds() / 60.0
            > rewind_boundary + 1e-9
        )
    }
    if not rewound_ids:
        return []

    changed = True
    while changed:
        changed = False
        for op_id in committed_assignment_by_op:
            if op_id in rewound_ids:
                continue
            operation = ops_by_id.get(op_id)
            predecessor_op_id = (
                operation.predecessor_op_id if operation is not None else None
            )
            if predecessor_op_id in rewound_ids:
                rewound_ids.add(op_id)
                changed = True

    if len(rewound_ids) > backtracking_max_ops:
        return []

    return sorted(
        [committed_assignment_by_op[op_id] for op_id in rewound_ids],
        key=lambda assignment: assignment.start_time,
    )


# ---------------------------------------------------------------------------
# Temporal-consistency stabilizer (forward-only repair)
# ---------------------------------------------------------------------------


def stabilize_temporal_consistency(
    assignments: list[Assignment],
    *,
    ops_by_id: Mapping[UUID, Operation],
    setup_minutes: Mapping[tuple[UUID, UUID, UUID], int],
    max_passes: int = 8,
) -> dict[str, int]:
    """Repair residual precedence and machine/setup conflicts in-place.

    Forward-only and bounded: each pass walks the topologically ordered
    operations and shifts later, never earlier. Two kinds of shifts are
    accounted for:

    * ``precedence_shifts`` — current op starts before its predecessor
      ends; shift forward by the deficit.
    * ``machine_shifts`` — within the same work center, current op
      starts before the previous op's end + required setup; shift
      forward by the deficit.

    The pass converges when neither shift type fires. Termination is
    guaranteed because shifts are monotone forward and bounded by the
    horizon, but we cap the number of passes at ``max_passes`` for
    defense in depth.

    Returns ``{"passes", "precedence_shifts", "machine_shifts"}``.

    This function mutates ``Assignment`` objects in ``assignments``
    in place; that is intentional and is the function's sole side
    effect.
    """
    if not assignments:
        return {
            "passes": 0,
            "precedence_shifts": 0,
            "machine_shifts": 0,
        }

    assignment_by_op: dict[UUID, Assignment] = {
        assignment.operation_id: assignment for assignment in assignments
    }
    assigned_op_ids = set(assignment_by_op.keys())

    indegree: dict[UUID, int] = {op_id: 0 for op_id in assigned_op_ids}
    successors: dict[UUID, list[UUID]] = defaultdict(list)
    for op_id in assigned_op_ids:
        operation = ops_by_id.get(op_id)
        if operation is None:
            continue
        predecessor_op_id = operation.predecessor_op_id
        if predecessor_op_id is None or predecessor_op_id not in assigned_op_ids:
            continue
        successors[predecessor_op_id].append(op_id)
        indegree[op_id] = indegree.get(op_id, 0) + 1

    topo_queue = deque(
        sorted(
            [op_id for op_id, deg in indegree.items() if deg == 0],
            key=lambda op_id: (
                ops_by_id[op_id].seq_in_order if op_id in ops_by_id else 0
            ),
        )
    )
    topo_order: list[UUID] = []
    while topo_queue:
        op_id = topo_queue.popleft()
        topo_order.append(op_id)
        for succ_id in successors.get(op_id, []):
            indegree[succ_id] -= 1
            if indegree[succ_id] == 0:
                topo_queue.append(succ_id)

    if len(topo_order) < len(assigned_op_ids):
        # Cycle detected in the precedence DAG (or an op missing from
        # ops_by_id). Append the rest in stable order so the pass still
        # makes progress on the well-formed prefix.
        remaining_ids = assigned_op_ids - set(topo_order)
        topo_order.extend(
            sorted(
                remaining_ids,
                key=lambda op_id: (
                    ops_by_id[op_id].seq_in_order if op_id in ops_by_id else 0
                ),
            )
        )

    precedence_shifts = 0
    machine_shifts = 0
    passes = 0

    for pass_index in range(max_passes):
        changed = False
        passes = pass_index + 1

        for op_id in topo_order:
            operation = ops_by_id.get(op_id)
            if operation is None or operation.predecessor_op_id is None:
                continue
            predecessor_assignment = assignment_by_op.get(operation.predecessor_op_id)
            current_assignment = assignment_by_op.get(op_id)
            if predecessor_assignment is None or current_assignment is None:
                continue
            if current_assignment.start_time < predecessor_assignment.end_time:
                delta = predecessor_assignment.end_time - current_assignment.start_time
                current_assignment.start_time += delta
                current_assignment.end_time += delta
                precedence_shifts += 1
                changed = True

        assignments_by_machine: dict[UUID, list[Assignment]] = defaultdict(list)
        for assignment in assignment_by_op.values():
            assignments_by_machine[assignment.work_center_id].append(assignment)

        for work_center_id, machine_assignments in assignments_by_machine.items():
            machine_assignments.sort(key=lambda assignment: assignment.start_time)
            previous_assignment: Assignment | None = None
            for current_assignment in machine_assignments:
                if previous_assignment is None:
                    previous_assignment = current_assignment
                    continue

                previous_operation = ops_by_id.get(previous_assignment.operation_id)
                current_operation = ops_by_id.get(current_assignment.operation_id)
                required_setup = 0
                if previous_operation is not None and current_operation is not None:
                    required_setup = setup_minutes.get(
                        (
                            work_center_id,
                            previous_operation.state_id,
                            current_operation.state_id,
                        ),
                        0,
                    )

                required_start = previous_assignment.end_time + timedelta(
                    minutes=required_setup,
                )
                if current_assignment.start_time < required_start:
                    delta = required_start - current_assignment.start_time
                    current_assignment.start_time += delta
                    current_assignment.end_time += delta
                    machine_shifts += 1
                    changed = True

                previous_assignment = current_assignment

        if not changed:
            break

    return {
        "passes": passes,
        "precedence_shifts": precedence_shifts,
        "machine_shifts": machine_shifts,
    }
