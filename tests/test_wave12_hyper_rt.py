"""Wave 12 hyper Red Team + Aug 2026 lit fix-pack regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityViolation, proven_hard_violations
from synaps.solvers.incremental_repair import IncrementalRepair

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def test_proven_hard_keeps_capacity_when_lane_unproven() -> None:
    """H12-1: physical MACHINE_CAPACITY_VIOLATION stays proven."""
    wc = uuid4()
    violations = [
        FeasibilityViolation("LANE_INFERENCE_UNPROVEN", "unproven", work_center_id=wc),
        FeasibilityViolation("SETUP_GAP_VIOLATION", "gap", work_center_id=wc),
        FeasibilityViolation("MACHINE_CAPACITY_VIOLATION", "cap", work_center_id=wc),
    ]
    proven = proven_hard_violations(violations)
    kinds = {v.kind for v in proven}
    assert "SETUP_GAP_VIOLATION" not in kinds
    assert "MACHINE_CAPACITY_VIOLATION" in kinds


def test_cpsat_frozen_enforces_sdst_gap() -> None:
    """C12-1: free op after frozen must respect setup minutes."""
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op_frozen = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s1.id,
        base_duration_min=30,
        eligible_wc_ids=[wc.id],
    )
    op_free = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=s2.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=[order],
        operations=[op_free],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=15,
            )
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    frozen = Assignment(
        operation_id=op_frozen.id,
        work_center_id=wc.id,
        start_time=_H0,
        end_time=_H0 + timedelta(minutes=30),
    )
    result = CpSatSolver().solve(
        problem,
        time_limit_s=5,
        num_workers=1,
        auto_greedy_warm_start=False,
        frozen_assignments=[frozen],
        frozen_context_operations=[op_frozen, op_free],
    )
    assert result.assignments
    free_a = next(a for a in result.assignments if a.operation_id == op_free.id)
    assert free_a.start_time >= frozen.end_time + timedelta(minutes=15)


def test_incremental_repair_refuses_missing_frozen_predecessor() -> None:
    """C12-3: missing frozen pred must fail closed (no cleared edge)."""
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op_missing_pred = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s1.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    op_repair = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=s2.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
        predecessor_op_id=op_missing_pred.id,
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=[order],
        operations=[op_missing_pred, op_repair],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    # Only repair op is "remaining"; pred is neither remaining nor frozen.
    repaired = IncrementalRepair()._cpsat_fallback(
        problem,
        frozen_assignments=[],
        remaining_op_ids={op_repair.id},
        already_scheduled_ids=set(),
        num_workers=1,
    )
    assert repaired is None


def test_cpsat_material_alias_weight() -> None:
    """H12-2: canonical `material` key is accepted."""
    from synaps.solvers.cpsat_solver import CpSatSolver as _S

    # Smoke: building weights path does not KeyError on material-only dict.
    s = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s.id,
        base_duration_min=5,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[s],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    result = _S().solve(
        problem,
        time_limit_s=2,
        num_workers=1,
        auto_greedy_warm_start=False,
        objective_weights={"makespan": 1, "material": 3},
    )
    assert result.status.value in {"OPTIMAL", "FEASIBLE", "optimal", "feasible"} or result.assignments


def test_cpsat_refuses_collapsed_frozen() -> None:
    """C12-4: collapsed frozen interval raises."""
    s = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op_f = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    op = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=s.id,
        base_duration_min=5,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[s],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    frozen = Assignment(
        operation_id=op_f.id,
        work_center_id=wc.id,
        start_time=_H0,
        end_time=_H0,  # zero-length
    )
    with pytest.raises(ValueError, match="collapses|clamps"):
        CpSatSolver().solve(
            problem,
            time_limit_s=2,
            num_workers=1,
            auto_greedy_warm_start=False,
            frozen_assignments=[frozen],
            frozen_context_operations=[op_f, op],
        )
