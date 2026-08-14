"""Campaign windows: approximate lot combining without cross-order predecessors.

INFIMUM 2.0 and ADVARIS both cluster similar SKUs into one launch. SynAPS
rejects cross-order ``predecessor_op_id``, so this preprocessor only aligns
``earliest_start`` of first-stage ops in the same state into due-date buckets.

The gate is the earliest release in that (state, due-slot) group, snapped down
to the slot grid. Snapping the gate *to the due date* (the 2026-08-14 bug)
forbids starting until the due bucket and overflows a loaded month.
"""

from __future__ import annotations

from datetime import timedelta

from synaps.model import Operation, Order, ScheduleProblem


def _first_stage_ops(problem: ScheduleProblem) -> dict[object, Operation]:
    first_ops: dict[object, Operation] = {}
    for operation in problem.operations:
        current = first_ops.get(operation.order_id)
        if current is None or operation.seq_in_order < current.seq_in_order:
            first_ops[operation.order_id] = operation
    return first_ops


def apply_campaign_windows(
    problem: ScheduleProblem,
    *,
    slot_hours: int = 8,
) -> ScheduleProblem:
    """Open a shared start gate per SKU×due slot at the group's earliest release."""

    if slot_hours <= 0:
        return problem
    slot = timedelta(hours=slot_hours)
    horizon = problem.planning_horizon_start
    orders_by_id = {order.id: order for order in problem.orders}
    groups: dict[tuple[object, int], list[tuple[Operation, Order]]] = {}
    for operation in _first_stage_ops(problem).values():
        order = orders_by_id[operation.order_id]
        due_bucket = max(
            0, int((order.due_date - horizon).total_seconds() // slot.total_seconds())
        )
        groups.setdefault((operation.state_id, due_bucket), []).append((operation, order))
    for members in groups.values():
        gate_seconds = min(
            max(0.0, ((order.release_date or horizon) - horizon).total_seconds())
            for _operation, order in members
        )
        snapped = horizon + slot * int(gate_seconds // slot.total_seconds())
        for operation, _order in members:
            operation.earliest_start = snapped
    return problem
