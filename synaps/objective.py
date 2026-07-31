"""Canonical objective helpers: coverage and the lexicographic comparison key.

Red Team audit P0-5 (coverage as a level-0 objective) and the groundwork for
P0-6 (a single objective evaluator). Keeping the comparison key here \u2014 rather
than re-deriving a tuple inline in every solver / the portfolio / the benchmark
harness \u2014 is the same single-source-of-truth discipline that P0-4 applied to the
duration grain and N4 to the metricity predicate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from synaps.model import ObjectiveValues


def coverage_fraction(*, total_operations: int, scheduled_operations: int) -> float:
    """Fraction of operations that received an assignment.

    A problem with no operations is vacuously fully covered (1.0), so an empty
    instance never scores as "0% covered".
    """
    if total_operations <= 0:
        return 1.0
    return scheduled_operations / total_operations


def objective_sort_key(objective: ObjectiveValues) -> tuple[float, float, float]:
    """Canonical lexicographic rank (lower is better).

    Level 0 is coverage (negated so HIGHER coverage sorts first): a schedule
    that abandons operations must never rank ahead of a fuller one, no matter
    how good its makespan looks (P0-5). Ties fall back to makespan, then the
    scalarized weighted sum.
    """
    return (-objective.coverage, objective.makespan_minutes, objective.weighted_sum)


__all__ = ["coverage_fraction", "objective_sort_key"]
