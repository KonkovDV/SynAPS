"""N4 (audit v3): SDST metricity has one canonical implementation, and the flag
reaches the solver metadata.

Before the fix ``synaps.problem_profile`` carried a second inline copy of the
triangle-inequality predicate (``_setup_matrix_is_metric``) whose own docstring
admitted it "Mirrors ``synaps.validation.is_setup_matrix_metric``". The canonical
validator was never called in production and no solver surfaced the metricity
flag, so a metricity-dependent bound could silently run on a non-metric matrix —
the same duplicate-formula anti-pattern that caused P0-4.
"""

from __future__ import annotations

import json
from pathlib import Path

from synaps.model import ScheduleProblem
from synaps.solvers.cpsat_solver import CpSatSolver

_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"
_SYNAPS_ROOT = Path(__file__).resolve().parent.parent / "synaps"


def _load(name: str) -> ScheduleProblem:
    return ScheduleProblem.model_validate(json.loads((_INSTANCES / f"{name}.json").read_text()))


def test_no_duplicate_metricity_predicate() -> None:
    """No inline mirror of the canonical metricity predicate may exist."""
    offenders: list[str] = []
    for path in _SYNAPS_ROOT.rglob("*.py"):
        if path.name == "validation.py":
            continue  # the single canonical home
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            # A local function that re-derives the metricity predicate is a
            # duplicate; the canonical one lives only in validation.py.
            if stripped.startswith("def ") and (
                "is_metric" in stripped or "is_setup_matrix_metric" in stripped
            ):
                offenders.append(f"{path.relative_to(_SYNAPS_ROOT)}:{lineno}: {stripped}")
    assert not offenders, f"duplicate metricity predicate(s): {offenders}"


def test_sdst_metric_reaches_solver_metadata() -> None:
    """Every ScheduleResult must expose the metricity flag (N4 acceptance)."""
    problem = _load("medium_stress_20x4")
    result = CpSatSolver().solve(
        problem, time_limit_s=3, num_workers=1, auto_greedy_warm_start=False
    )
    assert "sdst_metric" in result.metadata
    assert isinstance(result.metadata["sdst_metric"], bool)
