"""Deterministic solver routing for the current SynAPS portfolio.

The router is intentionally conservative: it chooses among the implemented
standalone solver configurations using measurable instance characteristics and
explicit operational regime hints.  ML advisory layers can later override these
heuristics, but the default path remains explainable and reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from synaps.problem_profile import build_problem_profile
from synaps.solvers.registry import create_solver

if TYPE_CHECKING:
    from synaps.model import ScheduleProblem
    from synaps.solvers import BaseSolver


class SolveRegime(StrEnum):
    """Operational contexts described in the solver portfolio docs."""

    NOMINAL = "nominal"
    RUSH_ORDER = "rush_order"
    BREAKDOWN = "breakdown"
    MATERIAL_SHORTAGE = "material_shortage"
    INTERACTIVE = "interactive"
    WHAT_IF = "what_if"


@dataclass(frozen=True)
class SolverRoutingContext:
    """High-level inputs used by the deterministic router."""

    regime: SolveRegime = SolveRegime.NOMINAL
    preferred_max_latency_s: int | None = None
    exact_required: bool = False


@dataclass(frozen=True)
class SolverRoutingDecision:
    """Explainable routing result for one scheduling request."""

    solver_config: str
    reason: str


def route_solver_config(
    problem: ScheduleProblem,
    *,
    context: SolverRoutingContext | None = None,
) -> SolverRoutingDecision:
    """Select the smallest sound solver configuration for *problem*.

    Incremental repair is intentionally not returned here because it requires an
    existing schedule and disrupted-operation context, which is a different call
    surface from the standalone `solve(problem, **kwargs)` portfolio.
    """

    ctx = context or SolverRoutingContext()
    profile = build_problem_profile(problem)
    op_count = profile.operation_count
    wc_count = profile.work_center_count
    has_aux_constraints = profile.has_aux_constraints
    has_nonzero_setups = profile.has_nonzero_setups

    if ctx.preferred_max_latency_s is not None and ctx.preferred_max_latency_s <= 1:
        return SolverRoutingDecision(
            solver_config="GREED",
            reason="latency budget <= 1s, so the constructive heuristic is the only safe choice",
        )

    if ctx.regime is SolveRegime.INTERACTIVE:
        return SolverRoutingDecision(
            solver_config="GREED",
            reason=(
                "interactive regime prioritizes immediate feasible feedback over "
                "global optimality"
            ),
        )

    if ctx.regime in {SolveRegime.BREAKDOWN, SolveRegime.RUSH_ORDER}:
        if op_count <= 30 and (
            ctx.preferred_max_latency_s is None or ctx.preferred_max_latency_s >= 10
        ):
            return SolverRoutingDecision(
                solver_config="CPSAT-10",
                reason=(
                    "small disruption window fits an exact CP-SAT patch within the "
                    "latency budget"
                ),
            )
        return SolverRoutingDecision(
            solver_config="GREED",
            reason="disruption regime defaults to the fastest deterministic recovery path",
        )

    if ctx.regime is SolveRegime.MATERIAL_SHORTAGE:
        if op_count <= 120:
            return SolverRoutingDecision(
                solver_config="CPSAT-30",
                reason="material scarcity benefits from exact propagation of tightened constraints",
            )
        return SolverRoutingDecision(
            solver_config="LBBD-5",
            reason=(
                "large constrained instances benefit from decomposition before exact "
                "local sequencing"
            ),
        )

    if ctx.regime is SolveRegime.WHAT_IF:
        if op_count <= 40 and has_nonzero_setups:
            return SolverRoutingDecision(
                solver_config="CPSAT-EPS-SETUP-110",
                reason=(
                    "what-if analysis on a small setup-sensitive instance benefits "
                    "from the Pareto-slice epsilon profile"
                ),
            )
        if op_count <= 120:
            return SolverRoutingDecision(
                solver_config="CPSAT-30",
                reason="what-if analysis favors stronger optimality on medium instances",
            )
        return SolverRoutingDecision(
            solver_config="LBBD-10",
            reason=(
                "large scenario analysis benefits from the slower but more scalable "
                "LBBD portfolio member"
            ),
        )

    if ctx.exact_required:
        if op_count <= 40:
            return SolverRoutingDecision(
                solver_config="CPSAT-10",
                reason="exact solve explicitly required and the instance remains small",
            )
        if op_count <= 120:
            return SolverRoutingDecision(
                solver_config="CPSAT-30",
                reason=(
                    "exact solve explicitly required and the instance remains within "
                    "the CP-SAT comfort zone"
                ),
            )
        return SolverRoutingDecision(
            solver_config="LBBD-10",
            reason=(
                "exactness requested on a larger instance, so decomposition is the "
                "smallest sound path"
            ),
        )

    if op_count <= 20 and wc_count <= 5 and not has_aux_constraints:
        return SolverRoutingDecision(
            solver_config="CPSAT-10",
            reason="small nominal instance fits the low-latency exact portfolio member",
        )

    if op_count <= 120 and (has_nonzero_setups or has_aux_constraints or wc_count <= 20):
        return SolverRoutingDecision(
            solver_config="CPSAT-30",
            reason=(
                "medium nominal instance with richer constraints still fits the exact "
                "CP-SAT path"
            ),
        )

    return SolverRoutingDecision(
        solver_config="LBBD-10",
        reason=(
            "larger nominal instance benefits from decomposition before exact "
            "subproblem sequencing"
        ),
    )


def select_solver(
    problem: ScheduleProblem,
    *,
    context: SolverRoutingContext | None = None,
) -> tuple[BaseSolver, dict[str, object], SolverRoutingDecision]:
    """Route and instantiate a solver in one step."""

    decision = route_solver_config(problem, context=context)
    solver, solve_kwargs = create_solver(decision.solver_config)
    return solver, solve_kwargs, decision


__all__ = [
    "SolveRegime",
    "SolverRoutingContext",
    "SolverRoutingDecision",
    "route_solver_config",
    "select_solver",
]
