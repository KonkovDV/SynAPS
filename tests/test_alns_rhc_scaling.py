"""Tests for SDST Matrix, ALNS Solver, RHC Solver, and Instance Generator.

Test hierarchy:
    1. SdstMatrix unit tests — correctness of NumPy-backed lookups
    2. ALNS solver tests — correctness at small scale, smoke at medium
    3. RHC solver tests — correctness with temporal windows
    4. Instance generator tests — structural validity at various scales
    5. Integration / cross-solver parity test
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    ObjectiveValues,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.sdst_matrix import SdstMatrix


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 3, 20, 0, tzinfo=UTC)

SA = uuid4()
SB = uuid4()
SC = uuid4()
WC1 = uuid4()
WC2 = uuid4()


def _make_3state_problem(n_orders: int = 10, ops_per_order: int = 3) -> ScheduleProblem:
    """Build a medium FJSP-SDST fixture with 3 states, 2 machines."""
    states = [
        State(id=SA, code="A", label="Alpha"),
        State(id=SB, code="B", label="Beta"),
        State(id=SC, code="C", label="Gamma"),
    ]
    wcs = [
        WorkCenter(id=WC1, code="M1", capability_group="grp", speed_factor=1.0),
        WorkCenter(id=WC2, code="M2", capability_group="grp", speed_factor=1.2),
    ]
    setup_matrix = [
        SetupEntry(work_center_id=WC1, from_state_id=SA, to_state_id=SB, setup_minutes=10, material_loss=1.0),
        SetupEntry(work_center_id=WC1, from_state_id=SB, to_state_id=SA, setup_minutes=15, material_loss=2.0),
        SetupEntry(work_center_id=WC1, from_state_id=SA, to_state_id=SC, setup_minutes=20, material_loss=0.5),
        SetupEntry(work_center_id=WC1, from_state_id=SC, to_state_id=SA, setup_minutes=12, material_loss=0.8),
        SetupEntry(work_center_id=WC1, from_state_id=SB, to_state_id=SC, setup_minutes=8, material_loss=1.5),
        SetupEntry(work_center_id=WC1, from_state_id=SC, to_state_id=SB, setup_minutes=18, material_loss=3.0),
        SetupEntry(work_center_id=WC2, from_state_id=SA, to_state_id=SB, setup_minutes=8),
        SetupEntry(work_center_id=WC2, from_state_id=SB, to_state_id=SA, setup_minutes=12),
        SetupEntry(work_center_id=WC2, from_state_id=SA, to_state_id=SC, setup_minutes=15),
        SetupEntry(work_center_id=WC2, from_state_id=SC, to_state_id=SA, setup_minutes=10),
        SetupEntry(work_center_id=WC2, from_state_id=SB, to_state_id=SC, setup_minutes=6),
        SetupEntry(work_center_id=WC2, from_state_id=SC, to_state_id=SB, setup_minutes=14),
    ]

    orders: list[Order] = []
    operations: list[Operation] = []
    state_cycle = [SA, SB, SC]

    for i in range(n_orders):
        oid = uuid4()
        orders.append(
            Order(
                id=oid,
                external_ref=f"ORD-{i:04d}",
                due_date=HORIZON_START + timedelta(hours=8 + i * 2),
                priority=500 + i * 50,
            )
        )
        prev_op = None
        for j in range(ops_per_order):
            op_id = uuid4()
            operations.append(
                Operation(
                    id=op_id,
                    order_id=oid,
                    seq_in_order=j,
                    state_id=state_cycle[(i + j) % 3],
                    base_duration_min=20 + (j * 10),
                    eligible_wc_ids=[WC1, WC2],
                    predecessor_op_id=prev_op,
                )
            )
            prev_op = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=wcs,
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. SdstMatrix tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSdstMatrix:
    def test_from_problem_builds_correct_dimensions(self) -> None:
        problem = _make_3state_problem(n_orders=2, ops_per_order=2)
        sdst = SdstMatrix.from_problem(problem)
        assert sdst.n_wc == 2
        assert sdst.n_states == 3
        assert sdst.setup_minutes.shape == (2, 3, 3)

    def test_get_setup_returns_correct_values(self) -> None:
        problem = _make_3state_problem()
        sdst = SdstMatrix.from_problem(problem)
        assert sdst.get_setup(WC1, SA, SB) == 10
        assert sdst.get_setup(WC1, SB, SA) == 15
        assert sdst.get_setup(WC2, SA, SB) == 8
        # Self-transition = 0
        assert sdst.get_setup(WC1, SA, SA) == 0

    def test_get_material_loss_returns_correct_values(self) -> None:
        problem = _make_3state_problem()
        sdst = SdstMatrix.from_problem(problem)
        assert sdst.get_material_loss(WC1, SA, SB) == pytest.approx(1.0)
        assert sdst.get_material_loss(WC1, SB, SA) == pytest.approx(2.0)

    def test_unknown_id_returns_zero(self) -> None:
        problem = _make_3state_problem()
        sdst = SdstMatrix.from_problem(problem)
        assert sdst.get_setup(uuid4(), SA, SB) == 0
        assert sdst.get_material_loss(WC1, uuid4(), SB) == 0.0

    def test_total_setup_for_sequence(self) -> None:
        problem = _make_3state_problem()
        sdst = SdstMatrix.from_problem(problem)
        # A → B → C on WC1: 10 + 8 = 18
        total = sdst.total_setup_for_sequence(WC1, [SA, SB, SC])
        assert total == 10 + 8

    def test_vectorized_setup_row(self) -> None:
        problem = _make_3state_problem()
        sdst = SdstMatrix.from_problem(problem)
        row = sdst.vectorized_setup_row(WC1, SA)
        assert row.shape == (3,)
        # Verify specific entries
        sb_idx = sdst.state_id_to_idx[SB]
        assert int(row[sb_idx]) == 10

    def test_memory_bytes_positive(self) -> None:
        problem = _make_3state_problem()
        sdst = SdstMatrix.from_problem(problem)
        assert sdst.memory_bytes() > 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. ALNS solver tests
# ═══════════════════════════════════════════════════════════════════════════


class TestAlnsSolver:
    def test_alns_produces_feasible_solution_small(self) -> None:
        """ALNS must produce a feasible schedule for a small instance."""
        from synaps.solvers.alns_solver import AlnsSolver
        from synaps.validation import verify_schedule_result

        problem = _make_3state_problem(n_orders=5, ops_per_order=2)
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=50,
            time_limit_s=30,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            repair_time_limit_s=5,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(result.assignments) == len(problem.operations)
        assert result.objective.makespan_minutes > 0

        verification = verify_schedule_result(problem, result)
        assert verification.feasible, f"Violations: {verification.violations}"

    def test_alns_improves_over_initial(self) -> None:
        """ALNS should improve over the initial greedy/beam solution."""
        from synaps.solvers.alns_solver import AlnsSolver
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        problem = _make_3state_problem(n_orders=10, ops_per_order=3)

        greedy = GreedyDispatch()
        greedy_result = greedy.solve(problem)

        alns = AlnsSolver()
        alns_result = alns.solve(
            problem,
            max_iterations=100,
            time_limit_s=30,
            repair_time_limit_s=5,
        )

        # ALNS should produce at least as good a makespan (or very close)
        assert alns_result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        # Allow 10% tolerance — ALNS may not beat greedy on tiny instances
        assert alns_result.objective.makespan_minutes <= greedy_result.objective.makespan_minutes * 1.1

    def test_alns_metadata_correct(self) -> None:
        """ALNS result should contain the expected metadata fields."""
        from synaps.solvers.alns_solver import AlnsSolver

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=20,
            time_limit_s=15,
            repair_time_limit_s=3,
        )
        assert "iterations_completed" in result.metadata
        assert "cpsat_repairs" in result.metadata
        assert "destroy_operators" in result.metadata
        assert "sdst_matrix_bytes" in result.metadata

    def test_alns_deterministic_with_seed(self) -> None:
        """Same seed should produce identical results."""
        from synaps.solvers.alns_solver import AlnsSolver

        problem = _make_3state_problem(n_orders=5, ops_per_order=2)
        solver = AlnsSolver()

        r1 = solver.solve(problem, max_iterations=30, time_limit_s=15, random_seed=123)
        r2 = solver.solve(problem, max_iterations=30, time_limit_s=15, random_seed=123)

        assert r1.objective.makespan_minutes == pytest.approx(r2.objective.makespan_minutes)


# ═══════════════════════════════════════════════════════════════════════════
# 3. RHC solver tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRhcSolver:
    def test_rhc_schedules_all_operations(self) -> None:
        """RHC must schedule all operations across windows."""
        from synaps.solvers.rhc_solver import RhcSolver
        from synaps.validation import verify_schedule_result

        problem = _make_3state_problem(n_orders=10, ops_per_order=3)
        solver = RhcSolver()
        result = solver.solve(
            problem,
            window_minutes=240,
            overlap_minutes=60,
            inner_solver="greedy",
            time_limit_s=30,
            max_ops_per_window=100,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(result.assignments) == len(problem.operations)

        verification = verify_schedule_result(problem, result)
        assert verification.feasible, f"Violations: {verification.violations}"

    def test_rhc_with_cpsat_inner(self) -> None:
        """RHC with CP-SAT inner solver should produce exact solutions per window."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=6, ops_per_order=2)
        solver = RhcSolver()
        result = solver.solve(
            problem,
            window_minutes=360,
            overlap_minutes=120,
            inner_solver="cpsat",
            time_limit_s=30,
            max_ops_per_window=50,
            inner_kwargs={"time_limit_s": 10},
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(result.assignments) == len(problem.operations)

    def test_rhc_metadata_includes_window_count(self) -> None:
        """RHC result should report how many windows were solved."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=5, ops_per_order=2)
        solver = RhcSolver()
        result = solver.solve(
            problem,
            window_minutes=240,
            overlap_minutes=60,
            inner_solver="greedy",
            time_limit_s=15,
        )
        assert "windows_solved" in result.metadata
        assert result.metadata["windows_solved"] >= 1


# ═══════════════════════════════════════════════════════════════════════════
# 4. Instance generator tests
# ═══════════════════════════════════════════════════════════════════════════


class TestInstanceGenerator:
    def test_generate_1000_ops(self) -> None:
        from synaps.benchmarks.instance_generator import generate_large_instance

        problem = generate_large_instance(n_operations=1000, n_machines=20, n_states=10)
        assert len(problem.operations) == 1000
        assert len(problem.work_centers) == 20
        assert len(problem.states) == 10
        # All ops have valid predecessors
        op_ids = {op.id for op in problem.operations}
        for op in problem.operations:
            if op.predecessor_op_id:
                assert op.predecessor_op_id in op_ids

    def test_generate_10000_ops_fast(self) -> None:
        from synaps.benchmarks.instance_generator import generate_large_instance

        t0 = time.monotonic()
        problem = generate_large_instance(n_operations=10_000, n_machines=50, n_states=15)
        elapsed = time.monotonic() - t0
        assert len(problem.operations) >= 9_900  # approximate due to rounding
        assert elapsed < 30.0, f"Generation took {elapsed:.1f}s — too slow"

    def test_generate_50000_ops_under_60s(self) -> None:
        from synaps.benchmarks.instance_generator import generate_large_instance

        t0 = time.monotonic()
        problem = generate_large_instance(
            n_operations=50_000,
            n_machines=100,
            n_states=20,
            setup_density=0.3,  # Reduce density to keep SetupEntry count manageable
        )
        elapsed = time.monotonic() - t0
        assert len(problem.operations) >= 49_900  # approximate due to rounding
        assert elapsed < 60.0, f"Generation took {elapsed:.1f}s — too slow"

    def test_generated_problem_passes_validation(self) -> None:
        from synaps.benchmarks.instance_generator import generate_large_instance

        # If validation fails, Pydantic raises ValueError
        problem = generate_large_instance(n_operations=500, n_machines=10, n_states=5)
        assert problem is not None
        assert len(problem.setup_matrix) > 0

    def test_sdst_matrix_from_large_instance(self) -> None:
        from synaps.benchmarks.instance_generator import generate_large_instance

        problem = generate_large_instance(n_operations=1000, n_machines=20, n_states=10)
        sdst = SdstMatrix.from_problem(problem)
        assert sdst.n_wc == 20
        assert sdst.n_states == 10
        # Memory should be modest: 20 × 10 × 10 × 3 arrays × 4 bytes ≈ 24 KB
        assert sdst.memory_bytes() < 100_000


# ═══════════════════════════════════════════════════════════════════════════
# 5. Integration / cross-solver parity tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCrossSolverParity:
    def test_alns_vs_greedy_both_feasible(self) -> None:
        """Both solvers must produce feasible solutions for the same problem."""
        from synaps.solvers.alns_solver import AlnsSolver
        from synaps.solvers.greedy_dispatch import GreedyDispatch
        from synaps.validation import verify_schedule_result

        problem = _make_3state_problem(n_orders=8, ops_per_order=3)

        greedy_result = GreedyDispatch().solve(problem)
        alns_result = AlnsSolver().solve(
            problem,
            max_iterations=50,
            time_limit_s=20,
            repair_time_limit_s=5,
        )

        assert greedy_result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert alns_result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)

        v_greedy = verify_schedule_result(problem, greedy_result)
        v_alns = verify_schedule_result(problem, alns_result)

        assert v_greedy.feasible
        assert v_alns.feasible

    def test_registry_contains_new_solvers(self) -> None:
        """Registry should list all new ALNS and RHC configurations."""
        from synaps.solvers.registry import available_solver_configs

        configs = available_solver_configs()
        assert "ALNS-300" in configs
        assert "ALNS-500" in configs
        assert "ALNS-1000" in configs
        assert "RHC-ALNS" in configs
        assert "RHC-CPSAT" in configs
        assert "RHC-GREEDY" in configs
