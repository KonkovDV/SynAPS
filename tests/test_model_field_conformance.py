"""M0: solver x model-field conformance matrix (Red Team audit v2).

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
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
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


# (field, builder) pairs. Each builder returns (problem, field_name).
FIELD_BUILDERS = [
    _release_date_instance,
    _max_parallel_instance,
    _speed_factor_instance,
    _predecessor_instance,
    _setup_minutes_instance,
]


def _minutes(a) -> float:
    return (a.end_time - a.start_time).total_seconds() / 60.0


@pytest.mark.parametrize("solver_config", REPRESENTATIVES)
@pytest.mark.parametrize("builder", FIELD_BUILDERS, ids=lambda b: b.__name__)
def test_solver_field_conformance(solver_config: str, builder) -> None:
    """M0: every representative solver honors every guarded model field."""
    problem, field = builder()
    result = _solve(solver_config, problem)
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

    # In every case the produced schedule must itself be feasible.
    assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True), (
        f"{solver_config}/{field}: produced an infeasible schedule"
    )
