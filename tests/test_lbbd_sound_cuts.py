"""T-06: the sound LBBD master relaxation never over-claims (Rule 6).

Ground truth is the exhaustive oracle in ``tests/_fjsp_oracle.py`` (every
assignment, every lane sequence). The oracle itself is cross-checked against
CP-SAT's proven optimum, so a bug in the oracle cannot hide a bug in the rows.

Validity is tested per ROW, not only per bound: every candidate row (all
static rows, every anchored energy threshold pair, every state subset of a
state-path row, and whatever the separator emits at every assignment) is
evaluated at EVERY assignment and compared with that assignment's optimum.
That is the Benders requirement: a row separated at one incumbent must hold
at all of them.
"""

from __future__ import annotations

import itertools
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_DNS, UUID, uuid5

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, assume, given, settings

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers._lbbd_sound import (
    SoundRelaxation,
    SoundRow,
    compute_sound_master_lower_bound,
)
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.lbbd_hd_solver import LbbdHdSolver
from synaps.solvers.lbbd_solver import LbbdSolver
from tests._fjsp_oracle import Oracle

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HORIZON = timedelta(minutes=2000)
_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"


def _uid(tag: str, index: int) -> UUID:
    return uuid5(NAMESPACE_DNS, f"synaps-t06-{tag}-{index}")


@st.composite
def tiny_problems(draw: st.DrawFn, max_ops: int = 5) -> ScheduleProblem:
    """Up to 5 operations, 3 machines (some 2-lane), 3 states, chains and windows.

    Setup matrices are random (positive diagonals included), the A-06 star
    (hub <-> leaf 1, leaf <-> leaf 50: non-metric) or empty.
    """
    n_states = draw(st.integers(1, 3))
    n_wc = draw(st.sampled_from([1, 2, 2, 3, 3]))
    n_ops = draw(st.integers(min(3, max_ops), max_ops))
    states = [State(id=_uid("s", i), code=f"S{i}") for i in range(n_states)]
    wcs = [
        WorkCenter(
            id=_uid("m", k),
            code=f"M{k}",
            capability_group="g",
            speed_factor=draw(st.sampled_from([1.0, 1.0, 0.7, 1.5])),
            max_parallel=draw(st.sampled_from([1, 1, 2])),
        )
        for k in range(n_wc)
    ]
    shape = draw(st.sampled_from(["random", "random", "star", "zero"]))
    setup: list[SetupEntry] = []
    for wc in wcs:
        for a, b in itertools.product(states, states):
            if shape == "zero":
                continue
            if shape == "star":
                value = 0 if a == b else (1 if states[0] in (a, b) else 50)
            else:
                value = draw(st.integers(0, 30))
            if value:
                setup.append(
                    SetupEntry(
                        work_center_id=wc.id,
                        from_state_id=a.id,
                        to_state_id=b.id,
                        setup_minutes=value,
                    )
                )
    n_jobs = draw(st.integers(1, n_ops))
    job_of = [draw(st.integers(0, n_jobs - 1)) for _ in range(n_ops)]
    orders = [
        Order(
            id=_uid("o", j),
            external_ref=f"J{j}",
            due_date=_H0 + _HORIZON,
            release_date=_H0 + timedelta(minutes=draw(st.integers(0, 12)))
            if draw(st.booleans())
            else None,
        )
        for j in range(n_jobs)
    ]
    operations: list[Operation] = []
    for j in range(n_jobs):
        members = [i for i in range(n_ops) if job_of[i] == j]
        for position, i in enumerate(members):
            # The model allows one chain per order (by seq_in_order);
            # normalisation fills predecessor_op_id.
            eligible = sorted(
                draw(st.lists(st.integers(0, n_wc - 1), min_size=1, max_size=n_wc, unique=True))
            )
            overrides = {
                wcs[k].id: draw(st.integers(1, 9)) for k in eligible if draw(st.booleans())
            }
            operations.append(
                Operation(
                    id=_uid("op", i),
                    order_id=orders[j].id,
                    seq_in_order=position,
                    state_id=states[draw(st.integers(0, n_states - 1))].id,
                    base_duration_min=draw(st.integers(1, 9)),
                    eligible_wc_ids=[wcs[k].id for k in eligible],
                    earliest_start=_H0 + timedelta(minutes=draw(st.integers(0, 15)))
                    if draw(st.booleans())
                    else None,
                    machine_duration_overrides=overrides,
                )
            )
    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=wcs,
        setup_matrix=setup,
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + _HORIZON,
    )


