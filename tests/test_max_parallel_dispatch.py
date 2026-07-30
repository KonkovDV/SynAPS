"""M2: max_parallel must be honored by the dispatch-based solvers.

Measured before the fix (Red Team audit v2, tag M2): a work center with
``max_parallel=2`` and two 60-minute operations in different states with a
600-minute setup between them has optimum makespan 60 / setup 0 (run the two
lanes concurrently). GREEDY/BEAM/ALNS/LBBD instead serialized the machine and
charged a phantom 600-minute setup (makespan 720), while only CP-SAT (which
virtualizes parallel lanes) got it right — a 12x makespan error the checker
did not catch.

Fix: the dispatch layer virtualizes ``max_parallel > 1`` work centers into
independent lanes before solving and unrolls ``lane_id`` back on the way out,
reusing the proven CP-SAT lane model.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import Operation, Order, ScheduleProblem, SetupEntry, State, WorkCenter
from synaps.solvers.greedy_dispatch import BeamSearchDispatch, GreedyDispatch

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=10)


def _parallel_problem() -> ScheduleProblem:
    s1, s2 = State(code="s1"), State(code="s2")
    wc = WorkCenter(code="M2LANE", capability_group="G", max_parallel=2)
    o1, o2 = uuid4(), uuid4()
    ops = [
        Operation(
            order_id=o1, seq_in_order=1, state_id=s1.id, base_duration_min=60,
            eligible_wc_ids=[wc.id],
        ),
        Operation(
            order_id=o2, seq_in_order=1, state_id=s2.id, base_duration_min=60,
            eligible_wc_ids=[wc.id],
        ),
    ]
    setups = [
        SetupEntry(work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=600),
        SetupEntry(work_center_id=wc.id, from_state_id=s2.id, to_state_id=s1.id, setup_minutes=600),
    ]
    return ScheduleProblem(
        states=[s1, s2],
        orders=[
            Order(id=o1, external_ref="O1", due_date=H0 + timedelta(days=9)),
            Order(id=o2, external_ref="O2", due_date=H0 + timedelta(days=9)),
        ],
        operations=ops,
        work_centers=[wc],
        setup_matrix=setups,
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )


@pytest.mark.parametrize("solver", [GreedyDispatch(), BeamSearchDispatch(beam_width=3)])
def test_dispatch_honors_max_parallel(solver: object) -> None:
    """M2: two 60-min ops run concurrently on a 2-lane machine, no phantom setup."""
    problem = _parallel_problem()
    result = solver.solve(problem)  # type: ignore[attr-defined]
    mk = result.objective.makespan_minutes
    setup = result.objective.total_setup_minutes
    lanes = [a.lane_id for a in result.assignments]
    assert mk <= 60.0 + 1e-6, f"{solver}: makespan {mk} > 60 (serialized a parallel machine)"
    assert setup <= 1e-6, f"{solver}: phantom setup {setup} charged between concurrent lanes"
    assert all(lane is not None for lane in lanes), f"{solver}: lane_id missing for max_parallel>1"
    assert len(set(lanes)) == 2, f"{solver}: both ops on the same lane: {lanes}"
