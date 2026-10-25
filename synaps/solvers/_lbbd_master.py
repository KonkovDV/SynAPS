"""HiGHS master pieces shared by LBBD and LBBD-HD (T-05).

Both masters assign operations with binary ``y[i, k]`` and bound the makespan
with a continuous ``C_max``. The assignment rows, the relaxed capacity rows,
the no-good rows and the read-back of the solution were two hand-kept copies;
they live here once. Row order is part of the behaviour (HiGHS' search path,
golden snapshots), so callers add the pieces in their historical order.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import highspy
import numpy as np

from synaps.timegrain import duration_minutes_for

if TYPE_CHECKING:
    from uuid import UUID

    from synaps.model import ScheduleProblem

VarIndex = dict[tuple["UUID", "UUID"], int]


def add_assignment_rows(
    h: Any, problem: ScheduleProblem, eligible_by_op: dict[UUID, list[UUID]], var_index: VarIndex
) -> None:
    """Unique assignment — ``∑_k y[i,k] = 1`` for each operation."""
    for op in problem.operations:
        indices = [var_index[(op.id, wc_id)] for wc_id in eligible_by_op[op.id]]
        h.addRow(
            1.0,
            1.0,
            len(indices),
            np.array(indices, dtype=np.int32),
            np.array([1.0] * len(indices)),
        )


def add_capacity_rows(
    h: Any,
    problem: ScheduleProblem,
    var_index: VarIndex,
    cmax_idx: int,
    min_setup_by_wc: dict[UUID, float] | None,
) -> None:
    """Relaxed capacity — ``∑_i P[i,k] · y[i,k] ≤ C_max`` for each machine."""
    for wc in problem.work_centers:
        indices: list[int] = []
        coeffs: list[float] = []
        upper_bound = 0.0
        for op in problem.operations:
            key = (op.id, wc.id)
            if key in var_index:
                # CP-SAT duration semantics, divided by the number of parallel
                # lanes: a machine with max_parallel lanes finishes load L in
                # L / max_parallel, so `Sum p_i y_i / lanes <= C_max` stays a
                # valid lower bound (matching average_capacity_lb in
                # lower_bounds.py). Without the division the bound over-claims
                # on max_parallel > 1 machines.
                lanes = float(max(1, wc.max_parallel))
                indices.append(var_index[key])
                coeffs.append(float(duration_minutes_for(op, wc)) / lanes)
        if not indices:
            continue
        # The min-setup transition floor assumes n_k - 1 sequential transitions
        # on a single lane; with parallel lanes that count no longer holds, so
        # only apply it to single-lane machines (keeps the bound valid).
        if min_setup_by_wc and wc.id in min_setup_by_wc and wc.max_parallel <= 1:
            min_setup = min_setup_by_wc[wc.id]
            if min_setup > 0:
                coeffs = [coefficient + min_setup for coefficient in coeffs]
                upper_bound = min_setup
        # ∑ P·y - C_max ≤ 0
        indices.append(cmax_idx)
        coeffs.append(-1.0)
        h.addRow(
            -highspy.kHighsInf,
            upper_bound,
            len(indices),
            np.array(indices, dtype=np.int32),
            np.array(coeffs),
        )


def add_nogood_row(
    h: Any, assignment_map: dict[UUID, UUID], var_index: VarIndex, solver_label: str
) -> None:
    """Exclude an exact assignment: ``∑ y[i, assignment[i]] ≤ |ops| - 1``."""
    indices = [
        var_index[(op_id, wc_id)]
        for op_id, wc_id in assignment_map.items()
        if (op_id, wc_id) in var_index
    ]
    if not indices:
        raise ValueError(
            f"{solver_label} nogood cut has no bindable variables; refusing silent skip "
            "(Wave 14 / H14-nogood)."
        )
    h.addRow(
        -highspy.kHighsInf,
        len(indices) - 1.0,
        len(indices),
        np.array(indices, dtype=np.int32),
        np.array([1.0] * len(indices)),
    )


def extract_master_solution(
    h: Any,
    problem: ScheduleProblem,
    eligible_by_op: dict[UUID, list[UUID]],
    var_index: VarIndex,
    cmax_idx: int,
    best_dual: float = float("-inf"),
) -> tuple[tuple[dict[UUID, UUID], float] | None, bool]:
    """``((assignment_map, master_bound), proven_infeasible)`` of a solved master.

    ``best_dual`` carries a proven bound from an earlier run of the same model
    family (T-06 separation rounds): every round holds only valid rows, so the
    largest of the bounds is still valid.
    """
    status = h.getInfoValue("primal_solution_status")[1]
    if status != 2:  # 2 = feasible
        # F12 (audit v4): only HiGHS kInfeasible is a PROOF; a time-limited
        # master without an incumbent is inconclusive and must not be reported
        # as SolverStatus.INFEASIBLE upstream.
        proven_infeasible = h.getModelStatus() == highspy.HighsModelStatus.kInfeasible
        return None, proven_infeasible

    col_values = h.getSolution().col_value

    # For each op, pick the machine with y closest to 1.
    assignment_map: dict[UUID, UUID] = {}
    for op in problem.operations:
        best_val = -1.0
        best_wc: UUID | None = None
        for wc_id in eligible_by_op[op.id]:
            val = col_values[var_index[(op.id, wc_id)]]
            if val > best_val:
                best_val = val
                best_wc = wc_id
        if best_wc is not None:
            assignment_map[op.id] = best_wc

    master_bound = col_values[cmax_idx]
    # D3 validity: when the master is time-limited it may return a FEASIBLE but
    # non-optimal incumbent, whose C_max is an UPPER bound on the master
    # optimum, not a valid lower bound. Use the proven dual bound for the
    # reported relaxation LB (it equals the primal at optimality) so the S1/S2/
    # S3 lower-bound-validity invariant is preserved even on time-limited runs.
    try:
        dual_bound = float(h.getInfoValue("mip_dual_bound")[1])
    except (IndexError, TypeError, ValueError):
        dual_bound = master_bound
    dual_bound = max(dual_bound, best_dual)
    if math.isfinite(dual_bound):
        master_bound = min(master_bound, dual_bound)
    return (assignment_map, master_bound), False
