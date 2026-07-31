"""Deterministic lower-bound helpers for makespan-oriented solvers."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from synaps.timegrain import duration_minutes

if TYPE_CHECKING:
    from uuid import UUID

    from synaps.model import ScheduleProblem


logger = logging.getLogger(__name__)


def _clamp_non_negative(
    name: str,
    raw_value: float,
    *,
    operation_count: int,
    machine_count: int,
) -> float:
    """Clamp a lower-bound quantity to ``[0, +inf)`` with telemetry on negatives.

    Any valid relaxation of a makespan is non-negative by construction. A
    negative intermediate value therefore always signals a pathological input
    (empty eligible-machine sets, precedence cycles, auxiliary-resource
    mismatches) or an upstream bug. Clamping keeps the aggregated lower bound
    sound (a 0 floor is always a valid — if weak — bound) and prevents
    ``as_metadata`` from surfacing misleading negative numbers downstream, while
    the WARNING log preserves observability so the offending input can still be
    diagnosed. This is a diagnostic clamp, not a silent mask.

    P1-2 note: the ``speed_factor <= 0`` source (negative durations) is now
    rejected at model construction (``WorkCenter.speed_factor`` has ``gt=0``), so
    this guard remains only for the other pathologies above — a firing WARNING
    now genuinely indicates one of them, not a bad speed factor.
    """

    if raw_value < 0.0:
        logger.warning(
            "lower_bound_component_clamped: component=%s raw_value=%.6f "
            "operation_count=%d machine_count=%d",
            name,
            raw_value,
            operation_count,
            machine_count,
        )
        return 0.0
    return raw_value


@dataclass(frozen=True)
class MakespanLowerBound:
    """Relaxed lower-bound decomposition for schedule makespan."""

    value: float
    precedence_critical_path_lb: float
    average_capacity_lb: float
    exclusive_machine_lb: float
    max_operation_lb: float
    # R4 (2026-05-03): auxiliary-resource pool bound. For each shared
    # auxiliary resource r with finite pool_size(r), the cumulative
    # processing time required across all operations that consume r divided
    # by pool_size(r) is a valid makespan floor (the pool can serve at most
    # pool_size(r) units of work in parallel at any moment).
    auxiliary_resource_lb: float = 0.0
    # P1-3: release-aware head-tail (Jackson) bound. For each operation,
    # Cmax >= est(op) + p(op) + tail(op), where est folds in the order's
    # release_date and the predecessor chain and tail is the longest successor
    # chain. Dominates the release-free critical path; valid by construction.
    head_tail_lb: float = 0.0

    def as_metadata(self) -> dict[str, float]:
        return {
            "precedence_critical_path_lb": round(self.precedence_critical_path_lb, 4),
            "average_capacity_lb": round(self.average_capacity_lb, 4),
            "exclusive_machine_lb": round(self.exclusive_machine_lb, 4),
            "max_operation_lb": round(self.max_operation_lb, 4),
            "auxiliary_resource_lb": round(self.auxiliary_resource_lb, 4),
            "head_tail_lb": round(self.head_tail_lb, 4),
        }


def _compute_auxiliary_resource_lb(
    problem: ScheduleProblem,
    min_duration_by_op: dict[UUID, float],
) -> float:
    """Pool-divided cumulative-load lower bound on the makespan.

    Each `OperationAuxRequirement` contributes `quantity_needed` units of
    auxiliary capacity for the operation's processing duration. With a pool
    of capacity `pool_size` for resource `r`, the makespan must be at least
    the per-resource cumulative resource-time divided by the pool size:

        LB_arc(r) = sum_{j: requires(j, r)} p_j * q_{j,r} / pool_size(r)

    The problem-level ARC bound is the maximum of `LB_arc(r)` over all
    auxiliary resources that actually have requirements pointing at them.
    Safe fallback (0.0) when no auxiliary resources or requirements exist.

    TODO(R4-tech-debt): min_duration_by_op must be precomputed as
    min(duration over eligible machines) by the caller. Moving this
    computation inside would duplicate work from compute_relaxed_makespan_lower_bound
    and add coupling; document this contract clearly for future solver authors.
    """

    if not problem.auxiliary_resources or not problem.aux_requirements:
        return 0.0

    pool_by_resource: dict[UUID, int] = {
        resource.id: max(1, resource.pool_size) for resource in problem.auxiliary_resources
    }
    load_by_resource: dict[UUID, float] = defaultdict(float)
    for requirement in problem.aux_requirements:
        if requirement.aux_resource_id not in pool_by_resource:
            continue
        op_duration = min_duration_by_op.get(requirement.operation_id, 0.0)
        if op_duration <= 0.0:
            continue
        load_by_resource[requirement.aux_resource_id] += op_duration * float(
            requirement.quantity_needed
        )

    return max(
        (load / pool_by_resource[resource_id] for resource_id, load in load_by_resource.items()),
        default=0.0,
    )


def _compute_head_tail_lb(
    problem: ScheduleProblem,
    topo_order: list[UUID],
    successors_by_op: dict[UUID, list[UUID]],
    min_duration_by_op: dict[UUID, float],
) -> float:
    """Release-aware head-tail (Jackson) makespan bound (P1-3).

    ``Cmax >= max_op (est(op) + p(op) + tail(op))``: est(op) folds in the order
    release_date and the predecessor chain; tail(op) is the longest successor
    chain of min-durations. Valid because every feasible schedule starts op no
    earlier than est(op) and completes op's successor chain after op.
    Operations carry at most one predecessor, so the precedence graph is a
    forest of chains.
    """
    horizon_start = problem.planning_horizon_start
    order_release_offset: dict[UUID, float] = {}
    for order in problem.orders:
        if order.release_date is not None:
            offset = (order.release_date - horizon_start).total_seconds() / 60.0
            order_release_offset[order.id] = max(0.0, offset)
    op_release_offset: dict[UUID, float] = {
        operation.id: order_release_offset.get(operation.order_id, 0.0)
        for operation in problem.operations
    }
    predecessor_of: dict[UUID, UUID] = {
        operation.id: operation.predecessor_op_id
        for operation in problem.operations
        if operation.predecessor_op_id is not None
        and operation.predecessor_op_id in min_duration_by_op
    }
    est_by_op: dict[UUID, float] = {}
    for op_id in topo_order:
        est = op_release_offset.get(op_id, 0.0)
        predecessor_id = predecessor_of.get(op_id)
        if predecessor_id is not None:
            est = max(
                est,
                est_by_op.get(predecessor_id, 0.0) + min_duration_by_op.get(predecessor_id, 0.0),
            )
        est_by_op[op_id] = est
    tail_by_op: dict[UUID, float] = {}
    for op_id in reversed(topo_order):
        tail = 0.0
        for successor_id in successors_by_op.get(op_id, []):
            tail = max(
                tail,
                min_duration_by_op.get(successor_id, 0.0) + tail_by_op.get(successor_id, 0.0),
            )
        tail_by_op[op_id] = tail
    return max(
        (
            est_by_op.get(op_id, 0.0)
            + min_duration_by_op.get(op_id, 0.0)
            + tail_by_op.get(op_id, 0.0)
            for op_id in min_duration_by_op
        ),
        default=0.0,
    )


def compute_relaxed_makespan_lower_bound(problem: ScheduleProblem) -> MakespanLowerBound:
    """Return a deterministic makespan lower bound from relaxed structure.

    Components are chosen to remain valid under flexible routing:

    - precedence critical path using each operation's fastest eligible duration
    - average load over total parallel machine capacity
    - exclusive-machine load for operations pinned to one work center
    - the longest single-operation processing time
    """

    if not problem.operations or not problem.work_centers:
        return MakespanLowerBound(
            value=0.0,
            precedence_critical_path_lb=0.0,
            average_capacity_lb=0.0,
            exclusive_machine_lb=0.0,
            max_operation_lb=0.0,
            auxiliary_resource_lb=0.0,
        )

    work_centers_by_id = {work_center.id: work_center for work_center in problem.work_centers}
    all_work_center_ids = [work_center.id for work_center in problem.work_centers]

    min_duration_by_op: dict[UUID, float] = {}
    successors_by_op: dict[UUID, list[UUID]] = defaultdict(list)
    indegree_by_op: dict[UUID, int] = {operation.id: 0 for operation in problem.operations}
    exclusive_machine_loads: dict[UUID, float] = defaultdict(float)

    total_min_duration = 0.0
    max_operation_lb = 0.0
    for operation in problem.operations:
        eligible_work_centers = operation.eligible_wc_ids or all_work_center_ids
        # P0-4: use the canonical integer time grain shared with every solver,
        # so the bound cannot exceed a realized schedule just because it used a
        # finer (raw) duration than the round-based dispatch/CP-SAT models.
        min_duration = min(
            float(
                duration_minutes(
                    operation.base_duration_min,
                    work_centers_by_id[work_center_id].speed_factor,
                )
            )
            for work_center_id in eligible_work_centers
        )
        min_duration_by_op[operation.id] = min_duration
        total_min_duration += min_duration
        max_operation_lb = max(max_operation_lb, min_duration)

        if len(eligible_work_centers) == 1:
            exclusive_machine_loads[eligible_work_centers[0]] += min_duration

        if (
            operation.predecessor_op_id is not None
            and operation.predecessor_op_id in indegree_by_op
        ):
            successors_by_op[operation.predecessor_op_id].append(operation.id)
            indegree_by_op[operation.id] += 1

    topo_frontier = [
        operation.id for operation in problem.operations if indegree_by_op.get(operation.id, 0) == 0
    ]
    topo_order: list[UUID] = []
    while topo_frontier:
        op_id = topo_frontier.pop()
        topo_order.append(op_id)
        for successor_id in successors_by_op.get(op_id, []):
            indegree_by_op[successor_id] -= 1
            if indegree_by_op[successor_id] == 0:
                topo_frontier.append(successor_id)

    if len(topo_order) != len(problem.operations):
        # Precedence graph contains a cycle — topological sort is incomplete.
        # Fall back to flat ordering which yields a weaker (degenerate) lower
        # bound.  This signals upstream data corruption that should be fixed.
        logger.warning(
            "precedence_cycle_detected: topological sort covered %d of %d "
            "operations — lower bound will be weaker than expected",
            len(topo_order),
            len(problem.operations),
        )
        topo_order = [operation.id for operation in problem.operations]

    longest_path_to: dict[UUID, float] = {}
    for op_id in topo_order:
        longest_path_to[op_id] = max(
            longest_path_to.get(op_id, 0.0),
            min_duration_by_op.get(op_id, 0.0),
        )
        for successor_id in successors_by_op.get(op_id, []):
            candidate = longest_path_to[op_id] + min_duration_by_op.get(successor_id, 0.0)
            if candidate > longest_path_to.get(successor_id, 0.0):
                longest_path_to[successor_id] = candidate

    precedence_critical_path_lb = max(longest_path_to.values(), default=0.0)

    head_tail_lb = _compute_head_tail_lb(
        problem, topo_order, successors_by_op, min_duration_by_op
    )
    total_parallel_capacity = max(
        1,
        sum(max(1, work_center.max_parallel) for work_center in problem.work_centers),
    )
    average_capacity_lb = total_min_duration / total_parallel_capacity
    exclusive_machine_lb = max(
        (
            load / max(1, work_centers_by_id[work_center_id].max_parallel)
            for work_center_id, load in exclusive_machine_loads.items()
        ),
        default=0.0,
    )

    auxiliary_resource_lb = _compute_auxiliary_resource_lb(problem, min_duration_by_op)

    # Defensive clamp: any valid relaxation of a makespan is non-negative by
    # construction. If a component comes out negative (malformed input or an
    # upstream bug), clamp it to 0 so the aggregated LB and as_metadata() are
    # never contaminated, and emit a WARNING so the anomaly stays observable.
    operation_count = len(problem.operations)
    machine_count = len(problem.work_centers)
    precedence_critical_path_lb = _clamp_non_negative(
        "precedence_critical_path_lb",
        precedence_critical_path_lb,
        operation_count=operation_count,
        machine_count=machine_count,
    )
    average_capacity_lb = _clamp_non_negative(
        "average_capacity_lb",
        average_capacity_lb,
        operation_count=operation_count,
        machine_count=machine_count,
    )
    exclusive_machine_lb = _clamp_non_negative(
        "exclusive_machine_lb",
        exclusive_machine_lb,
        operation_count=operation_count,
        machine_count=machine_count,
    )
    max_operation_lb = _clamp_non_negative(
        "max_operation_lb",
        max_operation_lb,
        operation_count=operation_count,
        machine_count=machine_count,
    )
    auxiliary_resource_lb = _clamp_non_negative(
        "auxiliary_resource_lb",
        auxiliary_resource_lb,
        operation_count=operation_count,
        machine_count=machine_count,
    )
    head_tail_lb = _clamp_non_negative(
        "head_tail_lb",
        head_tail_lb,
        operation_count=operation_count,
        machine_count=machine_count,
    )

    raw_lower_bound = max(
        precedence_critical_path_lb,
        average_capacity_lb,
        exclusive_machine_lb,
        max_operation_lb,
        auxiliary_resource_lb,
        head_tail_lb,
    )
    lower_bound = _clamp_non_negative(
        "aggregate_value",
        raw_lower_bound,
        operation_count=operation_count,
        machine_count=machine_count,
    )
    return MakespanLowerBound(
        value=lower_bound,
        precedence_critical_path_lb=precedence_critical_path_lb,
        average_capacity_lb=average_capacity_lb,
        exclusive_machine_lb=exclusive_machine_lb,
        max_operation_lb=max_operation_lb,
        auxiliary_resource_lb=auxiliary_resource_lb,
        head_tail_lb=head_tail_lb,
    )


__all__ = ["MakespanLowerBound", "compute_relaxed_makespan_lower_bound"]
