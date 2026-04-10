"""High-level orchestration API for the SynAPS solver portfolio.

These helpers provide a stable runtime surface above the individual solver
classes.  They are intentionally deterministic-first: routing is explainable,
explicit overrides are supported, and execution provenance is written back into
``ScheduleResult.metadata`` for downstream auditability.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from synaps.instrumentation import (
    record_feasibility_event,
    record_routing_event,
    record_solve_event,
)
from synaps.logging import get_logger
from synaps.problem_profile import build_problem_profile
from synaps.solvers.incremental_repair import IncrementalRepair
from synaps.solvers.registry import create_solver
from synaps.solvers.router import (
    SolveRegime,
    SolverRoutingContext,
    SolverRoutingDecision,
    select_solver,
)
from synaps.validation import verify_schedule_result

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from synaps.model import Assignment, ScheduleProblem, ScheduleResult

_log = get_logger("synaps.portfolio")


class PortfolioValidationError(RuntimeError):
    """Raised when a high-level portfolio execution returns an infeasible schedule."""


def _merge_kwargs(
    base_kwargs: Mapping[str, object],
    override_kwargs: Mapping[str, object] | None,
) -> dict[str, object]:
    merged = dict(base_kwargs)
    if override_kwargs:
        merged.update(override_kwargs)
    return merged


def _attach_portfolio_metadata(
    result: ScheduleResult,
    *,
    execution_mode: str,
    solver_config: str,
    routed: bool,
    routing_reason: str,
    regime: SolveRegime,
    preferred_max_latency_s: int | None,
    exact_required: bool,
    details: Mapping[str, object] | None = None,
) -> ScheduleResult:
    result.metadata = {
        **result.metadata,
        "portfolio": {
            "execution_mode": execution_mode,
            "solver_config": solver_config,
            "routed": routed,
            "routing_reason": routing_reason,
            "regime": regime.value,
            "preferred_max_latency_s": preferred_max_latency_s,
            "exact_required": exact_required,
            **(dict(details) if details is not None else {}),
        },
    }
    return result


def recommend_repair_radius(
    problem: ScheduleProblem,
    disrupted_op_ids: Sequence[Any],
    *,
    regime: SolveRegime = SolveRegime.BREAKDOWN,
) -> int:
    """Recommend a deterministic repair radius based on disruption regime."""

    disrupted = set(disrupted_op_ids)
    if not disrupted:
        return 1

    successors_by_op: dict[Any, list[Any]] = {}
    for operation in problem.operations:
        if operation.predecessor_op_id is None:
            continue
        successors_by_op.setdefault(operation.predecessor_op_id, []).append(operation.id)

    reachable: set[Any] = set()
    frontier = set(disrupted)
    while frontier:
        next_frontier: set[Any] = set()
        for operation_id in frontier:
            for successor_id in successors_by_op.get(operation_id, []):
                if successor_id in reachable or successor_id in disrupted:
                    continue
                reachable.add(successor_id)
                next_frontier.add(successor_id)
        frontier = next_frontier

    disrupted_count = len(disrupted)
    downstream_count = len(reachable)

    if regime is SolveRegime.BREAKDOWN:
        return max(2, min(len(problem.operations), max(disrupted_count * 2, downstream_count)))
    if regime is SolveRegime.RUSH_ORDER:
        return max(3, min(len(problem.operations), max(disrupted_count + 2, downstream_count)))
    if regime is SolveRegime.MATERIAL_SHORTAGE:
        return max(5, min(len(problem.operations), max(disrupted_count * 3, downstream_count)))
    if regime is SolveRegime.INTERACTIVE:
        return 1
    if regime is SolveRegime.WHAT_IF:
        return max(5, min(len(problem.operations), max(disrupted_count * 2, downstream_count)))

    return max(5, min(len(problem.operations), max(disrupted_count * 2, downstream_count)))


def solve_schedule(
    problem: ScheduleProblem,
    *,
    context: SolverRoutingContext | None = None,
    solver_config: str | None = None,
    solve_kwargs: Mapping[str, object] | None = None,
    verify_feasibility: bool = True,
) -> ScheduleResult:
    """Solve *problem* via either an explicit or routed portfolio member."""

    ctx = context or SolverRoutingContext()
    decision: SolverRoutingDecision | None = None
    profile = build_problem_profile(problem)

    if solver_config is None:
        solver, default_kwargs, decision = select_solver(problem, context=ctx)
        selected_solver_config = decision.solver_config
        routing_reason = decision.reason
        routed = True
    else:
        solver, default_kwargs = create_solver(solver_config)
        selected_solver_config = solver_config
        routing_reason = "explicit solver_config override"
        routed = False

    _log.info(
        "solve_started",
        solver_config=selected_solver_config,
        routed=routed,
        regime=ctx.regime,
        op_count=profile.operation_count,
        size_band=profile.size_band,
    )
    record_routing_event(
        selected_solver_config,
        regime=ctx.regime.value,
        reason=routing_reason,
    )

    result = solver.solve(problem, **_merge_kwargs(default_kwargs, solve_kwargs))

    _log.info(
        "solve_completed",
        solver_config=selected_solver_config,
        status=result.status.value,
        duration_ms=result.duration_ms,
        assignment_count=len(result.assignments),
    )
    record_solve_event(
        selected_solver_config,
        status=result.status.value,
        duration_ms=result.duration_ms,
        op_count=profile.operation_count,
    )

    verification_details: dict[str, object] = {"problem_profile": profile.as_dict()}
    if verify_feasibility:
        verification = verify_schedule_result(problem, result)
        verification_details.update(
            {
                "verified_feasible": verification.feasible,
                "violation_count": verification.violation_count,
                "violation_kinds": verification.violation_kinds,
            }
        )
        record_feasibility_event(
            feasible=verification.feasible,
            violation_count=verification.violation_count,
            violation_kinds=verification.violation_kinds,
        )
        if result.status.value in {"feasible", "optimal"} and not verification.feasible:
            raise PortfolioValidationError(
                "Portfolio solve produced an infeasible schedule: "
                + "; ".join(violation.message for violation in verification.violations)
            )

    return _attach_portfolio_metadata(
        result,
        execution_mode="solve",
        solver_config=selected_solver_config,
        routed=routed,
        routing_reason=routing_reason,
        regime=ctx.regime,
        preferred_max_latency_s=ctx.preferred_max_latency_s,
        exact_required=ctx.exact_required,
        details=verification_details,
    )


def repair_schedule(
    problem: ScheduleProblem,
    *,
    base_assignments: Sequence[Assignment],
    disrupted_op_ids: Sequence[Any],
    radius: int | None = None,
    regime: SolveRegime = SolveRegime.BREAKDOWN,
    solve_kwargs: Mapping[str, object] | None = None,
    verify_feasibility: bool = True,
) -> ScheduleResult:
    """Repair an existing schedule through the dedicated repair engine."""

    solver = IncrementalRepair()
    profile = build_problem_profile(problem)
    applied_radius = radius
    if applied_radius is None:
        applied_radius = recommend_repair_radius(
            problem,
            disrupted_op_ids,
            regime=regime,
        )

    _log.info(
        "repair_started",
        regime=regime,
        disrupted_count=len(set(disrupted_op_ids)),
        radius=applied_radius,
        op_count=profile.operation_count,
    )

    result = solver.solve(
        problem,
        **_merge_kwargs(
            {
                "base_assignments": list(base_assignments),
                "disrupted_op_ids": list(disrupted_op_ids),
                "radius": applied_radius,
            },
            solve_kwargs,
        ),
    )
    verification_details: dict[str, object] = {
        "applied_radius": applied_radius,
        "disrupted_operation_count": len(set(disrupted_op_ids)),
        "problem_profile": profile.as_dict(),
    }
    if verify_feasibility:
        verification = verify_schedule_result(problem, result)
        verification_details.update(
            {
                "verified_feasible": verification.feasible,
                "violation_count": verification.violation_count,
                "violation_kinds": verification.violation_kinds,
            }
        )
        if result.status.value in {"feasible", "optimal"} and not verification.feasible:
            raise PortfolioValidationError(
                "Portfolio repair produced an infeasible schedule: "
                + "; ".join(violation.message for violation in verification.violations)
            )

    return _attach_portfolio_metadata(
        result,
        execution_mode="repair",
        solver_config="INCREMENTAL_REPAIR",
        routed=False,
        routing_reason="repair flow uses the dedicated incremental repair engine",
        regime=regime,
        preferred_max_latency_s=None,
        exact_required=False,
        details=verification_details,
    )


__all__ = [
    "PortfolioValidationError",
    "recommend_repair_radius",
    "repair_schedule",
    "solve_schedule",
]
