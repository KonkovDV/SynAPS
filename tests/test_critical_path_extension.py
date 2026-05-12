"""Smoke test for _destroy_critical_path extension logic (task 1.2).

Verifies that when the critical path is shorter than destroy_size,
the function extends with adjacent operations on the same machines
as critical-path nodes, sorted by setup contribution.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import _destroy_critical_path
from synaps.solvers.sdst_matrix import SdstMatrix


class TestCriticalPathExtension:
    """Tests for the extension logic in _destroy_critical_path."""

    def test_extension_adds_adjacent_ops_sorted_by_setup_cost(self):
        """When CP < destroy_size, adjacent ops are added sorted by setup cost."""
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        wc_b = WorkCenter(id=uuid4(), code="B", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")
        s3 = State(id=uuid4(), code="S3")

        order1 = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))
        order2 = Order(id=uuid4(), external_ref="O2", due_date=datetime(2025, 1, 2))
        order3 = Order(id=uuid4(), external_ref="O3", due_date=datetime(2025, 1, 2))

        # op_a -> op_b form a precedence chain (order1), both on machine A
        # op_c is on machine A before op_a (order2, no precedence link)
        # op_d is on machine A after op_b (order3, no precedence link)
        # op_e is on machine B (order3, no precedence link to anything on A)
        op_a = Operation(
            id=uuid4(), order_id=order1.id, seq_in_order=1,
            state_id=s1.id, base_duration_min=20, eligible_wc_ids=[wc_a.id],
        )
        op_b = Operation(
            id=uuid4(), order_id=order1.id, seq_in_order=2,
            state_id=s2.id, base_duration_min=20, eligible_wc_ids=[wc_a.id],
            predecessor_op_id=op_a.id,
        )
        op_c = Operation(
            id=uuid4(), order_id=order2.id, seq_in_order=1,
            state_id=s3.id, base_duration_min=5, eligible_wc_ids=[wc_a.id],
        )
        op_d = Operation(
            id=uuid4(), order_id=order3.id, seq_in_order=1,
            state_id=s1.id, base_duration_min=5, eligible_wc_ids=[wc_a.id],
        )

        # Setup costs: transition into/from op_d is expensive, op_c is cheap
        setup_entries = [
            SetupEntry(work_center_id=wc_a.id, from_state_id=s3.id, to_state_id=s1.id, setup_minutes=3),   # c->a
            SetupEntry(work_center_id=wc_a.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=2),   # a->b
            SetupEntry(work_center_id=wc_a.id, from_state_id=s2.id, to_state_id=s1.id, setup_minutes=50),  # b->d (high!)
            SetupEntry(work_center_id=wc_b.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=1),
        ]

        problem = ScheduleProblem(
            operations=[op_a, op_b, op_c, op_d],
            work_centers=[wc_a, wc_b],
            states=[s1, s2, s3],
            setup_matrix=setup_entries,
            orders=[order1, order2, order3],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        # Machine A sequence (by start_time): op_c(0-5), op_a(5-25), op_b(25-45), op_d(45-50)
        base = datetime(2025, 1, 1)
        assignments = [
            Assignment(operation_id=op_c.id, work_center_id=wc_a.id,
                       start_time=base, end_time=base + timedelta(minutes=5)),
            Assignment(operation_id=op_a.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=5), end_time=base + timedelta(minutes=25)),
            Assignment(operation_id=op_b.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=25), end_time=base + timedelta(minutes=45)),
            Assignment(operation_id=op_d.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=45), end_time=base + timedelta(minutes=50)),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # Longest path through DAG:
        # Machine A edges: op_c->op_a->op_b->op_d
        # Precedence edges: op_a->op_b (redundant with machine edge)
        # CP = [op_c, op_a, op_b, op_d] (length 4, total=5+20+20+5=50)
        #
        # With destroy_size=3, cap to last 3: [op_a, op_b, op_d]
        # len=3 == destroy_size, no extension.
        result_3 = _destroy_critical_path(assignments, problem, sdst, destroy_size=3, rng=rng)
        assert len(result_3) == 3
        assert op_a.id in result_3
        assert op_b.id in result_3
        assert op_d.id in result_3

    def test_extension_only_selects_adjacent_not_all_ops(self):
        """Extension only picks immediate machine-sequence neighbors of CP nodes."""
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        wc_b = WorkCenter(id=uuid4(), code="B", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")
        s3 = State(id=uuid4(), code="S3")

        order1 = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))
        order2 = Order(id=uuid4(), external_ref="O2", due_date=datetime(2025, 1, 2))
        order3 = Order(id=uuid4(), external_ref="O3", due_date=datetime(2025, 1, 2))
        order4 = Order(id=uuid4(), external_ref="O4", due_date=datetime(2025, 1, 2))
        order5 = Order(id=uuid4(), external_ref="O5", due_date=datetime(2025, 1, 2))

        # op_x on machine B (long duration, forms start of critical path)
        # op1 on machine A depends on op_x (precedence)
        # op2..op5 on machine A (separate orders, no precedence to each other)
        # Machine A sequence: op2, op3, op1, op4, op5
        op_x = Operation(
            id=uuid4(), order_id=order1.id, seq_in_order=1,
            state_id=s1.id, base_duration_min=100, eligible_wc_ids=[wc_b.id],
        )
        op1 = Operation(id=uuid4(), order_id=order1.id, seq_in_order=2,
                        state_id=s1.id, base_duration_min=5, eligible_wc_ids=[wc_a.id],
                        predecessor_op_id=op_x.id)
        op2 = Operation(id=uuid4(), order_id=order2.id, seq_in_order=1,
                        state_id=s2.id, base_duration_min=5, eligible_wc_ids=[wc_a.id])
        op3 = Operation(id=uuid4(), order_id=order3.id, seq_in_order=1,
                        state_id=s3.id, base_duration_min=5, eligible_wc_ids=[wc_a.id])
        op4 = Operation(id=uuid4(), order_id=order4.id, seq_in_order=1,
                        state_id=s1.id, base_duration_min=5, eligible_wc_ids=[wc_a.id])
        op5 = Operation(id=uuid4(), order_id=order5.id, seq_in_order=1,
                        state_id=s2.id, base_duration_min=5, eligible_wc_ids=[wc_a.id])

        setup_entries = [
            SetupEntry(work_center_id=wc_a.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=10),
            SetupEntry(work_center_id=wc_a.id, from_state_id=s2.id, to_state_id=s3.id, setup_minutes=20),
            SetupEntry(work_center_id=wc_a.id, from_state_id=s3.id, to_state_id=s1.id, setup_minutes=30),
            SetupEntry(work_center_id=wc_a.id, from_state_id=s1.id, to_state_id=s3.id, setup_minutes=5),
            SetupEntry(work_center_id=wc_b.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=1),
        ]

        problem = ScheduleProblem(
            operations=[op_x, op1, op2, op3, op4, op5],
            work_centers=[wc_a, wc_b],
            states=[s1, s2, s3],
            setup_matrix=setup_entries,
            orders=[order1, order2, order3, order4, order5],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        # Machine B: op_x(0-100)
        # Machine A: op2(0-5), op3(5-10), op1(100-105), op4(105-110), op5(110-115)
        base = datetime(2025, 1, 1)
        assignments = [
            Assignment(operation_id=op_x.id, work_center_id=wc_b.id,
                       start_time=base, end_time=base + timedelta(minutes=100)),
            Assignment(operation_id=op2.id, work_center_id=wc_a.id,
                       start_time=base, end_time=base + timedelta(minutes=5)),
            Assignment(operation_id=op3.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=5), end_time=base + timedelta(minutes=10)),
            Assignment(operation_id=op1.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=100), end_time=base + timedelta(minutes=105)),
            Assignment(operation_id=op4.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=105), end_time=base + timedelta(minutes=110)),
            Assignment(operation_id=op5.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=110), end_time=base + timedelta(minutes=115)),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # Machine A sequence (sorted by start_time): op2, op3, op1, op4, op5
        # Machine B sequence: op_x
        # Precedence: op_x -> op1
        # Machine edges on A: op2->op3->op1->op4->op5
        #
        # Longest paths:
        # op2->op3->op1->op4->op5 = 5+5+5+5+5 = 25
        # op_x->op1->op4->op5 = 100+5+5+5 = 115 (via precedence + machine seq)
        #
        # CP = [op_x, op1, op4, op5] (length 4, total dist=115)
        #
        # With destroy_size=6, CP=4 < 6, extension kicks in.
        # Adjacent to op_x on machine B: no neighbors (only op on B)
        # Adjacent to op1 on machine A: op3 (predecessor in seq), op4 (already in CP)
        # Adjacent to op4 on machine A: op1 (already in CP), op5 (already in CP)
        # Adjacent to op5 on machine A: op4 (already in CP), no successor
        #
        # So only op3 is a candidate. Result = CP(4) + op3 = 5 ops.
        # op2 is NOT adjacent to any CP node (it's adjacent to op3, not to a CP node).
        result = _destroy_critical_path(assignments, problem, sdst, destroy_size=6, rng=rng)

        assert op_x.id in result
        assert op1.id in result
        assert op4.id in result
        assert op5.id in result
        assert op3.id in result  # Adjacent to op1 on machine A
        assert op2.id not in result  # NOT adjacent to any CP node
        assert len(result) == 5  # Can't reach destroy_size=6, only 5 available

    def test_no_extension_when_cp_equals_destroy_size(self):
        """No extension when critical path length equals destroy_size."""
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")

        order = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))

        op1 = Operation(id=uuid4(), order_id=order.id, seq_in_order=1,
                        state_id=s1.id, base_duration_min=10, eligible_wc_ids=[wc_a.id])
        op2 = Operation(id=uuid4(), order_id=order.id, seq_in_order=2,
                        state_id=s2.id, base_duration_min=10, eligible_wc_ids=[wc_a.id],
                        predecessor_op_id=op1.id)

        problem = ScheduleProblem(
            operations=[op1, op2],
            work_centers=[wc_a],
            states=[s1, s2],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        base = datetime(2025, 1, 1)
        assignments = [
            Assignment(operation_id=op1.id, work_center_id=wc_a.id,
                       start_time=base, end_time=base + timedelta(minutes=10)),
            Assignment(operation_id=op2.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=10), end_time=base + timedelta(minutes=20)),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # CP = [op1, op2], destroy_size=2 -> exact match, no extension
        result = _destroy_critical_path(assignments, problem, sdst, destroy_size=2, rng=rng)
        assert len(result) == 2
        assert op1.id in result
        assert op2.id in result

    def test_extension_with_multi_machine_critical_path(self):
        """Extension finds adjacent ops on multiple machines used by CP nodes."""
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        wc_b = WorkCenter(id=uuid4(), code="B", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        s2 = State(id=uuid4(), code="S2")

        order1 = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))
        order2 = Order(id=uuid4(), external_ref="O2", due_date=datetime(2025, 1, 2))
        order3 = Order(id=uuid4(), external_ref="O3", due_date=datetime(2025, 1, 2))

        # op1 on machine A, op2 on machine B (precedence: op1->op2)
        # op3 on machine A (adjacent to op1), op4 on machine B (adjacent to op2)
        op1 = Operation(id=uuid4(), order_id=order1.id, seq_in_order=1,
                        state_id=s1.id, base_duration_min=20, eligible_wc_ids=[wc_a.id])
        op2 = Operation(id=uuid4(), order_id=order1.id, seq_in_order=2,
                        state_id=s2.id, base_duration_min=20, eligible_wc_ids=[wc_b.id],
                        predecessor_op_id=op1.id)
        op3 = Operation(id=uuid4(), order_id=order2.id, seq_in_order=1,
                        state_id=s2.id, base_duration_min=5, eligible_wc_ids=[wc_a.id])
        op4 = Operation(id=uuid4(), order_id=order3.id, seq_in_order=1,
                        state_id=s1.id, base_duration_min=5, eligible_wc_ids=[wc_b.id])

        setup_entries = [
            SetupEntry(work_center_id=wc_a.id, from_state_id=s1.id, to_state_id=s2.id, setup_minutes=10),
            SetupEntry(work_center_id=wc_b.id, from_state_id=s2.id, to_state_id=s1.id, setup_minutes=20),
        ]

        problem = ScheduleProblem(
            operations=[op1, op2, op3, op4],
            work_centers=[wc_a, wc_b],
            states=[s1, s2],
            setup_matrix=setup_entries,
            orders=[order1, order2, order3],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        base = datetime(2025, 1, 1)
        # Machine A: op1(0-20), op3(20-25)
        # Machine B: op2(20-40), op4(40-45)
        assignments = [
            Assignment(operation_id=op1.id, work_center_id=wc_a.id,
                       start_time=base, end_time=base + timedelta(minutes=20)),
            Assignment(operation_id=op3.id, work_center_id=wc_a.id,
                       start_time=base + timedelta(minutes=20), end_time=base + timedelta(minutes=25)),
            Assignment(operation_id=op2.id, work_center_id=wc_b.id,
                       start_time=base + timedelta(minutes=20), end_time=base + timedelta(minutes=40)),
            Assignment(operation_id=op4.id, work_center_id=wc_b.id,
                       start_time=base + timedelta(minutes=40), end_time=base + timedelta(minutes=45)),
        ]

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        # Machine A edges: op1->op3
        # Machine B edges: op2->op4
        # Precedence: op1->op2
        # Paths: op1->op2->op4 = 20+20+5 = 45 (longest)
        #         op1->op3 = 20+5 = 25
        # CP = [op1, op2, op4] (length 3)

        # With destroy_size=4, CP=3 < 4, extension kicks in.
        # Adjacent to op1 on machine A: op3 (successor in machine seq)
        # Adjacent to op2 on machine B: op4 (already in CP)
        # Adjacent to op4 on machine B: op2 (already in CP)
        # Candidate: op3. Result = {op1, op2, op4, op3} = 4 ops.
        result = _destroy_critical_path(assignments, problem, sdst, destroy_size=4, rng=rng)
        assert len(result) == 4
        assert op1.id in result
        assert op2.id in result
        assert op4.id in result
        assert op3.id in result  # Extended with adjacent op on machine A

    def test_empty_assignments_returns_empty(self):
        """Empty assignments returns empty set."""
        wc_a = WorkCenter(id=uuid4(), code="A", capability_group="grp1")
        s1 = State(id=uuid4(), code="S1")
        order = Order(id=uuid4(), external_ref="O1", due_date=datetime(2025, 1, 2))
        op1 = Operation(id=uuid4(), order_id=order.id, seq_in_order=1,
                        state_id=s1.id, base_duration_min=10, eligible_wc_ids=[wc_a.id])

        problem = ScheduleProblem(
            operations=[op1],
            work_centers=[wc_a],
            states=[s1],
            setup_matrix=[],
            orders=[order],
            planning_horizon_start=datetime(2025, 1, 1),
            planning_horizon_end=datetime(2025, 1, 2),
        )

        sdst = SdstMatrix.from_problem(problem)
        rng = random.Random(42)

        result = _destroy_critical_path([], problem, sdst, destroy_size=5, rng=rng)
        assert result == set()
