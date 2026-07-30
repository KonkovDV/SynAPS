"""Q1: beam search makespan must be non-increasing in the beam width.

Measured before the fix (Red Team audit v2, tag Q1): beam makespan was
non-monotone in the beam width (e.g. width 3/5 far worse than width 1) because
beams were ranked by a one-step ATCS score (incomparable across beams), the
completion-to-go projection (Ow & Morton's second stage) was missing, and the
final pick only considered beams that survived the last step. A wider beam that
contains the greedy trajectory cannot be worse than a narrower one.

Fix: rank partial beams by a completion-to-go greedy rollout of the actual
objective, and keep a global incumbent over every completed schedule (not only
the last-step survivors). Combined with the M2 earliest-completion lane choice
this makes makespan non-increasing in the beam width.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from synaps.model import Operation, Order, ScheduleProblem, SetupEntry, State, WorkCenter
from synaps.solvers.greedy_dispatch import BeamSearchDispatch

INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"
WIDTHS = [1, 2, 3, 5, 8, 12]


def _assert_monotone(problem: ScheduleProblem, label: str) -> None:
    best_so_far = float("inf")
    for width in WIDTHS:
        mk = BeamSearchDispatch(beam_width=width).solve(problem).objective.makespan_minutes
        assert mk <= best_so_far + 1e-6, (
            f"{label}: beam_width={width} makespan {mk} worse than a narrower beam {best_so_far}"
        )
        best_so_far = min(best_so_far, mk)


def test_beam_monotone_on_medium_stress() -> None:
    """Q1: the audit's headline instance must be monotone in beam width."""
    problem = ScheduleProblem.model_validate(
        json.loads((INSTANCES / "medium_stress_20x4.json").read_text(encoding="utf-8"))
    )
    _assert_monotone(problem, "medium_stress_20x4")


def _random_problem(seed: int) -> ScheduleProblem:
    rng = random.Random(seed)
    states = [State(code=f"s{i}") for i in range(rng.randint(2, 4))]
    machines = [
        WorkCenter(code=f"M{i}", capability_group="G", speed_factor=1.0)
        for i in range(rng.randint(2, 3))
    ]
    setups = [
        SetupEntry(
            work_center_id=wc.id, from_state_id=a.id, to_state_id=b.id,
            setup_minutes=rng.randint(1, 20),
        )
        for wc in machines
        for a in states
        for b in states
        if a.id != b.id
    ]
    orders: list[Order] = []
    ops: list[Operation] = []
    for _ in range(rng.randint(4, 8)):
        order_id = uuid4()
        orders.append(
            Order(id=order_id, external_ref="O", due_date=datetime(2026, 1, 6, tzinfo=UTC))
        )
        prev = None
        for seq in range(rng.randint(1, 3)):
            op = Operation(
                order_id=order_id, seq_in_order=seq, state_id=rng.choice(states).id,
                base_duration_min=rng.randint(10, 40),
                eligible_wc_ids=rng.sample([m.id for m in machines], rng.randint(1, len(machines))),
                predecessor_op_id=prev,
            )
            ops.append(op)
            prev = op.id
    return ScheduleProblem(
        states=states, orders=orders, operations=ops, work_centers=machines, setup_matrix=setups,
        planning_horizon_start=datetime(2026, 1, 1, tzinfo=UTC),
        planning_horizon_end=datetime(2026, 1, 11, tzinfo=UTC),
    )


@pytest.mark.parametrize("seed", range(12))
def test_beam_monotone_property(seed: int) -> None:
    """Q1: makespan non-increasing in beam width on random small instances."""
    _assert_monotone(_random_problem(seed), f"seed={seed}")
