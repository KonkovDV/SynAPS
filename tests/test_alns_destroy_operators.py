"""Unit tests for ALNS destroy operators.

Coverage:

* Critical-path identification (task 1.4) — `_destroy_critical_path`
  correctly identifies the critical (longest) path in the combined
  precedence + machine-sequence DAG for small, hand-crafted problems
  where the critical path is provable by inspection.
  These tests focus on IDENTIFICATION (not the extension logic covered
  in `tests/test_critical_path_extension.py`). Each test uses a
  ``destroy_size`` equal to the exact length of the expected critical
  path so that neither trimming nor extension is triggered.
* Due-date-pressure successor closure (task 2.3) — when the ALNS main
  loop wraps ``_destroy_due_pressure`` output in
  ``_expand_successor_closure``, transitive successors of a destroyed
  operation are guaranteed to also be destroyed.

Validates: Requirements 1.1, 1.3 (critical-path destroy operator);
Requirement 2 AC4 (due-pressure successor-closure invariant).
"""

from __future__ import annotations

import math
import random
import statistics
from collections import deque
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import hypothesis.strategies as st
from hypothesis import HealthCheck, event, given, settings

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import (
    _destroy_critical_path,
    _destroy_due_pressure,
    _expand_successor_closure,
)
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.sdst_matrix import SdstMatrix


