"""Wave 15 algebra probes: status = notary, not coverage.

A15-P0-1: RHC FEASIBLE ⇒ proven hard violations empty.
A15-P0-4: stabilize residual at pass cap is visible (converged=0).
A15-P0-5: empty disruption must not legalize a forged base plan.
A15-P2: native eligible=[] means all WCs; ALNS/RHC publish wall-clock path dependence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from synaps.model import Operation, Order, ScheduleProblem, State, WorkCenter
from synaps.portfolio import repair_schedule
from synaps.solvers.alns_solver import (
    AlnsSolver,
    _native_eligible_machine_indices,
    _try_native_greedy_repair,
    _try_native_initial_seed,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker, proven_hard_violations
from synaps.solvers.rhc import RhcSolver
from tests.conftest import make_simple_problem


def test_rhc_feasible_implies_notary_clean() -> None:
    problem = make_simple_problem(n_orders=2, ops_per_order=2)
    result = RhcSolver().solve(problem)
    hard = proven_hard_violations(FeasibilityChecker().check(problem, result.assignments))
    if result.status.value == "feasible":
        assert hard == []
        assert result.metadata.get("temporal_stabilization_converged") is True
        assert result.metadata.get("notary_hard_violation_count") == 0
    else:
        assert result.status.value == "error"


def test_repair_rejects_empty_disruption() -> None:
    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    with pytest.raises(ValueError, match="disrupted_op_ids must be non-empty"):
        repair_schedule(
            problem,
            base_assignments=[],
            disrupted_op_ids=[],
        )


def test_frozen_precedence_offset_requires_horizon() -> None:
    """A15-P0-2 / P1-8: cleared pred still constrained when horizon is passed."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from synaps.model import Assignment
    from synaps.solvers.alns_solver import _violates_frozen_precedence

    horizon = datetime(2026, 1, 1, tzinfo=UTC)
    pred_id, succ_id = uuid4(), uuid4()
    frozen = Assignment(
        operation_id=pred_id,
        work_center_id=uuid4(),
        start_time=horizon,
        end_time=horizon + timedelta(minutes=40),
    )
    too_early = Assignment(
        operation_id=succ_id,
        work_center_id=uuid4(),
        start_time=horizon + timedelta(minutes=10),
        end_time=horizon + timedelta(minutes=20),
    )
    ops_by_id = {succ_id: type("Op", (), {"predecessor_op_id": None})()}
    assert _violates_frozen_precedence(
        [too_early],
        {pred_id: frozen},
        ops_by_id,
        frozen_predecessor_end_offsets={succ_id: 40.0},
        horizon_start=horizon,
    )
    assert not _violates_frozen_precedence(
        [too_early],
        {pred_id: frozen},
        ops_by_id,
        frozen_predecessor_end_offsets={succ_id: 40.0},
    )


