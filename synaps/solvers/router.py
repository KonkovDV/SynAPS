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
    setup_density = profile.nonzero_setup_density
    resource_contention = profile.resource_contention
    precedence_depth = profile.precedence_depth

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
        if op_count <= 500:
            return SolverRoutingDecision(
                solver_config="LBBD-5",
                reason=(
                    "large constrained instances benefit from decomposition before exact "
                    "local sequencing"
                ),
            )
        return SolverRoutingDecision(
            solver_config="LBBD-10-HD",
            reason=(
                "industrial-scale material-shortage instance routed to hierarchical "
                "decomposition with balanced partitioning"
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
        if op_count <= 500:
            return SolverRoutingDecision(
                solver_config="LBBD-10",
                reason=(
                    "large scenario analysis benefits from the slower but more scalable "
                    "LBBD portfolio member"
                ),
            )
        return SolverRoutingDecision(
            solver_config="LBBD-10-HD",
            reason=(
                "industrial-scale what-if analysis routed to hierarchical LBBD "
                "with parallel subproblems"
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
        if op_count <= 500:
            return SolverRoutingDecision(
                solver_config="LBBD-10",
                reason=(
                    "exactness requested on a larger instance, so decomposition is the "
                    "smallest sound path"
                ),
            )
        if op_count <= 50_000:
            return SolverRoutingDecision(
                solver_config="LBBD-10-HD",
                reason=(
                    "industrial-scale exact solve via hierarchical LBBD with balanced "
                    "partitioning (≤200 ops/cluster)"
                ),
            )
        return SolverRoutingDecision(
            solver_config="LBBD-20-HD",
            reason=(
                "ultra-large exact solve (50k+ ops) via extended hierarchical LBBD "
                "with tighter convergence and smaller clusters"
            ),
        )

    if op_count <= 20 and wc_count <= 5 and not has_aux_constraints:
        return SolverRoutingDecision(
            solver_config="CPSAT-10",
            reason="small nominal instance fits the low-latency exact portfolio member",
        )

    # Dense setups or deep precedence chains benefit from the longer CP-SAT
    # budget even at moderate sizes — propagation exploits the structure.
    setup_heavy = setup_density > 0.3
    deep_chains = precedence_depth > 6

    if op_count <= 120 and (has_nonzero_setups or has_aux_constraints or wc_count <= 20):
        if (setup_heavy or deep_chains) and op_count > 60:
            return SolverRoutingDecision(
                solver_config="CPSAT-120",
                reason=(
                    "medium nominal instance with dense setups "
                    f"(density={setup_density:.2f}) or deep precedence chains "
                    f"(depth={precedence_depth}) benefits from extended CP-SAT budget"
                ),
            )
        return SolverRoutingDecision(
            solver_config="CPSAT-30",
            reason=(
                "medium nominal instance with richer constraints still fits the exact "
                "CP-SAT path"
            ),
        )

    # High resource contention means machines are shared heavily — decomposition
    # with smaller clusters reduces subproblem complexity.
    contention_heavy = resource_contention > 15.0

    if op_count <= 500:
        if contention_heavy and op_count > 300:
            return SolverRoutingDecision(
                solver_config="LBBD-10",
                reason=(
                    "larger nominal instance with high resource contention "
                    f"(avg {resource_contention:.1f} ops/wc) benefits from "
                    "decomposition with more Benders iterations"
                ),
            )
        return SolverRoutingDecision(
            solver_config="LBBD-10",
            reason=(
                "larger nominal instance benefits from decomposition before exact "
                "subproblem sequencing"
            ),
        )

    if op_count <= 50_000:
        return SolverRoutingDecision(
            solver_config="LBBD-10-HD",
            reason=(
                "industrial-scale nominal instance (>500 ops) routed to hierarchical LBBD "
                "with balanced partitioning, greedy warm-start, and parallel subproblems"
            ),
        )

    return SolverRoutingDecision(
        solver_config="LBBD-20-HD",
        reason=(
            "ultra-large nominal instance (50k+ ops) routed to extended hierarchical LBBD "
            "with tighter convergence, smaller clusters, and 20-iteration budget"
        ),
    )


def select_solver(
    problem: ScheduleProblem,
    *,
    context: SolverRoutingContext | None = None,
    advisory_predictor: object | None = None,
    advisory_confidence_threshold: float = 0.6,
) -> tuple[BaseSolver, dict[str, object], SolverRoutingDecision]:
    """Route and instantiate a solver in one step.

    When *advisory_predictor* is provided (a ``RuntimePredictor`` instance),
    its recommendation is used if its confidence exceeds the threshold.
    Otherwise, the deterministic router decision applies.
    """

    deterministic = route_solver_config(problem, context=context)

    # Try ML advisory if a predictor is provided
    if advisory_predictor is not None:
        try:
            from synaps.ml_advisory import RuntimePredictor, encode_problem_features
            from synaps.problem_profile import build_problem_profile as _build_profile

            if isinstance(advisory_predictor, RuntimePredictor):
                profile = _build_profile(problem)
                features = encode_problem_features(problem, profile)
                advisory = advisory_predictor.predict(features)

                if advisory.confidence >= advisory_confidence_threshold:
                    try:
                        solver, solve_kwargs = create_solver(advisory.recommended_solver)
                        return solver, solve_kwargs, SolverRoutingDecision(
                            solver_config=advisory.recommended_solver,
                            reason=(
                                f"ML advisory (model={advisory.model_version}, "
                                f"confidence={advisory.confidence:.2f}) overrode "
                                f"deterministic choice ({deterministic.solver_config})"
                            ),
                        )
                    except KeyError:
                        pass  # advisory recommended unknown config — fall through
        except ImportError:
            pass  # ml_advisory module not available — use deterministic

    solver, solve_kwargs = create_solver(deterministic.solver_config)
    return solver, solve_kwargs, deterministic


__all__ = [
    "SolveRegime",
    "SolverRoutingContext",
    "SolverRoutingDecision",
    "route_solver_config",
    "select_solver",
]
