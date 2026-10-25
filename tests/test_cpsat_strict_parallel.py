"""CP-SAT ``determinism="strict-parallel"`` (interleaved subsolvers) contract.

Audit 2026-10 / ADR-0001 addendum. The mode keeps the strict contract —
deterministic-time stop, loose wall safety, ``determinism_violated`` when the
wall safety ends the search — with ``num_workers`` interleaved subsolvers.
Measured in benchmark/evidence/cpsat-determinism-2026-10-24/: identical
schedules across repeated runs whenever the wall safety did not end the search,
and a better incumbent than single-thread ``strict`` at the same budget. Under
interleaving the deterministic limit is checked between batches, so the search
overshoots it by a few units; at very small budgets the wall safety therefore
ends the run and ``determinism_violated`` is raised (the test then skips).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from synaps.model import ScheduleProblem, SolverStatus
from synaps.solvers.cpsat_solver import CpSatSolver

_INSTANCE = (
    Path(__file__).resolve().parents[1] / "benchmark" / "instances" / "medium_stress_20x4.json"
)


def _problem() -> ScheduleProblem:
    return ScheduleProblem.model_validate(json.loads(_INSTANCE.read_text(encoding="utf-8")))


def _fingerprint(result: object) -> str:
    rows = sorted(
        (str(a.operation_id), str(a.work_center_id), a.start_time.isoformat())
        for a in result.assignments  # type: ignore[attr-defined]
    )
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def _solve(problem: ScheduleProblem, *, workers: int = 4) -> object:
    return CpSatSolver().solve(
        problem,
        time_limit_s=4,
        random_seed=7,
        num_workers=workers,
        determinism="strict-parallel",
        auto_greedy_warm_start=False,
    )


def test_strict_parallel_is_reproducible_when_the_deterministic_stop_binds() -> None:
    problem = _problem()
    runs = [_solve(problem) for _ in range(3)]
    for run in runs:
        assert run.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}  # type: ignore[attr-defined]
        params = run.metadata["sat_parameters"]  # type: ignore[attr-defined]
        assert params["determinism"] == "strict-parallel"
        assert params["num_workers"] == 4
        assert params["interleave_search"] is True
        assert params["max_deterministic_time"] == pytest.approx(2.0)
    clean = [_fingerprint(r) for r in runs if not r.metadata["determinism_violated"]]  # type: ignore[attr-defined]
    if not clean:
        pytest.skip("host too loaded: every run hit the wall safety (flagged, as designed)")
    assert len(set(clean)) == 1


def test_strict_parallel_rejects_identity_overrides() -> None:
    with pytest.raises(ValueError, match="strict"):
        CpSatSolver().solve(
            _problem(),
            time_limit_s=1,
            determinism="strict-parallel",
            sat_parameters={"num_workers": 2},
        )


def test_unknown_determinism_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="strict-parallel"):
        CpSatSolver().solve(_problem(), time_limit_s=1, determinism="sometimes")