def test_machine_overlap_is_setup_aware() -> None:
    """A15-P0-3: end_frozen == start_free with setup>0 is a conflict."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from synaps.model import Assignment
    from synaps.solvers.alns_solver import _has_machine_overlap

    horizon = datetime(2026, 1, 1, tzinfo=UTC)
    wc, s1, s2, op_a, op_b = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    frozen = Assignment(
        operation_id=op_a,
        work_center_id=wc,
        start_time=horizon,
        end_time=horizon + timedelta(minutes=30),
    )
    abutting = Assignment(
        operation_id=op_b,
        work_center_id=wc,
        start_time=horizon + timedelta(minutes=30),
        end_time=horizon + timedelta(minutes=40),
    )
    ops_by_id = {
        op_a: type("Op", (), {"state_id": s1})(),
        op_b: type("Op", (), {"state_id": s2})(),
    }
    assert not _has_machine_overlap([frozen, abutting])
    assert _has_machine_overlap(
        [frozen, abutting],
        ops_by_id=ops_by_id,
        setup_minutes={(wc, s1, s2): 10},
    )


def test_stabilize_does_not_move_immutable_ops() -> None:
    """A15-P1-6: previous RHC windows stay put during final stabilize."""
    from datetime import UTC, datetime, timedelta

    from synaps.model import Assignment, Operation, Order, State, WorkCenter
    from synaps.solvers.rhc._window import stabilize_temporal_consistency

    horizon = datetime(2026, 1, 1, tzinfo=UTC)
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=horizon + timedelta(days=1))
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
    pinned_start = horizon
    a = Assignment(
        operation_id=op_a.id,
        work_center_id=wc.id,
        start_time=pinned_start,
        end_time=pinned_start + timedelta(minutes=10),
    )
    b = Assignment(
        operation_id=op_b.id,
        work_center_id=wc.id,
        start_time=horizon + timedelta(minutes=5),
        end_time=horizon + timedelta(minutes=15),
    )
    stabilize_temporal_consistency(
        [a, b],
        ops_by_id={op_a.id: op_a, op_b.id: op_b},
        setup_minutes={},
        immutable_op_ids={op_a.id},
    )
    assert a.start_time == pinned_start
    assert b.start_time >= a.end_time


def test_native_eligible_empty_means_all_machines() -> None:
    """A15-P2: empty eligible_wc_ids packs every work-center index."""
    wc_ids = ["slow", "fast"]
    wc_id_to_idx = {"slow": 0, "fast": 1}
    empty = type("Op", (), {"eligible_wc_ids": []})()
    assert _native_eligible_machine_indices(empty, wc_id_to_idx, wc_ids) == [0, 1]
    one = type("Op", (), {"eligible_wc_ids": ["fast"]})()
    assert _native_eligible_machine_indices(one, wc_id_to_idx, wc_ids) == [1]


def _two_speed_empty_eligible_problem() -> tuple[ScheduleProblem, WorkCenter, WorkCenter]:
    horizon = datetime(2026, 1, 1, tzinfo=UTC)
    state = State(code="s")
    slow = WorkCenter(code="SLOW", capability_group="G", speed_factor=1.0)
    fast = WorkCenter(code="FAST", capability_group="G", speed_factor=10.0)
    order = Order(external_ref="O", due_date=horizon + timedelta(days=1))
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=100,
        eligible_wc_ids=[],
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[slow, fast],
        setup_matrix=[],
        planning_horizon_start=horizon,
        planning_horizon_end=horizon + timedelta(days=1),
    )
    return problem, slow, fast


def test_native_empty_eligible_does_not_pin_machine_zero() -> None:
    """A15-P2: native seed/repair must not invent machine 0 + 1e6 on eligible=[]."""
    pytest.importorskip("synaps_native", reason="native module not built")
    problem, _slow, fast = _two_speed_empty_eligible_problem()
    ops_by_id = {op.id: op for op in problem.operations}

    seed = _try_native_initial_seed(
        problem,
        frozen_assignments=[],
        ops_by_id=ops_by_id,
        frozen_assignments_by_op={},
    )
    assert seed is not None
    assert seed[0].work_center_id == fast.id
    start_offset = (
        seed[0].start_time - problem.planning_horizon_start
    ).total_seconds() / 60.0
    assert start_offset < 1_000.0

    repaired = _try_native_greedy_repair(
        problem,
        [],
        [problem.operations[0].id],
        {problem.operations[0].id: 0},
    )
    assert repaired is not None
    assert repaired.assignments[0].work_center_id == fast.id


def test_alns_and_rhc_publish_wall_clock_path_dependence() -> None:
    """A15-P2: do not claim bitwise-identical ALNS/RHC under a wall timeout."""
    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    alns = AlnsSolver().solve(
        problem, max_iterations=1, time_limit_s=30, random_seed=1
    )
    assert alns.metadata["wall_clock_path_dependent"] is True
    assert alns.metadata["search_stop_reason"] in {
        "max_iterations",
        "wall_clock",
        "wall_clock_before_search",
        "completed",
    }
    assert "determinism_violated" in alns.metadata

    rhc = RhcSolver().solve(
        problem, time_limit_s=30, random_seed=1, inner_solver="greedy"
    )
    assert rhc.metadata["wall_clock_path_dependent"] is True
    assert rhc.metadata["search_stop_reason"] in {"wall_clock", "completed"}


def test_alns_final_claim_respects_frozen_overlap() -> None:
    """W16-P0-2: ALNS must not return FEASIBLE when the incumbent overlaps
    frozen assignments (RHC poisons all later windows on a frozen-overlap)."""
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from synaps.model import Assignment

    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    horizon = problem.planning_horizon_start
    frozen = [
        Assignment(
            operation_id=uuid4(),
            work_center_id=work_center.id,
            start_time=horizon,
            end_time=horizon + timedelta(days=1),
        )
        for work_center in problem.work_centers
    ]
    result = AlnsSolver().solve(
        problem,
        max_iterations=1,
        time_limit_s=30,
        random_seed=1,
        frozen_assignments=frozen,
    )
    assert result.status.value != "feasible"


def test_incremental_repair_final_notary() -> None:
    """W16-P1: IncrementalRepair must run a final feasibility pass; a forged
    base plan (no assignments for live ops) must not come back FEASIBLE."""
    from synaps.solvers.incremental_repair import IncrementalRepair

    problem = make_simple_problem(n_orders=1, ops_per_order=2)
    result = IncrementalRepair().solve(
        problem,
        base_assignments=[],
        disrupted_op_ids=[problem.operations[0].id],
    )
    assert result.status.value != "feasible"


def test_proven_hard_violations_unknown_on_unproven_lanes() -> None:
    """W16b-1: greedy lane inference demotion must not hide setup gaps."""
    from synaps.solvers.feasibility_checker import (
        FeasibilityViolation,
        proven_hard_violations,
    )

    unproven = FeasibilityViolation(
        "LANE_INFERENCE_UNPROVEN",
        "greedy fallback",
        work_center_id="wc-1",
    )
    gap = FeasibilityViolation(
        "SETUP_GAP_VIOLATION",
        "planted gap",
        work_center_id="wc-1",
    )
    proven = proven_hard_violations([unproven, gap])
    # The gap is demoted, but the unproven lane itself must surface as UNKNOWN.
    assert any(v.kind == "LANE_INFERENCE_UNPROVEN" for v in proven)
    assert not any(v.kind == "SETUP_GAP_VIOLATION" for v in proven)


def test_native_repair_skips_aux_and_records_reason() -> None:
    """Coverage #6: native greedy is aux-blind — skip, do not inject."""
    from synaps.model import AuxiliaryResource, OperationAuxRequirement

    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    aux = AuxiliaryResource(code="tool", resource_type="fixture", pool_size=1)
    problem = problem.model_copy(
        update={
            "auxiliary_resources": [aux],
            "aux_requirements": [
                OperationAuxRequirement(
                    operation_id=problem.operations[0].id,
                    aux_resource_id=aux.id,
                    quantity_needed=1,
                )
            ],
        }
    )
    reasons: list[str] = []
    repaired = _try_native_greedy_repair(
        problem,
        [],
        [problem.operations[0].id],
        {problem.operations[0].id: 0},
        skip_reasons=reasons,
    )
    assert repaired is None
    assert "aux_requirements" in reasons


