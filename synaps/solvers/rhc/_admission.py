"""Pure admission/candidate-frontier kernels for the RHC solver.

This module hosts the algorithmic primitives used by the RHC window loop to
maintain the *admission frontier* and the *due frontier* of operations
eligible for the current window, along with the precedence-readiness filter.

Decomposed from `synaps/solvers/rhc/_solver.py` as part of the R7 subpackage
split (see AGENTS.md Wave 4 / R7 roadmap). Only side-effect-free helpers live
here; the RHC solver retains ownership of all mutable cursors and counter
state. This keeps the contract narrow and the helpers trivially testable.

Academic basis:
    - Rolling-horizon dispatch literature uses a "candidate set" maintained
      across windows; the admission cursor is a monotone pointer over an
      immutable sort order, mirroring the classic dispatch-rule frontier.
    - The precedence-closure kernel is the standard fixed-point computation
      from constraint-programming literature: drop ops whose predecessors
      are not reachable, repeat until stable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from synaps.model import Operation


def advance_admission_frontier(
    *,
    cursor: int,
    ops_sorted_by_admission: Sequence[Operation],
    op_admission_offset_by_id: Mapping[UUID, float],
    op_earliest: Mapping[UUID, float],
    window_boundary: float,
) -> tuple[list[UUID], int]:
    """Advance the admission cursor up to (but excluding) the window boundary.

    Returns ``(newly_admitted_ids, new_cursor)`` so the caller can update its
    candidate-set and counter state without exposing internal sequence
    semantics here.

    Pure function: does not mutate any inputs.
    """
    newly_admitted: list[UUID] = []
    n = len(ops_sorted_by_admission)
    while cursor < n:
        op = ops_sorted_by_admission[cursor]
        op_offset = op_admission_offset_by_id.get(op.id, op_earliest.get(op.id, 0.0))
        if op_offset >= window_boundary:
            break
        newly_admitted.append(op.id)
        cursor += 1
    return newly_admitted, cursor


def advance_due_frontier(
    *,
    cursor: int,
    ops_sorted_by_due: Sequence[Operation],
    order_due_offsets: Mapping[UUID, float],
    horizon_minutes: float,
    window_boundary: float,
) -> tuple[list[UUID], int]:
    """Advance the due-date cursor up to (but excluding) the window boundary.

    Returns ``(newly_due_ids, new_cursor)``.
    Pure function: does not mutate any inputs.
    """
    newly_due: list[UUID] = []
    n = len(ops_sorted_by_due)
    while cursor < n:
        op = ops_sorted_by_due[cursor]
        op_due = order_due_offsets.get(op.order_id, horizon_minutes)
        if op_due >= window_boundary:
            break
        newly_due.append(op.id)
        cursor += 1
    return newly_due, cursor


def compute_precedence_closed_set(
    candidate_ids: set[UUID],
    *,
    ops_by_id: Mapping[UUID, Operation],
    resolved_predecessor_ids: set[UUID],
) -> set[UUID]:
    """Drop candidates whose predecessor is neither in the candidate set
    nor already resolved.

    Iterates the standard precedence-closure fixed point:
    keep ``op`` iff every direct predecessor of ``op`` is either already
    closed externally (``resolved_predecessor_ids``) or still present in the
    closure under construction. Repeat until the closure stabilizes.

    Pure function: does not mutate the input set or the input mappings.
    """
    closure: set[UUID] = set(candidate_ids)
    while True:
        changed = False
        for op_id in tuple(closure):
            operation = ops_by_id.get(op_id)
            predecessor_id = (
                operation.predecessor_op_id if operation is not None else None
            )
            if predecessor_id is None:
                continue
            if (
                predecessor_id in closure
                or predecessor_id in resolved_predecessor_ids
            ):
                continue
            closure.discard(op_id)
            changed = True
        if not changed:
            return closure


def count_admitted_candidates(
    raw_candidate_ids: set[UUID],
    *,
    op_admission_offset_by_id: Mapping[UUID, float],
    op_earliest: Mapping[UUID, float],
    window_boundary: float,
) -> int:
    """Effective candidate count for the current window.

    If at least one candidate has its admission offset strictly below the
    window boundary, return the count of those *admitted* candidates;
    otherwise fall back to the raw candidate count so the caller's pressure
    metric does not collapse to zero on starved windows.

    Pure function.
    """
    admitted = sum(
        1
        for op_id in raw_candidate_ids
        if op_admission_offset_by_id.get(op_id, op_earliest.get(op_id, 0.0))
        < window_boundary
    )
    return admitted if admitted else len(raw_candidate_ids)
