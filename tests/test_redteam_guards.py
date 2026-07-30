"""Phase 0.5 (final brief): the redteam GUARDS as ordinary pytest tests.

Ports the GUARDS section of ``synaps_redteam_repro_v3.py`` into the regular
test suite so every PR runs them — the v2→v3 lesson is that locally-correct
fixes collided at their seams (D3 killed D1) precisely because these guards
were only run manually.

Mapping (repro tag -> this file):
    GUARD-S1  lower bound <= proven optimum        test_guard_s1_*
    GUARD-S3  BHK subset monotonicity               test_guard_s3_*  (xfail sentinel)
    GUARD-S4  setup interval allows idle            test_guard_s4_*
    GUARD-S5  symmetry breaking keeps optimum       test_guard_s5_*
    GUARD-M1  release_date honored by portfolio     test_guard_m1_*
    GUARD-D2  LBBD determinism                      test_guard_d2_*
    GUARD-D3  timebox (wall <= 1.2x budget)         test_guard_d3_*  (slow-marked)

GUARD-S3 is INTENTIONALLY red (xfail strict): the machine-TSP cut was removed
(S3), but `compute_machine_tsp_lower_bound` still over-claims on subsets:
L(S) - L(S\\{j}) > 0 is not covered by the cut discount. It must be fixed
BEFORE optimization cuts return (final brief, Phase 1 N2 step 4); when that
happens this xfail turns XPASS and strict=True fails the suite, forcing the
sentinel's removal.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    ScheduleResult,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import AlnsSolver
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.greedy_dispatch import BeamSearchDispatch, GreedyDispatch
from synaps.solvers.lbbd_solver import LbbdSolver

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=10)
_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"


def _load(name: str) -> ScheduleProblem:
    return ScheduleProblem.model_validate(
        json.loads((_INSTANCES / f"{name}.json").read_text(encoding="utf-8"))
    )


def _fingerprint(result: ScheduleResult) -> str:
    body = "\n".join(
        f"{a.operation_id}|{a.work_center_id}|{a.start_time.isoformat()}|{a.end_time.isoformat()}"
        for a in sorted(result.assignments, key=lambda x: str(x.operation_id))
    )
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def _portfolio() -> list[tuple[str, object, dict[str, object]]]:
    return [
        ("GREEDY", GreedyDispatch(), {}),
        ("BEAM-3", BeamSearchDispatch(beam_width=3), {}),
        (
            "CPSAT",
            CpSatSolver(),
            {
                "time_limit_s": 10,
                "num_workers": 1,
                "auto_greedy_warm_start": False,
                "enable_symmetry_breaking": False,
            },
        ),
        ("ALNS", AlnsSolver(), {"time_limit_s": 5, "random_seed": 42, "max_iterations": 200}),
        ("LBBD", LbbdSolver(), {"time_limit_s": 10, "random_seed": 42, "max_iterations": 4}),
    ]


def test_guard_s1_lbbd_bound_not_above_proven_optimum() -> None:
    problem = _load("tiny_3x3")
    lbbd = LbbdSolver().solve(problem, time_limit_s=15, max_iterations=20, random_seed=42)
    cpsat = CpSatSolver().solve(
        problem,
        time_limit_s=60,
        num_workers=1,
        auto_greedy_warm_start=False,
        enable_symmetry_breaking=False,
    )
    lb = float(lbbd.metadata.get("lower_bound", 0.0))
    assert lb <= cpsat.objective.makespan_minutes + 1e-6


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Intentional sentinel: compute_machine_tsp_lower_bound over-claims on subsets "
        "(L(S) - L(S\\{j}) > 0). Must be fixed BEFORE optimization cuts return (N2 "
        "step 4); an XPASS here means it was fixed - remove this marker then."
    ),
)
def test_guard_s3_bhk_bound_subset_monotone() -> None:
    from synaps.solvers._lbbd_cuts import compute_machine_tsp_lower_bound

    s1, s2, s3 = State(code="s1"), State(code="s2"), State(code="s3")
    wc = WorkCenter(code="M", capability_group="G")
    pairs = [(s1, s2, 1), (s2, s3, 1), (s1, s3, 100), (s3, s1, 1), (s2, s1, 1), (s3, s2, 1)]
    lookup = {(wc.id, a.id, b.id): float(v) for a, b, v in pairs}
    states = [s1.id, s2.id, s3.id]
    l_full = compute_machine_tsp_lower_bound(states, wc.id, lookup)
    worst = max(
        l_full
        - compute_machine_tsp_lower_bound(
            [s for i, s in enumerate(states) if i != j], wc.id, lookup
        )
        for j in range(len(states))
    )
    assert worst <= 1e-9, f"L(S) - L(S\\{{j}}) = {worst}; a cut discount must cover this"


def test_guard_s4_setup_interval_allows_idle() -> None:
    st = State(code="s")
    m1 = WorkCenter(code="M1", capability_group="G")
    m2 = WorkCenter(code="M2", capability_group="H")
    o1 = Order(external_ref="O1", due_date=H0 + timedelta(days=9))
    o2 = Order(external_ref="O2", due_date=H0 + timedelta(days=9))
    a = Operation(
        order_id=o1.id, seq_in_order=1, state_id=st.id, base_duration_min=10,
        eligible_wc_ids=[m1.id],
    )
    c = Operation(
        order_id=o1.id, seq_in_order=2, state_id=st.id, base_duration_min=60,
        eligible_wc_ids=[m2.id], predecessor_op_id=a.id,
    )
    b = Operation(
        order_id=o2.id, seq_in_order=1, state_id=st.id, base_duration_min=10,
        eligible_wc_ids=[m1.id],
    )
    problem = ScheduleProblem(
        states=[st], orders=[o1, o2], operations=[a, c, b], work_centers=[m1, m2],
        setup_matrix=[], planning_horizon_start=H0, planning_horizon_end=HE,
    )
    r = CpSatSolver().solve(problem, time_limit_s=20, num_workers=1, auto_greedy_warm_start=False)
    assert r.objective.makespan_minutes <= 70.0 + 1e-6


def test_guard_s5_symmetry_breaking_keeps_optimum() -> None:
    st = State(code="s")
    m1 = WorkCenter(code="M1", capability_group="G", speed_factor=1.0)
    m2 = WorkCenter(code="M2", capability_group="G", speed_factor=1.0)
    orders = [Order(external_ref=f"O{i}", due_date=H0 + timedelta(days=5)) for i in range(3)]
    ops = [
        Operation(
            order_id=orders[0].id, seq_in_order=1, state_id=st.id, base_duration_min=100,
            eligible_wc_ids=[m1.id],
        ),
        Operation(
            order_id=orders[1].id, seq_in_order=1, state_id=st.id, base_duration_min=10,
            eligible_wc_ids=[m1.id, m2.id],
        ),
        Operation(
            order_id=orders[2].id, seq_in_order=1, state_id=st.id, base_duration_min=10,
            eligible_wc_ids=[m1.id, m2.id],
        ),
    ]
    problem = ScheduleProblem(
        states=[st], orders=orders, operations=ops, work_centers=[m1, m2], setup_matrix=[],
        planning_horizon_start=H0, planning_horizon_end=HE,
    )
    off = CpSatSolver().solve(
        problem, time_limit_s=10, num_workers=1, auto_greedy_warm_start=False,
        enable_symmetry_breaking=False,
    )
    on = CpSatSolver().solve(
        problem, time_limit_s=10, num_workers=1, auto_greedy_warm_start=False,
        enable_symmetry_breaking=True,
    )
    assert on.objective.makespan_minutes == off.objective.makespan_minutes


def test_guard_m1_release_date_honored_by_portfolio() -> None:
    st = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(
        external_ref="O1", due_date=H0 + timedelta(days=9),
        release_date=H0 + timedelta(minutes=500),
    )
    op = Operation(
        order_id=order.id, seq_in_order=1, state_id=st.id, base_duration_min=60,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[st], orders=[order], operations=[op], work_centers=[wc], setup_matrix=[],
        planning_horizon_start=H0, planning_horizon_end=HE,
    )
    offenders: list[str] = []
    for name, solver, kwargs in _portfolio():
        result = solver.solve(problem, **kwargs)  # type: ignore[attr-defined]
        assert order.release_date is not None
        for assignment in result.assignments:
            early = (order.release_date - assignment.start_time).total_seconds() / 60.0
            if early > 0:
                offenders.append(f"{name}(-{early:.0f}min)")
    assert not offenders, f"start before release_date: {offenders}"


def test_guard_d2_lbbd_deterministic_fingerprints() -> None:
    problem = _load("medium_stress_20x4")
    prints = {
        _fingerprint(
            LbbdSolver().solve(problem, time_limit_s=8, random_seed=42, max_iterations=8)
        )
        for _ in range(2)
    }
    assert len(prints) == 1, f"fingerprints differ: {prints}"


@pytest.mark.slow
def test_guard_d3_timebox_within_tolerance() -> None:
    """Wall <= 1.2x budget for the long-running solvers (repro GUARD-D3).

    Slow-marked (runs three solvers) and load-sensitive; the repro script is the
    authoritative check. In strict determinism CP-SAT stops on deterministic
    time (ADR-0001), so its wall bound holds at the measured wall/deterministic
    ratio but may stretch under heavy parallel CPU load.
    """
    problem = _load("medium_stress_20x4")
    budget = 6
    for name, solver, base in (
        ("CPSAT", CpSatSolver(), {"num_workers": 1, "auto_greedy_warm_start": False}),
        ("ALNS", AlnsSolver(), {"random_seed": 42, "max_iterations": 100000}),
        ("LBBD", LbbdSolver(), {"random_seed": 42, "max_iterations": 50}),
    ):
        t0 = time.monotonic()
        solver.solve(problem, time_limit_s=budget, **base)  # type: ignore[attr-defined]
        wall = time.monotonic() - t0
        assert wall / budget <= 1.2, f"{name} overshoot {wall / budget:.2f}x"