def test_native_repair_validation_ignores_foreign_frozen_ops() -> None:
    """Coverage #6: frozen ops outside the window problem are not UNKNOWN faults."""
    from uuid import uuid4

    from synaps.model import Assignment
    from synaps.solvers.alns_solver import _native_repair_blocking_violations

    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    op = problem.operations[0]
    wc = problem.work_centers[0]
    horizon = problem.planning_horizon_start
    repaired = Assignment(
        operation_id=op.id,
        work_center_id=wc.id,
        start_time=horizon + timedelta(minutes=30),
        end_time=horizon + timedelta(minutes=30 + op.base_duration_min),
    )
    frozen = Assignment(
        operation_id=uuid4(),
        work_center_id=wc.id,
        start_time=horizon,
        end_time=horizon + timedelta(minutes=10),
    )
    assert (
        _native_repair_blocking_violations(problem, [frozen], [repaired], [op.id]) == []
    )


def test_stabilize_refuses_horizon_ceiling() -> None:
    """Coverage #3: stabilize must not push an op past latest_finish/horizon."""
    from synaps.model import Assignment
    from synaps.solvers.rhc._window import stabilize_temporal_consistency

    horizon = datetime(2026, 1, 1, tzinfo=UTC)
    wc = WorkCenter(code="M", capability_group="G")
    state = State(code="S")
    order = Order(external_ref="O", due_date=horizon + timedelta(hours=2))
    op_a = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=20,
        eligible_wc_ids=[wc.id],
    )
    op_b = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=state.id,
        base_duration_min=20,
        eligible_wc_ids=[wc.id],
        latest_finish=horizon + timedelta(minutes=25),
    )
    a = Assignment(
        operation_id=op_a.id,
        work_center_id=wc.id,
        start_time=horizon,
        end_time=horizon + timedelta(minutes=20),
    )
    b = Assignment(
        operation_id=op_b.id,
        work_center_id=wc.id,
        start_time=horizon + timedelta(minutes=5),
        end_time=horizon + timedelta(minutes=25),
    )
    stats = stabilize_temporal_consistency(
        [a, b],
        ops_by_id={op_a.id: op_a, op_b.id: op_b},
        setup_minutes={},
        horizon_end=horizon + timedelta(minutes=30),
    )
    assert stats["ceiling_blocks"] >= 1
    assert stats["converged"] == 0
    assert b.end_time <= horizon + timedelta(minutes=25)


