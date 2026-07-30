"""D1: CP-SAT must be reproducible at the default settings.

Measured before the fix (Red Team audit v2, tag D1): with the default
``num_workers=8`` and a fixed ``random_seed``, three runs on
``medium_stress_20x4`` produced three different schedules (makespans
170/174/182, a 7% spread) because the CP-SAT portfolio workers race under a
wall-clock limit. OR-Tools' prescription for deterministic multi-threading is
``interleave_search=True`` with ``interleave_batch_size ~ 2*num_workers``.

Fix: a ``determinism`` mode (``strict`` default, ``fast`` opt-out). ``strict``
sets interleaved search and a deterministic time limit so a fixed seed yields
a byte-identical schedule; the chosen mode is recorded in
``metadata["determinism"]``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from synaps.model import ScheduleProblem, ScheduleResult
from synaps.solvers.cpsat_solver import CpSatSolver

INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"


def _fingerprint(result: ScheduleResult) -> str:
    body = "\n".join(
        f"{a.operation_id}|{a.work_center_id}|{a.start_time.isoformat()}|{a.end_time.isoformat()}"
        for a in sorted(result.assignments, key=lambda x: str(x.operation_id))
    )
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _medium() -> ScheduleProblem:
    return ScheduleProblem.model_validate(
        json.loads((INSTANCES / "medium_stress_20x4.json").read_text(encoding="utf-8"))
    )


def test_cpsat_strict_is_reproducible_at_default_workers() -> None:
    """D1: three runs at the default settings must yield identical schedules."""
    problem = _medium()
    prints = set()
    for _ in range(3):
        result = CpSatSolver().solve(
            problem, time_limit_s=8, random_seed=42, auto_greedy_warm_start=False
        )
        assert result.metadata["determinism"] == "strict"
        prints.add(_fingerprint(result))
    assert len(prints) == 1, f"non-reproducible at default settings: {prints}"


def test_cpsat_fast_mode_is_opt_out() -> None:
    """The fast (non-deterministic) mode remains available and is recorded."""
    problem = _medium()
    result = CpSatSolver().solve(
        problem, time_limit_s=5, random_seed=42, determinism="fast",
        auto_greedy_warm_start=False,
    )
    assert result.metadata["determinism"] == "fast"
