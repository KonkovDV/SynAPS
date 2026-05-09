"""Tests for R8 — ARC-aware lower bound (auxiliary-resource pool bound).

R17 acceptance:
- 3 ops × 60 min, shared ARC pool_size=1 → auxiliary_resource_lb ≥ 180.
- Same with pool_size=3 → auxiliary_resource_lb does NOT dominate other LB components.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    State,
    WorkCenter,
)
from synaps.solvers.lower_bounds import compute_relaxed_makespan_lower_bound

_HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
_HORIZON_END = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)


def _make_arc_problem(
    *,
    n_ops: int = 3,
    base_duration_min: float = 60.0,
    pool_size: int = 1,
    quantity_needed: float = 1.0,
) -> ScheduleProblem:
    """Build a problem where every op needs the same shared ARC."""
    state = State(id=uuid4(), code="S0", label="State 0")
    wc = WorkCenter(
        id=uuid4(),
        code="WC0",
        capability_group="machining",
        max_parallel=1,
        speed_factor=1.0,
    )
    arc = AuxiliaryResource(
        id=uuid4(),
        code="TOOL-01",
        resource_type="tool",
        pool_size=pool_size,
    )
    order = Order(id=uuid4(), external_ref="ORD-ARC", due_date=_HORIZON_END)
    ops = [
        Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=k,
            state_id=state.id,
            base_duration_min=base_duration_min,
            eligible_wc_ids=[wc.id],
        )
        for k in range(n_ops)
    ]
    requirements = [
        OperationAuxRequirement(
            id=uuid4(),
            operation_id=op.id,
            aux_resource_id=arc.id,
            quantity_needed=quantity_needed,
        )
        for op in ops
    ]
    return ScheduleProblem(
        id=uuid4(),
        name="arc-lb-test",
        horizon_start=_HORIZON_START,
        horizon_end=_HORIZON_END,
        work_centers=[wc],
        states=[state],
        auxiliary_resources=[arc],
        operations=ops,
        orders=[order],
        aux_requirements=requirements,
        setup_matrix=[],
        planning_horizon_start=_HORIZON_START,
        planning_horizon_end=_HORIZON_END,
    )


class TestArcLowerBound:
    def test_pool_size_one_dominates(self) -> None:
        """3 ops × 60 min with pool_size=1 → ARC LB = 180, must dominate."""
        problem = _make_arc_problem(n_ops=3, base_duration_min=60.0, pool_size=1)
        lb = compute_relaxed_makespan_lower_bound(problem)
        assert lb.auxiliary_resource_lb >= 180.0
        assert lb.value >= 180.0
        assert lb.value == max(
            lb.precedence_critical_path_lb,
            lb.average_capacity_lb,
            lb.exclusive_machine_lb,
            lb.max_operation_lb,
            lb.auxiliary_resource_lb,
        )

    def test_pool_size_three_does_not_dominate(self) -> None:
        """Same case with pool_size=3 → ARC LB = 60, should not dominate."""
        problem = _make_arc_problem(n_ops=3, base_duration_min=60.0, pool_size=3)
        lb = compute_relaxed_makespan_lower_bound(problem)
        assert lb.auxiliary_resource_lb == pytest.approx(60.0)
        # precedence critical path of 3 chained ops is 180, so value should be 180
        assert lb.value >= 180.0
        assert lb.value != lb.auxiliary_resource_lb

    def test_no_arc_resources_returns_zero(self) -> None:
        """Problem without auxiliary resources yields ARC LB = 0."""
        problem = _make_arc_problem(n_ops=2, pool_size=1)
        # Strip ARC data
        problem_no_arc = problem.model_copy(
            update={
                "auxiliary_resources": [],
                "aux_requirements": [],
            }
        )
        lb = compute_relaxed_makespan_lower_bound(problem_no_arc)
        assert lb.auxiliary_resource_lb == 0.0

    def test_metadata_contains_arc_key(self) -> None:
        """as_metadata() must include the auxiliary_resource_lb key."""
        problem = _make_arc_problem(n_ops=2, pool_size=1)
        lb = compute_relaxed_makespan_lower_bound(problem)
        meta = lb.as_metadata()
        assert "auxiliary_resource_lb" in meta
        assert isinstance(meta["auxiliary_resource_lb"], float)
