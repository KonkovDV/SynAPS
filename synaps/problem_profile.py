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
    sdst_metric: bool
    size_band: str
    precedence_depth: int
    resource_contention: float

    def as_dict(self) -> dict[str, int | float | bool | str]:
        return asdict(self)


def _has_sequence_dependent_transition_cost(entry: SetupEntry) -> bool:
    return entry.setup_minutes > 0 or entry.material_loss > 0 or entry.energy_kwh > 0


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


def _setup_matrix_is_metric(problem: ScheduleProblem) -> bool:
    """True iff the SDST matrix satisfies the triangle inequality everywhere (M3).

    Mirrors ``synaps.validation.is_setup_matrix_metric`` but is computed inline
    to keep this lightweight profiling module free of solver imports. A missing
    (from, to) cell is treated as unknown and never fabricates a violation.
    """
    setup = {
        (e.work_center_id, e.from_state_id, e.to_state_id): float(e.setup_minutes)
        for e in problem.setup_matrix
    }
    wc_ids = {e.work_center_id for e in problem.setup_matrix}
    state_ids = [s.id for s in problem.states]
    for wc_id in wc_ids:
        for a in state_ids:
            for c in state_ids:
                if a == c:
                    continue
                direct = setup.get((wc_id, a, c))
                if direct is None:
                    continue
                for b in state_ids:
                    if b in (a, c):
                        continue
                    ab = setup.get((wc_id, a, b))
                    bc = setup.get((wc_id, b, c))
                    if ab is None or bc is None:
                        continue
                    if direct > ab + bc + 1e-9:
                        return False
    return True


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
        sdst_metric=_setup_matrix_is_metric(problem),
        size_band=_size_band(operation_count),
        precedence_depth=precedence_depth,
        resource_contention=resource_contention,
    )


__all__ = ["ProblemProfile", "build_problem_profile"]
