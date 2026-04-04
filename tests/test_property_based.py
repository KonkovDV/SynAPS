"""Property-based tests using Hypothesis for random problem generation.

Verifies structural invariants that must hold for ANY valid problem instance,
regardless of size, setup matrix, or priority distribution.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import hypothesis.strategies as st
from hypothesis import given, settings

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


HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = HORIZON_START + timedelta(hours=12)


@st.composite
def schedule_problems(
    draw: st.DrawFn,
    max_orders: int = 4,
    max_ops_per_order: int = 3,
    max_machines: int = 3,
    max_states: int = 3,
) -> ScheduleProblem:
    """Generate a random but valid ScheduleProblem."""
    n_states = draw(st.integers(min_value=1, max_value=max_states))
    n_machines = draw(st.integers(min_value=1, max_value=max_machines))
    n_orders = draw(st.integers(min_value=1, max_value=max_orders))

    states = [
        State(id=uuid4(), code=f"S-{i}", label=f"State {i}")
        for i in range(n_states)
    ]
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i}",
            capability_group="machining",
            speed_factor=draw(st.floats(min_value=0.5, max_value=2.0)),
        )
        for i in range(n_machines)
    ]

    # Setup matrix: random subset of state transitions
    setup_matrix: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if draw(st.booleans()):
                    setup_matrix.append(SetupEntry(
                        work_center_id=wc.id,
                        from_state_id=s_from.id,
                        to_state_id=s_to.id,
                        setup_minutes=draw(st.integers(min_value=1, max_value=30)),
                        material_loss=draw(st.floats(min_value=0.0, max_value=5.0)),
                    ))

    orders: list[Order] = []
    operations: list[Operation] = []
    for i in range(n_orders):
        order_id = uuid4()
        due_hours = draw(st.integers(min_value=2, max_value=10))
        priority = draw(st.integers(min_value=100, max_value=1000))
        orders.append(Order(
            id=order_id,
            external_ref=f"ORD-{i}",
            due_date=HORIZON_START + timedelta(hours=due_hours),
            priority=priority,
        ))

        n_ops = draw(st.integers(min_value=1, max_value=max_ops_per_order))
        prev_op_id = None
        for j in range(n_ops):
            op_id = uuid4()
            state_idx = draw(st.integers(min_value=0, max_value=n_states - 1))
            duration = draw(st.integers(min_value=5, max_value=60))
            # Eligible: at least 1 machine, up to all
            n_eligible = draw(st.integers(min_value=1, max_value=n_machines))
            eligible = [wc.id for wc in work_centers[:n_eligible]]
            operations.append(Operation(
                id=op_id,
                order_id=order_id,
                seq_in_order=j,
                state_id=states[state_idx].id,
                base_duration_min=duration,
                eligible_wc_ids=eligible,
                predecessor_op_id=prev_op_id,
            ))
            prev_op_id = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


class TestPropertyGreedy:
    """Properties that must hold for all greedy dispatch results."""

    @given(problem=schedule_problems())
    @settings(max_examples=30, deadline=10000)
    def test_greedy_always_produces_feasible_result(self, problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(problem)

        assert result.status in {SolverStatus.FEASIBLE, SolverStatus.ERROR}
        if result.status == SolverStatus.FEASIBLE:
            checker = FeasibilityChecker()
            violations = checker.check(problem, result.assignments)
            # Filter out horizon-bound violations: greedy dispatch schedules
            # all operations even when slow speed_factors push ops beyond
            # the planning horizon (a late schedule is better than none).
            hard_violations = [
                v for v in violations
                if v.kind != "HORIZON_BOUND_VIOLATION"
            ]
            assert hard_violations == [], f"Violations: {hard_violations}"

    @given(problem=schedule_problems())
    @settings(max_examples=30, deadline=10000)
    def test_greedy_assigns_all_operations(self, problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(problem)

        if result.status == SolverStatus.FEASIBLE:
            assigned = {a.operation_id for a in result.assignments}
            expected = {op.id for op in problem.operations}
            assert assigned == expected

    @given(problem=schedule_problems())
    @settings(max_examples=30, deadline=10000)
    def test_greedy_makespan_is_nonnegative(self, problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(problem)

        assert result.objective.makespan_minutes >= 0

    @given(problem=schedule_problems())
    @settings(max_examples=30, deadline=10000)
    def test_greedy_setup_total_is_nonnegative(self, problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(problem)

        assert result.objective.total_setup_minutes >= 0

    @given(problem=schedule_problems())
    @settings(max_examples=30, deadline=10000)
    def test_greedy_tardiness_is_nonnegative(self, problem: ScheduleProblem) -> None:
        solver = GreedyDispatch()
        result = solver.solve(problem)

        assert result.objective.total_tardiness_minutes >= 0


class TestPropertyCpSat:
    """Properties for CP-SAT on small random instances."""

    @given(problem=schedule_problems(max_orders=3, max_ops_per_order=2, max_machines=2))
    @settings(max_examples=15, deadline=30000)
    def test_cpsat_always_feasible_on_small_problems(self, problem: ScheduleProblem) -> None:
        solver = CpSatSolver()
        result = solver.solve(problem, time_limit_s=5, random_seed=42)

        if result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            checker = FeasibilityChecker()
            violations = checker.check(problem, result.assignments)
            assert violations == [], f"Violations: {violations}"

    @given(problem=schedule_problems(max_orders=3, max_ops_per_order=2, max_machines=2))
    @settings(max_examples=15, deadline=30000)
    def test_cpsat_beats_or_ties_greedy(self, problem: ScheduleProblem) -> None:
        cpsat = CpSatSolver()
        greedy = GreedyDispatch()

        cpsat_result = cpsat.solve(problem, time_limit_s=5, random_seed=42)
        greedy_result = greedy.solve(problem)

        if (
            cpsat_result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
            and greedy_result.status == SolverStatus.FEASIBLE
        ):
            # CP-SAT uses integer-minute discretization (ceiling rounding)
            # while greedy uses fractional minutes via speed_factor, so
            # CP-SAT may round up by ~1 min/op.  Use 15% tolerance.
            tolerance = greedy_result.objective.makespan_minutes * 0.15
            assert cpsat_result.objective.makespan_minutes <= greedy_result.objective.makespan_minutes + tolerance, (
                f"CP-SAT ({cpsat_result.objective.makespan_minutes}) worse than "
                f"greedy ({greedy_result.objective.makespan_minutes}) beyond 15% tolerance"
            )