def test_reanchor_stacked_external_blockers_terminates() -> None:
    """Stacked frozen extra-ops must not pin ALNS reanchor in a while-True loop."""
    from uuid import uuid4

    from synaps.model import Assignment
    from synaps.solvers._dispatch_support import build_dispatch_context
    from synaps.solvers.alns_solver import _reanchor_against_frozen

    horizon = datetime(2026, 1, 1, tzinfo=UTC)
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=horizon + timedelta(days=1))
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
        planning_horizon_start=horizon,
        planning_horizon_end=horizon + timedelta(days=1),
    )
    inner = Assignment(
        operation_id=op.id,
        work_center_id=wc.id,
        start_time=horizon,
        end_time=horizon + timedelta(minutes=10),
    )
    # Short blocker first: the old next() picked this forever when float dust
    # kept the same grain-snapped slot overlapping the long blocker.
    short = Assignment(
        operation_id=uuid4(),
        work_center_id=wc.id,
        start_time=horizon,
        end_time=horizon + timedelta(minutes=10, microseconds=1),
    )
    long = Assignment(
        operation_id=uuid4(),
        work_center_id=wc.id,
        start_time=horizon,
        end_time=horizon + timedelta(minutes=100),
    )
    result, _changed = _reanchor_against_frozen(
        [inner],
        problem=problem,
        frozen_assignments=[short, long],
        ops_by_id={op.id: op},
        op_positions={op.id: 0},
        frozen_assignments_by_op={},
        frozen_predecessor_end_offsets={},
        dispatch_context=build_dispatch_context(problem),
    )
    assert result, "reanchor must terminate with a placement or fail-closed empty"
    assert result[0].start_time >= long.end_time - timedelta(microseconds=1)


def test_native_seed_tournament_prefers_cheaper_greedy() -> None:
    """Small-n native packing must not lock ALNS onto a worse-than-greedy seed."""
    from synaps.solvers.alns_solver import _maybe_prefer_python_seed
    from synaps.solvers.greedy_dispatch import GreedyDispatch
    from synaps.solvers.sdst_matrix import SdstMatrix

    problem = make_simple_problem(n_orders=4, ops_per_order=2)
    greedy = GreedyDispatch().solve(problem)
    native = _try_native_initial_seed(
        problem,
        frozen_assignments=[],
        ops_by_id={op.id: op for op in problem.operations},
        frozen_assignments_by_op={},
    )
    if native is None:
        pytest.skip("native seed unavailable")
    name, chosen = _maybe_prefer_python_seed(
        problem,
        native,
        n_ops=len(problem.operations),
        initial_beam_op_limit=60,
        seed_budget_s=5.0,
        sdst=SdstMatrix.from_problem(problem),
        ops_by_id={op.id: op for op in problem.operations},
        objective_weights={"makespan": 1.0},
        is_valid=lambda assignments: len(assignments) == len(problem.operations),
    )
    greedy_ms = greedy.objective.makespan_minutes
    native_ms = max(
        (a.end_time - problem.planning_horizon_start).total_seconds() / 60.0
        for a in native
    )
    chosen_ms = max(
        (a.end_time - problem.planning_horizon_start).total_seconds() / 60.0
        for a in chosen
    )
    if native_ms > greedy_ms + 1e-9:
        assert name == "greedy"
    assert chosen_ms <= min(native_ms, greedy_ms) + 1e-6
