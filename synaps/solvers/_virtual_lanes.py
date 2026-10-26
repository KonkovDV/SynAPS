"""Operation copy for virtual-lane expansion (greedy dispatch and CP-SAT)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from uuid import UUID

    from synaps.model import Operation


def operation_on_lanes(
    operation: Operation,
    lanes_by_work_center: Mapping[UUID, Sequence[UUID]],
    default_eligible: Sequence[UUID],
) -> Operation:
    """Copy ``operation`` onto the virtual lanes of its expanded work centers.

    A lane is its machine: it inherits the eligibility and the per-machine
    ``machine_duration_overrides`` (T-30 ``p_{o,m}``). Remapping only the
    eligibility left overrides keyed by a work center the transformed problem
    no longer has, so model validation rejected it and every solve of an
    override instance with ``max_parallel > 1`` failed (found by the T-06
    oracle cross-check).
    """
    eligible = (
        list(operation.eligible_wc_ids) if operation.eligible_wc_ids else list(default_eligible)
    )
    update: dict[str, object] = {
        "eligible_wc_ids": [
            lane for wc_id in eligible for lane in lanes_by_work_center.get(wc_id, [wc_id])
        ]
    }
    overrides = operation.machine_duration_overrides
    if any(wc_id in lanes_by_work_center for wc_id in overrides):
        update["machine_duration_overrides"] = {
            lane: minutes
            for wc_id, minutes in overrides.items()
            for lane in lanes_by_work_center.get(wc_id, [wc_id])
        }
    return operation.model_copy(update=update)
