"""Campaign windows: approximate lot combining without cross-order predecessors.

INFIMUM 2.0 and ADVARIS both cluster similar SKUs into one launch. SynAPS
rejects cross-order ``predecessor_op_id``, so this preprocessor only aligns
``earliest_start`` of first-stage ops.

The gate is the earliest release in a (state, due-slot) group, snapped down
to the slot grid. Mixing 16 mm² and 35 mm² into one colour gate (tried
2026-08-15) interleaved 360 min section setups and raised tardiness.
With ``colour_phase``, shops of ≤8 machines/stage use a 6-colour wheel
(at most five slots, skipped if it would pass due). Wider shops keep the
hash%3 stagger: a 40 h wheel raised tardiness at 16/stage (2026-08-15).
hash%3 packs two colours into one slot; the wheel is for the tight shop
where colour SDST otherwise fills the calendar. Snapping the gate *to
the due date* (the 2026-08-14 bug) forbids starting until the due bucket.

Algebra (1600-order month): processing is 19% of an 8-machine calendar;
the leftover ~1.7e6 min must cover setups. Random SDST is ~175 min/op
and does not fit. Bounded ATCS delay of one SMED on an append-only SGS
collapsed 16-stage coverage (Kolisch non-delay vs Artigues insertion).
Hold-until-successor drums do not add machine-minutes (C5a stays gated).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from synaps.domains.cable.adapter import CABLE_COLORS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from synaps.model import Operation, Order, ScheduleProblem, State


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
    colour_phase: bool = False,
    colour_cycle: int = 3,
) -> ScheduleProblem:
    """Open a shared start gate per SKU x due slot at the group's earliest release."""

    if slot_hours <= 0:
        return problem
    slot = timedelta(hours=slot_hours)
    horizon = problem.planning_horizon_start
    orders_by_id = {order.id: order for order in problem.orders}
    states_by_id = {state.id: state for state in problem.states}
    groups: dict[tuple[object, int], list[tuple[Operation, Order]]] = {}
    for operation in _first_stage_ops(problem).values():
        order = orders_by_id[operation.order_id]
        due_bucket = max(0, int((order.due_date - horizon).total_seconds() // slot.total_seconds()))
        groups.setdefault((operation.state_id, due_bucket), []).append((operation, order))
    for members in groups.values():
        gate_seconds = min(
            max(0.0, ((order.release_date or horizon) - horizon).total_seconds())
            for _operation, order in members
        )
        gate = horizon + slot * int(gate_seconds // slot.total_seconds())
        for operation, order in members:
            operation.earliest_start = _colour_stagger_gate(
                gate,
                slot,
                horizon,
                order,
                operation,
                states_by_id,
                colour_phase,
                colour_cycle,
            )
    return problem


def _colour_stagger_gate(
    gate: datetime,
    slot: timedelta,
    horizon: datetime,
    order: Order,
    operation: Operation,
    states_by_id: Mapping[Any, State],
    colour_phase: bool,
    colour_cycle: int,
) -> datetime:
    if not colour_phase:
        return gate
    state = states_by_id.get(operation.state_id)
    attrs = state.domain_attributes if state is not None else {}
    if colour_cycle >= 6:
        color = str(attrs.get("color", ""))
        try:
            index = CABLE_COLORS.index(color)
        except ValueError:
            return gate
        gate_slot = round((gate - horizon).total_seconds() / slot.total_seconds())
        wait = (index - gate_slot) % len(CABLE_COLORS)
    else:
        wait = sum(
            ord(char) for char in f"{attrs.get('insulation', '')}-{attrs.get('color', '')}"
        ) % max(colour_cycle, 1)
    shifted = gate + slot * wait
    return shifted if shifted <= order.due_date else gate
