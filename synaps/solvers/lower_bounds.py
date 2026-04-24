"""Deterministic lower-bound helpers for makespan-oriented solvers."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from synaps.model import ScheduleProblem


@dataclass(frozen=True)
class MakespanLowerBound:
    """Relaxed lower-bound decomposition for schedule makespan."""

    value: float
    precedence_critical_path_lb: float
    average_capacity_lb: float
    exclusive_machine_lb: float
    max_operation_lb: float

    def as_metadata(self) -> dict[str, float]:
        return {
            "precedence_critical_path_lb": round(self.precedence_critical_path_lb, 4),
            "average_capacity_lb": round(self.average_capacity_lb, 4),
            "exclusive_machine_lb": round(self.exclusive_machine_lb, 4),
            "max_operation_lb": round(self.max_operation_lb, 4),
        }


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
        )

    work_centers_by_id = {work_center.id: work_center for work_center in problem.work_centers}
    all_work_center_ids = [work_center.id for work_center in problem.work_centers]

    min_duration_by_op: dict[object, float] = {}
    successors_by_op: dict[object, list[object]] = defaultdict(list)
    indegree_by_op: dict[object, int] = {operation.id: 0 for operation in problem.operations}
    exclusive_machine_loads: dict[object, float] = defaultdict(float)

    total_min_duration = 0.0
    max_operation_lb = 0.0
    for operation in problem.operations:
        eligible_work_centers = operation.eligible_wc_ids or all_work_center_ids
        min_duration = min(
            max(
                1.0,
                operation.base_duration_min / work_centers_by_id[work_center_id].speed_factor,
            )
            for work_center_id in eligible_work_centers
        )
        min_duration_by_op[operation.id] = min_duration
        total_min_duration += min_duration
        max_operation_lb = max(max_operation_lb, min_duration)

        if len(eligible_work_centers) == 1:
            exclusive_machine_loads[eligible_work_centers[0]] += min_duration

        if operation.predecessor_op_id is not None and operation.predecessor_op_id in indegree_by_op:
            successors_by_op[operation.predecessor_op_id].append(operation.id)
            indegree_by_op[operation.id] += 1

    topo_frontier = [
        operation.id
        for operation in problem.operations
        if indegree_by_op.get(operation.id, 0) == 0
    ]
    topo_order: list[object] = []
    while topo_frontier:
        op_id = topo_frontier.pop()
        topo_order.append(op_id)
        for successor_id in successors_by_op.get(op_id, []):
            indegree_by_op[successor_id] -= 1
            if indegree_by_op[successor_id] == 0:
                topo_frontier.append(successor_id)

    if len(topo_order) != len(problem.operations):
        topo_order = [operation.id for operation in problem.operations]

    longest_path_to: dict[object, float] = {}
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

    lower_bound = max(
        precedence_critical_path_lb,
        average_capacity_lb,
        exclusive_machine_lb,
        max_operation_lb,
    )
    return MakespanLowerBound(
        value=lower_bound,
        precedence_critical_path_lb=precedence_critical_path_lb,
        average_capacity_lb=average_capacity_lb,
        exclusive_machine_lb=exclusive_machine_lb,
        max_operation_lb=max_operation_lb,
    )


__all__ = ["MakespanLowerBound", "compute_relaxed_makespan_lower_bound"]