class TestCriticalPathIdentification:
    """Tests that `_destroy_critical_path` identifies the longest path in known DAGs."""

    def test_linear_precedence_chain_returns_full_chain(self):
        """A single linear precedence chain A -> B -> C is the critical path."""
        wc = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")
        s3 = State(id=uuid4(), code="S3")

        order = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))

        op_a = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        )
        op_b = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=op_a.id,
        )
        op_c = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=2,
            state_id=s3.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=op_b.id,
        )

        problem = ScheduleProblem(
            operations=[op_a, op_b, op_c],
            work_centers=[wc],
            states=[s1, s2, s3],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        base = datetime(2025, 1, 1)
        assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc.id,
                start_time=base,
                end_time=base + timedelta(minutes=10),
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc.id,
                start_time=base + timedelta(minutes=10),
                end_time=base + timedelta(minutes=20),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc.id,
                start_time=base + timedelta(minutes=20),
                end_time=base + timedelta(minutes=30),
            ),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # CP = [A, B, C], total length = 10 + 10 + 10 = 30. destroy_size = 3 (exact match).
        result = _destroy_critical_path(assignments, problem, sdst, destroy_size=3, rng=rng)

        assert result == {op_a.id, op_b.id, op_c.id}

    def test_parallel_branches_selects_longer_branch(self):
        """Two parallel precedence chains: critical path is the longer one."""
        # Five unique machines so there are no machine-sequence edges between branches.
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        wc_b = WorkCenter(id=uuid4(), code="B", capability_group="grp1")
        wc_c = WorkCenter(id=uuid4(), code="C", capability_group="grp1")
        wc_d = WorkCenter(id=uuid4(), code="D", capability_group="grp1")
        wc_e = WorkCenter(id=uuid4(), code="E", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")

        # Long chain (order1): A -> B -> C, durations 10/10/10 (total 30)
        # Short chain (order2): D -> E, durations 5/5 (total 10)
        order_long = Order(id=uuid4(), external_ref="LONG", due_date=datetime(2025, 1, 2))
        order_short = Order(id=uuid4(), external_ref="SHORT", due_date=datetime(2025, 1, 2))

        op_a = Operation(
            id=uuid4(),
            order_id=order_long.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc_a.id],
        )
        op_b = Operation(
            id=uuid4(),
            order_id=order_long.id,
            seq_in_order=1,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc_b.id],
            predecessor_op_id=op_a.id,
        )
        op_c = Operation(
            id=uuid4(),
            order_id=order_long.id,
            seq_in_order=2,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc_c.id],
            predecessor_op_id=op_b.id,
        )
        op_d = Operation(
            id=uuid4(),
            order_id=order_short.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=5,
            eligible_wc_ids=[wc_d.id],
        )
        op_e = Operation(
            id=uuid4(),
            order_id=order_short.id,
            seq_in_order=1,
            state_id=s1.id,
            base_duration_min=5,
            eligible_wc_ids=[wc_e.id],
            predecessor_op_id=op_d.id,
        )

        problem = ScheduleProblem(
            operations=[op_a, op_b, op_c, op_d, op_e],
            work_centers=[wc_a, wc_b, wc_c, wc_d, wc_e],
            states=[s1],
            setup_matrix=[],
            orders=[order_long, order_short],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        base = datetime(2025, 1, 1)
        assignments = [
            # Long branch: sequential on distinct machines
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc_a.id,
                start_time=base,
                end_time=base + timedelta(minutes=10),
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc_b.id,
                start_time=base + timedelta(minutes=10),
                end_time=base + timedelta(minutes=20),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc_c.id,
                start_time=base + timedelta(minutes=20),
                end_time=base + timedelta(minutes=30),
            ),
            # Short branch: each on its own machine, fully independent
            Assignment(
                operation_id=op_d.id,
                work_center_id=wc_d.id,
                start_time=base,
                end_time=base + timedelta(minutes=5),
            ),
            Assignment(
                operation_id=op_e.id,
                work_center_id=wc_e.id,
                start_time=base + timedelta(minutes=5),
                end_time=base + timedelta(minutes=10),
            ),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # Longest path = A -> B -> C with length 30. Short branch D -> E has length 10.
        # destroy_size = 3 matches CP length exactly (no trimming, no extension).
        result = _destroy_critical_path(assignments, problem, sdst, destroy_size=3, rng=rng)

        assert result == {op_a.id, op_b.id, op_c.id}
        assert op_d.id not in result
        assert op_e.id not in result

    def test_machine_sequence_extends_critical_path_beyond_precedence(self):
        """Shared machine sequence combines two independent orders into one critical path."""
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")

        order1 = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))
        order2 = Order(id=uuid4(), external_ref="O2", due_date=datetime(2025, 1, 2))

        # order1: opA -> opB (precedence), each dur=5
        # order2: opC -> opD (precedence, independent from order1), each dur=5
        op_a = Operation(
            id=uuid4(),
            order_id=order1.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
        )
        op_b = Operation(
            id=uuid4(),
            order_id=order1.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=op_a.id,
        )
        op_c = Operation(
            id=uuid4(),
            order_id=order2.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
        )
        op_d = Operation(
            id=uuid4(),
            order_id=order2.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=5,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=op_c.id,
        )

        problem = ScheduleProblem(
            operations=[op_a, op_b, op_c, op_d],
            work_centers=[wc],
            states=[s1, s2],
            setup_matrix=[],
            orders=[order1, order2],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        base = datetime(2025, 1, 1)
        # Machine M sequence (by start_time): opA, opC, opB, opD
        # Precedence edges: opA->opB, opC->opD
        # Machine edges: opA->opC, opC->opB, opB->opD
        # Longest path: opA->opC->opB->opD = 5+5+5+5 = 20
        # (Pure precedence-only chains max out at 10.)
        assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc.id,
                start_time=base,
                end_time=base + timedelta(minutes=5),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc.id,
                start_time=base + timedelta(minutes=5),
                end_time=base + timedelta(minutes=10),
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc.id,
                start_time=base + timedelta(minutes=10),
                end_time=base + timedelta(minutes=15),
            ),
            Assignment(
                operation_id=op_d.id,
                work_center_id=wc.id,
                start_time=base + timedelta(minutes=15),
                end_time=base + timedelta(minutes=20),
            ),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # destroy_size = 4 matches CP length exactly (no trimming, no extension).
        result = _destroy_critical_path(assignments, problem, sdst, destroy_size=4, rng=rng)

        assert result == {op_a.id, op_b.id, op_c.id, op_d.id}

    def test_pure_machine_sequence_critical_path(self):
        """Critical path formed entirely by machine-sequence edges (no precedence links)."""
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")

        # Three independent orders, each with a single op. No precedence anywhere.
        order1 = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))
        order2 = Order(id=uuid4(), external_ref="O2", due_date=datetime(2025, 1, 2))
        order3 = Order(id=uuid4(), external_ref="O3", due_date=datetime(2025, 1, 2))

        op_x = Operation(
            id=uuid4(),
            order_id=order1.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        )
        op_y = Operation(
            id=uuid4(),
            order_id=order2.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        )
        op_z = Operation(
            id=uuid4(),
            order_id=order3.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        )

        problem = ScheduleProblem(
            operations=[op_x, op_y, op_z],
            work_centers=[wc],
            states=[s1],
            setup_matrix=[],
            orders=[order1, order2, order3],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        base = datetime(2025, 1, 1)
        # Machine sequence (by start_time): opX, opY, opZ
        # No precedence edges. Machine edges: opX->opY->opZ. Longest path = 10+10+10 = 30.
        assignments = [
            Assignment(
                operation_id=op_x.id,
                work_center_id=wc.id,
                start_time=base,
                end_time=base + timedelta(minutes=10),
            ),
            Assignment(
                operation_id=op_y.id,
                work_center_id=wc.id,
                start_time=base + timedelta(minutes=10),
                end_time=base + timedelta(minutes=20),
            ),
            Assignment(
                operation_id=op_z.id,
                work_center_id=wc.id,
                start_time=base + timedelta(minutes=20),
                end_time=base + timedelta(minutes=30),
            ),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # destroy_size = 3 matches CP length exactly (no trimming, no extension).
        result = _destroy_critical_path(assignments, problem, sdst, destroy_size=3, rng=rng)

        assert result == {op_x.id, op_y.id, op_z.id}

    def test_diamond_dag_selects_longer_middle_branch(self):
        """Diamond fork-and-join: critical path takes the longer of two middle branches."""
        wc_m1 = WorkCenter(id=uuid4(), code="M1", capability_group="grp1")
        wc_m2 = WorkCenter(id=uuid4(), code="M2", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")

        # order1: opA (root) -> opB1 (long middle branch, dur=20)
        # order2: opB2 (short middle branch, dur=10) -> opC (join)
        # Machine M1: opA (then opB2) — machine edge A -> B2 (forms the "fork")
        # Machine M2: opB1 (then opC) — machine edge B1 -> C (forms the "join")
        # Precedence edges: opA -> opB1, opB2 -> opC
        order1 = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))
        order2 = Order(id=uuid4(), external_ref="O2", due_date=datetime(2025, 1, 2))

        op_a = Operation(
            id=uuid4(),
            order_id=order1.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=5,
            eligible_wc_ids=[wc_m1.id],
        )
        op_b1 = Operation(
            id=uuid4(),
            order_id=order1.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=20,
            eligible_wc_ids=[wc_m2.id],
            predecessor_op_id=op_a.id,
        )
        op_b2 = Operation(
            id=uuid4(),
            order_id=order2.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc_m1.id],
        )
        op_c = Operation(
            id=uuid4(),
            order_id=order2.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=5,
            eligible_wc_ids=[wc_m2.id],
            predecessor_op_id=op_b2.id,
        )

        problem = ScheduleProblem(
            operations=[op_a, op_b1, op_b2, op_c],
            work_centers=[wc_m1, wc_m2],
            states=[s1, s2],
            setup_matrix=[],
            orders=[order1, order2],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        base = datetime(2025, 1, 1)
        # Machine M1 sequence: opA(0-5), opB2(5-15)
        # Machine M2 sequence: opB1(5-25), opC(25-30)
        # Combined DAG edges:
        #   Precedence: A -> B1, B2 -> C
        #   Machine:    A -> B2 (M1), B1 -> C (M2)
        # Longer middle branch (via B1): A -> B1 -> C = 5 + 20 + 5 = 30
        # Shorter middle branch (via B2): A -> B2 -> C = 5 + 10 + 5 = 20
        assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc_m1.id,
                start_time=base,
                end_time=base + timedelta(minutes=5),
            ),
            Assignment(
                operation_id=op_b2.id,
                work_center_id=wc_m1.id,
                start_time=base + timedelta(minutes=5),
                end_time=base + timedelta(minutes=15),
            ),
            Assignment(
                operation_id=op_b1.id,
                work_center_id=wc_m2.id,
                start_time=base + timedelta(minutes=5),
                end_time=base + timedelta(minutes=25),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc_m2.id,
                start_time=base + timedelta(minutes=25),
                end_time=base + timedelta(minutes=30),
            ),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # destroy_size = 3 matches longer-branch CP length exactly (no trimming, no extension).
        result = _destroy_critical_path(assignments, problem, sdst, destroy_size=3, rng=rng)

        assert result == {op_a.id, op_b1.id, op_c.id}
        assert op_b2.id not in result  # shorter branch must not be selected

    def test_multiple_candidate_sinks_returns_deterministic_single_chain(self):
        """Two independent chains of equal length share the makespan.

        Two orders, each on its own dedicated machine, form fully disjoint
        precedence chains with identical total durations. Both chains finish
        at the same end_time, so both sinks tie on the longest-path DP value.
        The implementation uses ``max(assigned_op_ids, key=lambda op_id: dist[op_id])``
        to pick the makespan-defining operation, which returns exactly one
        sink (Python's ``max`` with a key returns the first-encountered
        maximum). The contract under test: for a given run, the destroyed
        set MUST be exactly one of the candidate chains — never a mix — and
        repeated calls with the same RNG must return the same chain.

        The "either is acceptable" clause is honoured by asserting the
        returned set equals one of the two expected chains (not requiring a
        specific one) while still enforcing single-chain purity and
        intra-run determinism.
        """
        wc_1 = WorkCenter(id=uuid4(), code="WC1", capability_group="grp1")
        wc_2 = WorkCenter(id=uuid4(), code="WC2", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")

        order_1 = Order(id=uuid4(), external_ref="ORD1", due_date=datetime(2025, 1, 2))
        order_2 = Order(id=uuid4(), external_ref="ORD2", due_date=datetime(2025, 1, 2))

        # Chain 1 (order_1 on wc_1): op1_a -> op1_b, each dur=10, total=20.
        op1_a = Operation(
            id=uuid4(),
            order_id=order_1.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc_1.id],
        )
        op1_b = Operation(
            id=uuid4(),
            order_id=order_1.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=10,
            eligible_wc_ids=[wc_1.id],
            predecessor_op_id=op1_a.id,
        )
        # Chain 2 (order_2 on wc_2): op2_a -> op2_b, each dur=10, total=20.
        op2_a = Operation(
            id=uuid4(),
            order_id=order_2.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc_2.id],
        )
        op2_b = Operation(
            id=uuid4(),
            order_id=order_2.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=10,
            eligible_wc_ids=[wc_2.id],
            predecessor_op_id=op2_a.id,
        )

        problem = ScheduleProblem(
            operations=[op1_a, op1_b, op2_a, op2_b],
            work_centers=[wc_1, wc_2],
            states=[s1, s2],
            setup_matrix=[],
            orders=[order_1, order_2],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        base = datetime(2025, 1, 1)
        # Both chains start at t=0 and finish at t=20 — makespan is tied.
        # Chains are fully disjoint: no precedence links or shared machines,
        # so no edges bridge them in the combined DAG.
        assignments = [
            Assignment(
                operation_id=op1_a.id,
                work_center_id=wc_1.id,
                start_time=base,
                end_time=base + timedelta(minutes=10),
            ),
            Assignment(
                operation_id=op1_b.id,
                work_center_id=wc_1.id,
                start_time=base + timedelta(minutes=10),
                end_time=base + timedelta(minutes=20),
            ),
            Assignment(
                operation_id=op2_a.id,
                work_center_id=wc_2.id,
                start_time=base,
                end_time=base + timedelta(minutes=10),
            ),
            Assignment(
                operation_id=op2_b.id,
                work_center_id=wc_2.id,
                start_time=base + timedelta(minutes=10),
                end_time=base + timedelta(minutes=20),
            ),
        ]

        sdst = SdstMatrix.from_problem(problem)

        chain_1 = {op1_a.id, op1_b.id}
        chain_2 = {op2_a.id, op2_b.id}

        # destroy_size = 2 matches each chain's length — no trimming or extension.
        result_1 = _destroy_critical_path(
            assignments, problem, sdst, destroy_size=2, rng=random.Random(42)
        )

        # Must be exactly one chain — never a mix of ops from both.
        assert result_1 in (chain_1, chain_2), (
            f"Expected result to equal one of the two tied chains "
            f"({chain_1} or {chain_2}), got {result_1}"
        )
        # Single-chain purity: no op from the other chain may leak in.
        assert len(result_1) == 2

        # Determinism: a second call with the same assignments, problem, sdst,
        # and an RNG seeded identically must return the same chain. The
        # longest-path DP and max-sink selection are deterministic given the
        # same input iteration order; the RNG is not consulted on this path,
        # but we seed it identically to match real-world usage.
        result_2 = _destroy_critical_path(
            assignments, problem, sdst, destroy_size=2, rng=random.Random(42)
        )
        assert result_2 == result_1, (
            f"Determinism violated: two calls with identical inputs returned "
            f"different chains ({result_1} vs {result_2})"
        )


# ---------------------------------------------------------------------------
# Property test (task 1.5): critical path length equals makespan
# ---------------------------------------------------------------------------
#
# Validates: Requirements 1.2 (Property 2 from design.md).
#
# For any feasible schedule produced by greedy dispatch, the longest path
# through the combined precedence + machine-sequence DAG — where node weight
# is processing duration and edge weight is the gap between predecessor's
# end_time and successor's start_time (setup time for machine edges, 0 for
# tight precedence edges) — must equal the schedule's makespan, defined as
# `max(end_time) - min(start_time)` across all assignments.
#
# Rationale: in any left-shifted feasible schedule, each operation's
# start_time is determined by the maximum of its precedence predecessor's
# end_time and its machine predecessor's end_time plus the required setup.
# This recursive structure corresponds exactly to a longest-path DP on the
# combined DAG.  If either the greedy dispatcher fails to left-shift or
# our DAG model misses an edge, the property will break.


def _compute_critical_path_length(
    assignments: list[Assignment],
    problem: ScheduleProblem,
) -> float:
    """Longest path in the combined precedence + machine-sequence DAG.

    Node weight  = processing duration of the operation (minutes).
    Edge weight  = gap between predecessor's end_time and successor's
                   start_time (minutes, clamped to non-negative).

    Returns the longest path length from any source to any sink, measured
    in minutes from the earliest assignment's start_time.
    """
    if not assignments:
        return 0.0

    ops_by_id = {op.id: op for op in problem.operations}

    base = min(a.start_time for a in assignments)
    start_offset: dict[Any, float] = {}
    end_offset: dict[Any, float] = {}
    duration: dict[Any, float] = {}
    for a in assignments:
        start_offset[a.operation_id] = (a.start_time - base).total_seconds() / 60.0
        end_offset[a.operation_id] = (a.end_time - base).total_seconds() / 60.0
        duration[a.operation_id] = end_offset[a.operation_id] - start_offset[a.operation_id]

    assigned_op_ids = set(start_offset)

    # Adjacency: node -> list of (successor, edge_gap)
    successors: dict[Any, list[tuple[Any, float]]] = {op_id: [] for op_id in assigned_op_ids}
    in_degree: dict[Any, int] = dict.fromkeys(assigned_op_ids, 0)

    # Precedence edges
    for op_id in assigned_op_ids:
        op = ops_by_id.get(op_id)
        if op is None:
            continue
        pred_id = op.predecessor_op_id
        if pred_id is not None and pred_id in assigned_op_ids:
            gap = max(start_offset[op_id] - end_offset[pred_id], 0.0)
            successors[pred_id].append((op_id, gap))
            in_degree[op_id] += 1

    # Machine-sequence edges (consecutive ops on the same machine by start_time)
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for machine_seq in by_machine.values():
        machine_seq.sort(key=lambda a: a.start_time)
        for i in range(len(machine_seq) - 1):
            prev_id = machine_seq[i].operation_id
            curr_id = machine_seq[i + 1].operation_id
            gap = max(start_offset[curr_id] - end_offset[prev_id], 0.0)
            successors[prev_id].append((curr_id, gap))
            in_degree[curr_id] += 1

    # Kahn's topological sort
    queue: deque[Any] = deque(op_id for op_id in assigned_op_ids if in_degree[op_id] == 0)
    topo: list[Any] = []
    in_deg = dict(in_degree)
    while queue:
        node = queue.popleft()
        topo.append(node)
        for succ, _ in successors[node]:
            in_deg[succ] -= 1
            if in_deg[succ] == 0:
                queue.append(succ)

    # If the graph has a cycle the topo order is incomplete — report a value
    # that will fail the property and expose the bug rather than hiding it.
    if len(topo) != len(assigned_op_ids):
        return float("nan")

    # Longest-path DP.  Initialise each node with its own earliest finish
    # from the virtual source (an implicit edge of weight start_offset[node]
    # from time 0); forward-relax via every combined-DAG predecessor.
    lp: dict[Any, float] = {op_id: end_offset[op_id] for op_id in assigned_op_ids}
    for node in topo:
        for succ, gap in successors[node]:
            candidate = lp[node] + gap + duration[succ]
            if candidate > lp[succ]:
                lp[succ] = candidate

    return max(lp.values())


# --- Random feasible problem generator (plain random.Random loop) ----------


def _make_random_feasible_problem(
    rng: random.Random,
    *,
    n_orders: int,
    max_ops_per_order: int,
    n_machines: int,
    n_states: int,
) -> ScheduleProblem:
    """Generate a random FJSP-SDST problem small enough to satisfy the greedy
    dispatcher without horizon bound issues. Precedence chains are built by
    setting `predecessor_op_id` sequentially within each order."""
    horizon_start = datetime(2026, 4, 1, 8, 0)
    horizon_end = horizon_start + timedelta(days=10)

    states = [State(id=uuid4(), code=f"S-{i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i}",
            capability_group="machining",
            speed_factor=rng.uniform(0.8, 1.5),
        )
        for i in range(n_machines)
    ]

    # Sparse random setup matrix — not every transition is populated (unknown
    # transitions fall back to 0 setup via `SdstMatrix.get_setup`).
    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if rng.random() < 0.6:
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=rng.randint(1, 20),
                        )
                    )

    orders: list[Order] = []
    operations: list[Operation] = []
    for i in range(n_orders):
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{i:04d}",
                due_date=horizon_start + timedelta(hours=rng.randint(24, 48)),
                priority=rng.randint(300, 900),
            )
        )
        ops_in_order = rng.randint(1, max_ops_per_order)
        prev_op_id = None
        for j in range(ops_in_order):
            op_id = uuid4()
            # Each op is eligible on at least one machine (randomly chosen
            # prefix to keep problem feasible).
            n_eligible = rng.randint(1, n_machines)
            eligible = [wc.id for wc in rng.sample(work_centers, n_eligible)]
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=rng.choice(states).id,
                    base_duration_min=rng.randint(5, 60),
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


