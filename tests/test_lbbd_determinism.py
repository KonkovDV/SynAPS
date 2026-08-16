"""D2: LBBD must be reproducible (identical schedule) at a fixed seed.

Measured before the fix (Red Team audit v2, tag D2): two runs of LBBD with the
same ``random_seed`` produced the same makespan but different schedule
fingerprints. Two causes: (a) ``parallel_subproblems=True`` collected cluster
results in ``as_completed`` (completion) order, so the merged assignment list
order was non-deterministic; (b) the inherited CP-SAT non-determinism (D1).

Fix: buffer cluster results by cluster index and concatenate in a deterministic
order, and sort the final assignments by the full stable key
``(work_center_id, start_time, operation_id)``. Combined with the D1 strict CP-SAT
default, two runs now yield byte-identical schedules.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from synaps.model import ScheduleProblem, ScheduleResult
from synaps.solvers.lbbd_solver import LbbdSolver

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


def test_lbbd_is_reproducible_at_fixed_seed() -> None:
    """D2: two LBBD runs at the same seed must yield identical schedules."""
    problem = _medium()
    prints = {
        _fingerprint(LbbdSolver().solve(problem, time_limit_s=8, random_seed=42, max_iterations=8))
        for _ in range(2)
    }
    assert len(prints) == 1, f"LBBD non-reproducible at fixed seed: {prints}"


def test_lbbd_assignments_sorted_by_stable_key() -> None:
    """The returned assignments use the full stable ordering key."""
    problem = _medium()
    result = LbbdSolver().solve(problem, time_limit_s=8, random_seed=42, max_iterations=8)
    keys = [(str(a.work_center_id), a.start_time, str(a.operation_id)) for a in result.assignments]
    assert keys == sorted(keys), "assignments are not in (work_center, start, op) order"
