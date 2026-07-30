"""D3/D4: solvers must honor ``time_limit_s`` as a hard wall-clock deadline.

Measured before the fix (Red Team audit v2, tag D3): ALNS overshot an 8-second
budget by 2.5-7.5x because (a) the deadline check was gated behind
``min_iterations`` and (b) each micro CP-SAT repair received the full
``repair_time_limit_s`` regardless of the remaining budget. LBBD spent
``sub_time_limit_s`` per cluster with no global deadline, overshooting >15x on
clustered instances.

Contract fixed here and documented in each solver docstring:
``max_iterations`` is a ceiling, ``time_limit_s`` is a hard deadline —
whichever is hit first wins. Tolerance: wall <= 1.2 x budget + 1s scheduling
slack (CP-SAT hands back control with sub-second granularity).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from synaps.model import ScheduleProblem
from synaps.solvers.alns_solver import AlnsSolver
from synaps.solvers.lbbd_hd_solver import LbbdHdSolver
from synaps.solvers.lbbd_solver import LbbdSolver

INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"
BUDGET_S = 8
# 1.2x per the audit acceptance criterion, +1.0s absolute slack for the last
# in-flight CP-SAT call returning control (granularity, not a policy leak).
MAX_WALL_S = BUDGET_S * 1.2 + 1.0


def _medium() -> ScheduleProblem:
    return ScheduleProblem.model_validate(
        json.loads((INSTANCES / "medium_stress_20x4.json").read_text(encoding="utf-8"))
    )


def test_alns_honors_time_limit() -> None:
    """D3: ALNS wall time must not exceed 1.2x the budget (was 5x)."""
    problem = _medium()
    t0 = time.monotonic()
    result = AlnsSolver().solve(
        problem, time_limit_s=BUDGET_S, random_seed=42, max_iterations=500
    )
    wall = time.monotonic() - t0
    assert result.assignments, "ALNS returned no schedule within the budget"
    assert wall <= MAX_WALL_S, f"ALNS wall {wall:.1f}s exceeds {MAX_WALL_S:.1f}s cap"


def test_lbbd_honors_time_limit() -> None:
    """D3: LBBD must clamp per-cluster budgets to the remaining deadline."""
    problem = _medium()
    t0 = time.monotonic()
    result = LbbdSolver().solve(
        problem, time_limit_s=BUDGET_S, random_seed=42, max_iterations=8
    )
    wall = time.monotonic() - t0
    assert result.assignments, "LBBD returned no schedule within the budget"
    assert wall <= MAX_WALL_S, f"LBBD wall {wall:.1f}s exceeds {MAX_WALL_S:.1f}s cap"


@pytest.mark.slow
def test_lbbd_hd_honors_time_limit() -> None:
    """D3: LBBD-HD must clamp per-cluster budgets to the remaining deadline."""
    problem = _medium()
    t0 = time.monotonic()
    result = LbbdHdSolver().solve(
        problem, time_limit_s=BUDGET_S, random_seed=42, max_iterations=8
    )
    wall = time.monotonic() - t0
    assert result.assignments, "LBBD-HD returned no schedule within the budget"
    assert wall <= MAX_WALL_S, f"LBBD-HD wall {wall:.1f}s exceeds {MAX_WALL_S:.1f}s cap"
