"""P1-1: the big-M objective must not overflow int64 at the model's stated scale.

The default hierarchical objective is ``makespan * secondary_bound +
secondary_terms``. At MAX_SCHEDULE_OPERATIONS the coefficient product
``(horizon + 1) * secondary_bound`` can exceed the CP-SAT int64 objective
domain and corrupt the solve. The solver now detects that and degrades to a
pure lexicographic objective (makespan only) instead of overflowing, recording
``metadata["objective_bigm_overflow_degraded"]``.
"""

from __future__ import annotations

import json
from pathlib import Path

from synaps.model import ScheduleProblem
from synaps.solvers.cpsat_solver import _SAFE_OBJECTIVE_MAX, CpSatSolver, _bigm_objective_overflows

_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"


def test_overflow_predicate_boundary() -> None:
    # Well within the safe ceiling.
    assert _bigm_objective_overflows(horizon=10_000, secondary_bound=10_000) is False
    # A product that exceeds the safe ceiling (2**62) overflows.
    assert _bigm_objective_overflows(horizon=10**10, secondary_bound=10**10) is True
    # Exactly at the ceiling is not an overflow; one above is.
    assert _bigm_objective_overflows(horizon=_SAFE_OBJECTIVE_MAX - 1, secondary_bound=1) is False
    assert _bigm_objective_overflows(horizon=_SAFE_OBJECTIVE_MAX, secondary_bound=1) is True


def test_normal_solve_is_not_degraded() -> None:
    """A normal small instance stays on the exact big-M objective (flag False)."""
    problem = ScheduleProblem.model_validate(
        json.loads((_INSTANCES / "tiny_3x3.json").read_text())
    )
    result = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False
    )
    assert result.metadata["objective_bigm_overflow_degraded"] is False
