"""Phase 0.2 (final brief): cross-validation oracle against PyJobShop.

PyJobShop (https://github.com/PyJobShop/PyJobShop) is an INDEPENDENT scheduling
library on the same CP-SAT backend. Building the identical problem in both and
comparing makespans at proven optimality turns a modeling error in the SynAPS
CP-SAT formulation into a test failure rather than the next audit finding.

The conversion mirrors ``benchmark/fjs_loader``'s mapping so both solvers attack
the SAME problem:

* one PyJobShop machine per ``max_parallel == 1`` work center; a renewable
  resource of capacity ``max_parallel`` for parallel-lane centers (so the M2
  parallel case is a direct, independent oracle);
* one task per operation, one mode per eligible work center, all with the SAME
  ``synaps.timegrain.duration_minutes`` duration (SynAPS models duration per
  operation, not per (operation, machine) pair);
* ``end_before_start`` precedence from ``predecessor_op_id``;
* makespan objective.

SDST is intentionally NOT transferred: the loader-based instances are setup-free
(the FJSP subset), and the parallel-lane oracle's optimum incurs no changeover,
so omitting it does not change the compared optimum. Instances with active SDST
are out of this oracle's scope and must not be passed to it.

``pyjobshop`` is an optional dependency; importing this module without it raises
``ImportError`` and the cross-validation tests skip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from synaps.timegrain import duration_minutes

if TYPE_CHECKING:
    from synaps.model import ScheduleProblem


@dataclass(frozen=True)
class OracleResult:
    """Independent-solver outcome for cross-validation."""

    makespan: float
    is_optimal: bool
    status: str


def solve_with_pyjobshop(
    problem: ScheduleProblem, *, time_limit_s: float = 30.0, num_workers: int = 8
) -> OracleResult:
    """Solve *problem* with PyJobShop and return its makespan + proof status.

    Raises ``ImportError`` if PyJobShop is not installed (callers skip).
    """
    import pyjobshop as pjs  # local import: optional dependency

    model = pjs.Model()

    resource_by_wc = {}
    speed_by_wc = {}
    for work_center in problem.work_centers:
        speed_by_wc[work_center.id] = work_center.speed_factor
        if work_center.max_parallel <= 1:
            resource_by_wc[work_center.id] = (model.add_machine(name=work_center.code), False)
        else:
            resource_by_wc[work_center.id] = (
                model.add_renewable(capacity=work_center.max_parallel, name=work_center.code),
                True,
            )

    job_by_order = {order.id: model.add_job(name=order.external_ref) for order in problem.orders}
    task_by_op = {
        op.id: model.add_task(job=job_by_order[op.order_id], name=str(op.id))
        for op in problem.operations
    }

    for op in problem.operations:
        task = task_by_op[op.id]
        for wc_id in op.eligible_wc_ids:
            resource, is_renewable = resource_by_wc[wc_id]
            duration = duration_minutes(op.base_duration_min, speed_by_wc[wc_id])
            if is_renewable:
                model.add_mode(task, resource, duration, demands=1)
            else:
                model.add_mode(task, resource, duration)

    for op in problem.operations:
        if op.predecessor_op_id is not None:
            model.add_end_before_start(task_by_op[op.predecessor_op_id], task_by_op[op.id])

    model.set_objective(weight_makespan=1)
    result = model.solve(time_limit=time_limit_s, display=False, num_workers=num_workers)
    status = str(result.status)
    return OracleResult(
        makespan=float(result.objective),
        is_optimal=status.endswith("OPTIMAL"),
        status=status,
    )


__all__ = ["OracleResult", "solve_with_pyjobshop"]
