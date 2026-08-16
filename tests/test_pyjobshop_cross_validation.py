"""Phase 0.2 (final brief): SynAPS CP-SAT cross-validated against PyJobShop.

An independent CP-SAT implementation is a model-error oracle: if SynAPS and
PyJobShop both prove optimality on the identical problem but disagree on the
makespan, SynAPS's formulation is wrong. Skips cleanly when PyJobShop is not
installed (optional dependency).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("pyjobshop", reason="PyJobShop cross-validation oracle is optional")

from benchmark.fjs_loader import load_fjs_problem
from benchmark.pyjobshop_oracle import solve_with_pyjobshop
from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.cpsat_solver import CpSatSolver

_BRANDIMARTE_DIR = (
    Path(__file__).resolve().parent.parent / "benchmark" / "instances" / "public" / "brandimarte"
)
_H0 = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("stem", ["mk01", "mk02"])
def test_synaps_agrees_with_pyjobshop_on_brandimarte(stem: str) -> None:
    """At proven optimality on a shared FJSP instance, makespans must be equal."""
    problem = load_fjs_problem(_BRANDIMARTE_DIR / f"{stem}.fjs")
    synaps = CpSatSolver().solve(
        problem, time_limit_s=30, determinism="fast", auto_greedy_warm_start=False
    )
    oracle = solve_with_pyjobshop(problem, time_limit_s=30)

    if synaps.status is not SolverStatus.OPTIMAL or not oracle.is_optimal:
        pytest.skip(
            f"{stem}: not both proven optimal "
            f"(synaps={synaps.status.value}, pyjobshop={oracle.status})"
        )
    assert synaps.objective.makespan_minutes == oracle.makespan, (
        f"{stem}: SynAPS {synaps.objective.makespan_minutes} != "
        f"PyJobShop {oracle.makespan} on the identical problem (model error)"
    )


def _parallel_lane_problem() -> ScheduleProblem:
    """The M2 instance: max_parallel=2, two ops, optimum is concurrent (mk 60)."""
    s1, s2 = State(code="s1"), State(code="s2")
    wc = WorkCenter(code="M2LANE", capability_group="G", max_parallel=2)
    o1, o2 = (
        Order(external_ref="O1", due_date=_H0 + timedelta(days=9)),
        Order(external_ref="O2", due_date=_H0 + timedelta(days=9)),
    )
    ops = [
        Operation(
            order_id=o1.id,
            seq_in_order=1,
            state_id=s1.id,
            base_duration_min=60,
            eligible_wc_ids=[wc.id],
        ),
        Operation(
            order_id=o2.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=60,
            eligible_wc_ids=[wc.id],
        ),
    ]
    # Setup exists in the SynAPS instance but is not transferred to the oracle;
    # the shared optimum (concurrent lanes) incurs no changeover either way.
    setups = [
        SetupEntry(work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=600),
        SetupEntry(work_center_id=wc.id, from_state_id=s2.id, to_state_id=s1.id, setup_minutes=600),
    ]
    return ScheduleProblem(
        states=[s1, s2],
        orders=[o1, o2],
        operations=ops,
        work_centers=[wc],
        setup_matrix=setups,
        planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=10),
    )


def test_synaps_agrees_with_pyjobshop_on_parallel_lanes() -> None:
    """M2 direct oracle: both must run the two lanes concurrently (makespan 60)."""
    problem = _parallel_lane_problem()
    synaps = CpSatSolver().solve(
        problem, time_limit_s=20, determinism="fast", auto_greedy_warm_start=False
    )
    oracle = solve_with_pyjobshop(problem, time_limit_s=20)
    assert oracle.makespan == 60.0, f"PyJobShop parallel oracle makespan {oracle.makespan} != 60"
    assert synaps.objective.makespan_minutes == oracle.makespan, (
        f"SynAPS {synaps.objective.makespan_minutes} != PyJobShop {oracle.makespan} "
        f"on the parallel-lane instance (M2 model divergence)"
    )