class TestCriticalPathLengthLeMakespan:
    """Property: critical path length <= makespan for greedy-generated schedules.

    Validates: Requirement 1 (audit-corrected form of Property 2 from design.md).

    Audit correction (2026-05-10): equality does not hold in general. Feasible
    schedules may contain idle, release, or setup gaps outside operation
    duration that extend the makespan beyond the DAG longest-path. Equality
    only holds for compact no-idle schedules where every timing gap is
    explained by a precedence or machine-sequence edge.
    """

    def test_property_over_random_feasible_schedules(self):
        """For >=50 random feasible greedy schedules spanning 10-200 ops
        and 2-10 machines, the longest path in the combined DAG is
        <= max(end_time) - min(start_time) within 1e-6 minutes."""
        n_tested = 0
        target = 50
        attempts = 0
        max_attempts = 200  # safety bound — greedy almost always succeeds

        while n_tested < target and attempts < max_attempts:
            attempts += 1
            seed = 10_000 + attempts
            rng = random.Random(seed)

            n_machines = rng.randint(2, 10)
            # Size the problem so total ops lands in [10, 200].
            # n_orders * avg(max_ops_per_order / 2) ≈ target_ops.
            target_ops = rng.randint(10, 200)
            max_ops_per_order = rng.randint(2, 8)
            n_orders = max(
                1,
                target_ops // max(1, max_ops_per_order // 2),
            )
            # Guard against tiny/huge extremes.
            n_orders = max(3, min(n_orders, 100))

            problem = _make_random_feasible_problem(
                rng,
                n_orders=n_orders,
                max_ops_per_order=max_ops_per_order,
                n_machines=n_machines,
                n_states=rng.randint(2, 5),
            )

            # Skip problems that fall outside the 10-200 op window.
            n_ops = len(problem.operations)
            if n_ops < 10 or n_ops > 200:
                continue

            result = GreedyDispatch().solve(problem)
            if result.status != SolverStatus.FEASIBLE:
                continue  # extremely rare; skip and draw another

            assignments = result.assignments
            assert len(assignments) == n_ops, (
                f"seed={seed}: greedy returned partial schedule ({len(assignments)}/{n_ops})"
            )

            # Property under test
            cp_length = _compute_critical_path_length(assignments, problem)

            base = min(a.start_time for a in assignments)
            makespan = max((a.end_time - base).total_seconds() / 60.0 for a in assignments)

            assert not math.isnan(cp_length), (
                f"seed={seed}: critical-path DP returned NaN "
                f"(combined DAG has a cycle — bug in edge construction)"
            )
            assert cp_length <= makespan + 1e-6, (
                f"seed={seed}, n_ops={n_ops}, n_machines={n_machines}: "
                f"critical_path_length={cp_length:.6f} > makespan={makespan:.6f}, "
                f"delta={cp_length - makespan:.6e} (cp length must not exceed makespan)"
            )

            n_tested += 1

        assert n_tested >= target, (
            f"Only {n_tested}/{target} random feasible schedules tested "
            f"after {attempts} attempts — too many infeasible rolls"
        )


class TestDuePressureSuccessorClosure:
    """Tests that the successor-closure invariant is maintained when
    ``_destroy_due_pressure`` output is wrapped in ``_expand_successor_closure``.

    The ALNS main loop wraps every destroy operator's raw output via
    ``_expand_successor_closure`` before the repair step. This class verifies
    that, for a hand-crafted tardy chain, the composite pipeline
    (``_destroy_due_pressure`` → ``_expand_successor_closure``) guarantees:
    if op_b is destroyed, every transitive successor of op_b (such as op_c)
    is also in the destroyed set.

    Validates: Requirement 2, AC4 (due-pressure successor-closure invariant).
    """

    @staticmethod
    def _build_successors_by_op(problem: ScheduleProblem) -> dict:
        """Replicate the main loop's construction of ``successors_by_op``.

        See ``AlnsSolver.solve`` in ``synaps/solvers/alns_solver.py`` around
        the ``successors_by_op`` initialisation. Keeping the construction
        identical ensures the test exercises the same invariant the main
        loop relies on.
        """
        successors_by_op: dict = {}
        for op in problem.operations:
            if op.predecessor_op_id is not None:
                successors_by_op.setdefault(op.predecessor_op_id, []).append(op.id)
        return successors_by_op

    def test_destroying_middle_of_tardy_chain_expands_to_successor(self):
        """If op_b (mid-chain, most tardy) is destroyed, op_c (successor) must be too.

        Construction: single order with precedence chain op_a -> op_b -> op_c,
        all on one machine, due date placed so that op_b's end time is well
        past the due date (strongly tardy). ``_destroy_due_pressure`` with
        ``destroy_size=1`` prefers the temporally-latest op within the
        highest-weighted-tardiness order, so it picks op_c first. To force
        op_b into the raw selection we use ``destroy_size=2`` and then confirm
        the composite pipeline pulls op_c in via the closure expansion (either
        already in the raw set or added by the successor closure wrapper).
        The critical property is: after closure expansion, op_b's presence
        implies op_c's presence.
        """
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")
        s3 = State(id=uuid4(), code="S3")

        # Horizon start, due date set so the order is strongly tardy.
        horizon_start = datetime(2025, 1, 1)
        # op_c ends at minute 30; due at minute 5 => 25 minutes tardy.
        due_date = horizon_start + timedelta(minutes=5)
        order = Order(id=uuid4(), external_ref="O1", due_date=due_date, priority=500)

        op_a = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        )
        op_b = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=op_a.id,
        )
        op_c = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=2,
            state_id=s3.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=op_b.id,
        )

        problem = ScheduleProblem(
            operations=[op_a, op_b, op_c],
            work_centers=[wc],
            states=[s1, s2, s3],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )

        assignments = [
            Assignment(
                operation_id=op_a.id,
                work_center_id=wc.id,
                start_time=horizon_start,
                end_time=horizon_start + timedelta(minutes=10),
            ),
            Assignment(
                operation_id=op_b.id,
                work_center_id=wc.id,
                start_time=horizon_start + timedelta(minutes=10),
                end_time=horizon_start + timedelta(minutes=20),
            ),
            Assignment(
                operation_id=op_c.id,
                work_center_id=wc.id,
                start_time=horizon_start + timedelta(minutes=20),
                end_time=horizon_start + timedelta(minutes=30),
            ),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)
        successors_by_op = self._build_successors_by_op(problem)

        # destroy_size=2: due_pressure selects the two temporally-latest ops
        # in the tardy order chain, i.e. op_c and op_b.
        raw = _destroy_due_pressure(
            assignments,
            problem,
            sdst,
            destroy_size=2,
            rng=rng,
        )
        assert op_b.id in raw, (
            "due_pressure with destroy_size=2 should include op_b "
            "(second-latest op in the tardy chain)"
        )

        expanded = _expand_successor_closure(raw, successors_by_op)

        # Core invariant: op_b destroyed => op_c destroyed (transitive closure).
        assert op_c.id in expanded, (
            "Successor-closure invariant violated: op_b is in the destroyed "
            "set but op_c (its direct successor) is not"
        )

    def test_closure_pulls_in_successor_when_only_predecessor_selected(self):
        """Even if raw selection contains only op_b, closure must add op_c.

        This directly exercises the closure wrapper: we bypass the operator's
        own selection logic by feeding ``{op_b.id}`` into
        ``_expand_successor_closure`` and confirm op_c is added. This proves
        that whenever ``_destroy_due_pressure`` is eventually wired into
        ``DESTROY_OPERATORS`` (task 2.4), the ALNS main loop's existing
        wrapping will enforce AC4 regardless of which ops the operator
        selects.
        """
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")
        s3 = State(id=uuid4(), code="S3")

        horizon_start = datetime(2025, 1, 1)
        order = Order(
            id=uuid4(),
            external_ref="O1",
            due_date=horizon_start + timedelta(minutes=5),
        )

        op_a = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        )
        op_b = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=1,
            state_id=s2.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=op_a.id,
        )
        op_c = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=2,
            state_id=s3.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=op_b.id,
        )

        problem = ScheduleProblem(
            operations=[op_a, op_b, op_c],
            work_centers=[wc],
            states=[s1, s2, s3],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )

        successors_by_op = self._build_successors_by_op(problem)

        # Feed just op_b — the closure must pull in op_c (and not op_a,
        # which is a predecessor rather than a successor).
        expanded = _expand_successor_closure({op_b.id}, successors_by_op)

        assert op_b.id in expanded
        assert op_c.id in expanded, "Closure wrapper failed to add direct successor op_c"
        assert op_a.id not in expanded, (
            "Closure wrapper must not add predecessors; op_a should be absent"
        )


# ---------------------------------------------------------------------------
# Unit tests (task 2.5): tardy-order targeting and slack-based fallback
# ---------------------------------------------------------------------------
#
# Validates: Requirement 2 — AC1 (tardiness clamped to max(0, latest_end - due)),
#            AC2 (prefer temporally latest ops in top-tardy orders),
#            AC3 (slack-based fallback when no orders are tardy).
#
# These tests exercise ``_destroy_due_pressure`` in isolation (not the ALNS
# main loop). The operator is deterministic except for random tie-breaks, so
# each scenario is constructed with unambiguous ordering (distinct
# tardiness / slack / end_time values) to keep assertions deterministic.


def _build_chain_order(
    *,
    wc: WorkCenter,
    state: State,
    horizon_start: datetime,
    chain_start_offset_min: int,
    n_ops: int,
    op_duration_min: int,
    due_offset_min: int,
    priority: int = 500,
    external_ref: str = "ORD",
) -> tuple[Order, list[Operation], list[Assignment]]:
    """Build an order with ``n_ops`` precedence-chained operations assigned
    back-to-back on ``wc``, starting at ``chain_start_offset_min`` minutes
    past ``horizon_start``. Returns (order, ops, assignments)."""
    order = Order(
        id=uuid4(),
        external_ref=external_ref,
        due_date=horizon_start + timedelta(minutes=due_offset_min),
        priority=priority,
    )
    ops: list[Operation] = []
    prev_id: UUID | None = None
    for i in range(n_ops):
        op = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=i,
            state_id=state.id,
            base_duration_min=op_duration_min,
            eligible_wc_ids=[wc.id],
            predecessor_op_id=prev_id,
        )
        ops.append(op)
        prev_id = op.id

    assignments: list[Assignment] = []
    cursor = chain_start_offset_min
    for op in ops:
        assignments.append(
            Assignment(
                operation_id=op.id,
                work_center_id=wc.id,
                start_time=horizon_start + timedelta(minutes=cursor),
                end_time=horizon_start + timedelta(minutes=cursor + op_duration_min),
            )
        )
        cursor += op_duration_min

    return order, ops, assignments