def _every_candidate_row(
    relaxation: SoundRelaxation, assignments: list[dict[UUID, UUID]]
) -> list[SoundRow]:
    rows = relaxation.static_rows(include_capacity=True)
    heads = sorted(set(relaxation.head.values()))
    tails = sorted(set(relaxation.tail.values()))
    for machine in relaxation.machines:
        rows += [
            relaxation.energy_row(machine, r, q)
            for r in heads
            for q in tails
            if relaxation.anchored(r, q)
        ]
        for size in range(2, len(machine.states) + 1):
            for subset in itertools.combinations(machine.states, size):
                rows.append(relaxation.state_path_row(machine, list(subset)))
    for assignment in assignments:
        # cmax = -1: every lazy row that is positive at this incumbent is "violated".
        rows += relaxation.separate(assignment, -1.0)
    return rows


def _assert_rows_hold(problem: ScheduleProblem) -> None:
    oracle = Oracle(problem)
    assignments = list(oracle.assignments())
    optima = [oracle.optimum_for(a) for a in assignments]
    relaxation = SoundRelaxation(problem)
    for row in _every_candidate_row(relaxation, assignments):
        for assignment, best in zip(assignments, optima, strict=True):
            if math.isfinite(best):
                value = row.value(assignment, relaxation.state_of)
                assert value <= best + 1e-6, (row.kind, value, best, assignment)


@given(tiny_problems())
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_every_sound_row_holds_at_every_assignment(problem: ScheduleProblem) -> None:
    _assert_rows_hold(problem)


