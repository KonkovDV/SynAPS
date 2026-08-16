"""Wave 7 tests: destroy_worst energy, native override metadata, repair extract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import AlnsSolver, _destroy_worst
from synaps.solvers.sdst_matrix import SdstMatrix

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def _three_op_energy_problem() -> tuple[ScheduleProblem, list[Assignment], SdstMatrix]:
    s_low, s_high, s_mid = State(code="L"), State(code="H"), State(code="M")
    wc = WorkCenter(code="M1", capability_group="G")
    orders = [
        Order(external_ref="O1", due_date=_HE),
        Order(external_ref="O2", due_date=_HE),
        Order(external_ref="O3", due_date=_HE),
    ]
    ops = [
        Operation(
            order_id=orders[0].id,
            seq_in_order=1,
            state_id=s_low.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
        ),
        Operation(
            order_id=orders[1].id,
            seq_in_order=1,
            state_id=s_high.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
        ),
        Operation(
            order_id=orders[2].id,
            seq_in_order=1,
            state_id=s_mid.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
        ),
    ]
    # Equal setup minutes; only L→H / H→M carry energy so middle op is worst
    # when energy_weight > 0.
    setups = [
        SetupEntry(
            work_center_id=wc.id,
            from_state_id=s_low.id,
            to_state_id=s_high.id,
            setup_minutes=1,
            energy_kwh=100.0,
        ),
        SetupEntry(
            work_center_id=wc.id,
            from_state_id=s_high.id,
            to_state_id=s_mid.id,
            setup_minutes=1,
            energy_kwh=100.0,
        ),
        SetupEntry(
            work_center_id=wc.id,
            from_state_id=s_low.id,
            to_state_id=s_mid.id,
            setup_minutes=1,
            energy_kwh=0.0,
        ),
    ]
    problem = ScheduleProblem(
        states=[s_low, s_high, s_mid],
        orders=orders,
        operations=ops,
        work_centers=[wc],
        setup_matrix=setups,
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    assignments = [
        Assignment(
            operation_id=ops[0].id,
            work_center_id=wc.id,
            start_time=_H0,
            end_time=_H0 + timedelta(minutes=5),
            setup_minutes=0,
        ),
        Assignment(
            operation_id=ops[1].id,
            work_center_id=wc.id,
            start_time=_H0 + timedelta(minutes=6),
            end_time=_H0 + timedelta(minutes=11),
            setup_minutes=1,
        ),
        Assignment(
            operation_id=ops[2].id,
            work_center_id=wc.id,
            start_time=_H0 + timedelta(minutes=12),
            end_time=_H0 + timedelta(minutes=17),
            setup_minutes=1,
        ),
    ]
    return problem, assignments, SdstMatrix.from_problem(problem)


def test_destroy_worst_prefers_high_energy_when_weighted() -> None:
    problem, assignments, sdst = _three_op_energy_problem()
    ops_by_id = {op.id: op for op in problem.operations}
    mid_id = problem.operations[1].id

    class _AlwaysPickRanked:
        def random(self) -> float:
            return 0.0  # always take the current ranked candidate

        def choice(self, seq):  # pragma: no cover - size=1 should not need fill
            return seq[0]

    destroyed = _destroy_worst(
        assignments,
        problem,
        sdst,
        destroy_size=1,
        rng=_AlwaysPickRanked(),  # type: ignore[arg-type]
        ops_by_id=ops_by_id,
        energy_weight=1.0,
    )
    assert destroyed == {mid_id}


def test_native_override_seed_fallback_reason_in_metadata() -> None:
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
    result = AlnsSolver().solve(
        problem,
        time_limit_s=2,
        max_iterations=5,
        use_cpsat_repair=False,
        native_initial_seed_enabled=True,
    )
    assert result.metadata.get("native_initial_seed_attempted") is True
    assert (
        result.metadata.get("native_initial_seed_fallback_reason") == "machine_duration_overrides"
    )
    # Repair reason is observe-only (not problem-wide pretension).
    assert result.metadata.get("native_greedy_repair_override_skips", 0) >= 0


def test_native_repair_fallback_reason_only_when_skipped() -> None:
    """Mixed overrides: bare disrupted ops may still use native; do not pretension."""
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    orders = [
        Order(external_ref="O1", due_date=_HE),
        Order(external_ref="O2", due_date=_HE),
    ]
    op_override = Operation(
        order_id=orders[0].id,
        seq_in_order=1,
        state_id=s1.id,
        base_duration_min=5,
        eligible_wc_ids=[wc.id],
        machine_duration_overrides={wc.id: 7},
    )
    op_bare = Operation(
        order_id=orders[1].id,
        seq_in_order=1,
        state_id=s2.id,
        base_duration_min=5,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=orders,
        operations=[op_override, op_bare],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    result = AlnsSolver().solve(
        problem,
        time_limit_s=3,
        max_iterations=30,
        use_cpsat_repair=False,
        native_initial_seed_enabled=True,
        destroy_fraction=0.5,
        min_destroy=1,
        max_destroy=2,
    )
    # Seed is problem-wide: any override → skip.
    if result.metadata.get("native_initial_seed_attempted"):
        assert (
            result.metadata.get("native_initial_seed_fallback_reason")
            == "machine_duration_overrides"
        )
    # Repair reason must not be pretensioned merely because the problem has overrides.
    # It is set only when a disrupted set that includes overrides was actually skipped.
    reason = result.metadata.get("native_greedy_repair_fallback_reason")
    skips = int(result.metadata.get("native_greedy_repair_override_skips", 0))
    if reason is not None:
        assert reason == "machine_duration_overrides"
        assert skips >= 1
    else:
        assert skips == 0
