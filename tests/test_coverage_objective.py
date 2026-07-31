"""P0-5: coverage is a level-0 objective; dropping work must never look better.

Measured before the fix (Red Team audit): an order with no assignments has
``completion = 0`` (so zero tardiness), and makespan is taken over the SCHEDULED
operations only, so the whole objective vector improves as coverage drops -- a
solver that abandons operations scores better than one that schedules them all.

Fix: ``ObjectiveValues`` carries ``coverage`` and ``unscheduled_operations``;
the canonical comparison ranks coverage first, so a lower-coverage schedule is
never preferred over a fuller one regardless of makespan.
"""

from __future__ import annotations

import json
from pathlib import Path

from synaps.model import ObjectiveValues, ScheduleProblem
from synaps.objective import coverage_fraction, objective_sort_key
from synaps.solvers.greedy_dispatch import GreedyDispatch

_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"


def test_coverage_fraction_basic() -> None:
    assert coverage_fraction(total_operations=10, scheduled_operations=10) == 1.0
    assert coverage_fraction(total_operations=10, scheduled_operations=5) == 0.5
    assert coverage_fraction(total_operations=0, scheduled_operations=0) == 1.0  # vacuous


def test_higher_coverage_ranks_first_even_with_worse_makespan() -> None:
    """A full-coverage schedule must sort ahead of a partial one that is faster."""
    full = ObjectiveValues(makespan_minutes=100.0, coverage=1.0, unscheduled_operations=0)
    partial = ObjectiveValues(makespan_minutes=50.0, coverage=0.5, unscheduled_operations=5)
    assert objective_sort_key(full) < objective_sort_key(partial), (
        "dropping work (coverage 0.5) must not beat full coverage on makespan alone"
    )


def test_solver_populates_full_coverage() -> None:
    """A solver that schedules every operation reports coverage 1.0."""
    problem = ScheduleProblem.model_validate(
        json.loads((_INSTANCES / "tiny_3x3.json").read_text())
    )
    result = GreedyDispatch().solve(problem)
    assert result.objective.coverage == 1.0
    assert result.objective.unscheduled_operations == 0
