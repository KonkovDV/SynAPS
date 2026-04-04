"""Stable instance characterization for SynAPS scheduling problems."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from synaps.model import ScheduleProblem


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
    size_band: str

    def as_dict(self) -> dict[str, int | float | bool | str]:
        return asdict(self)


def _size_band(operation_count: int) -> str:
    if operation_count <= 20:
        return "small"
    if operation_count <= 120:
        return "medium"
    return "large"


def build_problem_profile(problem: ScheduleProblem) -> ProblemProfile:
    """Compute a deterministic structural profile for *problem*."""

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
        1 for entry in problem.setup_matrix if entry.setup_minutes > 0
    )

    eligible_counts = [
        len(operation.eligible_wc_ids) if operation.eligible_wc_ids else work_center_count
        for operation in problem.operations
    ]
    avg_eligible_work_centers = (
        sum(eligible_counts) / operation_count if operation_count else 0.0
    )
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
        size_band=_size_band(operation_count),
    )


__all__ = ["ProblemProfile", "build_problem_profile"]