"""K3.6: ALNS must not burn the box on native seed/completion at n>=2000."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from synaps.model import Assignment, ScheduleProblem, ScheduleResult, SolverStatus
from synaps.solvers.alns_solver import AlnsSolver, _try_native_initial_seed
from tests.conftest import HORIZON_START, make_simple_problem

if TYPE_CHECKING:
    import pytest


def test_try_native_initial_seed_skips_at_append_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import synaps.solvers.alns_solver as alns

    monkeypatch.setattr(alns, "APPEND_GAP_SCAN_MIN_OPS", 1)
    problem = make_simple_problem(n_orders=1, ops_per_order=2)
    ops_by_id = {op.id: op for op in problem.operations}

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("native greedy_repair_batch must not run at append threshold")

    monkeypatch.setattr("synaps.accelerators._native_greedy_repair_batch", boom)
    result = _try_native_initial_seed(
        problem,
        frozen_assignments=[],
        ops_by_id=ops_by_id,
        frozen_assignments_by_op={},
    )
    assert result is None


def test_alns_enters_search_without_completion_repair_at_append_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fell before fix: native completion of thousands of holes never entered search."""

    import synaps.solvers.alns_solver as alns

    monkeypatch.setattr(alns, "APPEND_GAP_SCAN_MIN_OPS", 1)
    problem = make_simple_problem(n_orders=2, ops_per_order=2)

    def fake_solve(
        _self: object,
        problem_arg: ScheduleProblem,
        **_kwargs: object,
    ) -> ScheduleResult:
        op = problem_arg.operations[0]
        wc = problem_arg.work_centers[0]
        assignment = Assignment(
            operation_id=op.id,
            work_center_id=wc.id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=10),
            setup_minutes=0,
        )
        return ScheduleResult(
            solver_name="greedy",
            status=SolverStatus.TIMEOUT,
            assignments=[assignment],
            metadata={"partial_schedule": True},
        )

    monkeypatch.setattr("synaps.solvers.greedy_dispatch.GreedyDispatch.solve", fake_solve)
    monkeypatch.setattr("synaps.solvers.greedy_dispatch.BeamSearchDispatch.solve", fake_solve)

    completion_sized: list[int] = []
    real_repair = alns._repair_greedy_outcome

    def spy_repair(
        problem_arg: ScheduleProblem,
        frozen: list[Assignment],
        destroyed: set[object],
        **kwargs: object,
    ) -> object:
        if len(destroyed) >= len(problem_arg.operations) - 1:
            completion_sized.append(len(destroyed))
        return real_repair(problem_arg, frozen, destroyed, **kwargs)

    monkeypatch.setattr(alns, "_repair_greedy_outcome", spy_repair)

    result = AlnsSolver().solve(
        problem,
        max_iterations=3,
        time_limit_s=20,
        use_cpsat_repair=False,
        sa_auto_calibration_enabled=False,
        native_initial_seed_enabled=True,
        random_seed=1,
        min_destroy=1,
        max_destroy=2,
    )
    assert completion_sized == []
    assert result.metadata["search_stop_reason"] != "wall_clock_before_search"
    assert int(result.metadata.get("iterations_completed") or 0) >= 1
    assert result.assignments