@pytest.mark.slow
@given(tiny_problems(max_ops=6))
@settings(max_examples=1000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_every_sound_row_holds_at_every_assignment_six_operations(
    problem: ScheduleProblem,
) -> None:
    _assert_rows_hold(problem)


@given(tiny_problems())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_compute_sound_master_lower_bound_never_exceeds_the_optimum(
    problem: ScheduleProblem,
) -> None:
    optimum = Oracle(problem).optimum()
    assume(math.isfinite(optimum))
    bound = compute_sound_master_lower_bound(problem, time_limit_s=10.0)
    assert bound.value <= optimum + 1e-6, (bound, optimum)


@given(tiny_problems(max_ops=4))
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_oracle_agrees_with_cpsat_optimum(problem: ScheduleProblem) -> None:
    """The oracle's semantics are CP-SAT's: equal proven optima."""
    optimum = Oracle(problem).optimum()
    result = CpSatSolver().solve(problem, time_limit_s=10, random_seed=1)
    if not math.isfinite(optimum):
        assert result.status in (SolverStatus.INFEASIBLE, SolverStatus.TIMEOUT)
        return
    assume(result.status is SolverStatus.OPTIMAL)
    assert result.objective.makespan_minutes == pytest.approx(optimum)


def _two_machine_anchor_problem() -> ScheduleProblem:
    """A: release 10, p=1. B (p=1) precedes C (p=10). A and B share machine M0.

    Heads: A 10, B 0, C 1. Tails: A 0, B 10, C 0. The pair (r=10, q=10) mixes
    A's head with B's tail; no operation owns both, so an unanchored energy row
    would claim ``C >= 20`` while the optimum is 11 (B 0-1, A 10-11 on M0,
    C 1-11 on M1).
    """
    state = State(id=_uid("anchor-s", 0), code="S")
    m0 = WorkCenter(id=_uid("anchor-m", 0), code="M0", capability_group="g")
    m1 = WorkCenter(id=_uid("anchor-m", 1), code="M1", capability_group="g")
    late = Order(
        id=_uid("anchor-o", 0),
        external_ref="LATE",
        due_date=_H0 + _HORIZON,
        release_date=_H0 + timedelta(minutes=10),
    )
    chain = Order(id=_uid("anchor-o", 1), external_ref="CHAIN", due_date=_H0 + _HORIZON)
    b = Operation(
        id=_uid("anchor-op", 1),
        order_id=chain.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=1,
        eligible_wc_ids=[m0.id],
    )
    return ScheduleProblem(
        states=[state],
        orders=[late, chain],
        operations=[
            Operation(
                id=_uid("anchor-op", 0),
                order_id=late.id,
                seq_in_order=0,
                state_id=state.id,
                base_duration_min=1,
                eligible_wc_ids=[m0.id],
            ),
            b,
            Operation(
                id=_uid("anchor-op", 2),
                order_id=chain.id,
                seq_in_order=1,
                state_id=state.id,
                base_duration_min=10,
                eligible_wc_ids=[m1.id],
                predecessor_op_id=b.id,
            ),
        ],
        work_centers=[m0, m1],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + _HORIZON,
    )


def test_energy_rows_require_an_anchor() -> None:
    problem = _two_machine_anchor_problem()
    relaxation = SoundRelaxation(problem)
    assert not relaxation.anchored(10.0, 10.0)
    assert relaxation.anchored(10.0, 0.0) and relaxation.anchored(0.0, 10.0)
    optimum = Oracle(problem).optimum()
    assert optimum == 11
    bound = compute_sound_master_lower_bound(problem)
    assert bound.value == pytest.approx(11.0)


def _star_problem() -> ScheduleProblem:
    """A-06 star on one machine: states L1 H L2 H L3, hub <-> leaf 1, leaf <-> leaf 100.

    The walk ``L1 H L2 H L3`` pays 4 in setups; a Hamiltonian path over the raw
    distinct states pays >= 102. The metric closure keeps the row valid.
    """
    hub, *leaves = (State(id=_uid("star-s", i), code=f"S{i}") for i in range(4))
    machine = WorkCenter(id=_uid("star-m", 0), code="M", capability_group="g")
    setup = [
        SetupEntry(
            work_center_id=machine.id,
            from_state_id=a.id,
            to_state_id=b.id,
            setup_minutes=1 if hub in (a, b) else 100,
        )
        for a, b in itertools.permutations([hub, *leaves], 2)
    ]
    states_of_ops = [leaves[0], hub, leaves[1], hub, leaves[2]]
    orders = [
        Order(id=_uid("star-o", i), external_ref=f"O{i}", due_date=_H0 + _HORIZON)
        for i in range(len(states_of_ops))
    ]
    return ScheduleProblem(
        states=[hub, *leaves],
        orders=orders,
        operations=[
            Operation(
                id=_uid("star-op", i),
                order_id=orders[i].id,
                seq_in_order=0,
                state_id=state.id,
                base_duration_min=1,
            )
            for i, state in enumerate(states_of_ops)
        ],
        work_centers=[machine],
        setup_matrix=setup,
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + _HORIZON,
    )


def test_state_path_row_survives_the_star_matrix() -> None:
    problem = _star_problem()
    optimum = Oracle(problem).optimum()
    assert optimum == 5 + 4  # five unit operations, four hub transitions
    relaxation = SoundRelaxation(problem)
    machine = relaxation.machines[0]
    row = relaxation.state_path_row(machine, list(machine.states))
    assignment = {op.id: machine.wc_id for op in problem.operations}
    assert row.value(assignment, relaxation.state_of) <= optimum
    assert compute_sound_master_lower_bound(problem).value <= optimum


def _load_json(name: str) -> ScheduleProblem:
    return ScheduleProblem.model_validate(json.loads((_INSTANCES / name).read_text("utf-8")))


@pytest.mark.parametrize(
    ("instance", "legacy", "sound", "upper"),
    [
        # legacy = cut-free LBBD master relaxation (reported lower_bound before
        # T-06); upper = a feasible makespan (CP-SAT OPTIMAL 83 on tiny_3x3).
        ("tiny_3x3.json", 68.0, 75.0, 83.0),
        ("medium_4state_tsp_dominance_16x4.json", 166.0, 189.0, 210.0),
    ],
)
def test_sound_bound_is_stronger_than_the_legacy_relaxation(
    instance: str, legacy: float, sound: float, upper: float
) -> None:
    bound = compute_sound_master_lower_bound(_load_json(instance), time_limit_s=30.0)
    assert bound.converged
    assert bound.value == pytest.approx(sound)
    assert legacy < bound.value <= upper


def test_lbbd_sound_cuts_flag_reports_a_valid_stronger_bound() -> None:
    problem = _load_json("tiny_3x3.json")
    legacy = LbbdSolver().solve(problem, time_limit_s=20, max_iterations=3, random_seed=42)
    sound = LbbdSolver().solve(
        problem, time_limit_s=20, max_iterations=3, random_seed=42, sound_cuts=True
    )
    assert sound.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
    assert "sound_cuts" not in legacy.metadata
    meta = sound.metadata
    assert meta["lower_bound_method"] == "sound_master_relaxation"
    assert meta["lower_bound_invariant_violated"] is False
    assert meta["lower_bound"] >= legacy.metadata["lower_bound"]
    assert meta["lower_bound"] == pytest.approx(75.0)
    assert meta["lower_bound"] <= sound.objective.makespan_minutes + 1e-6
    assert meta["sound_cuts"]["rows_by_kind"]["energy"] >= 1


def test_lbbd_hd_sound_cuts_flag_reports_a_valid_bound() -> None:
    """HD uses the same rows on its precedence master. Default stays off."""
    problem = _load_json("tiny_3x3.json")
    legacy = LbbdHdSolver().solve(problem, time_limit_s=20, max_iterations=2, random_seed=42)
    sound = LbbdHdSolver().solve(
        problem, time_limit_s=20, max_iterations=2, random_seed=42, sound_cuts=True
    )
    assert sound.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
    assert "sound_cuts" not in legacy.metadata
    meta = sound.metadata
    assert meta["lower_bound_method"] == "sound_master_relaxation_hd"
    assert meta["lower_bound_invariant_violated"] is False
    assert meta["lower_bound"] >= legacy.metadata["lower_bound"] - 1e-6
    assert meta["lower_bound"] <= sound.objective.makespan_minutes + 1e-6
    assert meta["sound_cuts"]["rows_by_kind"]["energy"] >= 1
