"""Targeted regression tests for the four dissertation audit fixes.

Ch.II  — ATCS underflow on sparse SDST matrix
Ch.IV  — Repair priority-aware dispatch
Ch.I   — ε-constraint scalarization
Ch.III — Ghost setup recomputation
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.incremental_repair import IncrementalRepair

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)


# ── Ch.II: ATCS underflow on sparse SDST ─────────────────────────

def test_atcs_nonzero_score_with_sparse_setup_matrix() -> None:
    """Sparse SDST (1 nonzero out of many cells) must not collapse all ATCS
    scores to zero.  Before the fix, s̄ → 0 caused exp(-s/(K2·s̄)) underflow."""
    state_ids = [uuid4() for _ in range(5)]
    states = [State(id=sid, code=f"S{i}", label=f"State {i}") for i, sid in enumerate(state_ids)]
    wc_id = uuid4()
    work_centers = [WorkCenter(id=wc_id, code="WC-1", capability_group="machining")]

    # Only ONE nonzero setup entry; all others are implicitly zero (absent).
    setup_matrix = [
        SetupEntry(
            work_center_id=wc_id,
            from_state_id=state_ids[0],
            to_state_id=state_ids[1],
            setup_minutes=30,
        ),
    ]

    order = Order(id=uuid4(), external_ref="ORD-SPARSE", due_date=HORIZON_START + timedelta(hours=6))
    ops = []
    prev_id = None
    for i in range(3):
        op_id = uuid4()
        ops.append(
            Operation(
                id=op_id,
                order_id=order.id,
                seq_in_order=i,
                state_id=state_ids[i % len(state_ids)],
                base_duration_min=20,
                eligible_wc_ids=[wc_id],
                predecessor_op_id=prev_id,
            )
        )
        prev_id = op_id

    problem = ScheduleProblem(
        states=states,
        orders=[order],
        operations=ops,
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )

    solver = GreedyDispatch()
    result = solver.solve(problem)

    assert result.status == SolverStatus.FEASIBLE, f"Expected FEASIBLE, got {result.status}"
    assert len(result.assignments) == 3
    assert result.objective.makespan_minutes > 0


def test_atcs_uses_local_ready_queue_setup_scale() -> None:
    """Irrelevant giant setup entries elsewhere in the matrix must not dilute
    the setup penalty for the current ready queue.

    After the first A-state job is scheduled, the heuristic should prefer the
    second A-state job before the more urgent B-state job because the local
    A→B setup is material for the ready set, even if the full matrix contains
    unrelated 1000-minute transitions.
    """
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    state_b = State(id=uuid4(), code="STATE-B", label="State B")
    state_c = State(id=uuid4(), code="STATE-C", label="State C")
    state_d = State(id=uuid4(), code="STATE-D", label="State D")
    state_e = State(id=uuid4(), code="STATE-E", label="State E")
    wc_id = uuid4()
    work_centers = [WorkCenter(id=wc_id, code="WC-1", capability_group="machining")]

    setup_matrix = [
        SetupEntry(
            work_center_id=wc_id,
            from_state_id=state_a.id,
            to_state_id=state_b.id,
            setup_minutes=30,
        ),
        SetupEntry(
            work_center_id=wc_id,
            from_state_id=state_b.id,
            to_state_id=state_a.id,
            setup_minutes=30,
        ),
        SetupEntry(
            work_center_id=wc_id,
            from_state_id=state_c.id,
            to_state_id=state_d.id,
            setup_minutes=1000,
        ),
        SetupEntry(
            work_center_id=wc_id,
            from_state_id=state_d.id,
            to_state_id=state_e.id,
            setup_minutes=1000,
        ),
        SetupEntry(
            work_center_id=wc_id,
            from_state_id=state_e.id,
            to_state_id=state_c.id,
            setup_minutes=1000,
        ),
    ]

    order_a1 = Order(
        id=uuid4(),
        external_ref="ORD-A1",
        due_date=HORIZON_START + timedelta(minutes=20),
        priority=500,
    )
    order_b = Order(
        id=uuid4(),
        external_ref="ORD-B",
        due_date=HORIZON_START + timedelta(minutes=25),
        priority=500,
    )
    order_a2 = Order(
        id=uuid4(),
        external_ref="ORD-A2",
        due_date=HORIZON_START + timedelta(minutes=40),
        priority=500,
    )

    op_a1 = Operation(
        id=uuid4(),
        order_id=order_a1.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc_id],
    )
    op_b = Operation(
        id=uuid4(),
        order_id=order_b.id,
        seq_in_order=0,
        state_id=state_b.id,
        base_duration_min=10,
        eligible_wc_ids=[wc_id],
    )
    op_a2 = Operation(
        id=uuid4(),
        order_id=order_a2.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=10,
        eligible_wc_ids=[wc_id],
    )

    problem = ScheduleProblem(
        states=[state_a, state_b, state_c, state_d, state_e],
        orders=[order_a1, order_b, order_a2],
        operations=[op_a1, op_b, op_a2],
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )

    solver = GreedyDispatch()
    result = solver.solve(problem)

    assert result.status == SolverStatus.FEASIBLE
    by_start = sorted(result.assignments, key=lambda assignment: assignment.start_time)
    assert [assignment.operation_id for assignment in by_start] == [
        op_a1.id,
        op_a2.id,
        op_b.id,
    ]


# ── Ch.IV: Repair priority-aware dispatch ─────────────────────────

def test_repair_prefers_high_priority_over_early_finish() -> None:
    """VIP order (priority=900) must be repaired before regular (priority=100),
    even if the regular order could finish earlier."""
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    wc_id = uuid4()
    work_centers = [WorkCenter(id=wc_id, code="WC-1", capability_group="machining")]

    vip_order = Order(
        id=uuid4(), external_ref="VIP", due_date=HORIZON_START + timedelta(hours=6), priority=900
    )
    regular_order = Order(
        id=uuid4(), external_ref="REG", due_date=HORIZON_START + timedelta(hours=6), priority=100
    )

    vip_op = Operation(
        id=uuid4(),
        order_id=vip_order.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=60,  # longer
        eligible_wc_ids=[wc_id],
    )
    regular_op = Operation(
        id=uuid4(),
        order_id=regular_order.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=10,  # shorter — would finish earlier
        eligible_wc_ids=[wc_id],
    )

    problem = ScheduleProblem(
        states=[state_a],
        orders=[vip_order, regular_order],
        operations=[vip_op, regular_op],
        work_centers=work_centers,
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )

    # Create a trivial base schedule (all at time zero, then disrupt both)
    from synaps.model import Assignment

    base = [
        Assignment(
            operation_id=vip_op.id,
            work_center_id=wc_id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=60),
        ),
        Assignment(
            operation_id=regular_op.id,
            work_center_id=wc_id,
            start_time=HORIZON_START + timedelta(minutes=60),
            end_time=HORIZON_START + timedelta(minutes=70),
        ),
    ]

    solver = IncrementalRepair()
    result = solver.solve(
        problem,
        base_assignments=base,
        disrupted_op_ids=[vip_op.id, regular_op.id],
        radius=0,
    )

    assert result.status == SolverStatus.FEASIBLE
    assert len(result.assignments) == 2

    # VIP op must be scheduled first (earlier start_time on the single machine)
    sorted_by_start = sorted(result.assignments, key=lambda a: a.start_time)
    assert sorted_by_start[0].operation_id == vip_op.id, (
        "VIP operation should be scheduled before regular operation"
    )


# ── Ch.I: ε-constraint scalarization ─────────────────────────────

def test_epsilon_constraint_bounds_tardiness() -> None:
    """With max_tardiness_minutes=0, CP-SAT must produce zero tardiness
    (or declare infeasible if impossible)."""
    state_a = State(id=uuid4(), code="STATE-A", label="State A")
    wc_id = uuid4()
    work_centers = [WorkCenter(id=wc_id, code="WC-1", capability_group="machining")]

    # Generous due date so zero-tardiness is achievable
    order = Order(
        id=uuid4(), external_ref="ORD-E", due_date=HORIZON_START + timedelta(hours=10)
    )
    op = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=0,
        state_id=state_a.id,
        base_duration_min=30,
        eligible_wc_ids=[wc_id],
    )

    problem = ScheduleProblem(
        states=[state_a],
        orders=[order],
        operations=[op],
        work_centers=work_centers,
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )

    solver = CpSatSolver()
    result = solver.solve(
        problem,
        time_limit_s=5,
        random_seed=42,
        epsilon_constraints={"max_tardiness_minutes": 0},
    )

    assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
    assert result.objective.total_tardiness_minutes == 0


# ── Ch.III: Ghost setup recomputation ─────────────────────────────

def test_greedy_setup_minutes_correct_after_scheduling() -> None:
    """Per-assignment setup_minutes must reflect actual machine predecessor,
    not the constructive-time estimate (which may be stale after gap insertion)."""
    state_x = State(id=uuid4(), code="STATE-X", label="State X")
    state_y = State(id=uuid4(), code="STATE-Y", label="State Y")
    wc_id = uuid4()
    work_centers = [WorkCenter(id=wc_id, code="WC-1", capability_group="machining")]

    setup_x_to_y = 10
    setup_y_to_x = 15

    setup_matrix = [
        SetupEntry(
            work_center_id=wc_id,
            from_state_id=state_x.id,
            to_state_id=state_y.id,
            setup_minutes=setup_x_to_y,
        ),
        SetupEntry(
            work_center_id=wc_id,
            from_state_id=state_y.id,
            to_state_id=state_x.id,
            setup_minutes=setup_y_to_x,
        ),
    ]

    # Three operations in one order: X → Y → X (chain with alternating states)
    order = Order(id=uuid4(), external_ref="ORD-GHOST", due_date=HORIZON_START + timedelta(hours=10))
    op_a_id, op_b_id, op_c_id = uuid4(), uuid4(), uuid4()
    ops = [
        Operation(
            id=op_a_id,
            order_id=order.id,
            seq_in_order=0,
            state_id=state_x.id,
            base_duration_min=20,
            eligible_wc_ids=[wc_id],
        ),
        Operation(
            id=op_b_id,
            order_id=order.id,
            seq_in_order=1,
            state_id=state_y.id,
            base_duration_min=20,
            eligible_wc_ids=[wc_id],
            predecessor_op_id=op_a_id,
        ),
        Operation(
            id=op_c_id,
            order_id=order.id,
            seq_in_order=2,
            state_id=state_x.id,
            base_duration_min=20,
            eligible_wc_ids=[wc_id],
            predecessor_op_id=op_b_id,
        ),
    ]

    problem = ScheduleProblem(
        states=[state_x, state_y],
        orders=[order],
        operations=ops,
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )

    solver = GreedyDispatch()
    result = solver.solve(problem)

    assert result.status == SolverStatus.FEASIBLE
    assert len(result.assignments) == 3

    # Sort by start_time to get machine order
    by_start = sorted(result.assignments, key=lambda a: a.start_time)
    ops_by_id = {op.id: op for op in ops}

    # First op on machine: setup = 0
    assert by_start[0].setup_minutes == 0, "First op on machine should have 0 setup"

    # Verify each subsequent op's setup_minutes matches its actual predecessor
    for i in range(1, len(by_start)):
        prev_state = ops_by_id[by_start[i - 1].operation_id].state_id
        cur_state = ops_by_id[by_start[i].operation_id].state_id
        expected_setup = 0
        for entry in setup_matrix:
            if (entry.work_center_id == wc_id
                    and entry.from_state_id == prev_state
                    and entry.to_state_id == cur_state):
                expected_setup = entry.setup_minutes
                break
        assert by_start[i].setup_minutes == expected_setup, (
            f"Op at position {i}: expected setup={expected_setup}, "
            f"got {by_start[i].setup_minutes}"
        )

    # Also verify aggregate total_setup matches sum of individual setups
    individual_sum = sum(a.setup_minutes for a in result.assignments)
    assert result.objective.total_setup_minutes == individual_sum

    # Feasibility check
    checker = FeasibilityChecker()
    violations = checker.check(problem, result.assignments)
    assert violations == []


def test_repair_setup_recomputed_after_insertion() -> None:
    """When a repaired op is inserted between two frozen ops, the frozen
    successor's setup_minutes must be updated to reflect the new predecessor."""
    state_x = State(id=uuid4(), code="STATE-X", label="State X")
    state_y = State(id=uuid4(), code="STATE-Y", label="State Y")
    wc_id = uuid4()
    work_centers = [WorkCenter(id=wc_id, code="WC-1", capability_group="machining")]

    setup_matrix = [
        SetupEntry(work_center_id=wc_id, from_state_id=state_x.id, to_state_id=state_y.id, setup_minutes=10),
        SetupEntry(work_center_id=wc_id, from_state_id=state_y.id, to_state_id=state_x.id, setup_minutes=15),
    ]

    # Two orders — order_a with one op (state X), order_b with one op (state Y)
    order_a = Order(id=uuid4(), external_ref="ORD-A", due_date=HORIZON_START + timedelta(hours=10), priority=500)
    order_b = Order(id=uuid4(), external_ref="ORD-B", due_date=HORIZON_START + timedelta(hours=10), priority=500)
    op_frozen = Operation(
        id=uuid4(), order_id=order_a.id, seq_in_order=0, state_id=state_x.id,
        base_duration_min=20, eligible_wc_ids=[wc_id],
    )
    op_disrupted = Operation(
        id=uuid4(), order_id=order_b.id, seq_in_order=0, state_id=state_y.id,
        base_duration_min=20, eligible_wc_ids=[wc_id],
    )

    problem = ScheduleProblem(
        states=[state_x, state_y],
        orders=[order_a, order_b],
        operations=[op_frozen, op_disrupted],
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )

    from synaps.model import Assignment

    # Base: frozen op at t=0..20, disrupted op was at t=30..50 (to be re-dispatched)
    base = [
        Assignment(
            operation_id=op_frozen.id,
            work_center_id=wc_id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=20),
            setup_minutes=0,
        ),
        Assignment(
            operation_id=op_disrupted.id,
            work_center_id=wc_id,
            start_time=HORIZON_START + timedelta(minutes=30),
            end_time=HORIZON_START + timedelta(minutes=50),
            setup_minutes=10,
        ),
    ]

    solver = IncrementalRepair()
    result = solver.solve(
        problem,
        base_assignments=base,
        disrupted_op_ids=[op_disrupted.id],
        radius=0,
    )

    assert result.status == SolverStatus.FEASIBLE
    assert len(result.assignments) == 2

    # Find the disrupted op's assignment in the result
    by_start = sorted(result.assignments, key=lambda a: a.start_time)
    ops_by_id = {op_frozen.id: op_frozen, op_disrupted.id: op_disrupted}

    # Verify setup_minutes are correct for every assignment
    for i, assignment in enumerate(by_start):
        if i == 0:
            assert assignment.setup_minutes == 0
        else:
            prev_state = ops_by_id[by_start[i - 1].operation_id].state_id
            cur_state = ops_by_id[assignment.operation_id].state_id
            expected = 0
            for entry in setup_matrix:
                if (entry.work_center_id == wc_id
                        and entry.from_state_id == prev_state
                        and entry.to_state_id == cur_state):
                    expected = entry.setup_minutes
                    break
            assert assignment.setup_minutes == expected

    # Total setup in objective must match individual sum
    assert result.objective.total_setup_minutes == sum(a.setup_minutes for a in result.assignments)
