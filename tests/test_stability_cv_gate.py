"""CI stability gate: makespan CV across three seeds on a tracked instance.

GREED is seed-invariant on this instance (no RNG in the constructive path).
Expected CV is 0. Threshold 0.01 is a regression tripwire, not a quality claim.
A solver that starts depending on seed, host jitter, or unordered sets will
fail this test the same way a feasibility regression fails CI.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, stdev

from synaps.model import ScheduleProblem
from synaps.solvers.registry import create_solver

_ROOT = Path(__file__).resolve().parents[1]
_INSTANCE = _ROOT / "benchmark" / "instances" / "medium_stress_20x4.json"
_SEEDS = (1, 42, 999)
# Sample CV = s / mean. Deterministic GREED must stay well below this.
_MAX_MAKESPAN_CV = 0.01


def test_greed_makespan_cv_on_medium_stress_20x4() -> None:
    payload = json.loads(_INSTANCE.read_text(encoding="utf-8"))
    problem = ScheduleProblem.model_validate(payload)
    makespans: list[float] = []
    for seed in _SEEDS:
        solver, kwargs = create_solver("GREED")
        result = solver.solve(problem, **kwargs, random_seed=seed)
        assert result.objective is not None
        makespans.append(float(result.objective.makespan_minutes))
    assert len(makespans) == 3
    avg = mean(makespans)
    assert avg > 0
    cv = stdev(makespans) / avg
    assert cv <= _MAX_MAKESPAN_CV, (
        f"makespan CV={cv:.6g} exceeds {_MAX_MAKESPAN_CV} "
        f"on {_INSTANCE.name} seeds={_SEEDS} values={makespans}"
    )
