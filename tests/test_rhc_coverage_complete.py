"""Regression tests for RHC coverage-complete / residual-fill policy."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.registry import available_solver_configs, create_solver
from synaps.solvers.rhc import RhcPolicy, RhcSolver

if TYPE_CHECKING:
    import pytest

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)


def _chain_problem(*, n_ops: int = 24, duration: int = 30) -> ScheduleProblem:
    state = State(id=uuid4(), code="S0", label="S0")
    wc = WorkCenter(id=uuid4(), code="M1", capability_group="g", speed_factor=1.0)
    order = Order(
        id=uuid4(),
        external_ref="O1",
        due_date=HORIZON_START + timedelta(days=30),
        priority=1,
    )
    operations: list[Operation] = []
    prev = None
    for seq in range(n_ops):
        op_id = uuid4()
        operations.append(
            Operation(
                id=op_id,
                order_id=order.id,
                seq_in_order=seq,
                state_id=state.id,
                base_duration_min=duration,
                eligible_wc_ids=[wc.id],
                predecessor_op_id=prev,
            )
        )
        prev = op_id
    # Tight declared horizon: without extension many late ops clip.
    horizon_end = HORIZON_START + timedelta(minutes=n_ops * duration // 2)
    return ScheduleProblem(
        states=[state],
        orders=[order],
        operations=operations,
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=horizon_end,
    )


class TestCoverageReserveAndSoftFallback:
    def test_soft_overrun_runs_fallback_after_window_budget(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import synaps.solvers.rhc._solver as rhc_module

        problem = _chain_problem(n_ops=12, duration=20)
        # Window budget trips immediately; soft budget still allows residual fill.
        marks = iter([0.0, 0.0, 0.0, 10.0, 10.0, 10.1, 10.2, 10.3, 10.4, 10.5])

        def fake_monotonic() -> float:
            try:
                return next(marks)
            except StopIteration:
                return 10.5

        monkeypatch.setattr(rhc_module.time, "monotonic", fake_monotonic)

        result = RhcSolver(policy=RhcPolicy.BALANCED).solve(
            problem,
            window_minutes=60,
            overlap_minutes=0,
            inner_solver="greedy",
            time_limit_s=5.0,
            coverage_time_reserve_fraction=0.5,
            coverage_time_reserve_min_s=2.0,
            coverage_time_reserve_max_s=3.0,
            fallback_repair_on_timeout=True,
            fallback_repair_soft_budget_s=20.0,
            coverage_horizon_extension_factor=3.0,
            max_ops_per_window=2,
            max_windows=1,
        )

        assert result.metadata["fallback_repair_skipped"] is False
        assert result.metadata["fallback_repair_attempted"] is True
        assert result.metadata["coverage_reserve_s"] > 0.0
        assert result.metadata["planning_horizon_extended"] is True

    def test_greedy_cover_policy_schedules_full_small_chain(self) -> None:
        problem = _chain_problem(n_ops=8, duration=15)
        result = RhcSolver(policy=RhcPolicy.GREEDY_COVER).solve(
            problem,
            time_limit_s=30,
            max_windows=20,
            # Fixture horizon is intentionally half of chain length; cover needs room.
            coverage_horizon_extension_factor=4.0,
        )
        assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
        assert result.metadata["ops_unscheduled"] == 0
        assert len(result.assignments) == len(problem.operations)

    def test_coverage_reserve_never_exceeds_half_budget(self) -> None:
        """Short timeboxes must not starve the window loop via min reserve."""
        problem = _chain_problem(n_ops=6, duration=10)
        result = RhcSolver(policy=RhcPolicy.GREEDY_COVER).solve(
            problem,
            time_limit_s=40,
            coverage_time_reserve_fraction=0.20,
            coverage_time_reserve_min_s=60.0,
            coverage_time_reserve_max_s=300.0,
            coverage_horizon_extension_factor=4.0,
            max_windows=5,
        )
        assert result.metadata["coverage_reserve_s"] == 20.0
        assert result.metadata["window_time_limit_s"] == 20.0

    def test_registry_exposes_rhc_greedy_cover(self) -> None:
        assert "RHC-GREEDY-COVER" in available_solver_configs()
        solver, kwargs = create_solver("RHC-GREEDY-COVER")
        assert solver.name == "rhc"
        assert kwargs["inner_solver"] == "greedy"
        assert kwargs["coverage_time_reserve_fraction"] == 0.20
        assert float(kwargs["time_limit_s"]) == 1800.0

    def test_window_bound_inner_horizon_shrinks_subproblem(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Inner ALNS subproblems should not use the full planning horizon."""
        from synaps.solvers.alns_solver import AlnsSolver
        from synaps.solvers.greedy_dispatch import GreedyDispatch

        problem = _chain_problem(n_ops=12, duration=20)
        # Generous declared horizon so window bound is the tighter constraint.
        problem = problem.model_copy(
            update={
                "planning_horizon_end": HORIZON_START + timedelta(days=30),
            }
        )
        captured_ends: list[object] = []

        def fake_alns_solve(self: object, sub_problem: object, **kwargs: object) -> object:
            captured_ends.append(sub_problem.planning_horizon_end)
            return GreedyDispatch().solve(sub_problem)  # type: ignore[arg-type]

        monkeypatch.setattr(AlnsSolver, "solve", fake_alns_solve)

        result = RhcSolver(policy=RhcPolicy.BALANCED).solve(
            problem,
            inner_solver="alns",
            window_minutes=120,
            overlap_minutes=0,
            time_limit_s=30,
            max_windows=1,
            max_ops_per_window=20,
            window_bound_inner_horizon=True,
            window_horizon_slack_minutes=30.0,
            coverage_horizon_extension_factor=1.0,
            fallback_repair_on_timeout=True,
            coverage_time_reserve_fraction=0.0,
        )

        assert captured_ends, "expected at least one ALNS subproblem"
        full_end = problem.planning_horizon_end
        expected_end = HORIZON_START + timedelta(minutes=120 + 30)
        assert captured_ends[0] == expected_end
        assert captured_ends[0] < full_end
        assert result.metadata["window_bound_inner_horizon"] is True
