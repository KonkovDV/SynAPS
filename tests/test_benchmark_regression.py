"""Benchmark regression tests — pin solver quality bounds as CI guardrails.

These tests verify that solver improvements never regress below established
quality baselines.  Each test solves a deterministic instance and asserts
that the objective is within a known bound.
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
from synaps.solvers.lbbd_solver import LbbdSolver


def _make_stress_problem(
    n_orders: int = 5,
    ops_per_order: int = 3,
    n_machines: int = 3,
    n_states: int = 3,
) -> ScheduleProblem:
    """Build a deterministic stress problem for regression bounds."""
    states = [State(id=uuid4(), code=f"S-{i}", label=f"State {i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i}",
            capability_group="machining",
            speed_factor=1.0 + 0.1 * i,
        )
        for i in range(n_machines)
    ]
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = horizon_start + timedelta(hours=12)

    setup_matrix: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                setup_matrix.append(
                    SetupEntry(
                        work_center_id=wc.id,
                        from_state_id=s_from.id,
                        to_state_id=s_to.id,
                        setup_minutes=5 + abs(i - j) * 3,
                        material_loss=0.1 * abs(i - j),
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
                due_date=horizon_start + timedelta(hours=4 + i),
                priority=500 + i * 50,
            )
        )
        prev_op_id = None
        for j in range(ops_per_order):
            op_id = uuid4()
            state_idx = (i + j) % n_states
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=states[state_idx].id,
                    base_duration_min=20 + j * 5,
                    eligible_wc_ids=[wc.id for wc in work_centers],
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


class TestBenchmarkRegression:
    """Pinned quality bounds for deterministic solver runs."""

    def test_cpsat_stress_5x3_makespan_bound(self) -> None:
        """CP-SAT on 5 orders × 3 ops × 3 machines must achieve makespan ≤ 130 min."""
        problem = _make_stress_problem()
        solver = CpSatSolver()
        result = solver.solve(problem, time_limit_s=10, random_seed=42, num_workers=4)

        assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
        assert result.objective.makespan_minutes <= 130, (
            f"CP-SAT regression: makespan {result.objective.makespan_minutes} > 130 min"
        )

        checker = FeasibilityChecker()
        assert checker.check(problem, result.assignments) == []

    def test_greedy_stress_5x3_makespan_bound(self) -> None:
        """Greedy dispatch must produce a feasible schedule within 200 min makespan."""
        problem = _make_stress_problem()
        solver = GreedyDispatch()
        result = solver.solve(problem)

        assert result.status == SolverStatus.FEASIBLE
        assert result.objective.makespan_minutes <= 200, (
            f"Greedy regression: makespan {result.objective.makespan_minutes} > 200 min"
        )

        checker = FeasibilityChecker()
        assert checker.check(problem, result.assignments) == []

    def test_lbbd_stress_5x3_makespan_bound(self) -> None:
        """LBBD must converge to a solution within 250 min makespan."""
        problem = _make_stress_problem()
        solver = LbbdSolver()
        result = solver.solve(problem, max_iterations=10, time_limit_s=30, random_seed=42)

        assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
        assert result.objective.makespan_minutes <= 250, (
            f"LBBD regression: makespan {result.objective.makespan_minutes} > 250 min"
        )

        checker = FeasibilityChecker()
        assert checker.check(problem, result.assignments) == []

    def test_cpsat_always_beats_greedy_on_small_instance(self) -> None:
        """CP-SAT (exact) must produce equal or better makespan than greedy."""
        problem = _make_stress_problem(n_orders=3, ops_per_order=2, n_machines=2)

        cpsat = CpSatSolver()
        greedy = GreedyDispatch()

        cpsat_result = cpsat.solve(problem, time_limit_s=10, random_seed=42)
        greedy_result = greedy.solve(problem)

        assert (
            cpsat_result.objective.makespan_minutes <= greedy_result.objective.makespan_minutes
        ), (
            f"CP-SAT ({cpsat_result.objective.makespan_minutes}) worse than greedy "
            f"({greedy_result.objective.makespan_minutes})"
        )

    def test_tardiness_reported_for_tight_deadlines(self) -> None:
        """CP-SAT must report positive tardiness when due dates are very tight."""
        problem = _make_stress_problem(n_orders=4, ops_per_order=2, n_machines=2)
        # Override due dates to be very tight — all within 1 hour
        for order in problem.orders:
            order.due_date = problem.planning_horizon_start + timedelta(minutes=30)

        solver = CpSatSolver()
        result = solver.solve(problem, time_limit_s=10, random_seed=42)

        assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
        assert result.objective.total_tardiness_minutes > 0, (
            "Expected positive tardiness with impossible-to-meet deadlines"
        )

    def test_setup_cost_decreases_with_state_grouping(self) -> None:
        """Scheduling ops of the same state consecutively should reduce setup."""
        states = [
            State(id=uuid4(), code="S-A"),
            State(id=uuid4(), code="S-B"),
        ]
        wc = WorkCenter(id=uuid4(), code="WC-1", capability_group="m")
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=8)

        # 4 ops: A, B, A, B — alternating forces 3 setups
        # Optimal: A, A, B, B — only 1 setup
        orders = [Order(id=uuid4(), external_ref=f"O-{i}", due_date=horizon_end) for i in range(4)]
        ops = [
            Operation(
                id=uuid4(),
                order_id=orders[i].id,
                seq_in_order=0,
                state_id=states[i % 2].id,
                base_duration_min=20,
                eligible_wc_ids=[wc.id],
            )
            for i in range(4)
        ]

        problem = ScheduleProblem(
            states=states,
            orders=orders,
            operations=ops,
            work_centers=[wc],
            setup_matrix=[
                SetupEntry(
                    work_center_id=wc.id,
                    from_state_id=states[0].id,
                    to_state_id=states[1].id,
                    setup_minutes=15,
                    material_loss=1.0,
                ),
                SetupEntry(
                    work_center_id=wc.id,
                    from_state_id=states[1].id,
                    to_state_id=states[0].id,
                    setup_minutes=15,
                    material_loss=1.0,
                ),
            ],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        solver = CpSatSolver()
        result = solver.solve(problem, time_limit_s=10, random_seed=42)

        assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
        # Optimal grouping: 1 setup = 15 min. Sub-optimal would be 3 × 15 = 45.
        assert result.objective.total_setup_minutes <= 15, (
            f"Expected ≤ 1 setup (15 min), got {result.objective.total_setup_minutes} min"
        )
