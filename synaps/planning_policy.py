"""Inter-solve planning policy helpers (freeze horizon, rush admission).

RHC ``sealed_window_op_ids`` freezes commits *inside one solve*. A plant freeze
(Moskabelmet 3-day plan lock, ADVARIS WIP-limit planning) is a constraint on
the *next* repair: assignments that already start before ``freeze_horizon_end``
must not move unless ``allow_freeze_break`` is set (breakdown of that op).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from synaps.model import Assignment
from synaps.solvers.router import SolveRegime


def _frozen_operation_ids(
    assignments: list[Assignment],
    freeze_horizon_end: datetime | None,
) -> set[UUID]:
    """Ops whose current start lies inside the issued-plan freeze window."""

    if freeze_horizon_end is None:
        return set()
    return {
        assignment.operation_id
        for assignment in assignments
        if assignment.start_time < freeze_horizon_end
    }


def frozen_ids_for_repair(
    base_assignments: list[Assignment],
    kwargs: dict[str, Any],
) -> set[UUID]:
    """Neighbourhood subtraction for IncrementalRepair.

    Rush/material/what-if cannot steal freeze-window slots. A BREAKDOWN of an
    op that itself sits in the window remains repairable (the machine is dead).
    """

    freeze_end = kwargs.get("freeze_horizon_end")
    if freeze_end is None or kwargs.get("allow_freeze_break"):
        return set()
    locked = _frozen_operation_ids(base_assignments, freeze_end)
    regime = kwargs.get("regime")
    regime_value = getattr(regime, "value", regime)
    if regime_value in {SolveRegime.BREAKDOWN, SolveRegime.BREAKDOWN.value, None}:
        disrupted = {item for item in kwargs.get("disrupted_op_ids", [])}
        return locked - disrupted
    return locked


def pin_issued_plan(
    problem: Any,
    assignments: list[Assignment],
    freeze_horizon_end: datetime,
) -> Any:
    """Tighten freeze-window ops to their issued machine and interval.

    Encode-first pin for a subsequent constructive solve: eligible WC and
    ``earliest_start``/``latest_finish`` collapse to the issued slot so a rush
    cannot legally occupy that machine-time. Repair freeze remains
    ``frozen_ids_for_repair``.
    """

    locked = _frozen_operation_ids(assignments, freeze_horizon_end)
    by_op = {assignment.operation_id: assignment for assignment in assignments}
    for operation in problem.operations:
        assignment = by_op.get(operation.id)
        if assignment is None or operation.id not in locked:
            continue
        operation.earliest_start = assignment.start_time
        operation.latest_finish = assignment.end_time
        operation.eligible_wc_ids = [assignment.work_center_id]
    return problem
