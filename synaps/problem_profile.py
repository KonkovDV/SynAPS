"""Stable instance characterization for SynAPS scheduling problems."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synaps.model import ScheduleProblem, SetupEntry


@dataclass(frozen=True)
class ProblemProfile:
    """Compact structural summary of a scheduling instance."""

    state_count: int
    order_count: int
    operation_count: int
    work_center_count: int
    auxiliary_resource_count: int
    aux_requirement_count: int
    precedence_edge_count: int
    setup_entry_count: int
    setup_nonzero_entry_count: int
    avg_eligible_work_centers: float
    avg_duration_min: float
    setup_density: float
    nonzero_setup_density: float
    has_aux_constraints: bool
    has_nonzero_setups: bool
    has_per_op_windows: bool
    has_machine_calendar: bool
    has_hard_time_windows: bool
    sdst_metric: bool
    size_band: str
    precedence_depth: int
    resource_contention: float

    def as_dict(self) -> dict[str, int | float | bool | str]:
        return asdict(self)


def _has_sequence_dependent_transition_cost(entry: SetupEntry) -> bool:
    return entry.setup_minutes > 0 or entry.material_loss > 0 or entry.energy_kwh > 0


def _has_per_op_windows(problem: ScheduleProblem) -> bool:
    return any(
        operation.earliest_start is not None or operation.latest_finish is not None
        for operation in problem.operations
    )


def _has_machine_calendar(problem: ScheduleProblem) -> bool:
    return any(work_center.calendar for work_center in problem.work_centers)


def _has_hard_time_windows(problem: ScheduleProblem) -> bool:
    """Per-op windows or a non-empty machine calendar (KI-N1 / KI-N7)."""

    return _has_per_op_windows(problem) or _has_machine_calendar(problem)


def _size_band(operation_count: int) -> str:
    if operation_count <= 20:
        return "small"
    if operation_count <= 120:
        return "medium"
    if operation_count <= 500:
        return "large"
    if operation_count <= 2_000:
        return "industrial"
    if operation_count <= 10_000:
        return "industrial-hd"
    if operation_count <= 50_000:
        return "mega"
    return "ultra"


def build_problem_profile(problem: ScheduleProblem) -> ProblemProfile:
    """Compute a deterministic structural profile for *problem*."""

    # N4 (audit v3): call the single canonical metricity predicate rather than
    # an inline mirror. Imported lazily to keep this profiling module's import
    # graph free of the solver-side feasibility checker that validation pulls
    # in at module load.
    from synaps.validation import is_setup_matrix_metric

    state_count = len(problem.states)
    order_count = len(problem.orders)
    operation_count = len(problem.operations)
    work_center_count = len(problem.work_centers)
    auxiliary_resource_count = len(problem.auxiliary_resources)
    aux_requirement_count = len(problem.aux_requirements)
    precedence_edge_count = sum(
        1 for operation in problem.operations if operation.predecessor_op_id is not None
    )
    setup_entry_count = len(problem.setup_matrix)
    setup_nonzero_entry_count = sum(
        1 for entry in problem.setup_matrix if _has_sequence_dependent_transition_cost(entry)
    )

    eligible_counts = [
        len(operation.eligible_wc_ids) if operation.eligible_wc_ids else work_center_count
        for operation in problem.operations
    ]
    avg_eligible_work_centers = sum(eligible_counts) / operation_count if operation_count else 0.0
    avg_duration_min = (
        sum(operation.base_duration_min for operation in problem.operations) / operation_count
        if operation_count
        else 0.0
    )

    possible_setup_slots = work_center_count * state_count * state_count
    setup_density = setup_entry_count / possible_setup_slots if possible_setup_slots else 0.0
    nonzero_setup_density = (
        setup_nonzero_entry_count / possible_setup_slots if possible_setup_slots else 0.0
    )

    # Precedence depth: longest chain in the precedence DAG (BFS from roots).
    successors: dict[object, list[object]] = {}
    roots: list[object] = []
    for operation in problem.operations:
        if operation.predecessor_op_id is not None:
            successors.setdefault(operation.predecessor_op_id, []).append(operation.id)
        else:
            roots.append(operation.id)
    depth = 0
    frontier = list(roots)
    while frontier:
        depth += 1
        next_frontier: list[object] = []
        for node in frontier:
            next_frontier.extend(successors.get(node, []))
        frontier = next_frontier
    precedence_depth = depth

    # Resource contention: avg operations per eligible work center (higher = more contention).
    ops_per_wc: dict[object, int] = {}
    for operation in problem.operations:
        targets = (
            operation.eligible_wc_ids
            if operation.eligible_wc_ids
            else [wc.id for wc in problem.work_centers]
        )
        for wc_id in targets:
            ops_per_wc[wc_id] = ops_per_wc.get(wc_id, 0) + 1
    resource_contention = sum(ops_per_wc.values()) / len(ops_per_wc) if ops_per_wc else 0.0

    return ProblemProfile(
        state_count=state_count,
        order_count=order_count,
        operation_count=operation_count,
        work_center_count=work_center_count,
        auxiliary_resource_count=auxiliary_resource_count,
        aux_requirement_count=aux_requirement_count,
        precedence_edge_count=precedence_edge_count,
        setup_entry_count=setup_entry_count,
        setup_nonzero_entry_count=setup_nonzero_entry_count,
        avg_eligible_work_centers=avg_eligible_work_centers,
        avg_duration_min=avg_duration_min,
        setup_density=setup_density,
        nonzero_setup_density=nonzero_setup_density,
        has_aux_constraints=bool(problem.auxiliary_resources or problem.aux_requirements),
        has_nonzero_setups=setup_nonzero_entry_count > 0,
        has_per_op_windows=_has_per_op_windows(problem),
        has_machine_calendar=_has_machine_calendar(problem),
        has_hard_time_windows=_has_hard_time_windows(problem),
        sdst_metric=is_setup_matrix_metric(problem),
        size_band=_size_band(operation_count),
        precedence_depth=precedence_depth,
        resource_contention=resource_contention,
    )


__all__ = ["ProblemProfile", "build_problem_profile"]
