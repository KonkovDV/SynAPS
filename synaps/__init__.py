# SynAPS — Universal Advanced Planning & Scheduling Solver
"""
MO-FJSP-SDST-ARC solver portfolio (MO-FJSP-SDST-ML-ARC is the target label when advisory ML layers are added):
  - GreedyDispatch (ATCS-based, < 200 ms)
  - CpSatSolver (OR-Tools CP-SAT, time-boxed)
  - LbbdSolver (HiGHS master + CP-SAT sub, iterative Benders cuts)
  - IncrementalRepair (neighbourhood repair on disruptions)
  - FeasibilityChecker (constraint validation without solving)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from synaps.contracts import RepairRequest, RepairResponse, SolveRequest, SolveResponse
    from synaps.model import Assignment, ScheduleProblem, ScheduleResult
    from synaps.solvers.router import SolveRegime, SolverRoutingContext

__version__ = "0.1.0"


def solve_schedule(
    problem: ScheduleProblem,
    *,
    context: SolverRoutingContext | None = None,
    solver_config: str | None = None,
    solve_kwargs: Mapping[str, object] | None = None,
    verify_feasibility: bool = True,
) -> ScheduleResult:
    """Lazy package-level entrypoint for the routed solve API."""

    from synaps.portfolio import solve_schedule as _solve_schedule

    return _solve_schedule(
        problem,
        context=context,
        solver_config=solver_config,
        solve_kwargs=solve_kwargs,
        verify_feasibility=verify_feasibility,
    )


def repair_schedule(
    problem: ScheduleProblem,
    *,
    base_assignments: Sequence[Assignment],
    disrupted_op_ids: Sequence[Any],
    radius: int | None = None,
    regime: SolveRegime | None = None,
    solve_kwargs: Mapping[str, object] | None = None,
    verify_feasibility: bool = True,
) -> ScheduleResult:
    """Lazy package-level entrypoint for the repair orchestration API."""

    from synaps.portfolio import repair_schedule as _repair_schedule
    from synaps.solvers.router import SolveRegime

    return _repair_schedule(
        problem,
        base_assignments=base_assignments,
        disrupted_op_ids=disrupted_op_ids,
        radius=radius,
        regime=regime or SolveRegime.BREAKDOWN,
        solve_kwargs=solve_kwargs,
        verify_feasibility=verify_feasibility,
    )


def recommend_repair_radius(
    problem: ScheduleProblem,
    disrupted_op_ids: Sequence[Any],
    *,
    regime: SolveRegime | None = None,
) -> int:
    """Lazy package-level entrypoint for repair radius policy."""

    from synaps.portfolio import recommend_repair_radius as _recommend_repair_radius
    from synaps.solvers.router import SolveRegime

    return _recommend_repair_radius(
        problem,
        disrupted_op_ids,
        regime=regime or SolveRegime.BREAKDOWN,
    )


def execute_solve_request(request: SolveRequest) -> SolveResponse:
    """Lazy package-level entrypoint for the stable solve contract."""

    from synaps.contracts import execute_solve_request as _execute_solve_request

    return _execute_solve_request(request)


def execute_repair_request(request: RepairRequest) -> RepairResponse:
    """Lazy package-level entrypoint for the stable repair contract."""

    from synaps.contracts import execute_repair_request as _execute_repair_request

    return _execute_repair_request(request)


__all__ = [
    "__version__",
    "execute_repair_request",
    "execute_solve_request",
    "recommend_repair_radius",
    "repair_schedule",
    "solve_schedule",
]
