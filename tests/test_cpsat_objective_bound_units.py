"""Q3: CP-SAT best_objective_bound must be a makespan bound, not big-M units.

Measured before the fix (Red Team audit v2, tag Q3): on tiny_3x3 at makespan 82
the reported ``best_objective_bound`` was 430797 — the dual bound of the
scalarized big-M objective ``makespan * secondary_bound + ...``, emitted into
metadata with no units, so any consumer reads it as a makespan bound and it is
also unusable as the subproblem lower bound the LBBD S2 fix wants.

Fix (until the full staged lexicographic replacement, brief P1-1): publish the
raw scalarized dual bound as ``scalarized_objective_bound`` with an explicit
``objective_bound_units``, and report ``best_objective_bound`` in makespan
minutes (raw / secondary_bound for the default weighted-sum objective).
"""

from __future__ import annotations

import json
from pathlib import Path

from synaps.model import ScheduleProblem, SolverStatus
from synaps.solvers.cpsat_solver import CpSatSolver

INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"


def _tiny() -> ScheduleProblem:
    return ScheduleProblem.model_validate(
        json.loads((INSTANCES / "tiny_3x3.json").read_text(encoding="utf-8"))
    )


def test_best_objective_bound_is_in_makespan_minutes() -> None:
    """Q3: best_objective_bound must be a makespan bound (<= horizon), with units."""
    problem = _tiny()
    horizon = (
        problem.planning_horizon_end - problem.planning_horizon_start
    ).total_seconds() / 60.0
    result = CpSatSolver().solve(
        problem, time_limit_s=30, num_workers=1, auto_greedy_warm_start=False
    )
    assert result.status is SolverStatus.OPTIMAL
    bound = float(result.metadata["best_objective_bound"])
    assert bound <= horizon + 1e-6, (
        f"best_objective_bound {bound} is not in makespan minutes (horizon {horizon})"
    )
    # A valid lower bound must not exceed the achieved makespan either.
    assert bound <= result.objective.makespan_minutes + 1e-6
    assert result.metadata["objective_bound_units"] == "makespan_minutes"
    # The raw scalarized dual bound is preserved under its own key.
    assert "scalarized_objective_bound" in result.metadata
