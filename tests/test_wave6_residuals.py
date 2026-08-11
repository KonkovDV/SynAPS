"""Wave 6 tests: ALNS native override skip, energy in search, MAB pairs, SDST pack."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from synaps.model import (
    Assignment,
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import (
    _objective_cost,
    _ops_have_machine_duration_overrides,
    _try_native_greedy_repair,
)
from synaps.solvers.sdst_matrix import SdstMatrix

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)
_SDST_DIR = (
    Path(__file__).resolve().parent.parent
    / "benchmark"
    / "instances"
    / "public"
    / "sdst"
)


def test_ops_have_machine_duration_overrides_detects_field() -> None:
    op = Operation(
        order_id=uuid4(),
        seq_in_order=1,
        state_id=uuid4(),
        base_duration_min=10,
        machine_duration_overrides={uuid4(): 7},
    )
    assert _ops_have_machine_duration_overrides([op])
    bare = Operation(
        order_id=uuid4(), seq_in_order=1, state_id=uuid4(), base_duration_min=10
    )
    assert not _ops_have_machine_duration_overrides([bare])


def test_native_greedy_repair_skips_when_overrides_present() -> None:
    s1 = State(code="a")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s1.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
        machine_duration_overrides={wc.id: 12},
    )
    problem = ScheduleProblem(
        states=[s1],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    outcome = _try_native_greedy_repair(
        problem, [], [op.id], {op.id: 0}
    )
    assert outcome is None


def test_objective_cost_includes_energy_weight() -> None:
    obj = ObjectiveValues(makespan_minutes=10.0, total_energy_kwh=4.0)
    assert _objective_cost(obj, {"makespan": 1.0, "energy": 2.0}) == 18.0
    assert _objective_cost(obj, {"makespan": 1.0}) == 10.0


def test_sdst_matrix_get_energy() -> None:
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op = Operation(
        order_id=order.id, seq_in_order=1, state_id=s1.id, base_duration_min=1,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=s1.id,
                to_state_id=s2.id,
                setup_minutes=1,
                energy_kwh=2.25,
            )
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    sdst = SdstMatrix.from_problem(problem)
    assert sdst.get_energy(wc.id, s1.id, s2.id) == 2.25
    assert sdst.get_energy(wc.id, s2.id, s1.id) == 0.0


def test_sdst_pack_fixtures_parse() -> None:
    from benchmark.sdst_fjs_loader import load_sdst_fjs_problem

    stems = ["toy_2x2", "fattahi_style_3x3", "medium_4x3"]
    for stem in stems:
        problem = load_sdst_fjs_problem(_SDST_DIR / f"{stem}.sdstfjs")
        assert problem.setup_matrix, stem
        assert len(problem.orders) >= 2


def test_alns_mab_pair_metadata_and_runs() -> None:
    from synaps.solvers.alns_solver import AlnsSolver

    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    orders = [Order(external_ref="O1", due_date=_HE), Order(external_ref="O2", due_date=_HE)]
    ops = [
        Operation(
            order_id=orders[0].id, seq_in_order=1, state_id=s1.id,
            base_duration_min=5, eligible_wc_ids=[wc.id],
        ),
        Operation(
            order_id=orders[1].id, seq_in_order=1, state_id=s2.id,
            base_duration_min=5, eligible_wc_ids=[wc.id],
        ),
    ]
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=orders,
        operations=ops,
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id,
                setup_minutes=2, energy_kwh=1.0,
            )
        ],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    result = AlnsSolver().solve(
        problem,
        time_limit_s=3,
        max_iterations=20,
        mab_pair_selection=True,
        use_cpsat_repair=False,
        objective_weights={"makespan": 1.0, "energy": 1.0},
    )
    assert result.metadata.get("mab_pair_selection") is True
    assert result.metadata.get("mab_pair_count", 0) >= 1
    assert result.metadata.get("mab_repair_modes") == ["greedy"]
    assert result.objective.total_energy_kwh >= 0.0
