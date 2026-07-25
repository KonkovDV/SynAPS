"""Tests for the high-level SynAPS orchestration API."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest

from synaps import recommend_repair_radius, repair_schedule, solve_schedule
from synaps.model import Assignment, ScheduleProblem, SolverStatus
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.router import SolveRegime, SolverRoutingContext
from synaps.validation import verify_schedule_result
from tests.conftest import HORIZON_START


def test_solve_schedule_routes_small_nominal_problem(simple_problem: ScheduleProblem) -> None:
    result = solve_schedule(simple_problem)

    assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
    assert result.metadata["portfolio"]["solver_config"] == "CPSAT-10"
    assert result.metadata["portfolio"]["routed"] is True
    assert result.metadata["portfolio"]["execution_mode"] == "solve"
    assert result.metadata["portfolio"]["problem_profile"]["operation_count"] == 4
    assert result.metadata["portfolio"]["verified_feasible"] is True
    assert result.metadata["portfolio"]["violation_count"] == 0
    assert result.metadata["portfolio"]["violation_kind_counts"] == {}
    assert result.metadata["portfolio"]["feasibility_violation_kinds"] == {}


def test_solve_schedule_respects_explicit_solver_override(
    simple_problem: ScheduleProblem,
) -> None:
    result = solve_schedule(simple_problem, solver_config="GREED")

    assert result.status == SolverStatus.FEASIBLE
    assert result.solver_name == "greedy_dispatch"
    assert result.metadata["portfolio"]["solver_config"] == "GREED"
    assert result.metadata["portfolio"]["routed"] is False
    assert result.metadata["portfolio"]["routing_reason"] == "explicit solver_config override"


def test_solve_schedule_records_routing_context(simple_problem: ScheduleProblem) -> None:
    result = solve_schedule(
        simple_problem,
        context=SolverRoutingContext(
            regime=SolveRegime.INTERACTIVE,
            preferred_max_latency_s=1,
            exact_required=False,
        ),
    )

    assert result.status == SolverStatus.FEASIBLE
    assert result.metadata["portfolio"]["regime"] == SolveRegime.INTERACTIVE.value
    assert result.metadata["portfolio"]["preferred_max_latency_s"] == 1
    # The router may pick BEAM-3 when the problem has dense SDST setups
    # within the latency budget, otherwise falls back to GREED.
    assert result.metadata["portfolio"]["solver_config"] in {"GREED", "BEAM-3"}


def test_repair_schedule_executes_incremental_repair(
    simple_problem: ScheduleProblem,
) -> None:
    base_result = GreedyDispatch().solve(simple_problem)

    result = repair_schedule(
        simple_problem,
        base_assignments=base_result.assignments,
        disrupted_op_ids=[simple_problem.operations[0].id],
        radius=2,
        regime=SolveRegime.RUSH_ORDER,
    )

    assert result.status == SolverStatus.FEASIBLE
    assert result.solver_name == "incremental_repair"
    assert result.metadata["portfolio"]["execution_mode"] == "repair"
    assert result.metadata["portfolio"]["solver_config"] == "INCREMENTAL_REPAIR"
    assert result.metadata["portfolio"]["regime"] == SolveRegime.RUSH_ORDER.value
    assert result.metadata["portfolio"]["verified_feasible"] is True
    assert result.metadata["portfolio"]["violation_kind_counts"] == {}
    assert result.metadata["portfolio"]["feasibility_violation_kinds"] == {}

    checker = FeasibilityChecker()
    assert checker.check(simple_problem, result.assignments) == []


def test_solve_schedule_can_disable_feasibility_verification(
    simple_problem: ScheduleProblem,
) -> None:
    result = solve_schedule(simple_problem, verify_feasibility=False)

    assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
    assert "verified_feasible" not in result.metadata["portfolio"]


def test_recommend_repair_radius_scales_by_regime(
    simple_problem: ScheduleProblem,
) -> None:
    disrupted = [simple_problem.operations[0].id]

    interactive_radius = recommend_repair_radius(
        simple_problem,
        disrupted,
        regime=SolveRegime.INTERACTIVE,
    )
    breakdown_radius = recommend_repair_radius(
        simple_problem,
        disrupted,
        regime=SolveRegime.BREAKDOWN,
    )
    material_radius = recommend_repair_radius(
        simple_problem,
        disrupted,
        regime=SolveRegime.MATERIAL_SHORTAGE,
    )

    assert interactive_radius == 1
    assert breakdown_radius >= 2
    assert material_radius >= breakdown_radius


def test_repair_schedule_uses_policy_radius_when_not_provided(
    simple_problem: ScheduleProblem,
) -> None:
    base_result = GreedyDispatch().solve(simple_problem)
    disrupted = [simple_problem.operations[0].id]

    expected_radius = recommend_repair_radius(
        simple_problem,
        disrupted,
        regime=SolveRegime.BREAKDOWN,
    )
    result = repair_schedule(
        simple_problem,
        base_assignments=base_result.assignments,
        disrupted_op_ids=disrupted,
        regime=SolveRegime.BREAKDOWN,
    )

    assert result.status == SolverStatus.FEASIBLE
    assert result.metadata["portfolio"]["applied_radius"] == expected_radius
    assert result.metadata["portfolio"]["disrupted_operation_count"] == 1
    assert result.metadata["portfolio"]["problem_profile"]["size_band"] == "small"


def test_verify_schedule_result_reports_violation_kind_counts(
    simple_problem: ScheduleProblem,
) -> None:
    op_ids = [op.id for op in simple_problem.operations]
    wc_id = simple_problem.work_centers[0].id
    overlapping_assignments = [
        Assignment(
            operation_id=op_ids[index],
            work_center_id=wc_id,
            start_time=HORIZON_START + timedelta(minutes=index * 5),
            end_time=HORIZON_START + timedelta(minutes=index * 5 + 25),
        )
        for index in range(len(op_ids))
    ]

    result = GreedyDispatch().solve(simple_problem)
    result.status = SolverStatus.FEASIBLE
    result.assignments = overlapping_assignments

    verification = verify_schedule_result(simple_problem, result)

    assert verification.feasible is False
    assert verification.violation_count > 0
    assert verification.violation_kind_counts
    assert verification.violation_kinds == sorted(verification.violation_kind_counts.keys())
    assert sum(verification.violation_kind_counts.values()) == verification.violation_count


def test_verify_schedule_result_uses_exhaustive_checker_for_parallel_capacity(
    simple_problem: ScheduleProblem,
) -> None:
    widened_machine = simple_problem.work_centers[0].model_copy(update={"max_parallel": 2})
    problem = simple_problem.model_copy(
        update={
            "work_centers": [widened_machine, *simple_problem.work_centers[1:]],
        }
    )
    wc_id = widened_machine.id
    overloaded_assignments = [
        Assignment(
            operation_id=operation.id,
            work_center_id=wc_id,
            start_time=HORIZON_START,
            end_time=HORIZON_START + timedelta(minutes=30),
        )
        for operation in problem.operations
    ]

    result = GreedyDispatch().solve(problem)
    result.status = SolverStatus.FEASIBLE
    result.assignments = overloaded_assignments

    exhaustive_violations = FeasibilityChecker().check(
        problem,
        overloaded_assignments,
        exhaustive=True,
    )
    verification = verify_schedule_result(problem, result)

    assert verification.violation_count == len(exhaustive_violations)
    assert verification.violation_kind_counts == dict(
        sorted(Counter(v.kind for v in exhaustive_violations).items())
    )


def test_resolve_portfolio_resource_limits_inactive_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYNAPS_ENABLE_RESOURCE_GUARDS", raising=False)
    monkeypatch.delenv("SYNAPS_SOLVE_TIMEOUT_S", raising=False)
    monkeypatch.delenv("SYNAPS_SOLVE_MEMORY_LIMIT_MB", raising=False)
    from synaps.portfolio import resolve_portfolio_resource_limits

    assert resolve_portfolio_resource_limits(solve_kwargs={"time_limit_s": 30}) is None


def test_resolve_portfolio_resource_limits_from_env_and_latency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNAPS_SOLVE_TIMEOUT_S", "120")
    monkeypatch.setenv("SYNAPS_SOLVE_MEMORY_LIMIT_MB", "2048")
    from synaps.portfolio import resolve_portfolio_resource_limits

    limits = resolve_portfolio_resource_limits(preferred_max_latency_s=30)
    assert limits is not None
    assert limits.timeout_s == 30
    assert limits.memory_limit_mb == 2048


def test_solve_schedule_records_resource_guard_metadata(
    simple_problem: ScheduleProblem,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SYNAPS_ENABLE_RESOURCE_GUARDS", "1")
    result = solve_schedule(simple_problem, solver_config="GREED", solve_kwargs={"time_limit_s": 30})
    assert result.metadata["portfolio"]["resource_guards_active"] is True
    assert result.metadata["portfolio"]["resource_limits"]["timeout_s"] == 30
