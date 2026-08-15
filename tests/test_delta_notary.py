"""S4 delta notary: McKeeman differential vs exhaustive, Lemma I, A4 aux."""

from __future__ import annotations

from datetime import timedelta

from synaps.model import (
    Assignment,
    AuxiliaryResource,
    OperationAuxRequirement,
    SolverStatus,
)
from synaps.solvers.delta_notary import notarize_repair
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.incremental_repair import IncrementalRepair
from tests.conftest import HORIZON_START, make_simple_problem


def _kinds(outcome) -> set[str]:
    return {item.kind for item in outcome.violations}


def test_shadow_matches_exhaustive_on_feasible_repair() -> None:
    problem = make_simple_problem(n_orders=2, ops_per_order=2)
    base = GreedyDispatch().solve(problem)
    assert base.status == SolverStatus.FEASIBLE
    repaired = IncrementalRepair().solve(
        problem,
        base_assignments=base.assignments,
        disrupted_op_ids=[problem.operations[0].id],
        radius=2,
        notary="shadow",
    )
    assert repaired.status == SolverStatus.FEASIBLE
    assert repaired.metadata["notary_mode"] == "shadow"
    assert repaired.metadata["notary_mismatch"] is False
    exhaustive = FeasibilityChecker().check(problem, repaired.assignments, exhaustive=True)
    assert exhaustive == []


def test_default_repair_notary_is_exhaustive() -> None:
    problem = make_simple_problem(n_orders=1, ops_per_order=2)
    base = GreedyDispatch().solve(problem)
    repaired = IncrementalRepair().solve(
        problem,
        base_assignments=base.assignments,
        disrupted_op_ids=[problem.operations[0].id],
    )
    assert repaired.metadata["notary_mode"] == "exhaustive"
    assert repaired.metadata["notary_mismatch"] is False


def test_lemma_i_inherited_overlap_delta_misses_shadow_fail_closes() -> None:
    """Unchanged serial machine can hide an inherited overlap (Lemma I)."""

    problem = make_simple_problem(n_orders=3, ops_per_order=1)
    op0, op1, op2 = problem.operations
    wc1, wc2 = problem.work_centers[0].id, problem.work_centers[1].id
    overlap_a = Assignment(
        operation_id=op0.id,
        work_center_id=wc1,
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(minutes=30),
    )
    overlap_b = Assignment(
        operation_id=op1.id,
        work_center_id=wc1,
        start_time=HORIZON_START + timedelta(minutes=10),
        end_time=HORIZON_START + timedelta(minutes=40),
    )
    movable = Assignment(
        operation_id=op2.id,
        work_center_id=wc2,
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(minutes=30),
        setup_minutes=0,
    )
    shifted = movable.model_copy(
        update={
            "start_time": HORIZON_START + timedelta(minutes=5),
            "end_time": HORIZON_START + timedelta(minutes=35),
        }
    )
    baseline = [overlap_a, overlap_b, movable]
    repaired = [overlap_a, overlap_b, shifted]
    delta = notarize_repair(problem, repaired, mode="delta", baseline=baseline)
    shadow = notarize_repair(problem, repaired, mode="shadow", baseline=baseline)
    exhaustive = notarize_repair(problem, repaired, mode="exhaustive", baseline=baseline)
    assert "MACHINE_OVERLAP" not in _kinds(delta)
    assert "MACHINE_OVERLAP" in _kinds(exhaustive)
    assert shadow.mismatch is True
    assert "MACHINE_OVERLAP" in _kinds(shadow)


def test_lemma_a_aux_overload_outside_neighbourhood_is_still_caught() -> None:
    """One shared pool: dirty-op slice would miss frozen aux overload (A4)."""

    problem = make_simple_problem(n_orders=3, ops_per_order=1)
    op0, op1, op2 = problem.operations
    wc1, wc2 = problem.work_centers[0].id, problem.work_centers[1].id
    drum = AuxiliaryResource(code="DRUM", resource_type="drum", pool_size=1)
    problem = problem.model_copy(
        update={
            "auxiliary_resources": [drum],
            "aux_requirements": [
                OperationAuxRequirement(
                    operation_id=op0.id, aux_resource_id=drum.id, quantity_needed=1
                ),
                OperationAuxRequirement(
                    operation_id=op1.id, aux_resource_id=drum.id, quantity_needed=1
                ),
                OperationAuxRequirement(
                    operation_id=op2.id, aux_resource_id=drum.id, quantity_needed=1
                ),
            ],
        }
    )
    frozen_a = Assignment(
        operation_id=op0.id,
        work_center_id=wc1,
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(minutes=30),
    )
    frozen_b = Assignment(
        operation_id=op1.id,
        work_center_id=wc1,
        start_time=HORIZON_START + timedelta(minutes=40),
        end_time=HORIZON_START + timedelta(minutes=70),
    )
    # Overlap A with a later copy of A-time via op1 moved earlier — plant overlap
    # on aux by putting op1 on wc2 in the same window as op0.
    frozen_b = frozen_b.model_copy(
        update={
            "work_center_id": wc2,
            "start_time": HORIZON_START + timedelta(minutes=5),
            "end_time": HORIZON_START + timedelta(minutes=35),
        }
    )
    movable = Assignment(
        operation_id=op2.id,
        work_center_id=wc2,
        start_time=HORIZON_START + timedelta(minutes=80),
        end_time=HORIZON_START + timedelta(minutes=110),
    )
    shifted = movable.model_copy(
        update={
            "start_time": HORIZON_START + timedelta(minutes=90),
            "end_time": HORIZON_START + timedelta(minutes=120),
        }
    )
    baseline = [frozen_a, frozen_b, movable]
    repaired = [frozen_a, frozen_b, shifted]
    delta = notarize_repair(problem, repaired, mode="delta", baseline=baseline)
    assert "AUX_RESOURCE_CAPACITY_VIOLATION" in _kinds(delta)
    shadow = notarize_repair(problem, repaired, mode="shadow", baseline=baseline)
    assert shadow.mismatch is False
    assert "AUX_RESOURCE_CAPACITY_VIOLATION" in _kinds(shadow)


def test_delta_without_baseline_falls_back_to_exhaustive() -> None:
    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    op = problem.operations[0]
    wc = problem.work_centers[0].id
    assignments = [
        Assignment(
            operation_id=op.id,
            work_center_id=wc,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=30),
        )
    ]
    outcome = notarize_repair(problem, assignments, mode="delta", baseline=None)
    assert outcome.mode == "exhaustive"
    assert outcome.violations == []
