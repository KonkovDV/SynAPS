"""Tests for SDST Matrix, ALNS Solver, RHC Solver, and Instance Generator.

Test hierarchy:
    1. SdstMatrix unit tests — correctness of NumPy-backed lookups
    2. ALNS solver tests — correctness at small scale, smoke at medium
    3. RHC solver tests — correctness with temporal windows
    4. Instance generator tests — structural validity at various scales
    5. Integration / cross-solver parity test
"""

from __future__ import annotations

import math
import random
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from synaps.model import (
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
        SetupEntry(
            work_center_id=WC1, from_state_id=SA, to_state_id=SB,
            setup_minutes=10, material_loss=1.0,
        ),
        SetupEntry(
            work_center_id=WC1, from_state_id=SB, to_state_id=SA,
            setup_minutes=15, material_loss=2.0,
        ),
        SetupEntry(
            work_center_id=WC1, from_state_id=SA, to_state_id=SC,
            setup_minutes=20, material_loss=0.5,
        ),
        SetupEntry(
            work_center_id=WC1, from_state_id=SC, to_state_id=SA,
            setup_minutes=12, material_loss=0.8,
        ),
        SetupEntry(
            work_center_id=WC1, from_state_id=SB, to_state_id=SC,
            setup_minutes=8, material_loss=1.5,
        ),
        SetupEntry(
            work_center_id=WC1, from_state_id=SC, to_state_id=SB,
            setup_minutes=18, material_loss=3.0,
        ),
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


def _make_due_pressure_chain_problem() -> ScheduleProblem:
    """Build a chain where due-date pressure should pull deep successors.

    The expected effect is that they enter the first RHC window.
    """
    state_id = uuid4()
    work_center_id = uuid4()
    order_id = uuid4()

    op1_id = uuid4()
    op2_id = uuid4()
    op3_id = uuid4()

    return ScheduleProblem(
        states=[State(id=state_id, code="DUE", label="Due Pressure")],
        orders=[
            Order(
                id=order_id,
                external_ref="DUE-0001",
                due_date=HORIZON_START + timedelta(minutes=60),
                priority=1_000,
            )
        ],
        operations=[
            Operation(
                id=op1_id,
                order_id=order_id,
                seq_in_order=0,
                state_id=state_id,
                base_duration_min=180,
                eligible_wc_ids=[work_center_id],
                predecessor_op_id=None,
            ),
            Operation(
                id=op2_id,
                order_id=order_id,
                seq_in_order=1,
                state_id=state_id,
                base_duration_min=180,
                eligible_wc_ids=[work_center_id],
                predecessor_op_id=op1_id,
            ),
            Operation(
                id=op3_id,
                order_id=order_id,
                seq_in_order=2,
                state_id=state_id,
                base_duration_min=15,
                eligible_wc_ids=[work_center_id],
                predecessor_op_id=op2_id,
            ),
        ],
        work_centers=[
            WorkCenter(
                id=work_center_id,
                code="DUE-M1",
                capability_group="due",
                speed_factor=1.0,
            )
        ],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(hours=24),
    )


def _make_long_chain_problem(n_ops: int) -> ScheduleProblem:
    """Build a single-order precedence chain for RHC preprocessing timing guards."""
    state_id = uuid4()
    work_center_id = uuid4()
    order_id = uuid4()
    operations: list[Operation] = []
    predecessor_op_id = None

    for seq in range(n_ops):
        op_id = uuid4()
        operations.append(
            Operation(
                id=op_id,
                order_id=order_id,
                seq_in_order=seq,
                state_id=state_id,
                base_duration_min=10,
                eligible_wc_ids=[work_center_id],
                predecessor_op_id=predecessor_op_id,
            )
        )
        predecessor_op_id = op_id

    return ScheduleProblem(
        states=[State(id=state_id, code="CHAIN", label="Chain")],
        orders=[
            Order(
                id=order_id,
                external_ref=f"CHAIN-{n_ops}",
                due_date=HORIZON_START + timedelta(days=30),
                priority=100,
            )
        ],
        operations=operations,
        work_centers=[
            WorkCenter(
                id=work_center_id,
                code="CHAIN-M1",
                capability_group="chain",
                speed_factor=1.0,
            )
        ],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(days=60),
    )


def _make_tied_window_problem(n_orders: int = 40) -> ScheduleProblem:
    """Build a tie-heavy window-admission fixture for determinism checks."""
    state_id = uuid4()
    wc1_id = uuid4()
    wc2_id = uuid4()
    due_date = HORIZON_START + timedelta(hours=12)

    orders: list[Order] = []
    operations: list[Operation] = []
    for index in range(n_orders):
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"TIE-{index:04d}",
                due_date=due_date,
                priority=500,
            )
        )
        operations.append(
            Operation(
                id=uuid4(),
                order_id=order_id,
                seq_in_order=0,
                state_id=state_id,
                base_duration_min=30,
                eligible_wc_ids=[wc1_id, wc2_id],
                predecessor_op_id=None,
            )
        )

    return ScheduleProblem(
        states=[State(id=state_id, code="TIE", label="Tie")],
        orders=orders,
        operations=operations,
        work_centers=[
            WorkCenter(id=wc1_id, code="TIE-M1", capability_group="tie", speed_factor=1.0),
            WorkCenter(id=wc2_id, code="TIE-M2", capability_group="tie", speed_factor=1.0),
        ],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(days=2),
    )


def _make_bootstrap_frontier_problem(n_orders: int = 200) -> ScheduleProblem:
    """Build a far-due fixture where empty-frontier bootstrap would otherwise flood the window."""
    state_id = uuid4()
    wc1_id = uuid4()
    wc2_id = uuid4()
    due_date = HORIZON_START + timedelta(days=30)

    orders: list[Order] = []
    operations: list[Operation] = []
    for index in range(n_orders):
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"BOOT-{index:04d}",
                due_date=due_date,
                priority=100,
            )
        )
        operations.append(
            Operation(
                id=uuid4(),
                order_id=order_id,
                seq_in_order=0,
                state_id=state_id,
                base_duration_min=15,
                eligible_wc_ids=[wc1_id, wc2_id],
                predecessor_op_id=None,
            )
        )

    return ScheduleProblem(
        states=[State(id=state_id, code="BOOT", label="Bootstrap")],
        orders=orders,
        operations=operations,
        work_centers=[
            WorkCenter(id=wc1_id, code="BOOT-M1", capability_group="boot", speed_factor=1.0),
            WorkCenter(id=wc2_id, code="BOOT-M2", capability_group="boot", speed_factor=1.0),
        ],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(days=40),
    )


def _make_adaptive_admission_chain_problem(n_ops: int = 12) -> ScheduleProblem:
    """Build a chain whose first window is under-filled without look-ahead expansion."""
    state_id = uuid4()
    work_center_id = uuid4()
    order_id = uuid4()
    operations: list[Operation] = []
    predecessor_op_id = None

    for seq in range(n_ops):
        op_id = uuid4()
        operations.append(
            Operation(
                id=op_id,
                order_id=order_id,
                seq_in_order=seq,
                state_id=state_id,
                base_duration_min=10,
                eligible_wc_ids=[work_center_id],
                predecessor_op_id=predecessor_op_id,
            )
        )
        predecessor_op_id = op_id

    return ScheduleProblem(
        states=[State(id=state_id, code="ADAPT", label="Adaptive Window")],
        orders=[
            Order(
                id=order_id,
                external_ref=f"ADAPT-{n_ops}",
                due_date=HORIZON_START + timedelta(minutes=110),
                priority=250,
            )
        ],
        operations=operations,
        work_centers=[
            WorkCenter(
                id=work_center_id,
                code="ADAPT-M1",
                capability_group="adaptive",
                speed_factor=1.0,
            )
        ],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(hours=8),
    )


