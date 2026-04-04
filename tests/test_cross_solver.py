"""Cross-solver consistency tests — verify all solvers agree on structural invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
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
from synaps.solvers.lbbd_solver import LbbdSolver


def _make_cross_solver_problem() -> ScheduleProblem:
    """A 3-order, 2-machine problem all solvers should handle consistently."""
    state_a = State(id=uuid4(), code="S-A")
    state_b = State(id=uuid4(), code="S-B")
    wc_1 = WorkCenter(id=uuid4(), code="WC-1", capability_group="m", speed_factor=1.0)
    wc_2 = WorkCenter(id=uuid4(), code="WC-2", capability_group="m", speed_factor=1.0)
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = horizon_start + timedelta(hours=8)

    orders = [
        Order(id=uuid4(), external_ref=f"O-{i}", due_date=horizon_start + timedelta(hours=4 + i), priority=500 + i * 100)
        for i in range(3)
    ]

    ops: list[Operation] = []
    for i, order in enumerate(orders):
        op1_id = uuid4()
        op2_id = uuid4()
        ops.append(Operation(
            id=op1_id, order_id=order.id, seq_in_order=0,
            state_id=state_a.id if i % 2 == 0 else state_b.id,
            base_duration_min=25, eligible_wc_ids=[wc_1.id, wc_2.id],
        ))
        ops.append(Operation(
            id=op2_id, order_id=order.id, seq_in_order=1,
            state_id=state_b.id if i % 2 == 0 else state_a.id,
            base_duration_min=20, eligible_wc_ids=[wc_1.id, wc_2.id],
            predecessor_op_id=op1_id,
        ))

    return ScheduleProblem(
        states=[state_a, state_b],
        orders=orders,
        operations=ops,
        work_centers=[wc_1, wc_2],
        setup_matrix=[
            SetupEntry(work_center_id=wc_1.id, from_state_id=state_a.id, to_state_id=state_b.id, setup_minutes=8),
            SetupEntry(work_center_id=wc_1.id, from_state_id=state_b.id, to_state_id=state_a.id, setup_minutes=10),
            SetupEntry(work_center_id=wc_2.id, from_state_id=state_a.id, to_state_id=state_b.id, setup_minutes=8),
            SetupEntry(work_center_id=wc_2.id, from_state_id=state_b.id, to_state_id=state_a.id, setup_minutes=10),
        ],
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


class TestCrossSolverConsistency:
    """All solvers must satisfy the same structural properties."""

    @pytest.fixture
    def cross_problem(self) -> ScheduleProblem:
        return _make_cross_solver_problem()

    def test_all_solvers_produce_feasible_results(self, cross_problem: ScheduleProblem) -> None:
        checker = FeasibilityChecker()

        for name, solver, kwargs in [
            ("cpsat", CpSatSolver(), {"time_limit_s": 10, "random_seed": 42}),
            ("greedy", GreedyDispatch(), {}),
            ("lbbd", LbbdSolver(), {"max_iterations": 5, "time_limit_s": 30, "random_seed": 42}),
        ]:
            result = solver.solve(cross_problem, **kwargs)
            assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}, (
                f"{name} failed: {result.status}"
            )
            violations = checker.check(cross_problem, result.assignments)
            assert violations == [], f"{name} violations: {violations}"

    def test_all_solvers_assign_all_operations(self, cross_problem: ScheduleProblem) -> None:
        expected = {op.id for op in cross_problem.operations}

        for name, solver, kwargs in [
            ("cpsat", CpSatSolver(), {"time_limit_s": 10, "random_seed": 42}),
            ("greedy", GreedyDispatch(), {}),
            ("lbbd", LbbdSolver(), {"max_iterations": 5, "time_limit_s": 30, "random_seed": 42}),
        ]:
            result = solver.solve(cross_problem, **kwargs)
            assigned = {a.operation_id for a in result.assignments}
            assert assigned == expected, f"{name}: missing ops"

    def test_all_solvers_report_positive_makespan(self, cross_problem: ScheduleProblem) -> None:
        for name, solver, kwargs in [
            ("cpsat", CpSatSolver(), {"time_limit_s": 10, "random_seed": 42}),
            ("greedy", GreedyDispatch(), {}),
            ("lbbd", LbbdSolver(), {"max_iterations": 5, "time_limit_s": 30, "random_seed": 42}),
        ]:
            result = solver.solve(cross_problem, **kwargs)
            assert result.objective.makespan_minutes > 0, f"{name}: zero makespan"

    def test_all_solvers_report_nonnegative_objectives(self, cross_problem: ScheduleProblem) -> None:
        for name, solver, kwargs in [
            ("cpsat", CpSatSolver(), {"time_limit_s": 10, "random_seed": 42}),
            ("greedy", GreedyDispatch(), {}),
            ("lbbd", LbbdSolver(), {"max_iterations": 5, "time_limit_s": 30, "random_seed": 42}),
        ]:
            result = solver.solve(cross_problem, **kwargs)
            assert result.objective.total_setup_minutes >= 0, f"{name}: negative setup"
            assert result.objective.total_tardiness_minutes >= 0, f"{name}: negative tardiness"
            assert result.objective.total_material_loss >= 0, f"{name}: negative material"

    def test_repair_preserves_feasibility_after_disruption(self, cross_problem: ScheduleProblem) -> None:
        greedy = GreedyDispatch()
        base = greedy.solve(cross_problem)

        repair = IncrementalRepair()
        result = repair.solve(
            cross_problem,
            base_assignments=base.assignments,
            disrupted_op_ids=[cross_problem.operations[0].id],
            radius=3,
        )

        assert result.status == SolverStatus.FEASIBLE
        checker = FeasibilityChecker()
        assert checker.check(cross_problem, result.assignments) == []

    def test_cpsat_dominates_greedy_on_deterministic_instance(self, cross_problem: ScheduleProblem) -> None:
        cpsat = CpSatSolver()
        greedy = GreedyDispatch()

        cpsat_result = cpsat.solve(cross_problem, time_limit_s=10, random_seed=42)
        greedy_result = greedy.solve(cross_problem)

        assert cpsat_result.objective.makespan_minutes <= greedy_result.objective.makespan_minutes


class TestAuxResourceCrossSolver:
    """Auxiliary resource constraints must be respected by all solvers."""

    def test_aux_resource_serialized_by_all_solvers(self) -> None:
        state = State(id=uuid4(), code="S-A")
        wc_1 = WorkCenter(id=uuid4(), code="WC-1", capability_group="m")
        wc_2 = WorkCenter(id=uuid4(), code="WC-2", capability_group="m")
        tool = AuxiliaryResource(id=uuid4(), code="TOOL-1", resource_type="fixture", pool_size=1)
        horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
        horizon_end = horizon_start + timedelta(hours=4)

        orders = [
            Order(id=uuid4(), external_ref=f"O-{i}", due_date=horizon_end)
            for i in range(2)
        ]
        ops = [
            Operation(
                id=uuid4(), order_id=orders[i].id, seq_in_order=0,
                state_id=state.id, base_duration_min=30,
                eligible_wc_ids=[wc_1.id, wc_2.id],
            )
            for i in range(2)
        ]

        problem = ScheduleProblem(
            states=[state],
            orders=orders,
            operations=ops,
            work_centers=[wc_1, wc_2],
            setup_matrix=[],
            auxiliary_resources=[tool],
            aux_requirements=[
                OperationAuxRequirement(operation_id=ops[0].id, aux_resource_id=tool.id),
                OperationAuxRequirement(operation_id=ops[1].id, aux_resource_id=tool.id),
            ],
            planning_horizon_start=horizon_start,
            planning_horizon_end=horizon_end,
        )

        checker = FeasibilityChecker()

        for name, solver, kwargs in [
            ("cpsat", CpSatSolver(), {"time_limit_s": 10, "random_seed": 42}),
            ("greedy", GreedyDispatch(), {}),
        ]:
            result = solver.solve(problem, **kwargs)
            assert result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}, (
                f"{name} failed with tool constraint"
            )
            violations = checker.check(problem, result.assignments)
            assert violations == [], f"{name} violations with tool: {violations}"

            # With pool_size=1, ops must be serialized (makespan ≥ 60 min)
            assert result.objective.makespan_minutes >= 60, (
                f"{name}: makespan {result.objective.makespan_minutes} < 60 with single tool"
            )
