"""Canonical objective helpers: coverage and the lexicographic comparison key.

Red Team audit P0-5 (coverage as a level-0 objective) and the groundwork for
P0-6 (a single objective evaluator). Keeping the comparison key here \u2014 rather
than re-deriving a tuple inline in every solver / the portfolio / the benchmark
harness \u2014 is the same single-source-of-truth discipline that P0-4 applied to the
duration grain and N4 to the metricity predicate.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any
from uuid import UUID

from synaps.model import ObjectiveValues

if TYPE_CHECKING:
    from synaps.model import Assignment, ScheduleProblem


#: Default scalarization weights (makespan-dominant), matching the portfolio's
#: makespan-first intent. Callers may override per objective mode.
DEFAULT_WEIGHTS: dict[str, float] = {
    "makespan": 1.0,
    "setup": 0.0,
    "material": 0.0,
    "tardiness": 0.0,
}


def coverage_fraction(*, total_operations: int, scheduled_operations: int) -> float:
    """Fraction of operations that received an assignment.

    A problem with no operations is vacuously fully covered (1.0), so an empty
    instance never scores as "0% covered".
    """
    if total_operations <= 0:
        return 1.0
    return scheduled_operations / total_operations


def objective_sort_key(objective: ObjectiveValues) -> tuple[float, float, float]:
    """Canonical lexicographic rank (lower is better).

    Level 0 is coverage (negated so HIGHER coverage sorts first): a schedule
    that abandons operations must never rank ahead of a fuller one, no matter
    how good its makespan looks (P0-5). Ties fall back to makespan, then the
    scalarized weighted sum.
    """
    return (-objective.coverage, objective.makespan_minutes, objective.weighted_sum)


def evaluate(problem: ScheduleProblem, assignments: list[Assignment]) -> ObjectiveValues:
    """The single canonical objective evaluator (P0-6).

    Seven solvers historically re-derived the objective vector inline, diverging
    on details (notably: grouping setup by ``work_center_id`` instead of
    ``(work_center_id, lane_id)``, which charges a phantom changeover between
    concurrent parallel lanes — M2). This is the one place that defines it:

    * makespan — latest assignment end (minutes from the horizon start);
    * setup / material — summed over consecutive operations ON THE SAME LANE
      (``(work_center_id, lane_id)``), so parallel lanes incur no changeover.
      Assignments WITHOUT lane metadata on a parallel machine get their lanes
      inferred by the same exact search the FeasibilityChecker uses (audit v4,
      F3-consistency) instead of being charged phantom cross-lane setups;
    * tardiness — per order, ``max(0, completion - due_date)``. An order with
      no scheduled operations completes at the horizon END for this purpose
      (audit v4, F10) — it is maximally late, not free;
    * coverage / unscheduled — fraction of distinct operations scheduled.

    ``weighted_sum`` is left at its default here; use :func:`scalarize` to
    collapse the vector under explicit weights.
    """
    horizon_start = problem.planning_horizon_start
    horizon_end = problem.planning_horizon_end
    ops_by_id = {op.id: op for op in problem.operations}
    setup_lookup: dict[tuple[UUID, UUID, UUID], tuple[float, float]] = {
        (e.work_center_id, e.from_state_id, e.to_state_id): (
            float(e.setup_minutes),
            e.material_loss,
        )
        for e in problem.setup_matrix
    }

    makespan = 0.0
    for a in assignments:
        end = (a.end_time - horizon_start).total_seconds() / 60.0
        makespan = max(makespan, end)

    total_setup, total_material = _lane_setup_totals(
        problem, assignments, ops_by_id, setup_lookup
    )
    total_tardiness = _total_tardiness(problem, assignments, ops_by_id, horizon_start, horizon_end)

    total_ops = len(problem.operations)
    scheduled = len({a.operation_id for a in assignments})
    return ObjectiveValues(
        makespan_minutes=makespan,
        total_setup_minutes=total_setup,
        total_material_loss=total_material,
        total_tardiness_minutes=total_tardiness,
        coverage=coverage_fraction(
            total_operations=total_ops, scheduled_operations=scheduled
        ),
        unscheduled_operations=max(0, total_ops - scheduled),
    )


def _lane_setup_totals(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Any],
    setup_lookup: dict[tuple[UUID, UUID, UUID], tuple[float, float]],
) -> tuple[float, float]:
    """Sum setup minutes / material loss over consecutive ops ON THE SAME LANE.

    F3-consistency (audit v4): a parallel machine whose assignments carry NO
    lane metadata cannot be evaluated as one pseudo-lane — that charges
    PHANTOM setups between operations that would physically run on different
    lanes. Infer the lanes exactly, the same way the FeasibilityChecker does
    (single shared implementation), so the evaluator and the checker agree on
    setup semantics. If inference fails (infeasible/over budget) the
    pseudo-lane fallback is kept: the schedule is broken anyway and the
    objective merely has to stay defined.
    """
    by_lane: dict[tuple[UUID, UUID | None], list[Assignment]] = defaultdict(list)
    for a in assignments:
        by_lane[(a.work_center_id, a.lane_id)].append(a)

    work_centers_by_id = {wc.id: wc for wc in problem.work_centers}
    needs_inference = [
        wc_id
        for (wc_id, lane) in by_lane
        if lane is None
        and (work_centers_by_id.get(wc_id) is not None)
        and work_centers_by_id[wc_id].max_parallel > 1
        and len(by_lane[(wc_id, None)]) > 1
    ]
    if needs_inference:
        from synaps.solvers.feasibility_checker import FeasibilityChecker

        setup_minutes_lookup = {key: value[0] for key, value in setup_lookup.items()}
        checker = FeasibilityChecker()
        for wc_id in needs_inference:
            group = by_lane.pop((wc_id, None))
            ordered = sorted(group, key=lambda x: (x.start_time, x.end_time))
            inferred, _exhausted = checker._assign_lanes_exact(
                wc_id=wc_id,
                ordered=ordered,
                max_parallel=work_centers_by_id[wc_id].max_parallel,
                ops_by_id=ops_by_id,
                setup_lookup=setup_minutes_lookup,
                strict_setup_matrix=False,
            )
            if inferred is None:
                by_lane[(wc_id, None)] = group
                continue
            for lane_index, lane in enumerate(inferred):
                by_lane[(wc_id, UUID(int=lane_index + 1))] = lane

    total_setup = 0.0
    total_material = 0.0
    for (wc_id, _lane), lane_assignments in by_lane.items():
        ordered = sorted(lane_assignments, key=lambda x: x.start_time)
        for i in range(1, len(ordered)):
            prev_op = ops_by_id.get(ordered[i - 1].operation_id)
            curr_op = ops_by_id.get(ordered[i].operation_id)
            if prev_op is not None and curr_op is not None:
                setup_min, mat_loss = setup_lookup.get(
                    (wc_id, prev_op.state_id, curr_op.state_id), (0.0, 0.0)
                )
                total_setup += setup_min
                total_material += mat_loss
    return total_setup, total_material


def _total_tardiness(
    problem: ScheduleProblem,
    assignments: list[Assignment],
    ops_by_id: dict[UUID, Any],
    horizon_start: Any,
    horizon_end: Any,
) -> float:
    """Sum of per-order tardiness in minutes.

    F10 (audit v4): an order with NO scheduled operations previously got
    completion=0.0, UNDERSTATING its tardiness (a never-produced order is
    maximally late, not "completed at the horizon start"). Anchor its
    completion at the planning horizon end.
    """
    order_completion: dict[UUID, float] = {}
    for a in assignments:
        op = ops_by_id.get(a.operation_id)
        if op is None:
            continue
        end = (a.end_time - horizon_start).total_seconds() / 60.0
        order_completion[op.order_id] = max(order_completion.get(op.order_id, 0.0), end)
    horizon_span = (horizon_end - horizon_start).total_seconds() / 60.0
    total_tardiness = 0.0
    for order in problem.orders:
        completion = order_completion.get(order.id, horizon_span)
        due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
        total_tardiness += max(completion - due_offset, 0.0)
    return total_tardiness


def scalarize(objective: ObjectiveValues, weights: dict[str, float] | None = None) -> float:
    """Collapse an objective vector to a single weighted sum (P0-6).

    Weights default to :data:`DEFAULT_WEIGHTS` (makespan-only). This is the
    single definition of the scalarization; solvers that minimize a scalarized
    objective must remain consistent with it on their final solution.
    """
    w = weights if weights is not None else DEFAULT_WEIGHTS
    return (
        w.get("makespan", 0.0) * objective.makespan_minutes
        + w.get("setup", 0.0) * objective.total_setup_minutes
        + w.get("material", 0.0) * objective.total_material_loss
        + w.get("tardiness", 0.0) * objective.total_tardiness_minutes
    )


__all__ = ["DEFAULT_WEIGHTS", "coverage_fraction", "evaluate", "objective_sort_key", "scalarize"]
