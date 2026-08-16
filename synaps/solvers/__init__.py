"""Solver interface — abstract base class for all scheduling solvers."""

from __future__ import annotations

import functools
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    from synaps.model import ScheduleProblem, ScheduleResult


__all__ = ["BaseSolver"]


def _attach_sdst_metric(result: ScheduleResult, problem: ScheduleProblem) -> None:
    """Inject the canonical SDST metricity flag into a result's metadata (N4).

    Centralised here so every solver in the portfolio surfaces the flag without
    each one re-deriving it. Idempotent: a solver that already recorded the flag
    is left untouched. Imported lazily to avoid an import cycle through the
    solver-side feasibility checker that ``synaps.validation`` pulls in.
    """
    metadata = getattr(result, "metadata", None)
    if isinstance(metadata, dict) and "sdst_metric" not in metadata:
        from synaps.validation import is_setup_matrix_metric

        metadata["sdst_metric"] = is_setup_matrix_metric(problem)


def _attach_coverage(result: ScheduleResult, problem: ScheduleProblem) -> None:
    """Populate the coverage / unscheduled-operations objective fields (P0-5).

    Centralised so every solver surfaces coverage without re-deriving it, and
    so the fields cannot silently stay at the default 1.0 when a solver dropped
    work. Coverage is the fraction of DISTINCT operations that got an
    assignment.
    """
    from synaps.objective import coverage_fraction

    objective = getattr(result, "objective", None)
    if objective is None:
        return
    total = len(problem.operations)
    scheduled = len({assignment.operation_id for assignment in result.assignments})
    objective.coverage = coverage_fraction(total_operations=total, scheduled_operations=scheduled)
    objective.unscheduled_operations = max(0, total - scheduled)


def _attach_canonical_objective(
    result: ScheduleResult,
    problem: ScheduleProblem,
    weights: dict[str, float] | None = None,
) -> None:
    """Replace published objective with ``evaluate`` + ``scalarize`` (F4 / Wave 8).

    Assigns a full canonical ``ObjectiveValues`` so new fields cannot silently
    drop at the BaseSolver boundary (RT17-M2). Caller ``objective_weights`` are
    honored for ``weighted_sum`` (Wave 13 / H13-1); missing keys follow
    :data:`DEFAULT_WEIGHTS` via material/energy aliases.
    """
    from synaps.objective import DEFAULT_WEIGHTS, evaluate, scalarize

    if getattr(result, "objective", None) is None:
        return
    canonical = evaluate(problem, list(result.assignments))
    publish_weights = dict(DEFAULT_WEIGHTS)
    if weights:
        publish_weights.update(weights)
        if "material" not in weights and "material_loss" in weights:
            publish_weights["material"] = float(weights["material_loss"])
        if "energy" not in weights and "energy_kwh" in weights:
            publish_weights["energy"] = float(weights["energy_kwh"])
    result.objective = canonical.model_copy(
        update={"weighted_sum": scalarize(canonical, publish_weights)}
    )
    result.metadata["published_objective_weights"] = dict(publish_weights)


class BaseSolver(ABC):
    """Common interface for the entire solver portfolio."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Wrap each concrete ``solve`` so it always publishes ``sdst_metric``.

        A metricity-dependent bound or cut must never run on a non-metric matrix
        without a trace (audit v3, N4). Rather than thread the flag through every
        solver, decorate the subclass's own ``solve`` (if it defines one) once.
        """
        super().__init_subclass__(**kwargs)
        original_solve = cls.__dict__.get("solve")
        if original_solve is None or getattr(original_solve, "_sdst_metric_wrapped", False):
            return

        @functools.wraps(original_solve)
        def _solve_with_metricity(
            self: BaseSolver, problem: ScheduleProblem, **solve_kwargs: object
        ) -> ScheduleResult:
            result: ScheduleResult = original_solve(self, problem, **solve_kwargs)
            _attach_sdst_metric(result, problem)
            _attach_coverage(result, problem)
            raw_weights = solve_kwargs.get("objective_weights")
            weights = dict(raw_weights) if isinstance(raw_weights, dict) else None
            _attach_canonical_objective(result, problem, weights=weights)
            return result

        _solve_with_metricity._sdst_metric_wrapped = True  # type: ignore[attr-defined]
        cls.solve = cast(  # type: ignore[method-assign]
            "Callable[..., ScheduleResult]", _solve_with_metricity
        )

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique solver identifier."""

    @abstractmethod
    def solve(self, problem: ScheduleProblem, **kwargs: object) -> ScheduleResult:
        """Produce a schedule for the given problem.

        Args:
            problem: Fully specified scheduling problem.
            **kwargs: Solver-specific parameters (time_limit_s, random_seed, etc.).

        Returns:
            ScheduleResult with assignments and objective values.
        """
