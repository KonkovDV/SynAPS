"""Wave 11 hyper Red Team fix-pack regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from synaps.contracts import SolveOptions
from synaps.model import (
    Assignment,
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import _normalize_objective_weights, _objective_cost
from synaps.solvers.feasibility_checker import FeasibilityViolation, proven_hard_violations
from synaps.solvers.incremental_repair import IncrementalRepair
from synaps.solvers.lbbd_solver import _add_benders_cut_rows

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def test_proven_hard_violations_wc_scoped_demotion() -> None:
    """H1: unproven lane on WC-A must not demote hard overlap on WC-B."""
    wc_a, wc_b = uuid4(), uuid4()
    violations = [
        FeasibilityViolation("LANE_INFERENCE_UNPROVEN", "unproven", work_center_id=wc_a),
        FeasibilityViolation("SETUP_GAP_VIOLATION", "gap-a", work_center_id=wc_a),
        FeasibilityViolation("MACHINE_OVERLAP", "overlap-b", work_center_id=wc_b),
    ]
    proven = proven_hard_violations(violations)
    kinds = {(v.kind, v.work_center_id) for v in proven}
    assert ("SETUP_GAP_VIOLATION", wc_a) not in kinds
    assert ("MACHINE_OVERLAP", wc_b) in kinds


def test_alns_material_alias_matches_canonical_scalarize() -> None:
    """H3: material vs material_loss must rank identically under DEFAULT_WEIGHTS merge."""
    obj = ObjectiveValues(makespan_minutes=10.0, total_material_loss=5.0)
    via_material = _objective_cost(obj, {"makespan": 1.0, "material": 2.0})
    via_alias = _objective_cost(obj, {"makespan": 1.0, "material_loss": 2.0})
    assert via_material == via_alias
    assert _normalize_objective_weights(None)["material"] == 0.0
    assert _normalize_objective_weights(None)["makespan"] == 1.0


def test_solve_options_rejects_oob_time_limit() -> None:
    """H5: no silent clamp — reject out-of-range time_limit_s."""
    with pytest.raises(ValueError, match="time_limit_s"):
        SolveOptions(time_limit_s=0).to_runtime_kwargs()
    with pytest.raises(ValueError, match="time_limit_s"):
        SolveOptions(time_limit_s=7201).to_runtime_kwargs()
    assert SolveOptions(time_limit_s=3600).to_runtime_kwargs()["time_limit_s"] == 3600


def test_lbbd_refuses_retired_s3_cut_kinds() -> None:
    """M1 / KI-S3: applicator must fail closed on setup_cost / machine_tsp."""
    cut = SimpleNamespace(
        kind="machine_tsp",
        bottleneck_ops=[],
        assignment_map={},
        rhs=1.0,
    )
    with pytest.raises(ValueError, match="permanently retired"):
        _add_benders_cut_rows(h=None, cuts=[cut], var_index={}, cmax_idx=0)


def test_incremental_repair_virtualizes_max_parallel() -> None:
    """H2 close: max_parallel>1 uses lane virtualization, not silent serialization."""
    state = State(code="S")
    wc = WorkCenter(code="P", capability_group="G", max_parallel=2)
    order = Order(external_ref="O", due_date=_HE)
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    base = [
        Assignment(
            operation_id=op.id,
            work_center_id=wc.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=10),
        )
    ]
    result = IncrementalRepair().solve(
        problem, base_assignments=base, disrupted_op_ids=[op.id], radius=0
    )
    assert result.status == SolverStatus.FEASIBLE
    assert result.metadata.get("parallel_virtualization") is True
    assert result.assignments[0].work_center_id == wc.id
    assert result.assignments[0].lane_id is not None


def test_incremental_repair_cpsat_fallback_respects_frozen_predecessor() -> None:
    """C1: CP-SAT fallback must not start a repair before its frozen predecessor ends."""
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op_frozen = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s1.id,
        base_duration_min=60,
        eligible_wc_ids=[wc.id],
    )
    op_repair = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=s2.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
        predecessor_op_id=op_frozen.id,
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=[order],
        operations=[op_frozen, op_repair],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=0,
            )
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    frozen = Assignment(
        operation_id=op_frozen.id,
        work_center_id=wc.id,
        start_time=_H0,
        end_time=_H0 + timedelta(minutes=60),
    )
    repaired = IncrementalRepair()._cpsat_fallback(
        problem,
        [frozen],
        {op_repair.id},
        {op_frozen.id},
        num_workers=1,
    )
    assert repaired is not None
    assert len(repaired) == 1
    assert repaired[0].start_time >= frozen.end_time


def test_incremental_repair_infeasible_when_unrepaired_remain(monkeypatch) -> None:
    """C2: neighbourhood abort with remaining ops must not return FEASIBLE."""
    state = State(code="S")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op_a = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
    )
    op_b = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=state.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
        predecessor_op_id=op_a.id,
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op_a, op_b],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    base = [
        Assignment(
            operation_id=op_a.id,
            work_center_id=wc.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=10),
        ),
        Assignment(
            operation_id=op_b.id,
            work_center_id=wc.id,
            start_time=_H0 + timedelta(minutes=10),
            end_time=_H0 + timedelta(minutes=20),
        ),
    ]

    def _no_slot(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "synaps.solvers.incremental_repair.find_earliest_feasible_slot",
        _no_slot,
    )
    monkeypatch.setattr(
        IncrementalRepair,
        "_cpsat_fallback",
        lambda *_a, **_k: None,
    )
    result = IncrementalRepair().solve(
        problem,
        base_assignments=base,
        disrupted_op_ids=[op_a.id, op_b.id],
        radius=0,
    )
    assert result.status == SolverStatus.INFEASIBLE
    assert result.metadata.get("unrepaired_count", 0) >= 1