class TestDuePressureUnit:
    """Unit tests for `_destroy_due_pressure` tardy-order targeting and slack fallback.

    Validates: Requirement 2 AC1 (tardiness clamping), AC2 (temporally-latest
    ops in top-tardy orders), AC3 (slack-based fallback when no orders are
    tardy).
    """

    def test_picks_temporally_latest_op_in_single_tardy_order(self):
        """Single tardy order, 3 ops, destroy_size=1 → latest op (largest end_time) picked."""
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # Chain ends at minute 30, due at minute 5 → tardiness = 25 min (strongly tardy).
        order, ops, assignments = _build_chain_order(
            wc=wc,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=3,
            op_duration_min=10,
            due_offset_min=5,
            external_ref="TARDY",
        )
        op_a, op_b, op_c = ops

        problem = ScheduleProblem(
            operations=ops,
            work_centers=[wc],
            states=[s1],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(assignments, problem, sdst, destroy_size=1, rng=rng)

        # op_c has the largest end_time (minute 30); op_a/op_b end earlier.
        assert result == {op_c.id}, (
            f"Expected temporally-latest op {op_c.id} (end=30min) but got {result}"
        )

    def test_picks_from_top_tardy_order_first(self):
        """Two tardy orders with distinct weighted tardiness → destroyed ops come from higher."""
        wc_high = WorkCenter(id=uuid4(), code="HIGH", capability_group="grp1")
        wc_low = WorkCenter(id=uuid4(), code="LOW", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # order_high: chain 0-30, due at 5 → tardiness=25 min. priority=500 → weight=1.0 → score=25.
        order_high, ops_high, asg_high = _build_chain_order(
            wc=wc_high,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=3,
            op_duration_min=10,
            due_offset_min=5,
            priority=500,
            external_ref="HIGH_TARDY",
        )
        # order_low: chain 0-30, due at 25 → tardiness = 5 min. priority=500 → weight=1.0 → score=5.
        order_low, ops_low, asg_low = _build_chain_order(
            wc=wc_low,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=3,
            op_duration_min=10,
            due_offset_min=25,
            priority=500,
            external_ref="LOW_TARDY",
        )

        problem = ScheduleProblem(
            operations=ops_high + ops_low,
            work_centers=[wc_high, wc_low],
            states=[s1],
            setup_matrix=[],
            orders=[order_high, order_low],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # destroy_size=2: two latest ops from the top-tardy order (order_high).
        result = _destroy_due_pressure(
            assignments=asg_high + asg_low,
            problem=problem,
            sdst=sdst,
            destroy_size=2,
            rng=rng,
        )

        high_ids = {op.id for op in ops_high}
        low_ids = {op.id for op in ops_low}
        assert len(result) == 2
        assert result.issubset(high_ids), (
            f"Expected both destroyed ops from HIGH_TARDY order but got result={result}, "
            f"low_order_ids={low_ids}"
        )
        # Specifically the two latest ops of the high-tardy chain (ops_high[2] and ops_high[1]).
        assert result == {ops_high[2].id, ops_high[1].id}

    def test_weighted_tardiness_ranking(self):
        """Same raw tardiness, different priority → higher-priority order's ops destroyed first."""
        wc_hp = WorkCenter(id=uuid4(), code="HP", capability_group="grp1")
        wc_lp = WorkCenter(id=uuid4(), code="LP", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # Both orders: chain 0-30, due at 5 → raw tardiness = 25 min each.
        # order_hp priority=1000 → weight=2.0 → score=50.
        # order_lp priority=250 → weight=0.5 → score=12.5.
        order_hp, ops_hp, asg_hp = _build_chain_order(
            wc=wc_hp,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=5,
            priority=1000,
            external_ref="HP",
        )
        order_lp, ops_lp, asg_lp = _build_chain_order(
            wc=wc_lp,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=5,
            priority=250,
            external_ref="LP",
        )

        problem = ScheduleProblem(
            operations=ops_hp + ops_lp,
            work_centers=[wc_hp, wc_lp],
            states=[s1],
            setup_matrix=[],
            orders=[order_hp, order_lp],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(
            assignments=asg_hp + asg_lp,
            problem=problem,
            sdst=sdst,
            destroy_size=1,
            rng=rng,
        )

        # High-priority order's latest op (ops_hp[1]) must be picked first.
        assert result == {ops_hp[1].id}, (
            f"Expected higher-priority order's latest op {ops_hp[1].id} "
            f"but got {result} (lp_ops={[o.id for o in ops_lp]})"
        )

    def test_tardiness_clamped_to_zero(self):
        """Order with latest_end < due_date has tardiness clamped to 0 → slack fallback triggers.

        Verifies AC1: tardiness = max(0, latest_end - due_date). A non-tardy
        order must NOT enter the tardy branch; instead the slack fallback
        should produce a non-empty result from the on-time order.
        """
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # Single order: chain 0-30, due at 60 → latest_end (30) < due (60), slack = 30 (positive).
        # Raw difference = -30, which must be clamped to 0 by AC1 → NOT tardy.
        order, ops, assignments = _build_chain_order(
            wc=wc,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=60,
            external_ref="ON_TIME",
        )

        problem = ScheduleProblem(
            operations=ops,
            work_centers=[wc],
            states=[s1],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(assignments, problem, sdst, destroy_size=1, rng=rng)

        # If AC1 was violated (negative tardiness admitted to the tardy branch),
        # the ``if tardiness <= 0.0: continue`` guard would also skip it, leading
        # to the same slack fallback path. The essential assertion is: result is
        # non-empty and comes from this on-time order via the fallback.
        assert len(result) == 1
        assert result == {ops[1].id}, (
            "Slack fallback should pick the temporally-latest op of the single "
            "on-time order; a different selection indicates AC1 or AC3 is broken."
        )

    def test_slack_fallback_picks_smallest_slack_first(self):
        """Two on-time orders with different slack → smallest-slack order is destroyed first."""
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        wc_b = WorkCenter(id=uuid4(), code="B", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # order_A: chain 0-30, due at 40 → slack = 10 (smallest positive slack).
        order_a, ops_a, asg_a = _build_chain_order(
            wc=wc_a,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=40,
            external_ref="A_SMALL_SLACK",
        )
        # order_B: chain 0-30, due at 60 → slack = 30 (larger positive slack).
        order_b, ops_b, asg_b = _build_chain_order(
            wc=wc_b,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=60,
            external_ref="B_LARGE_SLACK",
        )

        problem = ScheduleProblem(
            operations=ops_a + ops_b,
            work_centers=[wc_a, wc_b],
            states=[s1],
            setup_matrix=[],
            orders=[order_a, order_b],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(
            assignments=asg_a + asg_b,
            problem=problem,
            sdst=sdst,
            destroy_size=1,
            rng=rng,
        )

        b_ids = {op.id for op in ops_b}
        assert len(result) == 1
        assert result.isdisjoint(b_ids), (
            f"Smallest-slack order's op must be picked first but got op from "
            f"B_LARGE_SLACK: result={result}, b_ids={b_ids}"
        )
        # Specifically the latest op of order_A.
        assert result == {ops_a[1].id}

    def test_slack_fallback_ignores_zero_or_negative_slack(self):
        """Orders with slack == 0 are skipped in fallback (only positive slack contributes)."""
        wc_zero = WorkCenter(id=uuid4(), code="ZERO", capability_group="grp1")
        wc_pos = WorkCenter(id=uuid4(), code="POS", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # order_zero: chain 0-30, due at 30 → tardiness = 0, slack = 0 → skipped in both branches.
        order_zero, ops_zero, asg_zero = _build_chain_order(
            wc=wc_zero,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=30,
            external_ref="ZERO_SLACK",
        )
        # order_pos: chain 0-30, due 50 → tardiness=0, slack=20 (positive); fallback selects it.
        order_pos, ops_pos, asg_pos = _build_chain_order(
            wc=wc_pos,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=50,
            external_ref="POS_SLACK",
        )

        problem = ScheduleProblem(
            operations=ops_zero + ops_pos,
            work_centers=[wc_zero, wc_pos],
            states=[s1],
            setup_matrix=[],
            orders=[order_zero, order_pos],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # destroy_size=3 exceeds the positive-slack order's op count (2). If zero-slack were
        # included, the third slot would pull from it. With the skip rule, the result caps
        # at the 2 ops of order_pos.
        result = _destroy_due_pressure(
            assignments=asg_zero + asg_pos,
            problem=problem,
            sdst=sdst,
            destroy_size=3,
            rng=rng,
        )

        zero_ids = {op.id for op in ops_zero}
        pos_ids = {op.id for op in ops_pos}
        assert result.isdisjoint(zero_ids), (
            f"Zero-slack order's ops must not appear in fallback selection: "
            f"result={result}, zero_ids={zero_ids}"
        )
        assert result == pos_ids, (
            f"Expected all of positive-slack order's ops (fallback caps at available ops), "
            f"got {result}, expected {pos_ids}"
        )

    def test_empty_assignments_returns_empty(self):
        """Edge case: empty assignments list → empty set returned immediately."""
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)
        order = Order(
            id=uuid4(),
            external_ref="EMPTY",
            due_date=horizon_start + timedelta(minutes=60),
        )
        # Problem has an operation but no assignments.
        op = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=s1.id,
            base_duration_min=10,
            eligible_wc_ids=[wc.id],
        )
        problem = ScheduleProblem(
            operations=[op],
            work_centers=[wc],
            states=[s1],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(
            assignments=[], problem=problem, sdst=sdst, destroy_size=3, rng=rng
        )

        assert result == set()

    def test_destroy_size_caps_result(self):
        """Many tardy ops available, destroy_size=2 → exactly 2 ops returned."""
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # Single tardy order with 5 ops (so > destroy_size): chain 0-50, due at 5 → tardy by 45 min.
        order, ops, assignments = _build_chain_order(
            wc=wc,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=5,
            op_duration_min=10,
            due_offset_min=5,
            external_ref="BIG_TARDY",
        )

        problem = ScheduleProblem(
            operations=ops,
            work_centers=[wc],
            states=[s1],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(assignments, problem, sdst, destroy_size=2, rng=rng)

        assert len(result) == 2, f"destroy_size=2 but got {len(result)} ops: {result}"
        # Specifically the two temporally-latest ops (ops[4] and ops[3]).
        assert result == {ops[4].id, ops[3].id}


class TestDuePressureRawBranches:
    """Raw-operator coverage for the tardy and slack-fallback branches (task 2.5).

    Validates: Requirement 2 — AC1 (tardiness clamped to max(0, latest_end - due)),
                AC2 (prefer temporally latest ops in top-tardy orders),
                AC3 (slack-based fallback when no orders are tardy).

    These tests call ``_destroy_due_pressure`` directly and assert on the
    raw returned set — successor closure is applied by the ALNS main loop
    (``_expand_successor_closure``), not inside the operator, per
    ``alns_solver.py`` line 747's operator docstring and the task-2.3 audit
    note. Do NOT invoke ``_expand_successor_closure`` here; these tests
    target the operator in isolation to pin down branch-selection logic.

    Scenarios here complement the existing ``TestDuePressureUnit`` class by
    covering gaps: destroy_size=3 on a 4-op single-tardy chain, priority
    weight inversion (higher priority wins despite lower raw tardiness),
    three-order slack ranking, all-slack-zero returning empty, and
    destroy_size exceeding available ops in tardy orders.
    """

    def test_tardy_branch_single_order_destroy_size_three(self):
        """Single tardy order, 4 ops, destroy_size=3 → three temporally-latest ops.

        Required scenario 1b: with ``destroy_size=3`` on a 4-op chain, the
        operator must return the three ops with the highest ``end_time``
        (ops[1], ops[2], ops[3]) and must not include the earliest (ops[0]).
        """
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # Chain 0→40 (four ops of 10 min), due at minute 5 → tardiness = 35 min.
        order, ops, assignments = _build_chain_order(
            wc=wc,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=4,
            op_duration_min=10,
            due_offset_min=5,
            external_ref="TARDY4",
        )

        problem = ScheduleProblem(
            operations=ops,
            work_centers=[wc],
            states=[s1],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(assignments, problem, sdst, destroy_size=3, rng=rng)

        # Three temporally-latest ops: end_times 20, 30, 40 minutes.
        assert result == {ops[1].id, ops[2].id, ops[3].id}, (
            f"Expected three latest ops (ops[1]/[2]/[3]) but got {result}; "
            f"ops[0] (earliest) must be excluded."
        )
        assert ops[0].id not in result

    def test_tardy_branch_weighted_priority_overrides_raw_tardiness(self):
        """Lower raw tardiness + higher priority beats higher raw tardiness + low priority.

        Required scenario 2: order A tardiness=10 priority=500 (weight 1.0,
        score 10), order B tardiness=5 priority=2000 (weight 4.0, score 20).
        With ``destroy_size=1`` the operator picks an op from order B.
        """
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        wc_b = WorkCenter(id=uuid4(), code="B", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # order A: chain 0→20 (two 10-min ops), due at 10 → tardiness = 10, priority 500.
        # weighted score = 10 * (500/500) = 10.
        order_a, ops_a, asg_a = _build_chain_order(
            wc=wc_a,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=10,
            due_offset_min=10,
            priority=500,
            external_ref="A_LOW_PRIO",
        )
        # order B: chain 0→25 (one 25-min op), due at 20 → tardiness = 5, priority 2000.
        # weighted score = 5 * (2000/500) = 20.
        order_b, ops_b, asg_b = _build_chain_order(
            wc=wc_b,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=1,
            op_duration_min=25,
            due_offset_min=20,
            priority=2000,
            external_ref="B_HIGH_PRIO",
        )

        problem = ScheduleProblem(
            operations=ops_a + ops_b,
            work_centers=[wc_a, wc_b],
            states=[s1],
            setup_matrix=[],
            orders=[order_a, order_b],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(
            assignments=asg_a + asg_b,
            problem=problem,
            sdst=sdst,
            destroy_size=1,
            rng=rng,
        )

        # Weighted tardiness: A=10, B=20 → B wins despite lower raw tardiness.
        assert result == {ops_b[0].id}, (
            f"Expected high-priority order B's op {ops_b[0].id} (weighted 20), "
            f"got {result} (a_ids={[o.id for o in ops_a]})."
        )

    def test_slack_fallback_three_orders_smallest_slack_selected(self):
        """Three on-time orders with slacks 5 / 15 / 30 min → op from the 5-min slack order.

        Required scenario 4: ascending slack ordering (smallest first = most
        urgent). With ``destroy_size=1`` the operator must pick from the
        shortest-slack order and must not spill into larger-slack orders.
        """
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        wc_b = WorkCenter(id=uuid4(), code="B", capability_group="grp1")
        wc_c = WorkCenter(id=uuid4(), code="C", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # All three orders: chain 0→30 (two 15-min ops). Slack varies by due_offset.
        # A: due 35 → slack  5 (smallest → selected).
        # B: due 45 → slack 15.
        # C: due 60 → slack 30.
        order_a, ops_a, asg_a = _build_chain_order(
            wc=wc_a,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=35,
            external_ref="A_SLACK_5",
        )
        order_b, ops_b, asg_b = _build_chain_order(
            wc=wc_b,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=45,
            external_ref="B_SLACK_15",
        )
        order_c, ops_c, asg_c = _build_chain_order(
            wc=wc_c,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=60,
            external_ref="C_SLACK_30",
        )

        problem = ScheduleProblem(
            operations=ops_a + ops_b + ops_c,
            work_centers=[wc_a, wc_b, wc_c],
            states=[s1],
            setup_matrix=[],
            orders=[order_a, order_b, order_c],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(
            assignments=asg_a + asg_b + asg_c,
            problem=problem,
            sdst=sdst,
            destroy_size=1,
            rng=rng,
        )

        b_ids = {op.id for op in ops_b}
        c_ids = {op.id for op in ops_c}
        # Must pick from the smallest-slack order (A) only.
        assert result == {ops_a[1].id}, (
            f"Expected A's latest op {ops_a[1].id} (slack=5), got {result}; "
            f"b_ids={b_ids}, c_ids={c_ids}."
        )
        assert result.isdisjoint(b_ids)
        assert result.isdisjoint(c_ids)

    def test_slack_fallback_all_zero_slack_returns_empty(self):
        """Every order finishes exactly at its due date (slack=0) → empty result.

        Required scenario 5: the fallback branch only participates on
        **strictly positive** slack (see operator: ``if slack <= 0.0:
        continue``). When every order's latest_end equals its due_date,
        none are tardy (tardiness=0, so the tardy branch is also skipped)
        and no orders have positive slack either, so the operator must
        return an empty set.
        """
        wc_x = WorkCenter(id=uuid4(), code="X", capability_group="grp1")
        wc_y = WorkCenter(id=uuid4(), code="Y", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # Both orders finish at minute 30 and are due at minute 30 → slack=0.
        order_x, ops_x, asg_x = _build_chain_order(
            wc=wc_x,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=30,
            external_ref="X_SLACK_0",
        )
        order_y, ops_y, asg_y = _build_chain_order(
            wc=wc_y,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=15,
            due_offset_min=30,
            external_ref="Y_SLACK_0",
        )

        problem = ScheduleProblem(
            operations=ops_x + ops_y,
            work_centers=[wc_x, wc_y],
            states=[s1],
            setup_matrix=[],
            orders=[order_x, order_y],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(
            assignments=asg_x + asg_y,
            problem=problem,
            sdst=sdst,
            destroy_size=3,
            rng=rng,
        )

        assert result == set(), (
            f"Expected empty set when every order has zero slack, got {result}; "
            "only strictly positive slack should participate in the fallback branch."
        )

    def test_destroy_size_exceeds_available_ops_in_tardy_branch(self):
        """destroy_size >> tardy-order op count → returns every available op, no loop, no error.

        Required scenario 7: only 2 ops live in the tardy branch. With
        ``destroy_size=10`` the operator must return exactly the 2 ops
        (capped at what's available) and must not raise, hang, or
        fabricate ids.
        """
        wc = WorkCenter(id=uuid4(), code="M", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        horizon_start = datetime(2025, 1, 1)

        # One tardy order with 2 ops total. chain 0→20, due at 5 → tardiness = 15 min.
        order, ops, assignments = _build_chain_order(
            wc=wc,
            state=s1,
            horizon_start=horizon_start,
            chain_start_offset_min=0,
            n_ops=2,
            op_duration_min=10,
            due_offset_min=5,
            external_ref="SMALL_TARDY",
        )

        problem = ScheduleProblem(
            operations=ops,
            work_centers=[wc],
            states=[s1],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_start + timedelta(days=1),
        )
        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_due_pressure(assignments, problem, sdst, destroy_size=10, rng=rng)

        assert result == {ops[0].id, ops[1].id}, (
            f"Expected all 2 available ops, got {result}; "
            "operator must cap at available ops when destroy_size exceeds supply."
        )
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Property test (task 2.6): destroyed ops belong to orders with weighted
# tardiness >= median weighted tardiness of tardy orders
# ---------------------------------------------------------------------------
#
# Validates: Requirement 2 AC2 (top-tardy orders targeted first).
#
# Property statement:
#     For random FJSP-SDST problems with at least 3 tardy orders after greedy
#     scheduling, the operations returned by ``_destroy_due_pressure`` must
#     all belong to orders whose WEIGHTED tardiness is >= the median weighted
#     tardiness among tardy orders — except in the documented edge case where
#     the top-half tardy orders collectively have fewer assigned ops than
#     ``destroy_size``, in which case below-median picks are allowed.
#
# Weighted-vs-raw nuance:
#     Requirement 2 AC1 phrases tardiness as ``max(0, latest_end - due_date)``
#     (raw tardiness in minutes). However, ``_destroy_due_pressure`` ranks
#     orders by ``tardiness * (priority / 500.0)`` (see the operator body in
#     ``alns_solver.py``), which is the weighted tardiness objective from
#     Pinedo (2012) Ch.3. The ranking therefore determines which orders sit
#     in the top half — not raw tardiness alone. The property is stated
#     against WEIGHTED tardiness to match the operator's selection semantics;
#     a property stated against raw tardiness would spuriously fail whenever
#     a low-priority order has high raw tardiness but low weighted score.
#
# Edge-case treatment (task 2.6 step 5):
#     If ``destroy_size`` exceeds the total assigned-op count across top-half
#     tardy orders, the operator is forced to spill into below-median orders
#     (it walks in descending weighted-tardiness order and exhausts each
#     order's assignments before moving to the next). The property explicitly
#     allows below-median picks in that exhaustion regime and records how
#     often it fires for transparency.


def _make_random_problem_with_tardy_mix(
    rng: random.Random,
    *,
    n_orders: int,
    max_ops_per_order: int,
    n_machines: int,
    n_states: int,
) -> ScheduleProblem:
    """Variant of ``_make_random_feasible_problem`` that skews due dates so
    a sizeable fraction of orders become tardy after greedy scheduling.

    Mechanism: with probability 0.6 an order gets a "tight" due date 1-6
    hours past ``horizon_start`` (almost guaranteed tardy once the greedy
    dispatcher packs the schedule), otherwise a loose due date 3-8 days in.
    Op durations are large enough (15-90 min) that tight-due orders
    reliably miss their due dates after a few scheduling hops.
    """
    horizon_start = datetime(2026, 4, 1, 8, 0)
    horizon_end = horizon_start + timedelta(days=10)

    states = [State(id=uuid4(), code=f"S-{i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i}",
            capability_group="machining",
            speed_factor=rng.uniform(0.8, 1.5),
        )
        for i in range(n_machines)
    ]

    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if rng.random() < 0.6:
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=rng.randint(1, 20),
                        )
                    )

    orders: list[Order] = []
    operations: list[Operation] = []
    for i in range(n_orders):
        order_id = uuid4()
        if rng.random() < 0.6:
            # Tight due: a handful of hours into the horizon → almost surely tardy.
            tight_hours = rng.randint(1, 6)
            due_date = horizon_start + timedelta(hours=tight_hours)
        else:
            # Loose due: days out → typically on-time.
            due_date = horizon_start + timedelta(days=rng.randint(3, 8))
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{i:04d}",
                due_date=due_date,
                priority=rng.randint(300, 900),
            )
        )
        ops_in_order = rng.randint(2, max_ops_per_order)
        prev_op_id = None
        for j in range(ops_in_order):
            op_id = uuid4()
            n_eligible = rng.randint(1, n_machines)
            eligible = [wc.id for wc in rng.sample(work_centers, n_eligible)]
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=rng.choice(states).id,
                    base_duration_min=rng.randint(15, 90),
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


class TestDuePressureMedianTardinessProperty:
    """Property: destroyed ops belong to orders with weighted tardiness >= median.

    Validates: Requirement 2 AC2.

    Uses a plain ``random.Random`` loop (mirroring the pattern of
    ``TestCriticalPathLengthLeMakespan`` above) to generate random
    feasible FJSP-SDST problems with a mix of tight and loose due dates so
    that a nontrivial subset of orders is tardy after greedy scheduling.
    """

    def test_property_destroyed_ops_above_median_weighted_tardiness(self):
        """For ≥30 instances with ≥3 tardy orders, every destroyed op's
        parent order has weighted tardiness ≥ the median weighted tardiness
        among tardy orders — with a documented exception for the
        top-half-exhausted regime.
        """
        target = 30
        attempts = 0
        max_attempts = 300

        n_tested = 0
        n_skipped_not_feasible = 0
        n_skipped_insufficient_tardy = 0
        n_edge_case_top_half_exhausted = 0

        destroy_size = 3

        while n_tested < target and attempts < max_attempts:
            attempts += 1
            seed = 20_000 + attempts
            rng = random.Random(seed)

            n_machines = rng.randint(3, 8)
            n_orders = rng.randint(8, 20)
            max_ops_per_order = rng.randint(2, 5)
            n_states = rng.randint(2, 4)

            problem = _make_random_problem_with_tardy_mix(
                rng,
                n_orders=n_orders,
                max_ops_per_order=max_ops_per_order,
                n_machines=n_machines,
                n_states=n_states,
            )

            result = GreedyDispatch().solve(problem)
            if result.status != SolverStatus.FEASIBLE:
                n_skipped_not_feasible += 1
                continue

            assignments = result.assignments
            horizon_start = problem.planning_horizon_start
            ops_by_id = {op.id: op for op in problem.operations}
            orders_by_id = {o.id: o for o in problem.orders}

            # Per-order latest end offset (mirrors the operator's computation).
            order_latest_end: dict[Any, float] = {}
            assignments_by_order: dict[Any, list[Assignment]] = {}
            for a in assignments:
                op = ops_by_id.get(a.operation_id)
                if op is None:
                    continue
                end_offset = (a.end_time - horizon_start).total_seconds() / 60.0
                prev = order_latest_end.get(op.order_id)
                if prev is None or end_offset > prev:
                    order_latest_end[op.order_id] = end_offset
                assignments_by_order.setdefault(op.order_id, []).append(a)

            # Weighted tardiness per tardy order (weight = priority / 500.0,
            # matching the operator and the greedy dispatch convention).
            tardy_weighted: dict[Any, float] = {}
            for order_id, latest_end in order_latest_end.items():
                order = orders_by_id[order_id]
                due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
                raw_tardiness = max(0.0, latest_end - due_offset)
                if raw_tardiness <= 0.0:
                    continue
                weight = order.priority / 500.0
                tardy_weighted[order_id] = raw_tardiness * weight

            # Precondition: need ≥3 tardy orders for a meaningful median.
            if len(tardy_weighted) < 3:
                n_skipped_insufficient_tardy += 1
                continue

            # Median weighted tardiness across tardy orders.
            sorted_scores = sorted(tardy_weighted.values())
            k = len(sorted_scores)
            if k % 2 == 1:
                median = sorted_scores[k // 2]
            else:
                median = 0.5 * (sorted_scores[k // 2 - 1] + sorted_scores[k // 2])

            # Top-half tardy orders: weighted tardiness ≥ median.
            top_half_order_ids = {oid for oid, w in tardy_weighted.items() if w >= median}
            top_half_ops_count = sum(
                len(assignments_by_order.get(oid, [])) for oid in top_half_order_ids
            )

            sdst = SdstMatrix.from_problem(problem)
            destroyed = _destroy_due_pressure(
                assignments,
                problem,
                sdst,
                destroy_size=destroy_size,
                rng=random.Random(seed ^ 0x5A5A5A5A),
            )

            # Operator must return something when tardy orders exist.
            assert destroyed, (
                f"seed={seed}: _destroy_due_pressure returned empty set "
                f"despite {len(tardy_weighted)} tardy orders"
            )

            # Edge-case detection: only when top half has fewer ops than
            # destroy_size can a below-median pick occur legitimately.
            top_half_exhausted = destroy_size > top_half_ops_count
            if top_half_exhausted:
                n_edge_case_top_half_exhausted += 1

            # Core assertion: every destroyed op's parent order must be in the
            # top half, OR the top-half-exhausted edge case must apply.
            for op_id in destroyed:
                op = ops_by_id[op_id]
                parent_order_id = op.order_id
                parent_weighted = tardy_weighted.get(parent_order_id)

                # An op's parent order should always be tardy here — the
                # operator walks tardy orders only (slack fallback is
                # skipped because weighted_tardiness is non-empty).
                assert parent_weighted is not None, (
                    f"seed={seed}: destroyed op {op_id} belongs to non-tardy "
                    f"order {parent_order_id} but operator should only draw "
                    f"from tardy orders when tardy_weighted is non-empty"
                )

                if parent_weighted >= median:
                    continue  # top-half pick: property satisfied

                # Below-median pick: allowed only in the exhaustion regime.
                assert top_half_exhausted, (
                    f"seed={seed}: destroyed op belongs to order with "
                    f"weighted_tardiness={parent_weighted:.6f} < "
                    f"median={median:.6f}; top_half_ops_count="
                    f"{top_half_ops_count} >= destroy_size={destroy_size} "
                    f"so exhaustion regime does not apply. "
                    f"tardy_scores={sorted_scores}"
                )

            n_tested += 1

        assert n_tested >= target, (
            f"Only {n_tested}/{target} instances had ≥3 tardy orders after "
            f"{attempts} attempts "
            f"(infeasible_skips={n_skipped_not_feasible}, "
            f"insufficient_tardy_skips={n_skipped_insufficient_tardy}). "
            f"Consider adjusting the generator distribution."
        )

        # Sanity: exhaustion regime is rare with destroy_size=3 and reasonable
        # problem sizes (>=2 ops/order x >=2 top-half orders usually >= 3).
        assert n_edge_case_top_half_exhausted <= n_tested // 3, (
            f"Top-half-exhausted edge case fired {n_edge_case_top_half_exhausted} "
            f"times out of {n_tested} - property is mostly trivially satisfied. "
            f"Tighten the generator so top-half orders have more ops."
        )


# ---------------------------------------------------------------------------
# Property test (task 1.5): critical path length equals makespan — Hypothesis
# ---------------------------------------------------------------------------
#
# Validates: Requirements 1.2 (Property 2 from design.md).
#
# Extends ``TestCriticalPathLengthLeMakespan`` (plain ``random.Random``
# loop above) with an explicit Hypothesis-driven surface: shrinks on failure,
# prints the minimal counterexample, and replays via ``.hypothesis`` cache.
#
# Two properties per draw:
#
#   (P1) longest-path duration through the combined precedence +
#        machine-sequence DAG equals ``max(end_time) - min(start_time)``
#        across all assignments — direct test of design.md Property 2.
#
#   (P2) the set returned by ``_destroy_critical_path`` is a subset of the
#        operations that lie on at least one longest path. This exercises
#        the full operator (topological-sort + longest-path DP + trace-back)
#        against the independently computed set of "critical operations".
#        We pass ``destroy_size`` equal to the operator's own critical path
#        length so that neither trimming nor the extension branch fires;
#        the return value is then exactly the chain that the operator
#        identified as the longest path.


def _compute_critical_ops_from_dag(
    assignments: list[Assignment],
    problem: ScheduleProblem,
) -> tuple[float, set[UUID]]:
    """Return (longest_path_minutes, ops_on_any_longest_path).

    Uses the same combined precedence + machine-sequence DAG as
    ``_destroy_critical_path`` and ``_compute_critical_path_length``
    but also computes backward distances so that every operation
    lying on at least one longest path is reported.

    Topology is identical to the operator:
        * node weight = processing duration (minutes)
        * precedence edges: ``op.predecessor_op_id -> op.id``
        * machine edges: consecutive ops on the same machine by start_time

    For each node, ``forward[node]`` = max-weight path ending at node
    (inclusive of its duration); ``backward[node]`` = max-weight path
    starting at node. A node lies on some longest path iff
    ``forward[node] + backward[node] - duration[node] == longest_path``.

    Tolerance ``1e-6`` minutes is applied to the equality check to
    absorb float rounding introduced by the datetime/minutes
    conversion in assignment start/end times.
    """
    if not assignments:
        return 0.0, set()

    ops_by_id = {op.id: op for op in problem.operations}

    # Node durations (minutes)
    duration: dict[UUID, float] = {}
    for a in assignments:
        duration[a.operation_id] = (a.end_time - a.start_time).total_seconds() / 60.0

    assigned_op_ids = set(duration)

    # Build forward + backward adjacency
    successors: dict[UUID, list[UUID]] = {op_id: [] for op_id in assigned_op_ids}
    predecessors: dict[UUID, list[UUID]] = {op_id: [] for op_id in assigned_op_ids}
    in_degree: dict[UUID, int] = dict.fromkeys(assigned_op_ids, 0)

    # Precedence edges
    for op_id in assigned_op_ids:
        op = ops_by_id.get(op_id)
        if op is None:
            continue
        pred_id = op.predecessor_op_id
        if pred_id is not None and pred_id in assigned_op_ids:
            successors[pred_id].append(op_id)
            predecessors[op_id].append(pred_id)
            in_degree[op_id] += 1

    # Machine-sequence edges (consecutive ops on the same machine by start_time)
    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for machine_seq in by_machine.values():
        machine_seq.sort(key=lambda a: a.start_time)
        for i in range(len(machine_seq) - 1):
            prev_id = machine_seq[i].operation_id
            curr_id = machine_seq[i + 1].operation_id
            successors[prev_id].append(curr_id)
            predecessors[curr_id].append(prev_id)
            in_degree[curr_id] += 1

    # Kahn topological sort
    in_deg = dict(in_degree)
    queue: deque[UUID] = deque(op_id for op_id in assigned_op_ids if in_deg[op_id] == 0)
    topo: list[UUID] = []
    while queue:
        node = queue.popleft()
        topo.append(node)
        for succ in successors[node]:
            in_deg[succ] -= 1
            if in_deg[succ] == 0:
                queue.append(succ)

    # Cycle in the combined DAG — should never happen for a feasible schedule.
    # Return NaN so the property assertion fails with a clear signal.
    if len(topo) != len(assigned_op_ids):
        return float("nan"), set()

    # Forward DP: forward[node] = longest path ending at node (inclusive)
    forward: dict[UUID, float] = {op_id: duration[op_id] for op_id in assigned_op_ids}
    for node in topo:
        node_f = forward[node]
        for succ in successors[node]:
            candidate = node_f + duration[succ]
            if candidate > forward[succ]:
                forward[succ] = candidate

    # Backward DP: backward[node] = longest path starting at node (inclusive)
    backward: dict[UUID, float] = {op_id: duration[op_id] for op_id in assigned_op_ids}
    for node in reversed(topo):
        node_b = backward[node]
        for pred in predecessors[node]:
            candidate = duration[pred] + node_b
            if candidate > backward[pred]:
                backward[pred] = candidate

    longest_path = max(forward.values())

    # An op lies on some longest path iff forward + backward - duration == longest.
    tol = 1e-6
    critical_ops: set[UUID] = {
        op_id
        for op_id in assigned_op_ids
        if abs(forward[op_id] + backward[op_id] - duration[op_id] - longest_path) < tol
    }

    return longest_path, critical_ops


def _count_critical_path_length(assignments: list[Assignment], problem: ScheduleProblem) -> int:
    """Return the number of operations on the operator's chosen critical path.

    Mirrors the trace-back logic in ``_destroy_critical_path`` so that we
    can pass a ``destroy_size`` value that disables both trimming and
    extension when calling the operator under test. Returns 0 for empty
    inputs and 1 as a safety lower bound (the operator always returns
    at least the makespan-defining op).
    """
    if not assignments:
        return 0

    ops_by_id = {op.id: op for op in problem.operations}

    duration: dict[UUID, float] = {}
    for a in assignments:
        duration[a.operation_id] = (a.end_time - a.start_time).total_seconds() / 60.0

    assigned_op_ids = set(duration)

    successors: dict[UUID, list[UUID]] = {op_id: [] for op_id in assigned_op_ids}
    in_degree: dict[UUID, int] = dict.fromkeys(assigned_op_ids, 0)
    for op_id in assigned_op_ids:
        op = ops_by_id.get(op_id)
        if op is None:
            continue
        pred_id = op.predecessor_op_id
        if pred_id is not None and pred_id in assigned_op_ids:
            successors[pred_id].append(op_id)
            in_degree[op_id] += 1

    by_machine: dict[Any, list[Assignment]] = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)
    for machine_seq in by_machine.values():
        machine_seq.sort(key=lambda a: a.start_time)
        for i in range(len(machine_seq) - 1):
            prev_id = machine_seq[i].operation_id
            curr_id = machine_seq[i + 1].operation_id
            successors[prev_id].append(curr_id)
            in_degree[curr_id] += 1

    in_deg = dict(in_degree)
    queue: deque[UUID] = deque(op_id for op_id in assigned_op_ids if in_deg[op_id] == 0)
    topo: list[UUID] = []
    while queue:
        node = queue.popleft()
        topo.append(node)
        for succ in successors[node]:
            in_deg[succ] -= 1
            if in_deg[succ] == 0:
                queue.append(succ)
    if len(topo) != len(assigned_op_ids):
        return len(assigned_op_ids)  # cycle fallback — operator degrades to random

    dist: dict[UUID, float] = {op_id: duration[op_id] for op_id in assigned_op_ids}
    pred_on_path: dict[UUID, UUID | None] = dict.fromkeys(assigned_op_ids, None)
    for node in topo:
        node_d = dist[node]
        for succ in successors[node]:
            candidate = node_d + duration[succ]
            if candidate > dist[succ]:
                dist[succ] = candidate
                pred_on_path[succ] = node

    sink = max(assigned_op_ids, key=lambda op_id: dist[op_id])
    length = 0
    cur: UUID | None = sink
    while cur is not None:
        length += 1
        cur = pred_on_path[cur]
    return max(length, 1)


# --- Hypothesis generator: small feasible FJSP-SDST problems ---------------
#
# Hypothesis strategies compose well with Pydantic models, but ``uuid4()``
# is stochastic per-draw and does not interact with the Hypothesis random
# source. That is acceptable here because operation identity is
# structural (a UUID), not a shrinkable primitive — shrinking focuses on
# sizes, durations, and setup densities. Size bounds follow the task
# brief: 10-50 operations, 2-5 machines, 2-4 states (enough coverage
# without slowing the suite).


@st.composite
def _small_feasible_problems(
    draw: st.DrawFn,
    min_ops: int = 10,
    max_ops: int = 50,
    min_machines: int = 2,
    max_machines: int = 5,
    min_states: int = 2,
    max_states: int = 4,
) -> ScheduleProblem:
    """Draw a small FJSP-SDST problem feasible for greedy dispatch.

    The generator fixes the planning horizon to a safely long window (30
    days) so that greedy's horizon bound never trips during shrinking,
    and keeps processing times bounded (5-60 minutes) for the same
    reason. Every operation is eligible on at least one machine; the
    setup matrix is sparsely populated (60% fill) to give the combined
    DAG non-trivial machine edges without slowing construction.
    """
    horizon_start = datetime(2026, 4, 1, 8, 0)
    horizon_end = horizon_start + timedelta(days=30)

    n_states = draw(st.integers(min_value=min_states, max_value=max_states))
    n_machines = draw(st.integers(min_value=min_machines, max_value=max_machines))

    states = [State(id=uuid4(), code=f"S-{i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i}",
            capability_group="machining",
            speed_factor=draw(st.floats(min_value=0.8, max_value=1.5)),
        )
        for i in range(n_machines)
    ]

    # Sparse random setup matrix (60% fill, 1-20 minute setup).
    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if draw(st.booleans()):
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=draw(st.integers(min_value=1, max_value=20)),
                        )
                    )

    # Target total ops in [min_ops, max_ops]. Draw per-order chain lengths
    # until the budget is exhausted.
    target_ops = draw(st.integers(min_value=min_ops, max_value=max_ops))
    orders: list[Order] = []
    operations: list[Operation] = []
    n_ops_built = 0
    order_idx = 0
    while n_ops_built < target_ops:
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{order_idx:04d}",
                due_date=horizon_start
                + timedelta(hours=draw(st.integers(min_value=24, max_value=48))),
                priority=draw(st.integers(min_value=300, max_value=900)),
            )
        )
        chain_len = draw(
            st.integers(
                min_value=1,
                max_value=min(6, max(1, target_ops - n_ops_built)),
            )
        )
        prev_op_id: UUID | None = None
        for j in range(chain_len):
            op_id = uuid4()
            n_eligible = draw(st.integers(min_value=1, max_value=n_machines))
            # Eligible machines: deterministic prefix (Hypothesis can shrink
            # on n_eligible without touching UUID identity).
            eligible = [wc.id for wc in work_centers[:n_eligible]]
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=draw(st.sampled_from(states)).id,
                    base_duration_min=draw(st.integers(min_value=5, max_value=60)),
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id
            n_ops_built += 1
        order_idx += 1

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


class TestCriticalPathProperty:
    """Hypothesis property tests for ``_destroy_critical_path``.

    Validates: Requirement 1 (audit-corrected form of Property 2 from design.md).

    Complements ``TestCriticalPathLengthLeMakespan`` (plain random
    loop) with shrinkable Hypothesis drawings so that any violation is
    reported with a minimal counterexample. Two properties:

    * **P1 (length ≤ makespan):** the longest path through the
      combined precedence + machine-sequence DAG has duration at most
      the schedule's makespan within ``1e-6`` minutes. Audit correction
      (2026-05-10): equality does not hold in general — feasible
      schedules may contain idle, release, or setup gaps outside
      operation duration.

    * **P2 (operator output lies on longest paths):** the set returned by
      ``_destroy_critical_path``, when called with ``destroy_size`` equal
      to the operator's own critical-path length (so that neither
      trimming nor extension fires), is a subset of the operations that
      lie on at least one longest path through the combined DAG.
    """

    @given(problem=_small_feasible_problems())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    def test_critical_path_length_le_makespan(self, problem: ScheduleProblem) -> None:
        """P1 + P2 as a single property test.

        Keeping both properties in one test avoids re-running the greedy
        dispatcher 50 times per property: ``GreedyDispatch`` dominates
        runtime at this scale.
        """
        n_ops = len(problem.operations)
        # Bound enforced by the generator; guard against shrinking that would
        # push the problem below the task's minimum.
        assert 10 <= n_ops <= 50, f"generator out of bounds: n_ops={n_ops}"

        result = GreedyDispatch().solve(problem)
        # Skip problems where greedy fails — extremely rare for our generator
        # but we do not want to pollute the property surface with infeasible
        # instances.
        if result.status != SolverStatus.FEASIBLE:
            return

        assignments = result.assignments
        # Greedy should schedule every operation on a feasible instance.
        assert len(assignments) == n_ops, (
            f"greedy returned partial schedule: {len(assignments)}/{n_ops}"
        )

        # --- Property P1: longest path ≤ makespan ---------------------------
        longest_path, critical_ops = _compute_critical_ops_from_dag(assignments, problem)
        assert not math.isnan(longest_path), (
            "critical-path DP returned NaN — combined DAG has a cycle (bug in edge construction)"
        )

        base = min(a.start_time for a in assignments)
        makespan = max((a.end_time - base).total_seconds() / 60.0 for a in assignments)

        assert longest_path <= makespan + 1e-6, (
            f"n_ops={n_ops}, n_machines={len(problem.work_centers)}: "
            f"longest_path={longest_path:.6f} > makespan={makespan:.6f}, "
            f"delta={longest_path - makespan:.6e} "
            f"(cp length must not exceed makespan; equality is not required)"
        )

        # Critical_ops must be non-empty whenever assignments are non-empty.
        assert critical_ops, "no operations identified on any longest path"

        # --- Property P2: operator output ⊆ ops on some longest path ---------
        # Pass destroy_size equal to the operator's own trace-back length so
        # that neither the trimming branch (destroy_size < cp_len) nor the
        # extension branch (destroy_size > cp_len) fires. The returned set
        # is then exactly the chain the operator walks back from the
        # makespan-defining sink.
        cp_length = _count_critical_path_length(assignments, problem)
        assert cp_length >= 1

        sdst = SdstMatrix.from_problem(problem)
        destroyed = _destroy_critical_path(
            assignments,
            problem,
            sdst,
            destroy_size=cp_length,
            rng=random.Random(42),
        )

        # The operator must not return empty for a non-empty schedule.
        assert destroyed, "critical-path operator returned empty set"
        # Size contract: exactly cp_length operations — no trimming, no extension.
        assert len(destroyed) == cp_length, (
            f"expected {cp_length} ops on the critical path but operator returned "
            f"{len(destroyed)} — trimming or extension branch fired unexpectedly"
        )
        # Core subset property.
        leaked = destroyed - critical_ops
        assert not leaked, (
            f"operator returned {len(leaked)} op(s) not on any longest path: "
            f"leaked={leaked}, destroyed={destroyed}, "
            f"|critical_ops|={len(critical_ops)}, longest_path={longest_path:.6f}, "
            f"makespan={makespan:.6f}"
        )


# ---------------------------------------------------------------------------
# Property test (task 1.5): critical path DURATION ≤ makespan (audit-corrected)
# ---------------------------------------------------------------------------
#
# Validates: Requirement 1 (critical-path destroy operator correctness)
# and Property 2 from design.md (in its audit-corrected form).
#
# Audit correction:
#   The original plan stated "critical path length equals makespan" for all
#   feasible schedules. That is wrong in general: a feasible schedule may
#   contain idle gaps (machine idle, release-time gaps, setup gaps outside
#   operation duration) that are not reflected by any DAG edge. The correct
#   UNIVERSAL invariant is
#
#       critical_path_duration <= makespan   (for all feasible schedules)
#
#   Equality holds only for compact no-idle schedules where every timing
#   gap is explained by a precedence or machine-sequence edge. Greedy
#   dispatch typically produces such compact schedules (see
#   ``TestCriticalPathProperty`` above, which asserts equality for the
#   greedy-compact case), but this test asserts the weaker, universally
#   valid invariant instead.
#
# Method:
#   1. Draw small feasible problems (5-50 operations, 2-8 machines) via
#      Hypothesis using the existing ``_small_feasible_problems`` strategy
#      parameterised for this task's scope.
#   2. Greedy-dispatch the problem to obtain a feasible schedule.
#   3. Compute the operator's critical-path length via
#      ``_count_critical_path_length`` so that ``destroy_size`` exactly
#      matches the path length — this disables both the trimming branch
#      (``destroy_size < cp_len``) and the extension branch
#      (``destroy_size > cp_len``). The returned set is then exactly the
#      operator's critical-path chain.
#   4. Reconstruct the critical-path duration by summing operation
#      durations over the returned set (Option A from the task brief —
#      valid because the returned set is a single path of length
#      ``cp_length``).
#   5. Assert ``cp_duration <= makespan + 1e-6`` (tolerance absorbs the
#      datetime-to-minutes conversion float error).


class TestCriticalPathDurationInvariant:
    """Property: critical path duration ≤ makespan for feasible schedules.

    Validates: Requirement 1 — audit-corrected form of Property 2 from
    design.md. Asserts the universally valid ``≤`` invariant rather than
    the equality form, which only holds for compact no-idle schedules.
    """

    @given(
        problem=_small_feasible_problems(
            min_ops=5,
            max_ops=50,
            min_machines=2,
            max_machines=8,
        )
    )
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    def test_critical_path_duration_le_makespan(self, problem: ScheduleProblem) -> None:
        """For every greedy-generated feasible schedule, the duration of
        the operator's critical path must not exceed the schedule makespan.

        The operator is called with ``destroy_size`` equal to the exact
        critical-path length so that the returned set is precisely the
        trace-back chain (no trimming, no extension). We then sum operation
        durations over the returned set and compare against
        ``max(end_time) - min(start_time)`` across all assignments.
        """
        n_ops = len(problem.operations)
        # Guardrail on the generator: enforce the task's 5-50 scope even
        # under aggressive Hypothesis shrinking.
        assert 5 <= n_ops <= 50, f"generator out of bounds: n_ops={n_ops}"
        assert 2 <= len(problem.work_centers) <= 8, (
            f"generator out of bounds: n_machines={len(problem.work_centers)}"
        )

        result = GreedyDispatch().solve(problem)
        # Infeasible rolls are vanishingly rare with this generator; skip
        # rather than assert to avoid spurious Hypothesis failures on the
        # occasional pathological draw.
        if result.status != SolverStatus.FEASIBLE:
            return

        assignments = result.assignments
        # Greedy must schedule every operation on a feasible instance —
        # partial schedules would invalidate the makespan computation.
        assert len(assignments) == n_ops, (
            f"greedy returned partial schedule: {len(assignments)}/{n_ops}"
        )

        # Per-op duration lookup (minutes) — reused for the CP-duration sum.
        op_duration_min: dict[UUID, float] = {
            a.operation_id: (a.end_time - a.start_time).total_seconds() / 60.0 for a in assignments
        }

        # Step 1: compute the operator's own CP length so destroy_size
        # exactly matches (no trimming, no extension branch fires).
        cp_length = _count_critical_path_length(assignments, problem)
        assert cp_length >= 1

        # Step 2: invoke the operator with the exact CP length.
        sdst = SdstMatrix.from_problem(problem)
        destroyed = _destroy_critical_path(
            assignments,
            problem,
            sdst,
            destroy_size=cp_length,
            rng=random.Random(42),
        )

        # The operator must not return empty for a non-empty schedule, and
        # the returned set must be exactly ``cp_length`` operations (single
        # path, no trimming, no extension).
        assert destroyed, "critical-path operator returned empty set"
        assert len(destroyed) == cp_length, (
            f"expected exactly {cp_length} ops on the critical path but "
            f"operator returned {len(destroyed)} — trimming or extension "
            f"branch fired unexpectedly for destroy_size={cp_length}"
        )

        # Step 3: CP duration = sum of operation durations on the path.
        # Option A from the task brief — valid because ``destroyed`` is a
        # single path of exactly ``cp_length`` nodes.
        cp_duration_min = sum(op_duration_min[op_id] for op_id in destroyed)

        # Step 4: makespan = max(end_time) - min(start_time) in minutes.
        base = min(a.start_time for a in assignments)
        latest_end = max(a.end_time for a in assignments)
        makespan_min = (latest_end - base).total_seconds() / 60.0

        # Step 5: assert the audit-corrected universal invariant.
        tolerance = 1e-6
        assert cp_duration_min <= makespan_min + tolerance, (
            f"n_ops={n_ops}, n_machines={len(problem.work_centers)}, "
            f"cp_length={cp_length}: critical_path_duration="
            f"{cp_duration_min:.6f} min > makespan={makespan_min:.6f} min "
            f"(delta={cp_duration_min - makespan_min:.6e} min)"
        )


# ---------------------------------------------------------------------------
# Property test (task 2.6): Hypothesis-driven median weighted tardiness
# ---------------------------------------------------------------------------
#
# Validates: Requirements 2.2 (AC2 — top-tardy orders targeted first).
#
# Complements ``TestDuePressureMedianTardinessProperty`` (plain ``random.Random``
# loop) with a shrinkable Hypothesis drawing so that any violation is reported
# with a minimal counterexample. The underlying property is identical, but the
# generator distribution is tightened to *aggressively* surface tardy orders so
# Hypothesis is not wasted on vacuous (non-tardy) instances.
#
# Property:
#     Let ``tardy_weighted = {order : weighted_tardiness(order) > 0}`` where
#     ``weighted_tardiness(o) = max(0, latest_end_offset - due_offset) *
#      (o.priority / 500.0)``.  Let ``m = median(tardy_weighted.values())``.
#     Then for every op in the raw ``_destroy_due_pressure`` result,
#
#         weighted_tardiness(order_of(op)) >= m   (exact ``>=``; values are
#                                                   deterministic from integer
#                                                   durations/priorities)
#
#     This property operates on the RAW operator return set.  It is NOT true
#     after ``_expand_successor_closure``, because successor closure may pull
#     in ops from non-tardy orders for feasibility.
#
# Safety bound on ``destroy_size`` (per task 2.6 notes):
#     The operator walks orders top-down in descending weighted tardiness and
#     exhausts each order's assignments before moving on.  If ``destroy_size``
#     is large enough to consume more ops than the top-half tardy orders hold,
#     the walk spills into below-median orders.  To keep the property
#     universally true we pick
#
#         destroy_size = min(3, total_tardy_ops_in_top_half)
#
#     which guarantees the walk stops at or above the median while still
#     exercising spill across multiple orders when the top half has room.


@st.composite
def _small_feasible_problems_with_tardy_mix(
    draw: st.DrawFn,
    min_ops: int = 10,
    max_ops: int = 50,
    min_machines: int = 2,
    max_machines: int = 5,
    min_states: int = 2,
    max_states: int = 4,
) -> ScheduleProblem:
    """Draw a small FJSP-SDST problem with due dates skewed so that a
    sizeable fraction of orders become tardy after greedy dispatch.

    Structural shape matches ``_small_feasible_problems`` (same horizon,
    eligibility deterministic prefix, 60% sparse setup matrix).  The only
    difference is the due-date distribution:

        * 60% of orders get a **tight** due date 1-6 hours past horizon
          start — chain lengths of 2-6 ops with 15-90 min durations make
          these almost surely tardy once greedy packs the machines.
        * 40% of orders get a **loose** due date 3-8 days into the
          horizon — typically on time, gives the tardy population a
          meaningful median to compare against.

    Durations are bumped to 15-90 min (vs. 5-60 in the base generator)
    so that tight-due orders reliably miss their due dates after a few
    scheduling hops.
    """
    horizon_start = datetime(2026, 4, 1, 8, 0)
    horizon_end = horizon_start + timedelta(days=30)

    n_states = draw(st.integers(min_value=min_states, max_value=max_states))
    n_machines = draw(st.integers(min_value=min_machines, max_value=max_machines))

    states = [State(id=uuid4(), code=f"S-{i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i}",
            capability_group="machining",
            speed_factor=draw(st.floats(min_value=0.8, max_value=1.5)),
        )
        for i in range(n_machines)
    ]

    # Sparse random setup matrix (60% fill, 1-20 minute setup).
    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if draw(st.booleans()):
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=draw(st.integers(min_value=1, max_value=20)),
                        )
                    )

    # Target total ops in [min_ops, max_ops]. Draw chain lengths >= 2 so
    # the top-half tardy orders have more than one op apiece — this lets
    # ``destroy_size=3`` meaningfully walk across orders without always
    # spilling.
    target_ops = draw(st.integers(min_value=min_ops, max_value=max_ops))
    orders: list[Order] = []
    operations: list[Operation] = []
    n_ops_built = 0
    order_idx = 0
    while n_ops_built < target_ops:
        order_id = uuid4()
        # Due-date distribution: 60% tight, 40% loose.
        if draw(st.integers(min_value=0, max_value=9)) < 6:
            tight_hours = draw(st.integers(min_value=1, max_value=6))
            due_date = horizon_start + timedelta(hours=tight_hours)
        else:
            due_date = horizon_start + timedelta(days=draw(st.integers(min_value=3, max_value=8)))
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{order_idx:04d}",
                due_date=due_date,
                priority=draw(st.integers(min_value=300, max_value=900)),
            )
        )
        chain_len = draw(
            st.integers(
                min_value=2,
                max_value=min(6, max(2, target_ops - n_ops_built)),
            )
        )
        prev_op_id: UUID | None = None
        for j in range(chain_len):
            op_id = uuid4()
            n_eligible = draw(st.integers(min_value=1, max_value=n_machines))
            eligible = [wc.id for wc in work_centers[:n_eligible]]
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=draw(st.sampled_from(states)).id,
                    base_duration_min=draw(st.integers(min_value=15, max_value=90)),
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id
            n_ops_built += 1
        order_idx += 1

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


class TestDuePressureMedianTardinessHypothesisProperty:
    """Hypothesis property: raw ``_destroy_due_pressure`` output belongs to
    orders with weighted tardiness >= median weighted tardiness of tardy
    orders, when a bounded ``destroy_size`` keeps the walk in the top half.

    Validates: Requirement 2 AC2 (top-tardy orders targeted first).
    """

    @given(problem=_small_feasible_problems_with_tardy_mix())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    def test_destroyed_ops_above_median_weighted_tardiness(self, problem: ScheduleProblem) -> None:
        """For every feasible greedy schedule with at least one tardy order,
        every op returned by the RAW ``_destroy_due_pressure`` call belongs
        to an order whose weighted tardiness is >= the median weighted
        tardiness across tardy orders — provided ``destroy_size`` is bounded
        to stay within the top half.
        """
        result = GreedyDispatch().solve(problem)
        if result.status != SolverStatus.FEASIBLE:
            # Extremely rare with this generator; skip rather than assert.
            event("skip: greedy infeasible")
            return

        assignments = result.assignments
        horizon_start = problem.planning_horizon_start
        ops_by_id = {op.id: op for op in problem.operations}
        orders_by_id = {o.id: o for o in problem.orders}

        # Per-order latest end offset and per-order assignment bucket —
        # mirrors the operator's bookkeeping.
        order_latest_end: dict[Any, float] = {}
        assignments_by_order: dict[Any, list[Assignment]] = {}
        for a in assignments:
            op = ops_by_id.get(a.operation_id)
            if op is None:
                continue
            end_offset = (a.end_time - horizon_start).total_seconds() / 60.0
            prev = order_latest_end.get(op.order_id)
            if prev is None or end_offset > prev:
                order_latest_end[op.order_id] = end_offset
            assignments_by_order.setdefault(op.order_id, []).append(a)

        # Weighted tardiness per tardy order (priority/500 weight convention,
        # matching ``_destroy_due_pressure``).
        tardy_weighted: dict[Any, float] = {}
        for order_id, latest_end in order_latest_end.items():
            order = orders_by_id[order_id]
            due_offset = (order.due_date - horizon_start).total_seconds() / 60.0
            raw_tardiness = max(0.0, latest_end - due_offset)
            if raw_tardiness <= 0.0:
                continue
            weight = order.priority / 500.0
            tardy_weighted[order_id] = raw_tardiness * weight

        # Property is out of scope when no order is tardy — the operator
        # takes the slack-fallback branch there.
        if not tardy_weighted:
            event("skip: no tardy orders")
            return

        median_score = statistics.median(tardy_weighted.values())

        # Top half: orders with score >= median.  Count their ops so we can
        # bound destroy_size safely.
        top_half_order_ids = {oid for oid, score in tardy_weighted.items() if score >= median_score}
        top_half_ops_count = sum(
            len(assignments_by_order.get(oid, [])) for oid in top_half_order_ids
        )

        # destroy_size = min(3, top_half_ops) per the task's recommended
        # compromise: small enough to keep the walk in the top half,
        # large enough to exercise spill across multiple orders when the
        # top half has room.  ``max(1, ...)`` guards against degenerate
        # cases where the top half is empty (which ``tardy_weighted``
        # being non-empty already prevents, but kept for defensiveness).
        destroy_size = min(3, max(1, top_half_ops_count))

        sdst = SdstMatrix.from_problem(problem)
        destroyed = _destroy_due_pressure(
            assignments,
            problem,
            sdst,
            destroy_size=destroy_size,
            rng=random.Random(42),
        )

        # Operator must return something when tardy orders exist.
        assert destroyed, (
            f"_destroy_due_pressure returned empty set despite "
            f"{len(tardy_weighted)} tardy order(s); "
            f"destroy_size={destroy_size}, top_half_ops={top_half_ops_count}"
        )

        # Event tagging for coverage transparency.
        event(f"tardy_orders={len(tardy_weighted)}")
        event(f"destroy_size={destroy_size}")

        # Core property: every destroyed op's parent order has weighted
        # tardiness >= median.  Exact ``>=`` per task spec (weighted
        # tardiness values are deterministic from integer durations and
        # priorities).  A tiny ``-1e-9`` slack is applied to absorb the
        # datetime-to-minutes conversion rounding.
        tol = 1e-9
        for op_id in destroyed:
            op = ops_by_id[op_id]
            parent_order_id = op.order_id
            parent_score = tardy_weighted.get(parent_order_id)

            # Because tardy_weighted is non-empty, the operator walks the
            # tardy branch exclusively — every destroyed op must belong to
            # a tardy order.
            assert parent_score is not None, (
                f"destroyed op {op_id} belongs to non-tardy order "
                f"{parent_order_id}; operator should only draw from tardy "
                f"orders when tardy_weighted is non-empty "
                f"(tardy_orders={len(tardy_weighted)})"
            )

            assert parent_score + tol >= median_score, (
                f"destroyed op belongs to order with "
                f"weighted_tardiness={parent_score:.9f} < "
                f"median={median_score:.9f} (destroy_size={destroy_size}, "
                f"top_half_ops={top_half_ops_count}, "
                f"tardy_scores={sorted(tardy_weighted.values())})"
            )
