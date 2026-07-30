"""Q4: ALNS must surface when it discarded the search and returned the seed.

The final-violation recovery mechanism itself is correct and unchanged: when
the search incumbent is infeasible, ALNS recovers to the initial feasible
solution (tracked via ``final_violation_recovery_*``). What was missing is a
signal that the whole search budget produced nothing usable, so a portfolio
could still prefer this "feasible" result over a genuine improvement. ALNS now
emits ``metadata["quality_warning"] = "search_discarded_returned_seed"`` in that
case, and ``None`` otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path

from synaps.model import ScheduleProblem
from synaps.solvers.alns_solver import AlnsSolver

INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"


def test_alns_metadata_exposes_quality_warning_key() -> None:
    """Q4: the quality_warning key is always present (None on a clean search)."""
    problem = ScheduleProblem.model_validate(
        json.loads((INSTANCES / "tiny_3x3.json").read_text(encoding="utf-8"))
    )
    result = AlnsSolver().solve(problem, time_limit_s=5, random_seed=42, max_iterations=30)
    assert "quality_warning" in result.metadata
    # On a schedulable instance the search should not have been discarded.
    if not result.metadata.get("final_violation_recovered"):
        assert result.metadata["quality_warning"] is None
    else:
        assert result.metadata["quality_warning"] == "search_discarded_returned_seed"
