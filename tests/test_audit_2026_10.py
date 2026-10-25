"""Regression tests for the 2026-10 deep audit (algebra + truth-gate findings).

Each test pins one verified defect (IDs match ``docs/rfc/AUDIT_2026_10.md``):

* A-01 float-robust integer grain (``21 / 0.7`` used to reserve 31 minutes);
* A-02 checker calendar check trusted the solver's ``setup_minutes`` stamp;
* A-03 checker aux-calendar check trusted the solver's ``aux_resource_ids``;
* A-04 CP-SAT silently truncated fractional objective weights to 0;
* A-05 CP-SAT due offsets truncated toward zero instead of flooring;
* A-06 BHK distinct-state Hamiltonian path is NOT a setup lower bound when a
  state repeats on a non-metric matrix; the metric-closure BHK is;
* A-07 coverage classification counted duplicate assignments as coverage;
* A-08 RHC coverage-pace controller never observed inner-solver windows;
* A-09 ALNS repair-time EMA averaged cumulative totals;
* A-10 CP-SAT truncated fractional ``time_limit_s`` (0.5 s -> 0 s);
* A-13 seeded instance generators drew random ``uuid4`` IDs, so one seed gave
  a different instance (and, via ``str(id)`` tie-breaks, schedule) per call.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from synaps.model import (
    Assignment,
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    ScheduleResult,
    SetupEntry,
    ShiftInterval,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.coverage_outcome import stamp_honest_coverage
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.timegrain import GRAIN_EPSILON_MIN, duration_minutes, physical_processing_minutes

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=1)


def _at(minutes: float) -> datetime:
    return H0 + timedelta(minutes=minutes)


# --------------------------------------------------------------------------- A-01


@pytest.mark.parametrize(
    ("base", "speed", "expected"),
    [(21, 0.7, 30), (42, 1.4, 30), (21, 0.35, 60), (84, 0.7, 120), (161, 0.7, 230), (10, 3.0, 4)],
)
def test_a01_grain_is_robust_to_float_division_noise(
    base: int, speed: float, expected: int
) -> None:
    assert duration_minutes(base, speed) == expected


def test_a01_grain_sweep_never_inflates_exact_quotients_or_undercuts_physics() -> None:
    speeds = (0.1, 0.15, 0.2, 0.3, 0.35, 0.6, 0.7, 0.9, 1.1, 1.2, 1.3, 1.4, 1.5, 2.5)
    for base in range(0, 600):
        for speed in speeds:
            grain = duration_minutes(base, speed)
            physical = physical_processing_minutes(base, speed)
            # Never below the physical floor beyond the checker's tolerance ...
            assert grain + GRAIN_EPSILON_MIN >= physical
            # ... and an exact quotient is never rounded up to the next minute.
            nearest = round(base / speed)
            if abs(base / speed - nearest) < 1e-9:
                assert grain == max(1, nearest)


# --------------------------------------------------------------- A-02 / A-03


def _two_state_calendar_problem() -> tuple[ScheduleProblem, list[Operation], WorkCenter]:
    state_a, state_b = State(code="A"), State(code="B")
    wc = WorkCenter(
        code="M",
        capability_group="G",
        calendar=[
            ShiftInterval(start=_at(480), end=_at(600)),  # 08:00-10:00
            ShiftInterval(start=_at(630), end=_at(720)),  # 10:30-12:00
        ],
    )
    order = Order(external_ref="O", due_date=HE)
    op1 = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=120,
        eligible_wc_ids=[wc.id],
    )
    op2 = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=state_b.id,
        base_duration_min=60,
        eligible_wc_ids=[wc.id],
        predecessor_op_id=op1.id,
    )
    setup = SetupEntry(
        work_center_id=wc.id, from_state_id=state_a.id, to_state_id=state_b.id, setup_minutes=30
    )
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order],
        operations=[op1, op2],
        work_centers=[wc],
        setup_matrix=[setup],
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )
    return problem, [op1, op2], wc


@pytest.mark.parametrize("stamped_setup", [0, 30])
def test_a02_calendar_check_uses_derived_setup_not_solver_stamp(stamped_setup: int) -> None:
    """Setup window [10:00, 10:30] lies in the closed gap whatever the stamp says."""
    problem, (op1, op2), wc = _two_state_calendar_problem()
    assignments = [
        Assignment(
            operation_id=op1.id, work_center_id=wc.id, start_time=_at(480), end_time=_at(600)
        ),
        Assignment(
            operation_id=op2.id,
            work_center_id=wc.id,
            start_time=_at(630),
            end_time=_at(690),
            setup_minutes=stamped_setup,
        ),
    ]
    kinds = [v.kind for v in FeasibilityChecker().check(problem, assignments, exhaustive=True)]
    assert "CALENDAR_VIOLATION" in kinds


def test_a02_calendar_check_positive_control() -> None:
    problem, (op1, op2), wc = _two_state_calendar_problem()
    assignments = [
        Assignment(
            operation_id=op1.id, work_center_id=wc.id, start_time=_at(480), end_time=_at(600)
        ),
        Assignment(
            operation_id=op2.id,
            work_center_id=wc.id,
            start_time=_at(660),
            end_time=_at(720),
            setup_minutes=30,
        ),
    ]
    assert FeasibilityChecker().check(problem, assignments, exhaustive=True) == []


def test_a03_aux_calendar_check_uses_problem_requirements_not_stamped_ids() -> None:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    tool = AuxiliaryResource(
        code="T",
        resource_type="tool",
        calendar=[ShiftInterval(start=_at(480), end=_at(600))],
    )
    order = Order(external_ref="O", due_date=HE)
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=30,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        auxiliary_resources=[tool],
        aux_requirements=[OperationAuxRequirement(operation_id=op.id, aux_resource_id=tool.id)],
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )
    # The solver "forgot" to stamp the tool; the op still needs it at 10:30.
    assignment = Assignment(
        operation_id=op.id,
        work_center_id=wc.id,
        start_time=_at(630),
        end_time=_at(660),
        aux_resource_ids=[],
    )
    kinds = [v.kind for v in FeasibilityChecker().check(problem, [assignment], exhaustive=True)]
    assert "CALENDAR_VIOLATION" in kinds


# --------------------------------------------------------------- A-04 / A-05 / A-10


def _setup_tiebreak_problem() -> tuple[ScheduleProblem, WorkCenter]:
    """M1 carries a 100-min op (makespan); M2 ops can be sequenced with 5 or 10 setup."""
    state_a, state_b = State(code="A"), State(code="B")
    m1 = WorkCenter(code="M1", capability_group="G1")
    m2 = WorkCenter(code="M2", capability_group="G2")
    orders = [Order(external_ref=f"O{i}", due_date=HE) for i in range(4)]
    ops = [
        Operation(
            order_id=orders[0].id,
            seq_in_order=1,
            state_id=state_a.id,
            base_duration_min=100,
            eligible_wc_ids=[m1.id],
        ),
        Operation(
            order_id=orders[1].id,
            seq_in_order=1,
            state_id=state_a.id,
            base_duration_min=10,
            eligible_wc_ids=[m2.id],
        ),
        Operation(
            order_id=orders[2].id,
            seq_in_order=1,
            state_id=state_b.id,
            base_duration_min=10,
            eligible_wc_ids=[m2.id],
        ),
        Operation(
            order_id=orders[3].id,
            seq_in_order=1,
            state_id=state_a.id,
            base_duration_min=10,
            eligible_wc_ids=[m2.id],
        ),
    ]
    setups = [
        SetupEntry(
            work_center_id=m2.id, from_state_id=state_a.id, to_state_id=state_b.id, setup_minutes=5
        ),
        SetupEntry(
            work_center_id=m2.id, from_state_id=state_b.id, to_state_id=state_a.id, setup_minutes=5
        ),
    ]
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=orders,
        operations=ops,
        work_centers=[m1, m2],
        setup_matrix=setups,
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )
    return problem, m2


def test_a04_cpsat_fractional_weight_is_honoured_not_truncated() -> None:
    from synaps.solvers.cpsat_solver import CpSatSolver

    problem, _ = _setup_tiebreak_problem()
    result = CpSatSolver().solve(
        problem, time_limit_s=10, objective_weights={"setup": 0.5}, auto_greedy_warm_start=False
    )
    assert result.status == SolverStatus.OPTIMAL
    assert result.objective.makespan_minutes == pytest.approx(100.0)
    assert result.objective.total_setup_minutes == pytest.approx(5.0)
    assert result.metadata["objective_weights"]["setup"] > 0


def test_a04_cpsat_rejects_negative_weights() -> None:
    from synaps.solvers.cpsat_solver import CpSatSolver

    problem, _ = _setup_tiebreak_problem()
    with pytest.raises(ValueError, match="non-negative"):
        CpSatSolver().solve(problem, time_limit_s=5, objective_weights={"setup": -1})


def test_a05_cpsat_due_offset_floors_for_past_due_orders() -> None:
    """Due 90 s before the horizon: the integer tardiness must not undercut the real one."""
    from synaps.solvers.cpsat_solver import CpSatSolver

    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=H0 - timedelta(seconds=90))
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=1,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )
    result = CpSatSolver().solve(problem, time_limit_s=5, objective_weights={"tardiness": 1})
    internal = result.metadata["objective_components"]["total_tardiness_minutes"]
    assert internal >= result.objective.total_tardiness_minutes - 1e-9
    assert result.objective.total_tardiness_minutes == pytest.approx(2.5)


def test_a10_cpsat_fractional_time_limit_is_not_truncated_to_zero() -> None:
    from synaps.solvers.cpsat_solver import CpSatSolver

    problem, _ = _setup_tiebreak_problem()
    result = CpSatSolver().solve(problem, time_limit_s=0.5, auto_greedy_warm_start=False)
    params = result.metadata["sat_parameters"]
    assert params["max_time_in_seconds"] > 0
    assert params["max_deterministic_time"] == pytest.approx(0.25)


# --------------------------------------------------------------------------- A-06


def test_a06_bhk_distinct_state_path_overclaims_on_repeated_non_metric_states() -> None:
    """Star matrix: hub H <-> leaves cost 1, leaf <-> leaf cost 100.

    The walk L1 -> H -> L2 -> H -> L3 (H twice) costs 4, but every Hamiltonian
    path over the DISTINCT states {H, L1, L2, L3} needs a leaf-leaf arc (>= 102).
    BHK is therefore not a valid setup lower bound for a multiset of states on
    a non-metric matrix; the min-out assignment relaxation stays valid.
    """
    from uuid import uuid4

    from synaps.solvers._lbbd_cuts import (
        compute_machine_tsp_lower_bound,
        compute_min_out_assignment_setup_lb,
    )

    wc = uuid4()
    hub, l1, l2, l3 = (uuid4() for _ in range(4))
    leaves = (l1, l2, l3)
    lookup: dict[tuple[Any, Any, Any], float] = {}
    for leaf in leaves:
        lookup[(wc, hub, leaf)] = 1.0
        lookup[(wc, leaf, hub)] = 1.0
        for other in leaves:
            if other != leaf:
                lookup[(wc, leaf, other)] = 100.0
    multiset = [l1, hub, l2, hub, l3]
    walk_cost = sum(lookup[(wc, a, b)] for a, b in itertools.pairwise(multiset))
    assert walk_cost == 4.0
    # Historical distinct-state BHK over-claims (the defect) ...
    assert compute_machine_tsp_lower_bound(multiset, wc, lookup, metric_closure=False) > walk_cost
    # ... the metric-closure BHK (now the default) is valid.
    assert compute_machine_tsp_lower_bound(multiset, wc, lookup) <= walk_cost
    assert compute_min_out_assignment_setup_lb(multiset, wc, lookup) <= walk_cost


# --------------------------------------------------------------------------- A-07


def test_a07_duplicate_assignments_do_not_count_as_coverage() -> None:
    problem, (op1, _op2), wc = _two_state_calendar_problem()
    dup = Assignment(
        operation_id=op1.id, work_center_id=wc.id, start_time=_at(480), end_time=_at(600)
    )
    result = ScheduleResult(solver_name="x", status=SolverStatus.FEASIBLE, assignments=[dup, dup])
    stamped = stamp_honest_coverage(problem, result)
    assert stamped.metadata["coverage_class"] == "incomplete"


# --------------------------------------------------------------------------- A-08


def test_a08_rhc_pace_controller_observes_inner_windows() -> None:
    from synaps.solvers.rhc import RhcPolicy, RhcSolver

    problem, _ = _setup_tiebreak_problem()
    result = RhcSolver(policy=RhcPolicy.BALANCED).solve(
        problem,
        inner_solver="cpsat",
        inner_kwargs={"time_limit_s": 5},
        window_minutes=240,
        overlap_minutes=60,
        time_limit_s=120,
        coverage_pace_guard_enabled=True,
        coverage_pace_threshold=0.0,  # observe only; never intervene
    )
    summaries = result.metadata["inner_window_summaries"]
    solved = [s for s in summaries if s["resolution_mode"] in {"inner", "fallback_greedy"}]
    assert solved, "expected at least one solved window"
    assert result.metadata["coverage_pace_windows_observed"] == len(solved)


# --------------------------------------------------------------------------- A-09


def test_a09_alns_repair_ema_is_per_iteration_not_cumulative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import synaps.solvers.alns_solver as alns_module

    real_attempt = alns_module._attempt_alns_pair_repair

    def fixed_cost_attempt(**kwargs: Any) -> Any:
        attempt = real_attempt(**kwargs)
        if attempt.repair_used == "greedy":
            return replace(attempt, greedy_repair_ms_total=7)
        return attempt

    monkeypatch.setattr(alns_module, "_attempt_alns_pair_repair", fixed_cost_attempt)
    problem, _ = _setup_tiebreak_problem()
    result = alns_module.AlnsSolver().solve(
        problem,
        max_iterations=12,
        time_limit_s=60,
        use_cpsat_repair=False,
        min_destroy=1,
        destroy_fraction=0.5,
    )
    assert result.metadata["ema_repair_samples"] > 0
    # Cumulative averaging would drift towards 7 * k; per-iteration stays at 7.
    assert math.isclose(result.metadata["ema_repair_ms"], 7.0)


# --------------------------------------------------------------------------- P-01


def _bruteforce_triangle_violations(problem: ScheduleProblem) -> list[tuple[Any, ...]]:
    """The historical O(|W| |S|^3) triple loop, kept as the reference oracle."""
    setup = {
        (e.work_center_id, e.from_state_id, e.to_state_id): float(e.setup_minutes)
        for e in problem.setup_matrix
    }
    out: list[tuple[Any, ...]] = []
    for wc_id in {e.work_center_id for e in problem.setup_matrix}:
        for a in [s.id for s in problem.states]:
            for c in [s.id for s in problem.states]:
                if a == c or (direct := setup.get((wc_id, a, c))) is None:
                    continue
                for b in [s.id for s in problem.states]:
                    if b in (a, c):
                        continue
                    ab, bc = setup.get((wc_id, a, b)), setup.get((wc_id, b, c))
                    if ab is not None and bc is not None and direct > ab + bc + 1e-9:
                        out.append((wc_id, a, b, c, direct, ab + bc))
    return out


@pytest.mark.parametrize("seed", range(6))
def test_p01_vectorised_metricity_matches_bruteforce(seed: int) -> None:
    import random

    from synaps.validation import is_setup_matrix_metric, validate_setup_matrix_metricity

    rng = random.Random(seed)
    states = [State(code=f"s{i}") for i in range(7)]
    wcs = [WorkCenter(code=f"m{i}", capability_group="G") for i in range(3)]
    entries = [
        SetupEntry(
            work_center_id=wc.id,
            from_state_id=a.id,
            to_state_id=b.id,
            setup_minutes=rng.choice([0, 1, 5, 10, 30, 60]),
        )
        for wc in wcs
        for a in states
        for b in states
        if rng.random() < 0.7
    ]
    order = Order(external_ref="O", due_date=HE)
    op = Operation(order_id=order.id, seq_in_order=1, state_id=states[0].id, base_duration_min=1)
    problem = ScheduleProblem(
        states=states,
        orders=[order],
        operations=[op],
        work_centers=wcs,
        setup_matrix=entries,
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )
    fast = [
        (
            v.work_center_id,
            v.from_state_id,
            v.via_state_id,
            v.to_state_id,
            v.direct_minutes,
            v.via_minutes,
        )
        for v in validate_setup_matrix_metricity(problem)
    ]
    assert fast == _bruteforce_triangle_violations(problem)
    assert is_setup_matrix_metric(problem) == (not fast)


# --------------------------------------------------------------------------- A-13


def test_a13_seeded_generators_are_reproducible_including_ids() -> None:
    from synaps.benchmarks.instance_generator import generate_large_instance as bench_gen
    from synaps.solvers.instance_generator import generate_large_instance as solver_gen

    def bench(seed: int) -> ScheduleProblem:
        return bench_gen(n_operations=60, n_machines=4, n_states=3, n_aux_resources=1, seed=seed)

    def solver(seed: int) -> ScheduleProblem:
        return solver_gen(num_operations=60, num_work_centers=4, num_states=3, seed=seed)

    for generate in (bench, solver):
        first, again, other = generate(5), generate(5), generate(6)
        assert first.model_dump_json() == again.model_dump_json()
        assert {op.id for op in first.operations}.isdisjoint({op.id for op in other.operations})


def test_a13_id_stream_leaves_structural_draws_unchanged() -> None:
    """IDs come from a dedicated stream: durations/eligibility match uuid4-era draws."""
    from synaps._ids import seeded_uuid_factory
    from synaps.benchmarks.instance_generator import generate_large_instance

    seeded = generate_large_instance(n_operations=60, n_machines=4, n_states=3, seed=9)
    random_ids = pytest.MonkeyPatch()
    random_ids.setattr(
        "synaps.benchmarks.instance_generator.seeded_uuid_factory",
        lambda _seed: seeded_uuid_factory(None),
    )
    try:
        legacy = generate_large_instance(n_operations=60, n_machines=4, n_states=3, seed=9)
    finally:
        random_ids.undo()
    assert [op.base_duration_min for op in seeded.operations] == [
        op.base_duration_min for op in legacy.operations
    ]
    assert [len(op.eligible_wc_ids or []) for op in seeded.operations] == [
        len(op.eligible_wc_ids or []) for op in legacy.operations
    ]
    assert [e.setup_minutes for e in seeded.setup_matrix] == [
        e.setup_minutes for e in legacy.setup_matrix
    ]


# --------------------------------------------------------------------------- R-09


def test_r09_config_clamps_map_nan_to_the_lower_bound_uniformly() -> None:
    """Red Team 2026-10: the decomposed configs clamp with min(high, max(low, x)).

    The pre-refactor code mixed ``min(hi, max(lo, x))`` and ``max(lo, min(hi, x))``,
    which agree on every number but not on NaN (0.0 vs 0.9 for
    ``coverage_time_reserve_fraction``). NaN now maps to the lower bound everywhere.
    """
    from synaps.solvers._alns_config import AlnsSeedConfig
    from synaps.solvers.rhc._config import RhcTimeBudget

    nan = float("nan")
    budget = RhcTimeBudget.from_kwargs({"coverage_time_reserve_fraction": nan})
    assert budget.coverage_time_reserve_fraction == 0.0
    seeding = AlnsSeedConfig.from_kwargs({"phase1_wall_fraction": nan})
    assert seeding.phase1_wall_fraction == 0.1