def _make_due_dense_starved_frontier_problem(n_ops: int = 20) -> ScheduleProblem:
    """Build an early-due fixture where admission offsets can starve a rich frontier."""
    state_id = uuid4()
    work_center_id = uuid4()

    orders: list[Order] = []
    operations: list[Operation] = []
    for index in range(n_ops):
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"RELAX-{index:04d}",
                due_date=HORIZON_START + timedelta(minutes=30),
                priority=900,
            )
        )
        operations.append(
            Operation(
                id=uuid4(),
                order_id=order_id,
                seq_in_order=0,
                state_id=state_id,
                base_duration_min=10,
                eligible_wc_ids=[work_center_id],
                predecessor_op_id=None,
            )
        )

    return ScheduleProblem(
        states=[State(id=state_id, code="RELAX", label="Admission Relax")],
        orders=orders,
        operations=operations,
        work_centers=[
            WorkCenter(
                id=work_center_id,
                code="RELAX-M1",
                capability_group="relax",
                speed_factor=1.0,
            )
        ],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_START + timedelta(hours=8),
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. SdstMatrix tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSdstMatrix:
    def test_from_problem_builds_correct_dimensions(self) -> None:
        problem = _make_3state_problem(n_orders=8, ops_per_order=2)
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
        assert (
            alns_result.objective.makespan_minutes
            <= greedy_result.objective.makespan_minutes * 1.1
        )

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
        assert "cpsat_repair_attempts" in result.metadata
        assert "cpsat_repairs" in result.metadata
        assert "cpsat_repair_skips_large_destroy" in result.metadata
        assert "cpsat_max_destroy_ops" in result.metadata
        assert "greedy_repair_attempts" in result.metadata
        assert "initial_beam_op_limit" in result.metadata
        assert "initial_solution_ms" in result.metadata
        assert "time_limit_exhausted_before_search" in result.metadata
        assert "max_no_improve_base_iters" in result.metadata
        assert "dynamic_no_improve_enabled" in result.metadata
        assert "due_pressure" in result.metadata
        assert "candidate_pressure" in result.metadata
        assert "cpsat_repair_ms_total" in result.metadata
        assert "greedy_repair_ms_total" in result.metadata
        assert "cpsat_repair_timeouts" in result.metadata
        assert "greedy_repair_timeouts" in result.metadata
        assert "repair_rejection_reasons" in result.metadata
        assert "destroy_operators" in result.metadata
        assert "sdst_matrix_bytes" in result.metadata
        assert "lower_bound" in result.metadata
        assert "upper_bound" in result.metadata
        assert "gap" in result.metadata
        assert "lower_bound_method" in result.metadata
        assert "lower_bound_components" in result.metadata
        assert result.metadata["cpsat_repair_attempts"] >= result.metadata["cpsat_repairs"]
        assert result.metadata["greedy_repair_attempts"] >= result.metadata["greedy_repairs"]
        assert result.metadata["lower_bound"] >= 0
        assert result.metadata["upper_bound"] >= result.objective.makespan_minutes
        assert result.metadata["upper_bound"] >= result.metadata["lower_bound"]

    def test_alns_skips_cpsat_for_large_destroy_neighbourhood(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ALNS should skip CP-SAT repair when the destroyed set exceeds the micro-solve cap."""
        from synaps.solvers.alns_solver import AlnsSolver

        problem = _make_3state_problem(n_orders=5, ops_per_order=2)

        def fail_if_called(self, problem, **kwargs):
            raise AssertionError("CP-SAT repair should have been skipped for large destroy sets")

        monkeypatch.setattr(
            "synaps.solvers.cpsat_solver.CpSatSolver.solve",
            fail_if_called,
        )

        result = AlnsSolver().solve(
            problem,
            max_iterations=10,
            time_limit_s=10,
            destroy_fraction=0.2,
            min_destroy=2,
            max_destroy=5,
            cpsat_max_destroy_ops=1,
            use_cpsat_repair=True,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["cpsat_repair_attempts"] == 0
        assert result.metadata["cpsat_repair_skips_large_destroy"] > 0
        assert result.metadata["greedy_repairs"] > 0

    def test_alns_uses_greedy_initial_solution_for_large_instances(self) -> None:
        """ALNS should avoid beam search as the initial seed on large instances."""
        from synaps.solvers.alns_solver import AlnsSolver

        problem = _make_3state_problem(n_orders=31, ops_per_order=2)
        solver = AlnsSolver()

        result = solver.solve(
            problem,
            max_iterations=1,
            time_limit_s=5,
            repair_time_limit_s=1,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["initial_solver"] == "greedy"
        assert result.metadata["initial_beam_op_limit"] == 60

    def test_alns_reports_zero_iterations_when_budget_exhausts_before_search(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ALNS should report zero iterations if the time budget is exhausted in phase 1."""
        import synaps.solvers.alns_solver as alns_module
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        problem = _make_3state_problem(n_orders=2, ops_per_order=2)
        seed_result = GreedyDispatch().solve(problem)

        def fake_beam_solve(self, problem, **kwargs):
            return seed_result

        monotonic_marks = iter([0.0, 0.0, 10.0, 10.0, 10.0])

        def fake_monotonic() -> float:
            try:
                return next(monotonic_marks)
            except StopIteration:
                return 10.0

        monkeypatch.setattr(
            "synaps.solvers.greedy_dispatch.BeamSearchDispatch.solve",
            fake_beam_solve,
        )
        monkeypatch.setattr(alns_module.time, "monotonic", fake_monotonic)

        result = alns_module.AlnsSolver().solve(
            problem,
            max_iterations=10,
            time_limit_s=5,
            initial_beam_op_limit=100,
        )

        assert result.metadata["initial_solver"] == "beam"
        assert result.metadata["time_limit_exhausted_before_search"] is True
        assert result.metadata["iterations_completed"] == 0
        assert result.metadata["cpsat_repair_attempts"] == 0
        assert result.metadata["greedy_repair_attempts"] == 0

    def test_alns_stops_early_on_no_improvement_streak(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ALNS should honor optional no-improvement early-stop guard."""
        import synaps.solvers.alns_solver as alns_module

        problem = _make_3state_problem(n_orders=4, ops_per_order=2)
        original_objective_cost = alns_module._objective_cost

        # Flat objective surface: no candidate can improve the incumbent.
        monkeypatch.setattr(alns_module, "_objective_cost", lambda obj, weights: 100.0)

        result = alns_module.AlnsSolver().solve(
            problem,
            max_iterations=50,
            time_limit_s=20,
            destroy_fraction=0.25,
            min_destroy=2,
            max_destroy=5,
            use_cpsat_repair=False,
            max_no_improve_iters=3,
        )

        # Restore in-module function so other tests keep normal behavior.
        monkeypatch.setattr(alns_module, "_objective_cost", original_objective_cost)

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["no_improve_early_stop"] is True
        assert result.metadata["iterations_completed"] <= 3
        assert result.metadata["no_improve_streak_final"] >= 3
        assert result.metadata["max_no_improve_iters"] == 3

    def test_alns_scales_no_improve_guard_with_pressure(self) -> None:
        """ALNS should scale no-improve guard when dynamic pressure mode is enabled."""
        from synaps.solvers.alns_solver import AlnsSolver

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)

        result = AlnsSolver().solve(
            problem,
            max_iterations=10,
            time_limit_s=10,
            use_cpsat_repair=False,
            max_no_improve_iters=10,
            dynamic_no_improve_enabled=True,
            due_pressure=1.0,
            candidate_pressure=2.0,
            no_improve_due_alpha=0.5,
            no_improve_candidate_beta=0.25,
            no_improve_min_iters=5,
            no_improve_max_iters=40,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["max_no_improve_base_iters"] == 10
        assert result.metadata["dynamic_no_improve_enabled"] is True
        assert result.metadata["max_no_improve_iters"] == 20
        assert result.metadata["due_pressure"] == pytest.approx(1.0)
        assert result.metadata["candidate_pressure"] == pytest.approx(2.0)

    def test_alns_scales_sa_profile_with_pressure(self) -> None:
        """ALNS should expose pressure-aware SA temperature and cooling metadata."""
        from synaps.solvers.alns_solver import AlnsSolver

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)

        result = AlnsSolver().solve(
            problem,
            max_iterations=10,
            time_limit_s=10,
            use_cpsat_repair=False,
            sa_auto_calibration_enabled=False,
            dynamic_sa_enabled=True,
            due_pressure=1.0,
            candidate_pressure=2.0,
            sa_initial_temp=100.0,
            sa_cooling_rate=0.995,
            sa_due_alpha=0.35,
            sa_candidate_beta=0.15,
            sa_pressure_cooling_gamma=0.0015,
            sa_temp_min=50.0,
            sa_temp_max=500.0,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["dynamic_sa_enabled"] is True
        assert result.metadata["sa_pressure_factor"] == pytest.approx(1.65)
        assert result.metadata["effective_sa_initial_temp"] == pytest.approx(165.0)
        assert result.metadata["effective_sa_cooling_rate"] == pytest.approx(0.995975)

    def test_alns_segment_weight_update_blends_towards_uniform(self) -> None:
        """Operator segment refresh should retain exploration pressure.

        It should not collapse completely to a single arm.
        """
        import synaps.solvers.alns_solver as alns_module

        refreshed = alns_module._update_operator_weights_for_segment(
            [30.0, 0.0, 0.0, 0.0],
            [3, 0, 0, 0],
            reset_mix=0.25,
        )

        assert len(refreshed) == 4
        assert sum(refreshed) == pytest.approx(1.0)
        assert refreshed[0] < 1.0
        assert all(weight > 0 for weight in refreshed)
        assert refreshed[1] > 0.0

    def test_alns_auto_calibration_derives_temperature_from_positive_deltas(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Auto-calibration should derive a base temperature from sampled worsening deltas."""
        import synaps.solvers.alns_solver as alns_module
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        problem = _make_3state_problem(n_orders=2, ops_per_order=2)
        current_assignments = GreedyDispatch().solve(problem).assignments
        sdst = alns_module.SdstMatrix.from_problem(problem)
        ops_by_id = {op.id: op for op in problem.operations}
        successors_by_op: dict[UUID, list[UUID]] = {}
        for op in problem.operations:
            if op.predecessor_op_id is not None:
                successors_by_op.setdefault(op.predecessor_op_id, []).append(op.id)

        destroyed_op_id = current_assignments[0].operation_id
        original_operator = alns_module.DESTROY_OPERATORS[0]

        def fake_destroy(assignments, problem, sdst, destroy_size, rng):
            return {destroyed_op_id}

        def fake_repair(problem, frozen_assignments, destroyed_op_ids):
            repaired = [
                assignment
                for assignment in current_assignments
                if assignment.operation_id in destroyed_op_ids
            ]
            return alns_module.RepairOutcome(
                status=alns_module.RepairStatus.FEASIBLE,
                assignments=tuple(repaired),
                reason="ok",
            )

        monkeypatch.setattr(
            alns_module,
            "DESTROY_OPERATORS",
            [("deterministic", fake_destroy)] + list(alns_module.DESTROY_OPERATORS[1:]),
        )
        monkeypatch.setattr(alns_module, "_repair_greedy_outcome", fake_repair)
        monkeypatch.setattr(alns_module, "_objective_cost", lambda obj, weights: 120.0)

        calibrated_temp, sample_count = alns_module._calibrate_sa_temperature(
            problem,
            current_assignments,
            current_cost=100.0,
            objective_weights={"makespan": 1.0},
            sdst=sdst,
            destroy_size=1,
            max_destroy=1,
            ops_by_id=ops_by_id,
            successors_by_op=successors_by_op,
            trials=3,
            acceptance_probability=0.8,
            seed=42,
            fallback_temperature=50.0,
        )

        monkeypatch.setattr(
            alns_module,
            "DESTROY_OPERATORS",
            [original_operator] + list(alns_module.DESTROY_OPERATORS[1:]),
        )

        assert sample_count == 3
        assert calibrated_temp == pytest.approx(-20.0 / math.log(0.8))

    def test_alns_recovers_when_final_validation_rejects_incumbent(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ALNS should recover to the initial solution if final incumbent is invalid."""
        import synaps.solvers.alns_solver as alns_module

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)
        check_calls = {"count": 0}

        def fake_check(self, problem, assignments):
            check_calls["count"] += 1
            if check_calls["count"] == 1:
                return ["forced_final_violation"]
            return []

        monkeypatch.setattr(alns_module.FeasibilityChecker, "check", fake_check)

        result = alns_module.AlnsSolver().solve(
            problem,
            max_iterations=20,
            time_limit_s=15,
            use_cpsat_repair=False,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["final_violation_recovery_attempted"] is True
        assert result.metadata["final_violation_recovered"] is True
        assert result.metadata["final_violation_recovery_source"] == "initial_solution"
        assert result.metadata["final_violations_before_recovery"] == 1
        assert result.metadata["final_violations"] == 0
        assert check_calls["count"] >= 2

    def test_alns_deterministic_with_seed(self) -> None:
        """Same seed should produce identical results."""
        from synaps.solvers.alns_solver import AlnsSolver
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        problem = _make_3state_problem(n_orders=5, ops_per_order=2)
        solver = AlnsSolver()

        r1 = solver.solve(problem, max_iterations=30, time_limit_s=15, random_seed=123)
        r2 = solver.solve(problem, max_iterations=30, time_limit_s=15, random_seed=123)

        assert r1.objective.makespan_minutes == pytest.approx(r2.objective.makespan_minutes)

        baseline = GreedyDispatch().solve(problem)
        partial_warm_start = [
            assignment
            for assignment in baseline.assignments
            if next(
                op for op in problem.operations if op.id == assignment.operation_id
            ).seq_in_order
            == 0
        ]

        warmed = solver.solve(
            problem,
            max_iterations=10,
            time_limit_s=15,
            random_seed=123,
            use_cpsat_repair=False,
            warm_start_assignments=partial_warm_start,
        )

        assert warmed.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert warmed.metadata["warm_start_used"] is True
        assert warmed.metadata["warm_start_supplied_assignments"] == len(partial_warm_start)
        assert warmed.metadata["warm_start_completed_assignments"] > 0
        assert warmed.metadata["initial_solver"] == "warm_start"

    def test_alns_reanchors_complete_warm_start_against_frozen_occupancy(self) -> None:
        """ALNS should not accept a complete warm start that overlaps frozen machine usage."""
        from datetime import timedelta

        from synaps.model import Assignment
        from synaps.solvers.alns_solver import AlnsSolver

        problem = _make_due_pressure_chain_problem()
        work_center_id = problem.work_centers[0].id
        ops_by_seq = sorted(problem.operations, key=lambda op: op.seq_in_order)

        frozen_assignment = Assignment(
            operation_id=uuid4(),
            work_center_id=work_center_id,
            start_time=problem.planning_horizon_start,
            end_time=problem.planning_horizon_start + timedelta(minutes=20),
            setup_minutes=0,
            aux_resource_ids=[],
        )
        overlapping_warm_start = [
            Assignment(
                operation_id=op.id,
                work_center_id=work_center_id,
                start_time=problem.planning_horizon_start
                + timedelta(minutes=index * 10),
                end_time=problem.planning_horizon_start
                + timedelta(minutes=(index + 1) * 10),
                setup_minutes=0,
                aux_resource_ids=[],
            )
            for index, op in enumerate(ops_by_seq)
        ]

        result = AlnsSolver().solve(
            problem,
            max_iterations=0,
            time_limit_s=5,
            use_cpsat_repair=False,
            warm_start_assignments=overlapping_warm_start,
            frozen_assignments=[frozen_assignment],
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.assignments
        assert result.assignments[0].start_time >= frozen_assignment.end_time


# ═══════════════════════════════════════════════════════════════════════════
# 3. RHC solver tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRhcSolver:
    def test_rhc_estimate_window_operation_cap_uses_machine_capacity(self) -> None:
        """RHC should derive a window budget from machine-time capacity and mean duration."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=10, ops_per_order=3)

        cap = RhcSolver._estimate_window_operation_cap(
            problem,
            window_span_minutes=300,
            window_load_factor=1.5,
        )

        assert cap == 30

    def test_rhc_earliest_start_preprocessing_scales_better_than_quadratic(self) -> None:
        """RHC preprocessing should stay near-linear enough to catch quadratic regressions."""
        from synaps.solvers.rhc_solver import RhcSolver

        small_problem = _make_long_chain_problem(2_000)
        large_problem = _make_long_chain_problem(4_000)

        def measure(problem: ScheduleProblem) -> float:
            timings: list[float] = []
            for _ in range(3):
                result: dict = {}
                t0 = time.monotonic()
                RhcSolver._compute_earliest_starts(problem, result)
                timings.append(time.monotonic() - t0)
            return min(timings)

        small_elapsed = measure(small_problem)
        large_elapsed = measure(large_problem)

        assert large_elapsed / max(small_elapsed, 1e-6) < 3.5

    def test_rhc_expand_predecessor_closure_includes_transitive_chain(self) -> None:
        """RHC must include the full unresolved predecessor chain, not just one hop."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_pressure_chain_problem()
        ops_by_id = {op.id: op for op in problem.operations}
        terminal_op = max(problem.operations, key=lambda op: op.seq_in_order)

        expanded = RhcSolver._expand_predecessor_closure(
            {terminal_op.id},
            ops_by_id,
            committed_op_ids=set(),
        )

        assert expanded == {op.id for op in problem.operations}

    def test_alns_cap_destroy_set_preserves_successor_closure(self) -> None:
        """ALNS destroy capping must not leave frozen successors behind repaired predecessors."""
        import random

        import synaps.solvers.alns_solver as alns_module

        problem = _make_due_pressure_chain_problem()
        ops_by_id = {op.id: op for op in problem.operations}
        successors_by_op: dict = {}
        for op in problem.operations:
            if op.predecessor_op_id is not None:
                successors_by_op.setdefault(op.predecessor_op_id, []).append(op.id)

        terminal_op = max(problem.operations, key=lambda op: op.seq_in_order)
        expanded = alns_module._expand_successor_closure(
            {problem.operations[0].id},
            successors_by_op,
        )
        assert expanded == {op.id for op in problem.operations}

        capped = alns_module._cap_destroy_set_preserving_successor_closure(
            expanded,
            ops_by_id,
            successors_by_op,
            max_destroy=2,
            rng=random.Random(1),
        )

        assert len(capped) == 2
        assert terminal_op.id in capped
        for op_id in capped:
            for successor_id in successors_by_op.get(op_id, []):
                assert successor_id in capped

    @given(
        chain_size=st.integers(min_value=3, max_value=30),
        destroy_cap=st.integers(min_value=1, max_value=20),
        seed=st.integers(min_value=0, max_value=10_000),
    )
    @settings(max_examples=40, deadline=None)
    def test_alns_cap_destroy_set_successor_closure_property(
        self,
        chain_size: int,
        destroy_cap: int,
        seed: int,
    ) -> None:
        """Capped destroy set must remain successor-closed for chain precedence graphs."""
        import synaps.solvers.alns_solver as alns_module

        problem = _make_long_chain_problem(chain_size)
        ops_by_id = {op.id: op for op in problem.operations}
        successors_by_op: dict = {}
        for op in problem.operations:
            if op.predecessor_op_id is not None:
                successors_by_op.setdefault(op.predecessor_op_id, []).append(op.id)

        full_destroy = {op.id for op in problem.operations}
        effective_cap = max(1, min(destroy_cap, chain_size))
        capped = alns_module._cap_destroy_set_preserving_successor_closure(
            full_destroy,
            ops_by_id,
            successors_by_op,
            max_destroy=effective_cap,
            rng=random.Random(seed),
        )

        assert len(capped) <= effective_cap
        for op_id in capped:
            for successor_id in successors_by_op.get(op_id, []):
                assert successor_id in capped

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

    def test_rhc_respects_max_windows_cap(self) -> None:
        """RHC should stop after max_windows when the cap is configured."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_pressure_chain_problem()
        result = RhcSolver().solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="greedy",
            time_limit_s=120,
            max_ops_per_window=10,
            max_windows=1,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert result.metadata["max_windows"] == 1
        assert result.metadata["windows_solved"] == 1

    def test_rhc_bootstraps_earliest_ready_ops_when_due_admission_starves_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should seed earliest-ready work when due/admission frontiers are empty."""
        from synaps.solvers.greedy_dispatch import GreedyDispatch
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_long_chain_problem(20)
        captured_window_sizes: list[int] = []

        def fake_alns_solve(self, sub_problem, **kwargs):
            captured_window_sizes.append(len(sub_problem.operations))
            return GreedyDispatch().solve(sub_problem)

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="alns",
            time_limit_s=120,
            max_ops_per_window=5,
            max_windows=1,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert result.metadata["windows_solved"] == 1
        assert result.metadata["max_windows"] == 1
        assert captured_window_sizes
        assert captured_window_sizes[0] > 0
        assert result.metadata["inner_window_summaries"]
        assert result.metadata["inner_window_summaries"][0]["ops_in_window"] > 0
        assert result.metadata["inner_window_summaries"][0]["resolution_mode"] != "no_candidates"

    def test_rhc_metadata_tracks_due_pressure_and_candidate_peak(self) -> None:
        """RHC should expose scaling metadata for candidate-pool pressure and due-date pulls."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_pressure_chain_problem()
        solver = RhcSolver()
        result = solver.solve(
            problem,
            window_minutes=120,
            overlap_minutes=30,
            inner_solver="greedy",
            time_limit_s=30,
            max_ops_per_window=10,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["preprocessing_ms"] >= 0
        assert result.metadata["peak_window_candidate_count"] >= 1
        assert result.metadata["due_pressure_selected_ops"] > 0
        assert result.metadata["candidate_pressure_mean"] > 0
        assert result.metadata["candidate_pressure_max"] > 0
        assert result.metadata["due_pressure_mean"] >= 0
        assert result.metadata["due_drift_minutes_mean"] >= 0
        assert result.metadata["due_drift_minutes_max"] >= 0
        assert result.metadata["spillover_count"] >= 0
        assert result.metadata["lower_bound"] >= 0
        assert result.metadata["upper_bound"] >= result.metadata["lower_bound"]
        assert result.metadata["lower_bound_method"] == "relaxed_precedence_capacity"
        assert result.metadata["lower_bound_components"]["precedence_critical_path_lb"] >= 0
        assert result.metadata["earliest_frontier_advances"] <= len(problem.operations)
        assert result.metadata["due_frontier_advances"] <= len(problem.operations)
        assert result.metadata["effective_window_operation_cap"] >= 1
        assert result.metadata["window_load_factor"] >= 1.0

    def test_rhc_inner_window_summary_exposes_window_lower_bound(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Inner-solver window summaries should carry deterministic lower bounds."""
        from synaps.solvers.greedy_dispatch import GreedyDispatch
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_long_chain_problem(12)

        def fake_alns_solve(self, sub_problem, **kwargs):
            return GreedyDispatch().solve(sub_problem)

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=120,
            overlap_minutes=0,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=20,
            max_windows=1,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.metadata["inner_window_summaries"]
        first_window = result.metadata["inner_window_summaries"][0]
        assert first_window["lower_bound"] >= 0

    def test_rhc_candidate_pool_clamp_prevents_frontier_explosion(self) -> None:
        """RHC should cap tie-heavy candidate frontiers to a bounded admission pool."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_tied_window_problem(n_orders=400)
        result = RhcSolver().solve(
            problem,
            window_minutes=240,
            overlap_minutes=0,
            inner_solver="greedy",
            time_limit_s=20,
            max_ops_per_window=10,
            max_windows=1,
            candidate_pool_factor=2.0,
            due_admission_horizon_factor=4.0,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert result.metadata["candidate_pool_limit"] == 20
        assert result.metadata["peak_window_candidate_count"] <= 20
        assert (
            result.metadata["peak_raw_window_candidate_count"]
            >= result.metadata["peak_window_candidate_count"]
        )
        assert result.metadata["candidate_pool_clamped_windows"] >= 1
        assert result.metadata["candidate_pool_filtered_ops"] >= 1

    def test_rhc_bootstrap_admission_respects_candidate_pool_limit(self) -> None:
        """Empty-frontier bootstrap should seed only a bounded earliest-ready candidate pool."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_bootstrap_frontier_problem(n_orders=200)
        result = RhcSolver().solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="greedy",
            time_limit_s=20,
            max_ops_per_window=10,
            max_windows=1,
            candidate_pool_factor=2.0,
            due_admission_horizon_factor=4.0,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert result.metadata["candidate_pool_limit"] == 20
        assert result.metadata["admission_starvation_count"] >= 1
        assert result.metadata["peak_window_candidate_count"] <= 20
        assert result.metadata["peak_raw_window_candidate_count"] <= 20
        assert result.metadata["candidate_pool_clamped_windows"] == 0
        assert result.metadata["candidate_pool_filtered_ops"] == 0

    def test_rhc_adaptive_window_expands_starved_frontier_before_bootstrap(self) -> None:
        """Adaptive look-ahead should widen a starved first window before bootstrap fallback."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_adaptive_admission_chain_problem(n_ops=12)
        result = RhcSolver().solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="greedy",
            time_limit_s=20,
            max_ops_per_window=4,
            max_windows=1,
            candidate_pool_factor=2.0,
            adaptive_window_enabled=True,
            adaptive_window_min_fill_ratio=0.5,
            adaptive_window_max_multiplier=2.0,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert result.metadata["candidate_pool_limit"] == 8
        assert result.metadata["adaptive_window_expansions"] == 1
        assert result.metadata["adaptive_window_max_multiplier_applied"] == pytest.approx(2.0)
        assert (
            result.metadata["peak_raw_window_candidate_count"]
            >= result.metadata["candidate_pool_limit"]
        )
        assert result.metadata["candidate_pool_clamped_windows"] >= 1
        assert result.metadata["admission_starvation_count"] == 0

    def test_rhc_progressive_admission_relaxation_recovers_due_frontier_capacity(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Low-fill admitted pools should temporarily fall back to the raw due/admission frontier."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_dense_starved_frontier_problem(n_ops=20)
        earliest_ids = {op.id for op in problem.operations[:2]}

        def fake_compute_earliest_starts(problem, result) -> None:
            for op in problem.operations:
                result[op.id] = 0.0 if op.id in earliest_ids else 300.0

        monkeypatch.setattr(
            RhcSolver,
            "_compute_earliest_starts",
            staticmethod(fake_compute_earliest_starts),
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="greedy",
            time_limit_s=20,
            max_ops_per_window=10,
            max_windows=1,
            candidate_pool_factor=1.0,
            adaptive_window_enabled=False,
            progressive_admission_relaxation_enabled=True,
            admission_relaxation_min_fill_ratio=0.5,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert result.metadata["peak_raw_window_candidate_count"] == 20
        assert result.metadata["peak_window_candidate_count"] == result.metadata[
            "candidate_pool_limit"
        ]
        assert result.metadata["peak_window_candidate_count"] > len(earliest_ids)
        assert result.metadata["admission_relaxation_windows"] == 1
        assert result.metadata["admission_relaxation_recovered_ops"] >= 8

    def test_rhc_window_cap_selection_is_deterministic_under_ties(self) -> None:
        """RHC should produce identical schedules under tie-heavy window ranking."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_tied_window_problem(n_orders=40)

        def solve_once():
            return RhcSolver().solve(
                problem,
                window_minutes=240,
                overlap_minutes=0,
                inner_solver="greedy",
                time_limit_s=60,
                max_ops_per_window=10,
            )

        r1 = solve_once()
        r2 = solve_once()

        assert r1.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert r2.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(r1.assignments) == len(problem.operations)
        assert len(r2.assignments) == len(problem.operations)

        def signature(result) -> list[tuple[str, str, int, int]]:
            return sorted(
                (
                    str(assignment.operation_id),
                    str(assignment.work_center_id),
                    int((assignment.start_time - HORIZON_START).total_seconds() / 60.0),
                    int((assignment.end_time - HORIZON_START).total_seconds() / 60.0),
                )
                for assignment in result.assignments
            )

        assert signature(r1) == signature(r2)

    def test_rhc_skips_global_fallback_after_time_limit_exhaustion(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should stop cleanly once the global time budget is exhausted."""
        import synaps.solvers.rhc_solver as rhc_module
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_pressure_chain_problem()

        time_marks = iter([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])

        def fake_monotonic() -> float:
            try:
                return next(time_marks)
            except StopIteration:
                return 1.0

        def fail_if_slot_search_runs(*args: object, **kwargs: object) -> None:
            raise AssertionError(
                "fallback slot search should be skipped after time limit exhaustion"
            )

        monkeypatch.setattr(rhc_module.time, "monotonic", fake_monotonic)
        monkeypatch.setattr(rhc_module, "find_earliest_feasible_slot", fail_if_slot_search_runs)

        result = RhcSolver().solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="greedy",
            time_limit_s=0.5,
            max_ops_per_window=10,
        )

        assert result.status == SolverStatus.ERROR
        assert result.metadata["time_limit_reached"] is True
        assert result.metadata["fallback_repair_attempted"] is False
        assert result.metadata["fallback_repair_skipped"] is True

    def test_rhc_backtracking_rewinds_recent_boundary_assignments_into_next_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Backtracking should re-inject recent committed assignments into the next inner window."""
        import synaps.solvers.alns_solver as alns_module
        from synaps.solvers.greedy_dispatch import GreedyDispatch
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_long_chain_problem(18)
        captured_window_ops: list[list[UUID]] = []

        def fake_alns_solve(self, sub_problem, **kwargs):
            captured_window_ops.append([op.id for op in sub_problem.operations])
            return GreedyDispatch().solve(sub_problem)

        monkeypatch.setattr(alns_module.AlnsSolver, "solve", fake_alns_solve)

        result = RhcSolver().solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=18,
            max_windows=2,
            backtracking_enabled=True,
            backtracking_tail_minutes=20,
            backtracking_max_ops=4,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert len(captured_window_ops) >= 2
        first_window_ids = set(captured_window_ops[0])
        second_window_ids = set(captured_window_ops[1])
        assert first_window_ids & second_window_ids
        assert result.metadata["backtracking_enabled"] is True
        assert result.metadata["backtracking_windows"] >= 1
        assert result.metadata["backtracking_ops_total"] >= 1
        assert result.metadata["inner_window_summaries"][1]["backtracking_rewind_ops"] >= 1


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


# ═══════════════════════════════════════════════════════════════════════════
# 6. RHC inner solver integration tests (BUG-2 regression)
# ═══════════════════════════════════════════════════════════════════════════


class TestRhcInnerSolver:
    """Verify that RHC actually delegates to the named inner solver."""

    def test_rhc_with_alns_inner_produces_feasible_result(self) -> None:
        """RHC-ALNS must produce a feasible schedule using ALNS per window."""
        from synaps.solvers.rhc_solver import RhcSolver
        from synaps.validation import verify_schedule_result

        problem = _make_3state_problem(n_orders=12, ops_per_order=3)
        solver = RhcSolver()
        result = solver.solve(
            problem,
            window_minutes=360,
            overlap_minutes=60,
            inner_solver="alns",
            time_limit_s=60,
            max_ops_per_window=100,
            inner_kwargs={
                "max_iterations": 30,
                "time_limit_s": 15,
                "destroy_fraction": 0.2,
                "min_destroy": 2,
                "max_destroy": 8,
                "repair_time_limit_s": 3,
            },
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(result.assignments) == len(problem.operations)
        assert result.metadata["inner_solver"] == "alns"
        assert "inner_window_summaries" in result.metadata
        assert result.metadata["inner_window_summaries"]
        first_window = result.metadata["inner_window_summaries"][0]
        assert first_window["inner_status"] in {"feasible", "optimal"}
        assert first_window["initial_solver"] in {"beam", "greedy"}
        assert "iterations_completed" in first_window
        assert "cpsat_repair_skips_large_destroy" in first_window
        assert "cpsat_max_destroy_ops" in first_window
        assert "cpsat_repair_attempts" in first_window
        assert "cpsat_repair_timeouts" in first_window
        assert "greedy_repairs" in first_window
        assert "greedy_repair_attempts" in first_window
        assert "greedy_repair_timeouts" in first_window
        assert "cpsat_repair_ms_total" in first_window
        assert "greedy_repair_ms_total" in first_window
        assert "repair_rejection_reasons" in first_window
        assert "time_limit_exhausted_before_search" in first_window
        assert "max_no_improve_iters" in first_window
        assert "no_improve_early_stop" in first_window
        assert "no_improve_streak_final" in first_window
        assert "feasibility_failures" in first_window
        assert first_window["cpsat_repair_attempts"] >= first_window["cpsat_repairs"]
        assert first_window["greedy_repair_attempts"] >= first_window["greedy_repairs"]

        verification = verify_schedule_result(problem, result)
        assert verification.feasible, f"Violations: {verification.violations}"

    def test_rhc_passes_pressure_context_to_alns_inner(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should pass pressure context used for dynamic ALNS no-improve scaling."""
        from synaps.solvers.greedy_dispatch import GreedyDispatch
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=5, ops_per_order=2)
        captured_inner_kwargs: list[dict[str, object]] = []

        def fake_alns_solve(self, problem, **kwargs):
            captured_inner_kwargs.append(dict(kwargs))
            return GreedyDispatch().solve(problem)

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=240,
            overlap_minutes=30,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=20,
            inner_kwargs={
                "max_iterations": 5,
                "max_no_improve_iters": 7,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert captured_inner_kwargs
        first_call = captured_inner_kwargs[0]
        assert first_call["dynamic_no_improve_enabled"] is True
        assert float(first_call["due_pressure"]) >= 0.0
        assert float(first_call["candidate_pressure"]) >= 0.0
        assert first_call["max_no_improve_iters"] == 7

    def test_rhc_auto_scales_alns_budget_before_inner_window_call(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should shrink ALNS iteration and destroy budgets when the window budget is tight."""
        from synaps.solvers.greedy_dispatch import GreedyDispatch
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=6, ops_per_order=2)
        captured_inner_kwargs: list[dict[str, object]] = []

        def fake_alns_solve(self, problem, **kwargs):
            captured_inner_kwargs.append(dict(kwargs))
            return GreedyDispatch().solve(problem)

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=240,
            overlap_minutes=0,
            inner_solver="alns",
            time_limit_s=10,
            alns_inner_window_time_cap_s=10,
            max_ops_per_window=50,
            max_windows=1,
            alns_budget_auto_scaling_enabled=True,
            alns_budget_estimated_repair_s_per_destroyed_op=0.5,
            inner_kwargs={
                "max_iterations": 100,
                "destroy_fraction": 0.5,
                "min_destroy": 1,
                "max_destroy": 10,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert captured_inner_kwargs
        first_call = captured_inner_kwargs[0]
        assert first_call["time_limit_s"] == pytest.approx(10.0)
        assert first_call["max_iterations"] == 20
        assert first_call["max_destroy"] == 1
        assert result.metadata["alns_budget_scaled_windows"] == 1
        first_window = result.metadata["inner_window_summaries"][0]
        assert first_window["alns_budget_auto_scaled"] is True
        assert first_window["alns_effective_max_iterations"] == 20
        assert first_window["alns_effective_max_destroy"] == 1

    def test_rhc_passes_overlap_tail_into_next_alns_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should reuse unfinished overlap assignments as warm start for the next window."""
        from datetime import timedelta

        from synaps.model import Assignment, ScheduleResult
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_pressure_chain_problem()
        work_center_id = problem.work_centers[0].id
        ops_by_seq = sorted(problem.operations, key=lambda op: op.seq_in_order)
        captured_warm_starts: list[list[Assignment]] = []

        def fake_alns_solve(self, sub_problem, **kwargs):
            supplied_warm_start = list(kwargs.get("warm_start_assignments", []) or [])
            captured_warm_starts.append(supplied_warm_start)

            assignments = []
            for op in sorted(sub_problem.operations, key=lambda op: op.seq_in_order):
                start_offset = op.seq_in_order * 40
                start_time = problem.planning_horizon_start + timedelta(minutes=start_offset)
                assignments.append(
                    Assignment(
                        operation_id=op.id,
                        work_center_id=work_center_id,
                        start_time=start_time,
                        end_time=start_time + timedelta(minutes=10),
                        setup_minutes=0,
                        aux_resource_ids=[],
                    )
                )

            return ScheduleResult(
                solver_name="alns",
                status=SolverStatus.FEASIBLE,
                assignments=assignments,
                metadata={
                    "warm_start_used": bool(supplied_warm_start),
                    "warm_start_supplied_assignments": len(supplied_warm_start),
                    "warm_start_completed_assignments": 0,
                },
            )

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=30,
            overlap_minutes=120,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=10,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(captured_warm_starts) >= 2
        assert captured_warm_starts[0] == []

        expected_tail_ids = {ops_by_seq[1].id, ops_by_seq[2].id}
        assert {
            assignment.operation_id for assignment in captured_warm_starts[1]
        } == expected_tail_ids

    def test_rhc_passes_external_warm_start_into_first_alns_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should pass external warm start assignments.

        The first inner window should receive them as a refinement seed.
        """
        from datetime import timedelta

        from synaps.model import Assignment
        from synaps.solvers.greedy_dispatch import GreedyDispatch
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_pressure_chain_problem()
        work_center_id = problem.work_centers[0].id
        ops_by_seq = sorted(problem.operations, key=lambda op: op.seq_in_order)
        captured_warm_starts: list[list[Assignment]] = []

        external_warm_start = [
            Assignment(
                operation_id=ops_by_seq[0].id,
                work_center_id=work_center_id,
                start_time=problem.planning_horizon_start,
                end_time=problem.planning_horizon_start + timedelta(minutes=10),
                setup_minutes=0,
                aux_resource_ids=[],
            ),
            Assignment(
                operation_id=ops_by_seq[1].id,
                work_center_id=work_center_id,
                start_time=problem.planning_horizon_start + timedelta(minutes=10),
                end_time=problem.planning_horizon_start + timedelta(minutes=20),
                setup_minutes=0,
                aux_resource_ids=[],
            ),
        ]

        def fake_alns_solve(self, sub_problem, **kwargs):
            supplied_warm_start = list(kwargs.get("warm_start_assignments", []) or [])
            captured_warm_starts.append(supplied_warm_start)
            return GreedyDispatch().solve(sub_problem)

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=240,
            overlap_minutes=30,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=20,
            max_windows=1,
            warm_start_assignments=external_warm_start,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert captured_warm_starts
        assert {
            assignment.operation_id for assignment in captured_warm_starts[0]
        } == {ops_by_seq[0].id, ops_by_seq[1].id}
        assert result.metadata["external_warm_start_supplied_assignments"] == 2
        assert result.metadata["external_warm_start_used_windows"] == 1

    def test_rhc_retains_boundary_crossing_assignments_for_next_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Assignments crossing the boundary must stay tentative for the next window."""
        from datetime import timedelta

        from synaps.model import Assignment, ScheduleResult
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_pressure_chain_problem()
        work_center_id = problem.work_centers[0].id
        ops_by_seq = sorted(problem.operations, key=lambda op: op.seq_in_order)
        captured_warm_starts: list[list[Assignment]] = []

        start_offsets = [0, 20, 50]
        end_offsets = [20, 50, 60]

        def fake_alns_solve(self, sub_problem, **kwargs):
            supplied_warm_start = list(kwargs.get("warm_start_assignments", []) or [])
            captured_warm_starts.append(supplied_warm_start)

            assignments = []
            for op, start_offset, end_offset in zip(
                sorted(sub_problem.operations, key=lambda op: op.seq_in_order),
                start_offsets,
                end_offsets,
                strict=False,
            ):
                start_time = problem.planning_horizon_start + timedelta(minutes=start_offset)
                end_time = problem.planning_horizon_start + timedelta(minutes=end_offset)
                assignments.append(
                    Assignment(
                        operation_id=op.id,
                        work_center_id=work_center_id,
                        start_time=start_time,
                        end_time=end_time,
                        setup_minutes=0,
                        aux_resource_ids=[],
                    )
                )

            return ScheduleResult(
                solver_name="alns",
                status=SolverStatus.FEASIBLE,
                assignments=assignments,
                metadata={
                    "warm_start_used": bool(supplied_warm_start),
                    "warm_start_supplied_assignments": len(supplied_warm_start),
                    "warm_start_completed_assignments": 0,
                },
            )

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=30,
            overlap_minutes=120,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=10,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(captured_warm_starts) >= 2
        assert captured_warm_starts[0] == []
        assert {
            assignment.operation_id for assignment in captured_warm_starts[1]
        } == {ops_by_seq[1].id, ops_by_seq[2].id}

    def test_rhc_passes_configured_alns_window_budget_to_inner_solver(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should honor an explicit ALNS per-window time cap for large-window runs."""
        from datetime import timedelta

        from synaps.model import Assignment, ScheduleResult
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_due_pressure_chain_problem()
        work_center_id = problem.work_centers[0].id
        captured_time_limits: list[float] = []

        def fake_alns_solve(self, sub_problem, **kwargs):
            captured_time_limits.append(float(kwargs["time_limit_s"]))

            assignments = []
            for op in sorted(sub_problem.operations, key=lambda op: op.seq_in_order):
                start_offset = op.seq_in_order * 40
                start_time = problem.planning_horizon_start + timedelta(minutes=start_offset)
                assignments.append(
                    Assignment(
                        operation_id=op.id,
                        work_center_id=work_center_id,
                        start_time=start_time,
                        end_time=start_time + timedelta(minutes=10),
                        setup_minutes=0,
                        aux_resource_ids=[],
                    )
                )

            return ScheduleResult(
                solver_name="alns",
                status=SolverStatus.FEASIBLE,
                assignments=assignments,
                metadata={},
            )

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=30,
            overlap_minutes=120,
            inner_solver="alns",
            time_limit_s=600,
            max_ops_per_window=10,
            alns_inner_window_time_cap_s=180,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert captured_time_limits
        assert captured_time_limits[0] == pytest.approx(180.0)
        assert result.metadata["inner_window_summaries"]
        assert result.metadata["inner_window_summaries"][0][
            "inner_time_limit_s"
        ] == pytest.approx(180.0)

    def test_rhc_uses_numpy_candidate_metrics_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should use the NumPy/native candidate-metrics seam for window scoring."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=5, ops_per_order=2)
        np_path_calls = {"count": 0}

        def fake_candidate_metrics_np(**kwargs):
            np_path_calls["count"] += 1
            n = len(kwargs["eligible_machine_indices"])
            return [0.0] * n, [1.0] * n

        monkeypatch.setattr(
            "synaps.solvers.rhc_solver.compute_rhc_candidate_metrics_batch_np",
            fake_candidate_metrics_np,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=240,
            overlap_minutes=30,
            inner_solver="greedy",
            time_limit_s=30,
            max_ops_per_window=20,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert np_path_calls["count"] >= 1

    def test_rhc_with_cpsat_inner_produces_feasible_result(self) -> None:
        """RHC-CPSAT must delegate to CP-SAT per window."""
        from synaps.solvers.rhc_solver import RhcSolver
        from synaps.validation import verify_schedule_result

        problem = _make_3state_problem(n_orders=4, ops_per_order=2)
        solver = RhcSolver()
        result = solver.solve(
            problem,
            window_minutes=480,
            overlap_minutes=60,
            inner_solver="cpsat",
            time_limit_s=30,
            max_ops_per_window=50,
            inner_kwargs={"time_limit_s": 10},
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(result.assignments) == len(problem.operations)
        assert result.metadata["inner_solver"] == "cpsat"

        verification = verify_schedule_result(problem, result)
        assert verification.feasible, f"Violations: {verification.violations}"

    def test_rhc_greedy_fallback_still_works(self) -> None:
        """When inner_solver='greedy', RHC should still schedule via greedy dispatch."""
        from synaps.solvers.rhc_solver import RhcSolver
        from synaps.validation import verify_schedule_result

        problem = _make_3state_problem(n_orders=6, ops_per_order=2)
        solver = RhcSolver()
        result = solver.solve(
            problem,
            window_minutes=360,
            overlap_minutes=60,
            inner_solver="greedy",
            time_limit_s=15,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(result.assignments) == len(problem.operations)
        assert result.metadata["inner_solver"] == "greedy"
        assert result.metadata["acceleration"]["rhc_candidate_metrics_backend"] in {
            "python",
            "native",
        }

        verification = verify_schedule_result(problem, result)
        assert verification.feasible, f"Violations: {verification.violations}"

    def test_rhc_clips_assignments_beyond_horizon(self) -> None:
        """RHC should never return assignments that end after planning horizon."""
        from synaps.solvers.feasibility_checker import FeasibilityChecker
        from synaps.solvers.rhc_solver import RhcSolver

        state_id = uuid4()
        work_center_id = uuid4()
        order_id = uuid4()
        op1_id = uuid4()
        op2_id = uuid4()

        problem = ScheduleProblem(
            states=[State(id=state_id, code="HZ", label="Horizon")],
            orders=[
                Order(
                    id=order_id,
                    external_ref="HZ-0001",
                    due_date=HORIZON_START + timedelta(minutes=60),
                    priority=1000,
                )
            ],
            operations=[
                Operation(
                    id=op1_id,
                    order_id=order_id,
                    seq_in_order=0,
                    state_id=state_id,
                    base_duration_min=40,
                    eligible_wc_ids=[work_center_id],
                    predecessor_op_id=None,
                ),
                Operation(
                    id=op2_id,
                    order_id=order_id,
                    seq_in_order=1,
                    state_id=state_id,
                    base_duration_min=40,
                    eligible_wc_ids=[work_center_id],
                    predecessor_op_id=op1_id,
                ),
            ],
            work_centers=[
                WorkCenter(
                    id=work_center_id,
                    code="HZ-M1",
                    capability_group="hz",
                    speed_factor=1.0,
                )
            ],
            setup_matrix=[],
            planning_horizon_start=HORIZON_START,
            planning_horizon_end=HORIZON_START + timedelta(minutes=60),
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="greedy",
            max_ops_per_window=10,
            time_limit_s=20,
        )

        violations = FeasibilityChecker().check(problem, result.assignments)
        assert all(v.kind != "HORIZON_BOUND_VIOLATION" for v in violations)
        assert result.metadata["horizon_clipped_assignments"] >= 1

    def test_rhc_records_fallback_window_summary_when_inner_solver_is_rejected(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fallback-greedy windows must still appear in inner_window_summaries."""
        from synaps.model import ScheduleResult
        from synaps.solvers.rhc_solver import RhcSolver
        from synaps.validation import verify_schedule_result

        problem = _make_3state_problem(n_orders=4, ops_per_order=2)

        def fake_alns_solve(self, problem, **kwargs):
            return ScheduleResult(
                solver_name="alns",
                status=SolverStatus.ERROR,
                assignments=[],
                duration_ms=5,
                metadata={"final_violations": 1},
            )

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=480,
            overlap_minutes=60,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=50,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["inner_window_summaries"]
        first_window = result.metadata["inner_window_summaries"][0]
        assert first_window["resolution_mode"] == "fallback_greedy"
        assert first_window["fallback_reason"] == "inner_status_error"
        assert first_window["inner_status"] == "error"
        assert first_window["final_violations"] == 1
        assert first_window["fallback_iterations"] > 0
        assert first_window["ops_committed"] > 0
        assert result.metadata["inner_fallback_windows"] >= 1
        assert result.metadata["inner_fallback_ratio"] > 0.0
        assert result.metadata["inner_resolution_counts"]["fallback_greedy"] >= 1

        verification = verify_schedule_result(problem, result)
        assert verification.feasible, f"Violations: {verification.violations}"

    def test_rhc_hybrid_routes_dense_window_to_cpsat(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should route ALNS windows to CP-SAT when hybrid thresholds are triggered."""
        from synaps.solvers.greedy_dispatch import GreedyDispatch
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=4, ops_per_order=2)
        captured_cpsat_kwargs: list[dict[str, object]] = []

        def fail_if_alns_called(self, problem, **kwargs):
            raise AssertionError("ALNS should be bypassed by hybrid routing")

        def fake_cpsat(self, problem, **kwargs):
            captured_cpsat_kwargs.append(dict(kwargs))
            return GreedyDispatch().solve(problem)

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fail_if_alns_called,
        )
        monkeypatch.setattr(
            "synaps.solvers.cpsat_solver.CpSatSolver.solve",
            fake_cpsat,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=480,
            overlap_minutes=60,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=50,
            hybrid_inner_routing_enabled=True,
            hybrid_inner_solver="cpsat",
            hybrid_due_pressure_threshold=0.0,
            hybrid_candidate_pressure_threshold=0.0,
            hybrid_max_ops=1000,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["hybrid_route_attempts"] >= 1
        assert result.metadata["hybrid_route_activations"] >= 1
        assert result.metadata["hybrid_route_activation_rate"] > 0.0
        assert result.metadata["inner_window_summaries"]
        assert result.metadata["inner_window_summaries"][0]["inner_solver_selected"] == "cpsat"
        assert captured_cpsat_kwargs
        assert captured_cpsat_kwargs[0]["auto_greedy_warm_start"] is False

    def test_rhc_skips_inner_alns_when_budget_below_minimum(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RHC should skip inner ALNS and use fallback greedy when budget is too low."""
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=4, ops_per_order=2)

        def fail_if_called(self, problem, **kwargs):
            raise AssertionError("inner ALNS should be skipped due to low budget")

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fail_if_called,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=480,
            overlap_minutes=60,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=50,
            inner_solver_min_budget_s=1000,
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["inner_solver_min_budget_s"] == 1000
        assert result.metadata["inner_window_summaries"]
        first_window = result.metadata["inner_window_summaries"][0]
        assert first_window["resolution_mode"] == "fallback_greedy"
        assert first_window["fallback_reason"] == "inner_skipped_low_budget"
        assert first_window["inner_status"] == "not_run"
        assert first_window["fallback_iterations"] > 0
        assert first_window["ops_committed"] > 0

    def test_rhc_inner_kwargs_time_limit_no_duplicate_kwarg(self) -> None:
        """Regression: inner_kwargs containing time_limit_s must not cause TypeError.

        Before the fix, RHC passed time_limit_s= explicitly AND via **inner_kwargs,
        resulting in 'got multiple values for keyword argument time_limit_s'.
        """
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_3state_problem(n_orders=4, ops_per_order=2)
        solver = RhcSolver()
        # This must NOT raise TypeError
        result = solver.solve(
            problem,
            window_minutes=480,
            overlap_minutes=60,
            inner_solver="alns",
            time_limit_s=30,
            inner_kwargs={
                "time_limit_s": 999,  # would collide without the pop() guard
                "max_iterations": 10,
            },
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        # The key invariant: solver ran without TypeError
        assert result.metadata["inner_solver"] == "alns"

    def test_rhc_reanchors_inner_assignments_before_freeze_merge(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Inner-window schedules should be re-anchored against frozen machine occupancy."""
        from datetime import timedelta

        from synaps.model import Assignment, ScheduleResult
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_long_chain_problem(12)
        work_center_id = problem.work_centers[0].id

        def fake_alns_solve(self, sub_problem, **kwargs):
            assignments = []
            for local_index, op in enumerate(
                sorted(sub_problem.operations, key=lambda op: op.seq_in_order)
            ):
                start_time = problem.planning_horizon_start + timedelta(
                    minutes=local_index * 10
                )
                assignments.append(
                    Assignment(
                        operation_id=op.id,
                        work_center_id=work_center_id,
                        start_time=start_time,
                        end_time=start_time + timedelta(minutes=10),
                        setup_minutes=0,
                        aux_resource_ids=[],
                    )
                )

            return ScheduleResult(
                solver_name="alns",
                status=SolverStatus.FEASIBLE,
                assignments=assignments,
                duration_ms=1,
                metadata={"initial_solver": "greedy"},
            )

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=30,
            overlap_minutes=0,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=12,
            max_windows=2,
            candidate_admission_enabled=False,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert result.metadata["boundary_reanchor_windows"] >= 1
        assert result.metadata["boundary_reanchor_changed_ops_total"] >= 1
        assert result.metadata["temporal_stabilization"]["machine_shifts"] == 0
        assert result.metadata["inner_window_summaries"]
        second_window = result.metadata["inner_window_summaries"][1]
        assert second_window["resolution_mode"] == "inner"
        assert second_window["boundary_reanchor_ops"] >= 1
        assert second_window["boundary_reanchor_changed_ops"] >= 1

    def test_rhc_passes_frozen_context_into_followup_alns_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Follow-up ALNS windows should receive committed-prefix context directly."""
        from datetime import timedelta

        from synaps.model import Assignment, ScheduleResult
        from synaps.solvers.rhc_solver import RhcSolver

        problem = _make_long_chain_problem(12)
        work_center_id = problem.work_centers[0].id
        captured_calls: list[dict[str, object]] = []

        def fake_alns_solve(self, sub_problem, **kwargs):
            captured_calls.append(dict(kwargs))
            assignments = []
            for local_index, op in enumerate(
                sorted(sub_problem.operations, key=lambda op: op.seq_in_order)
            ):
                start_time = problem.planning_horizon_start + timedelta(
                    minutes=local_index * 10
                )
                assignments.append(
                    Assignment(
                        operation_id=op.id,
                        work_center_id=work_center_id,
                        start_time=start_time,
                        end_time=start_time + timedelta(minutes=10),
                        setup_minutes=0,
                        aux_resource_ids=[],
                    )
                )

            return ScheduleResult(
                solver_name="alns",
                status=SolverStatus.FEASIBLE,
                assignments=assignments,
                duration_ms=1,
                metadata={"initial_solver": "greedy"},
            )

        monkeypatch.setattr(
            "synaps.solvers.alns_solver.AlnsSolver.solve",
            fake_alns_solve,
        )

        result = RhcSolver().solve(
            problem,
            window_minutes=30,
            overlap_minutes=0,
            inner_solver="alns",
            time_limit_s=30,
            max_ops_per_window=12,
            max_windows=2,
            candidate_admission_enabled=False,
            inner_kwargs={
                "max_iterations": 5,
                "use_cpsat_repair": False,
            },
        )

        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL, SolverStatus.ERROR)
        assert len(captured_calls) >= 2
        second_call = captured_calls[1]
        frozen_assignments = second_call["frozen_assignments"]
        assert frozen_assignments
        assert {
            assignment.operation_id for assignment in frozen_assignments
        } <= {assignment.operation_id for assignment in result.assignments}


# ═══════════════════════════════════════════════════════════════════════════
# 7. ALNS CP-SAT repair integration tests (BUG-3 regression)
# ═══════════════════════════════════════════════════════════════════════════


class TestAlnsCpsatRepair:
    """Verify that ALNS uses CP-SAT repair when use_cpsat_repair=True."""

    def test_repair_cpsat_timeout_without_assignments_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Regression: CP-SAT timeout with no assignments must not count as a repair."""
        from types import SimpleNamespace

        import synaps.solvers.alns_solver as alns_module

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)
        destroyed_op_ids = {problem.operations[0].id, problem.operations[1].id}

        def fake_cpsat_solve(self, sub_problem, **kwargs):
            return SimpleNamespace(status=SolverStatus.TIMEOUT, assignments=[])

        monkeypatch.setattr(
            "synaps.solvers.cpsat_solver.CpSatSolver.solve",
            fake_cpsat_solve,
        )

        repaired = alns_module._repair_cpsat(
            problem,
            frozen_assignments=[],
            destroyed_op_ids=destroyed_op_ids,
        )

        assert repaired is None

    def test_repair_cpsat_timeout_outcome_is_explicit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Outcome API should classify CP-SAT timeout explicitly."""
        from types import SimpleNamespace

        import synaps.solvers.alns_solver as alns_module

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)
        destroyed_op_ids = {problem.operations[0].id, problem.operations[1].id}

        def fake_cpsat_solve(self, sub_problem, **kwargs):
            return SimpleNamespace(status=SolverStatus.TIMEOUT, assignments=[])

        monkeypatch.setattr(
            "synaps.solvers.cpsat_solver.CpSatSolver.solve",
            fake_cpsat_solve,
        )

        outcome = alns_module._repair_cpsat_outcome(
            problem,
            frozen_assignments=[],
            destroyed_op_ids=destroyed_op_ids,
        )

        assert outcome.status == alns_module.RepairStatus.TIMEOUT
        assert outcome.reason == "cpsat_timeout"
        assert outcome.assignments == ()

    def test_repair_cpsat_disables_auto_greedy_warm_start(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ALNS CP-SAT repair must not spend budget on implicit GreedyDispatch warm starts."""
        from types import SimpleNamespace

        import synaps.solvers.alns_solver as alns_module

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)
        destroyed_op_ids = {problem.operations[0].id, problem.operations[1].id}
        captured_kwargs: dict[str, object] = {}

        def fake_cpsat_solve(self, sub_problem, **kwargs):
            captured_kwargs.update(kwargs)
            return SimpleNamespace(status=SolverStatus.TIMEOUT, assignments=[])

        monkeypatch.setattr(
            "synaps.solvers.cpsat_solver.CpSatSolver.solve",
            fake_cpsat_solve,
        )

        outcome = alns_module._repair_cpsat_outcome(
            problem,
            frozen_assignments=[],
            destroyed_op_ids=destroyed_op_ids,
            num_workers=2,
        )

        assert outcome.status == alns_module.RepairStatus.TIMEOUT
        assert captured_kwargs["auto_greedy_warm_start"] is False
        assert captured_kwargs["num_workers"] == 2

    def test_repair_greedy_partial_assignment_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Greedy fallback must reject partial repairs instead of emitting incomplete candidates."""
        from datetime import timedelta
        from types import SimpleNamespace

        import synaps.solvers.alns_solver as alns_module
        from synaps.model import Assignment

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)
        destroyed = {problem.operations[0].id, problem.operations[1].id}
        horizon_start = problem.planning_horizon_start

        partial_assignment = Assignment(
            operation_id=problem.operations[0].id,
            work_center_id=problem.work_centers[0].id,
            start_time=horizon_start,
            end_time=horizon_start + timedelta(minutes=10),
            setup_minutes=0,
            aux_resource_ids=[],
        )

        def fake_incremental_repair(self, problem, **kwargs):
            return SimpleNamespace(
                status=SolverStatus.FEASIBLE,
                assignments=[partial_assignment],
            )

        monkeypatch.setattr(
            "synaps.solvers.incremental_repair.IncrementalRepair.solve",
            fake_incremental_repair,
        )

        repaired = alns_module._repair_greedy(
            problem,
            frozen_assignments=[],
            destroyed_op_ids=destroyed,
        )

        assert repaired is None

    def test_repair_greedy_partial_assignment_outcome_is_infeasible(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Outcome API should mark partial greedy repairs as infeasible."""
        from datetime import timedelta
        from types import SimpleNamespace

        import synaps.solvers.alns_solver as alns_module
        from synaps.model import Assignment

        problem = _make_3state_problem(n_orders=3, ops_per_order=2)
        destroyed = {problem.operations[0].id, problem.operations[1].id}
        horizon_start = problem.planning_horizon_start

        partial_assignment = Assignment(
            operation_id=problem.operations[0].id,
            work_center_id=problem.work_centers[0].id,
            start_time=horizon_start,
            end_time=horizon_start + timedelta(minutes=10),
            setup_minutes=0,
            aux_resource_ids=[],
        )

        def fake_incremental_repair(self, problem, **kwargs):
            return SimpleNamespace(
                status=SolverStatus.FEASIBLE,
                assignments=[partial_assignment],
            )

        monkeypatch.setattr(
            "synaps.solvers.incremental_repair.IncrementalRepair.solve",
            fake_incremental_repair,
        )

        outcome = alns_module._repair_greedy_outcome(
            problem,
            frozen_assignments=[],
            destroyed_op_ids=destroyed,
        )

        assert outcome.status == alns_module.RepairStatus.INFEASIBLE
        assert outcome.reason == "partial_assignment"
        assert outcome.assignments == ()

    def test_repair_greedy_outcome_uses_stable_disrupted_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Greedy repair must pass disrupted ids to IncrementalRepair in operation order."""
        from datetime import timedelta
        from types import SimpleNamespace

        import synaps.solvers.alns_solver as alns_module
        from synaps.model import Assignment

        problem = _make_3state_problem(n_orders=2, ops_per_order=3)
        target_ops = {problem.operations[2].id, problem.operations[0].id, problem.operations[1].id}
        call_args: dict[str, list] = {}
        horizon_start = problem.planning_horizon_start

        assignments = [
            Assignment(
                operation_id=problem.operations[0].id,
                work_center_id=problem.work_centers[0].id,
                start_time=horizon_start,
                end_time=horizon_start + timedelta(minutes=10),
                setup_minutes=0,
                aux_resource_ids=[],
            ),
            Assignment(
                operation_id=problem.operations[1].id,
                work_center_id=problem.work_centers[0].id,
                start_time=horizon_start + timedelta(minutes=10),
                end_time=horizon_start + timedelta(minutes=20),
                setup_minutes=0,
                aux_resource_ids=[],
            ),
            Assignment(
                operation_id=problem.operations[2].id,
                work_center_id=problem.work_centers[0].id,
                start_time=horizon_start + timedelta(minutes=20),
                end_time=horizon_start + timedelta(minutes=30),
                setup_minutes=0,
                aux_resource_ids=[],
            ),
        ]

        def fake_incremental_repair(self, problem, **kwargs):
            call_args["disrupted_op_ids"] = kwargs["disrupted_op_ids"]
            return SimpleNamespace(
                status=SolverStatus.FEASIBLE,
                assignments=assignments,
            )

        monkeypatch.setattr(
            "synaps.solvers.incremental_repair.IncrementalRepair.solve",
            fake_incremental_repair,
        )

        outcome = alns_module._repair_greedy_outcome(
            problem,
            frozen_assignments=[],
            destroyed_op_ids=target_ops,
        )

        assert outcome.status == alns_module.RepairStatus.FEASIBLE
        expected_order = [
            problem.operations[0].id,
            problem.operations[1].id,
            problem.operations[2].id,
        ]
        assert call_args["disrupted_op_ids"] == expected_order

    def test_repair_cpsat_outcome_sorts_assignments_by_operation_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """CP-SAT repair outcome should normalize assignment order by operation positions."""
        from datetime import timedelta
        from types import SimpleNamespace

        import synaps.solvers.alns_solver as alns_module
        from synaps.model import Assignment

        problem = _make_3state_problem(n_orders=2, ops_per_order=2)
        destroyed_op_ids = {problem.operations[0].id, problem.operations[1].id}
        horizon_start = problem.planning_horizon_start

        reversed_assignments = [
            Assignment(
                operation_id=problem.operations[1].id,
                work_center_id=problem.work_centers[0].id,
                start_time=horizon_start + timedelta(minutes=10),
                end_time=horizon_start + timedelta(minutes=20),
                setup_minutes=0,
                aux_resource_ids=[],
            ),
            Assignment(
                operation_id=problem.operations[0].id,
                work_center_id=problem.work_centers[0].id,
                start_time=horizon_start,
                end_time=horizon_start + timedelta(minutes=10),
                setup_minutes=0,
                aux_resource_ids=[],
            ),
        ]

        def fake_cpsat_solve(self, sub_problem, **kwargs):
            return SimpleNamespace(status=SolverStatus.FEASIBLE, assignments=reversed_assignments)

        monkeypatch.setattr(
            "synaps.solvers.cpsat_solver.CpSatSolver.solve",
            fake_cpsat_solve,
        )

        outcome = alns_module._repair_cpsat_outcome(
            problem,
            frozen_assignments=[],
            destroyed_op_ids=destroyed_op_ids,
        )

        assert outcome.status == alns_module.RepairStatus.FEASIBLE
        assert [assignment.operation_id for assignment in outcome.assignments] == [
            problem.operations[0].id,
            problem.operations[1].id,
        ]

    def test_repair_cpsat_outcome_respects_frozen_machine_intervals(self) -> None:
        """CP-SAT repair must not overlap frozen machine occupancy."""
        from datetime import timedelta

        import synaps.solvers.alns_solver as alns_module
        from synaps.model import Assignment

        problem = _make_3state_problem(n_orders=1, ops_per_order=2)
        frozen_op = problem.operations[0].model_copy(update={"eligible_wc_ids": [WC1]})
        destroyed_op = problem.operations[1].model_copy(
            update={"eligible_wc_ids": [WC1], "predecessor_op_id": None}
        )
        constrained_problem = problem.model_copy(update={"operations": [frozen_op, destroyed_op]})
        frozen_assignment = Assignment(
            operation_id=frozen_op.id,
            work_center_id=WC1,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=30),
            setup_minutes=0,
            aux_resource_ids=[],
        )

        outcome = alns_module._repair_cpsat_outcome(
            constrained_problem,
            frozen_assignments=[frozen_assignment],
            destroyed_op_ids={destroyed_op.id},
            time_limit_s=3,
        )

        assert outcome.status == alns_module.RepairStatus.FEASIBLE
        assert len(outcome.assignments) == 1
        repaired = outcome.assignments[0]
        assert repaired.work_center_id == WC1
        assert repaired.start_time >= frozen_assignment.end_time

    def test_repair_cpsat_outcome_respects_frozen_predecessor_end(self) -> None:
        """CP-SAT repair must honor frozen predecessors that stay outside the sub-problem."""
        from datetime import timedelta

        import synaps.solvers.alns_solver as alns_module
        from synaps.model import Assignment

        problem = _make_3state_problem(n_orders=1, ops_per_order=2)
        frozen_op = problem.operations[0].model_copy(update={"eligible_wc_ids": [WC1]})
        destroyed_op = problem.operations[1].model_copy(update={"eligible_wc_ids": [WC2]})
        constrained_problem = problem.model_copy(update={"operations": [frozen_op, destroyed_op]})
        frozen_assignment = Assignment(
            operation_id=frozen_op.id,
            work_center_id=WC1,
            start_time=HORIZON_START + timedelta(minutes=5),
            end_time=HORIZON_START + timedelta(minutes=45),
            setup_minutes=0,
            aux_resource_ids=[],
        )

        outcome = alns_module._repair_cpsat_outcome(
            constrained_problem,
            frozen_assignments=[frozen_assignment],
            destroyed_op_ids={destroyed_op.id},
            time_limit_s=3,
        )

        assert outcome.status == alns_module.RepairStatus.FEASIBLE
        assert len(outcome.assignments) == 1
        repaired = outcome.assignments[0]
        assert repaired.work_center_id == WC2
        assert repaired.start_time >= frozen_assignment.end_time

    def test_alns_cpsat_repair_produces_feasible_result(self) -> None:
        """ALNS with use_cpsat_repair=True must exercise CP-SAT repair path."""
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
            use_cpsat_repair=True,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert len(result.assignments) == len(problem.operations)
        # CP-SAT repair should have been used at least once
        assert result.metadata["cpsat_repairs"] > 0

        verification = verify_schedule_result(problem, result)
        assert verification.feasible, f"Violations: {verification.violations}"

    def test_alns_greedy_only_repair_has_zero_cpsat_repairs(self) -> None:
        """ALNS with use_cpsat_repair=False should only use greedy repair."""
        from synaps.solvers.alns_solver import AlnsSolver

        problem = _make_3state_problem(n_orders=5, ops_per_order=2)
        solver = AlnsSolver()
        result = solver.solve(
            problem,
            max_iterations=30,
            time_limit_s=15,
            use_cpsat_repair=False,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["cpsat_repairs"] == 0
        assert result.metadata["greedy_repairs"] > 0
