"""D1/N1: CP-SAT must be reproducible at the default settings AND within budget.

Measured before the D1 fix (audit v2): with the default ``num_workers=8`` and a
fixed ``random_seed``, runs on ``medium_stress_20x4`` produced different
schedules because the portfolio workers race under a wall-clock limit.

The first D1 fix set ``interleave_search`` + ``max_deterministic_time`` but left
``max_time_in_seconds`` in place: on 8 workers the deterministic budget mapped to
~3x the wall time, so the wall cap cut first and the result was STILL
non-reproducible on the binding instance (audit v3, N1) — the old test passed
only because it did not measure the binding case.

Fix (N1): ``strict`` (default) runs single-threaded (deterministic search order)
and stops on ``max_deterministic_time = 0.8 * time_limit_s`` — a
machine-independent stop that binds BEFORE the wall cap, so the schedule is both
reproducible and within budget. ``metadata['determinism_violated']`` is True only
if the wall cap (not the deterministic stop) ended the search.
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
    """D1/N1: runs at the default settings on a BINDING instance are identical.

    ``time_limit_s=8`` binds on ``medium_stress_20x4`` (the search does not prove
    optimality), so this exercises the stopping limit — exactly the case the old
    test missed. Only ``auto_greedy_warm_start`` and ``random_seed`` are pinned;
    ``num_workers`` and ``determinism`` keep their defaults.
    """
    problem = _medium()
    prints = set()
    for _ in range(3):
        result = CpSatSolver().solve(
            problem, time_limit_s=8, random_seed=42, auto_greedy_warm_start=False
        )
        assert result.metadata["determinism"] == "strict"
        # The deterministic stop, not the wall cap, must have ended the search;
        # otherwise reproducibility is not guaranteed on this host.
        assert result.metadata["determinism_violated"] is False
        prints.add(_fingerprint(result))
    assert len(prints) == 1, f"non-reproducible at default settings: {prints}"


def test_cpsat_fast_mode_is_opt_out() -> None:
    """The fast (non-deterministic) mode remains available and is recorded."""
    problem = _medium()
    result = CpSatSolver().solve(
        problem,
        time_limit_s=5,
        random_seed=42,
        determinism="fast",
        auto_greedy_warm_start=False,
    )
    assert result.metadata["determinism"] == "fast"
