"""Tests for the high-level SynAPS orchestration API."""

from __future__ import annotations

from synaps import recommend_repair_radius, repair_schedule, solve_schedule
from synaps.model import ScheduleProblem, SolverStatus
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.router import SolveRegime, SolverRoutingContext


def test_solve_schedule_routes_small_nominal_problem(simple_problem: ScheduleProblem) -> None:
    result = solve_schedule(simple_problem)

    assert result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
    assert result.metadata["portfolio"]["solver_config"] == "CPSAT-10"
    assert result.metadata["portfolio"]["routed"] is True
    assert result.metadata["portfolio"]["execution_mode"] == "solve"
    assert result.metadata["portfolio"]["problem_profile"]["operation_count"] == 4
    assert result.metadata["portfolio"]["verified_feasible"] is True
    assert result.metadata["portfolio"]["violation_count"] == 0


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
    assert result.metadata["portfolio"]["solver_config"] == "GREED"


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
