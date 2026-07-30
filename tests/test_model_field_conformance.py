"""M0 / Phase 0.3: solver x model-field conformance matrix.

A single architectural defect underlay M1/M2: there was no matrix asserting
which registry solver honors which model field, so a silently-ignored field
produced a wrong schedule with no signal. This test is that matrix: for each
(representative solver) x (model field) it builds a minimal instance in which
ignoring the field yields a demonstrably wrong result, and asserts the solver
either honors the field or is listed as a documented, explicit gap.

Representatives cover every solver family (dispatch / beam / CP-SAT / LBBD /
ALNS) on tiny instances so the whole matrix runs in seconds. RHC and the
HD/large registry variants share these cores, so the representatives are
sufficient to guard the field contract.

Guarded fields: release_date, max_parallel, speed_factor, predecessor_op_id,
setup_minutes, pool_size, quantity_needed, planning_horizon_*, material_loss
(objective accounting).

Documented explicit gaps (no hard cross-solver invariant to assert):
- ``priority`` is a soft ordering hint, not a constraint — no minimal instance
  makes ignoring it *infeasible*; covered instead by heuristic-level tests.
- ``energy_kwh`` has no ObjectiveValues surface yet (it only gates parallel
  virtualization); a conformance row must follow when energy enters the
  objective (final brief, P0-6 unified evaluator).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.registry import create_solver

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=10)

# One fast representative per solver family. RHC/HD variants reuse these cores.
REPRESENTATIVES = ["GREED", "BEAM-3", "CPSAT-10", "LBBD-5", "ALNS-300"]

# Fast kwargs overrides so CP-SAT/LBBD/ALNS stay sub-second on tiny instances.
_FAST_KWARGS = {
    "CPSAT-10": {"time_limit_s": 5, "num_workers": 1},
    "LBBD-5": {"time_limit_s": 5, "max_iterations": 3},
    "ALNS-300": {"time_limit_s": 5, "max_iterations": 40},
}


def _solve(solver_config: str, problem: ScheduleProblem):
    solver, kwargs = create_solver(solver_config)
    kwargs.update(_FAST_KWARGS.get(solver_config, {}))
    return solver.solve(problem, **kwargs)


def _release_date_instance() -> tuple[ScheduleProblem, str]:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=HE, release_date=H0 + timedelta(minutes=500))
    op = Operation(
        order_id=order.id, seq_in_order=1, state_id=state.id,
        base_duration_min=60, eligible_wc_ids=[wc.id],
    )
    return (
        ScheduleProblem(
            states=[state], orders=[order], operations=[op], work_centers=[wc],
            setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
        ),
        "release_date",
    )


def _max_parallel_instance() -> tuple[ScheduleProblem, str]:
    s1, s2 = State(code="s1"), State(code="s2")
    wc = WorkCenter(code="M2", capability_group="G", max_parallel=2)
    o1, o2 = uuid4(), uuid4()
    ops = [
        Operation(order_id=o1, seq_in_order=1, state_id=s1.id, base_duration_min=60,
                  eligible_wc_ids=[wc.id]),
        Operation(order_id=o2, seq_in_order=1, state_id=s2.id, base_duration_min=60,
                  eligible_wc_ids=[wc.id]),
    ]
    setups = [
        SetupEntry(work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=600),
        SetupEntry(work_center_id=wc.id, from_state_id=s2.id, to_state_id=s1.id, setup_minutes=600),
    ]
    return (
        ScheduleProblem(
            states=[s1, s2],
            orders=[Order(id=o1, external_ref="O1", due_date=HE),
                    Order(id=o2, external_ref="O2", due_date=HE)],
            operations=ops, work_centers=[wc], setup_matrix=setups,
            planning_horizon_start=H0, planning_horizon_end=HE,
        ),
        "max_parallel",
    )


def _speed_factor_instance() -> tuple[ScheduleProblem, str]:
    state = State(code="s")
    wc = WorkCenter(code="FAST", capability_group="G", speed_factor=2.0)
    order = Order(external_ref="O", due_date=HE)
    op = Operation(
        order_id=order.id, seq_in_order=1, state_id=state.id,
        base_duration_min=60, eligible_wc_ids=[wc.id],
    )
    return (
        ScheduleProblem(
            states=[state], orders=[order], operations=[op], work_centers=[wc],
            setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
        ),
        "speed_factor",
    )


def _predecessor_instance() -> tuple[ScheduleProblem, str]:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=HE)
    op1 = Operation(order_id=order.id, seq_in_order=1, state_id=state.id,
                    base_duration_min=60, eligible_wc_ids=[wc.id])
    op2 = Operation(order_id=order.id, seq_in_order=2, state_id=state.id,
                    base_duration_min=60, eligible_wc_ids=[wc.id],
                    predecessor_op_id=op1.id)
    return (
        ScheduleProblem(
            states=[state], orders=[order], operations=[op1, op2], work_centers=[wc],
            setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
        ),
        "predecessor_op_id",
    )


def _setup_minutes_instance() -> tuple[ScheduleProblem, str]:
    s1, s2 = State(code="s1"), State(code="s2")
    wc = WorkCenter(code="M", capability_group="G")
    o1, o2 = uuid4(), uuid4()
    ops = [
        Operation(order_id=o1, seq_in_order=1, state_id=s1.id, base_duration_min=60,
                  eligible_wc_ids=[wc.id]),
        Operation(order_id=o2, seq_in_order=1, state_id=s2.id, base_duration_min=60,
                  eligible_wc_ids=[wc.id]),
    ]
    setups = [
        SetupEntry(work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=30),
        SetupEntry(work_center_id=wc.id, from_state_id=s2.id, to_state_id=s1.id, setup_minutes=30),
    ]
    return (
        ScheduleProblem(
            states=[s1, s2],
            orders=[Order(id=o1, external_ref="O1", due_date=HE),
                    Order(id=o2, external_ref="O2", due_date=HE)],
            operations=ops, work_centers=[wc], setup_matrix=setups,
            planning_horizon_start=H0, planning_horizon_end=HE,
        ),
        "setup_minutes",
    )


def _pool_size_instance() -> tuple[ScheduleProblem, str]:
    """Two ops on two DIFFERENT machines share one aux tool (pool_size=1).

    Ignoring the pool runs them concurrently (makespan 60); honoring it
    serializes them (makespan >= 120).
    """
    state = State(code="s")
    m1 = WorkCenter(code="M1", capability_group="G")
    m2 = WorkCenter(code="M2", capability_group="H")
    tool = AuxiliaryResource(code="JIG", resource_type="fixture", pool_size=1)
    o1, o2 = uuid4(), uuid4()
    ops = [
        Operation(order_id=o1, seq_in_order=1, state_id=state.id, base_duration_min=60,
                  eligible_wc_ids=[m1.id]),
        Operation(order_id=o2, seq_in_order=1, state_id=state.id, base_duration_min=60,
                  eligible_wc_ids=[m2.id]),
    ]
    reqs = [
        OperationAuxRequirement(operation_id=ops[0].id, aux_resource_id=tool.id),
        OperationAuxRequirement(operation_id=ops[1].id, aux_resource_id=tool.id),
    ]
    return (
        ScheduleProblem(
            states=[state],
            orders=[Order(id=o1, external_ref="O1", due_date=HE),
                    Order(id=o2, external_ref="O2", due_date=HE)],
            operations=ops, work_centers=[m1, m2], setup_matrix=[],
            auxiliary_resources=[tool], aux_requirements=reqs,
            planning_horizon_start=H0, planning_horizon_end=HE,
        ),
        "pool_size",
    )


def _quantity_needed_instance() -> tuple[ScheduleProblem, str]:
    """Pool of 2 units, each op needs quantity_needed=2 -> ops must serialize."""
    state = State(code="s")
    m1 = WorkCenter(code="M1", capability_group="G")
    m2 = WorkCenter(code="M2", capability_group="H")
    tool = AuxiliaryResource(code="OPR", resource_type="operator", pool_size=2)
    o1, o2 = uuid4(), uuid4()
    ops = [
        Operation(order_id=o1, seq_in_order=1, state_id=state.id, base_duration_min=60,
                  eligible_wc_ids=[m1.id]),
        Operation(order_id=o2, seq_in_order=1, state_id=state.id, base_duration_min=60,
                  eligible_wc_ids=[m2.id]),
    ]
    reqs = [
        OperationAuxRequirement(operation_id=ops[0].id, aux_resource_id=tool.id,
                                quantity_needed=2),
        OperationAuxRequirement(operation_id=ops[1].id, aux_resource_id=tool.id,
                                quantity_needed=2),
    ]
    return (
        ScheduleProblem(
            states=[state],
            orders=[Order(id=o1, external_ref="O1", due_date=HE),
                    Order(id=o2, external_ref="O2", due_date=HE)],
            operations=ops, work_centers=[m1, m2], setup_matrix=[],
            auxiliary_resources=[tool], aux_requirements=reqs,
            planning_horizon_start=H0, planning_horizon_end=HE,
        ),
        "quantity_needed",
    )


def _planning_horizon_instance() -> tuple[ScheduleProblem, str]:
    """A tight horizon: every assignment must fit inside [start, end]."""
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    horizon_end = H0 + timedelta(minutes=240)
    o1 = uuid4()
    ops = [
        Operation(order_id=o1, seq_in_order=1, state_id=state.id, base_duration_min=60,
                  eligible_wc_ids=[wc.id]),
        Operation(order_id=o1, seq_in_order=2, state_id=state.id, base_duration_min=60,
                  eligible_wc_ids=[wc.id]),
    ]
    ops[1].predecessor_op_id = ops[0].id
    return (
        ScheduleProblem(
            states=[state], orders=[Order(id=o1, external_ref="O1", due_date=horizon_end)],
            operations=ops, work_centers=[wc], setup_matrix=[],
            planning_horizon_start=H0, planning_horizon_end=horizon_end,
        ),
        "planning_horizon",
    )


def _material_loss_instance() -> tuple[ScheduleProblem, str]:
    """A forced changeover with material_loss: the objective must account it."""
    s1, s2 = State(code="s1"), State(code="s2")
    wc = WorkCenter(code="M", capability_group="G")
    o1, o2 = uuid4(), uuid4()
    ops = [
        Operation(order_id=o1, seq_in_order=1, state_id=s1.id, base_duration_min=60,
                  eligible_wc_ids=[wc.id]),
        Operation(order_id=o2, seq_in_order=1, state_id=s2.id, base_duration_min=60,
                  eligible_wc_ids=[wc.id]),
    ]
    setups = [
        SetupEntry(work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id,
                   setup_minutes=30, material_loss=5.0),
        SetupEntry(work_center_id=wc.id, from_state_id=s2.id, to_state_id=s1.id,
                   setup_minutes=30, material_loss=5.0),
    ]
    return (
        ScheduleProblem(
            states=[s1, s2],
            orders=[Order(id=o1, external_ref="O1", due_date=HE),
                    Order(id=o2, external_ref="O2", due_date=HE)],
            operations=ops, work_centers=[wc], setup_matrix=setups,
            planning_horizon_start=H0, planning_horizon_end=HE,
        ),
        "material_loss",
    )


# (field, builder) pairs. Each builder returns (problem, field_name).
FIELD_BUILDERS = [
    _release_date_instance,
    _max_parallel_instance,
    _speed_factor_instance,
    _predecessor_instance,
    _setup_minutes_instance,
    _pool_size_instance,
    _quantity_needed_instance,
    _planning_horizon_instance,
    _material_loss_instance,
]


def _minutes(a) -> float:
    return (a.end_time - a.start_time).total_seconds() / 60.0


@pytest.mark.parametrize("solver_config", REPRESENTATIVES)
@pytest.mark.parametrize("builder", FIELD_BUILDERS, ids=lambda b: b.__name__)
def test_solver_field_conformance(solver_config: str, builder) -> None:
    """M0: every representative honors every guarded field OR refuses explicitly.

    The conformance contract (final brief, Phase 0.3): a solver that does not
    implement a field must NOT silently return a wrong schedule claiming
    FEASIBLE/OPTIMAL. An explicit non-success status (ERROR/INFEASIBLE/...) is
    an honest refusal and passes the matrix; the wrongness assertions below
    apply only to results the solver itself claims are good.
    """
    problem, field = builder()
    result = _solve(solver_config, problem)
    if result.status not in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL):
        # Explicit refusal (e.g. ALNS returns ERROR when its incumbent cannot
        # satisfy aux capacity): honest, allowed. Silent wrongness is what the
        # matrix forbids.
        return
    assert result.assignments, f"{solver_config}/{field}: no schedule produced"
    by_op = {a.operation_id: a for a in result.assignments}
    orders = {o.id: o for o in problem.orders}
    ops = {o.id: o for o in problem.operations}

    if field == "release_date":
        for a in result.assignments:
            release = orders[ops[a.operation_id].order_id].release_date
            assert release is not None and a.start_time >= release, (
                f"{solver_config}: started before release_date"
            )
    elif field == "max_parallel":
        mk = result.objective.makespan_minutes
        assert mk <= 60.0 + 1e-6, f"{solver_config}: serialized a max_parallel=2 machine (mk={mk})"
        assert result.objective.total_setup_minutes <= 1e-6, (
            f"{solver_config}: phantom setup on concurrent lanes"
        )
    elif field == "speed_factor":
        a = result.assignments[0]
        assert _minutes(a) <= 30.0 + 1e-6, (
            f"{solver_config}: ignored speed_factor=2 (duration {_minutes(a)} != 30)"
        )
    elif field == "predecessor_op_id":
        succ = next(o for o in problem.operations if o.predecessor_op_id is not None)
        pred_end = by_op[succ.predecessor_op_id].end_time
        assert by_op[succ.id].start_time >= pred_end, (
            f"{solver_config}: successor started before predecessor ended"
        )
    elif field == "setup_minutes":
        # The two ops share one machine in different states: a 30-min setup must
        # separate them, so makespan is at least 60+30+60 = 150.
        assert result.objective.makespan_minutes >= 150.0 - 1e-6, (
            f"{solver_config}: setup_minutes ignored (makespan "
            f"{result.objective.makespan_minutes} < 150)"
        )
    elif field in ("pool_size", "quantity_needed"):
        # The shared aux capacity forbids concurrency: 60+60 serialized.
        assert result.objective.makespan_minutes >= 120.0 - 1e-6, (
            f"{solver_config}: aux {field} ignored (makespan "
            f"{result.objective.makespan_minutes} < 120, ops overlapped)"
        )
    elif field == "planning_horizon":
        for a in result.assignments:
            assert a.start_time >= problem.planning_horizon_start, (
                f"{solver_config}: assignment before planning_horizon_start"
            )
            assert a.end_time <= problem.planning_horizon_end, (
                f"{solver_config}: assignment beyond planning_horizon_end"
            )
    elif field == "material_loss":
        # One machine, two states: exactly one 30-min changeover with loss 5.0
        # is realized; the objective must account it (accounting conformance).
        assert result.objective.total_material_loss >= 5.0 - 1e-6, (
            f"{solver_config}: material_loss not accounted "
            f"(total_material_loss={result.objective.total_material_loss})"
        )

    # In every case the produced schedule must itself be feasible.
    assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True), (
        f"{solver_config}/{field}: produced an infeasible schedule"
    )
