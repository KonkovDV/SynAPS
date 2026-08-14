"""Campaign windows: approximate lot combining without cross-order predecessors.

INFIMUM 2.0 and ADVARIS both cluster similar SKUs into one launch. SynAPS
rejects cross-order ``predecessor_op_id``, so this preprocessor only aligns
``earliest_start`` of first-stage ops in the same state into due-date buckets.
"""

from __future__ import annotations

from datetime import timedelta

from synaps.model import Operation, ScheduleProblem


def apply_campaign_windows(
    problem: ScheduleProblem,
    *,
    slot_hours: int = 8,
) -> ScheduleProblem:
    """Snap each order's first op ``earliest_start`` to a family×due slot."""

    if slot_hours <= 0:
        return problem
    slot = timedelta(hours=slot_hours)
    horizon = problem.planning_horizon_start
    orders_by_id = {order.id: order for order in problem.orders}
    first_ops: dict[object, Operation] = {}
    for operation in problem.operations:
        current = first_ops.get(operation.order_id)
        if current is None or operation.seq_in_order < current.seq_in_order:
            first_ops[operation.order_id] = operation
    for operation in first_ops.values():
        order = orders_by_id[operation.order_id]
        due_delta = order.due_date - horizon
        buckets = max(0, int(due_delta.total_seconds() // slot.total_seconds()))
        operation.earliest_start = horizon + slot * buckets
    return problem
