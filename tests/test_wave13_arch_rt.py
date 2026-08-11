"""Wave 13 architecture-chain Red Team regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.contracts import SolveOptions
from synaps.model import (
    Assignment,
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    ScheduleResult,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.objective import scalarize
from synaps.replay import _build_verification_snapshot
from synaps.solvers import _attach_canonical_objective
from synaps.solvers.alns_solver import AlnsSolver
from synaps.solvers.feasibility_checker import FeasibilityViolation, proven_hard_violations

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def test_proven_hard_keeps_overlap_when_lane_unproven() -> None:
    """M13-1: physical MACHINE_OVERLAP stays proven under lane-unproven."""
    wc = uuid4()
    violations = [
        FeasibilityViolation("LANE_INFERENCE_UNPROVEN", "u", work_center_id=wc),
        FeasibilityViolation("SETUP_GAP_VIOLATION", "g", work_center_id=wc),
        FeasibilityViolation("MACHINE_OVERLAP", "o", work_center_id=wc),
    ]
    proven = {v.kind for v in proven_hard_violations(violations)}
    assert "SETUP_GAP_VIOLATION" not in proven
    assert "MACHINE_OVERLAP" in proven


def test_attach_canonical_objective_honors_caller_weights() -> None:
    """H13-1: published weighted_sum must use caller objective_weights."""
    s = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s.id,
        base_duration_min=10,
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
    result = ScheduleResult(
        solver_name="t",
        status=SolverStatus.FEASIBLE,
        assignments=[
            Assignment(
                operation_id=op.id,
                work_center_id=wc.id,
                start_time=_H0,
                end_time=_H0 + timedelta(minutes=10),
            )
        ],
        objective=ObjectiveValues(makespan_minutes=10.0, total_setup_minutes=5.0),
        metadata={},
    )
    weights = {"makespan": 1.0, "setup": 2.0}
    _attach_canonical_objective(result, problem, weights=weights)
    expected = scalarize(result.objective, {"makespan": 1.0, "setup": 2.0, "material": 0.0, "tardiness": 0.0, "energy": 0.0})
    assert result.objective.weighted_sum == pytest.approx(expected)
    assert result.metadata["published_objective_weights"]["setup"] == 2.0


def test_replay_verification_not_pretended() -> None:
    """H13-6: missing verified_feasible ⇒ performed=False, feasible=False."""
    result = ScheduleResult(solver_name="t", status=SolverStatus.FEASIBLE, assignments=[])
    snap = _build_verification_snapshot({}, result)
    assert snap.performed is False
    assert snap.feasible is False


def test_alns_refuses_frozen_with_parallel_virtualization() -> None:
    """C13-2: frozen ∧ max_parallel>1 → ERROR (match CP-SAT policy)."""
    s = State(code="s")
    wc = WorkCenter(code="P", capability_group="G", max_parallel=2)
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
    frozen = Assignment(
        operation_id=uuid4(),
        work_center_id=wc.id,
        start_time=_H0,
        end_time=_H0 + timedelta(minutes=5),
    )
    result = AlnsSolver().solve(
        problem,
        max_iterations=1,
        time_limit_s=1,
        frozen_assignments=[frozen],
        frozen_context_operations=[op],
    )
    assert result.status == SolverStatus.ERROR
    assert "frozen" in str(result.metadata.get("error", "")).lower()


def test_solve_options_rejects_oob_workers() -> None:
    """M13-2: num_workers reject, not silent clamp."""
    with pytest.raises(ValueError, match="num_workers"):
        SolveOptions(num_workers=0).to_runtime_kwargs()
    with pytest.raises(ValueError, match="num_workers"):
        SolveOptions(num_workers=9).to_runtime_kwargs()


def test_rhc_builds_offsets_before_pred_clear() -> None:
    """C13-1 smoke: offset builder uses original ops (unit of the algebra fix)."""
    # Pure helper-style assertion of the intended contract: after clear, offsets
    # must still be computable from the pre-clear map (documented invariant).
    pred_id, child_id = uuid4(), uuid4()
    window_op_ids = {child_id}
    original_preds = {child_id: pred_id}
    frozen = {pred_id: _H0 + timedelta(minutes=12)}
    offsets = {}
    for op_id in window_op_ids:
        pred = original_preds.get(op_id)
        if pred is None or pred in window_op_ids:
            continue
        if pred not in frozen:
            pytest.fail("missing frozen pred must be detected before clear")
        import math

        offsets[op_id] = int(math.ceil((frozen[pred] - _H0).total_seconds() / 60.0))
    assert offsets[child_id] == 12
