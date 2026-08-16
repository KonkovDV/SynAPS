"""Phase 0.1 (final brief): public Brandimarte instances vs best-known solutions.

The CI threshold that turns S1/S4/S5-class defects from "wait for the next
audit" into an automatic red build:

* every bundled ``mk01``..``mk10`` parses and matches its published shape;
* Wave 5 / T-30: ``fjs_loader`` populates ``machine_duration_overrides``, so
  the loaded instance is the true Brandimarte model. A claimed ``OPTIMAL`` on
  ``BRANDIMARTE_PROVEN_OPTIMAL`` stems must equal literature BKS; all stems
  still forbid OPTIMAL above BKS;
* every reported LBBD lower bound must be <= BKS (an S1-class invalid bound
  otherwise);
* the feasibility checker accepts the produced schedule (hard violations only).

Fast lane (not slow): mk01/mk02 with CPSAT-30 + LBBD. Full sweep of all ten
instances is slow-marked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.fjs_loader import load_fjs_problem
from benchmark.public_bks import BRANDIMARTE_BKS, BRANDIMARTE_PROVEN_OPTIMAL, BRANDIMARTE_SHAPE
from synaps.model import ScheduleProblem, SolverStatus
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityChecker, hard_violations
from synaps.solvers.lbbd_solver import LbbdSolver

_BRANDIMARTE_DIR = (
    Path(__file__).resolve().parent.parent / "benchmark" / "instances" / "public" / "brandimarte"
)
_ALL_STEMS = sorted(BRANDIMARTE_BKS)


def _load(stem: str) -> ScheduleProblem:
    return load_fjs_problem(_BRANDIMARTE_DIR / f"{stem}.fjs")


@pytest.mark.parametrize("stem", _ALL_STEMS)
def test_brandimarte_parses_and_matches_published_shape(stem: str) -> None:
    problem = _load(stem)
    jobs, machines, operations = BRANDIMARTE_SHAPE[stem]
    assert len(problem.orders) == jobs, f"{stem}: job count"
    assert len(problem.work_centers) == machines, f"{stem}: machine count"
    assert len(problem.operations) == operations, f"{stem}: operation count"


def _assert_bks_invariants(stem: str, *, time_limit_s: int) -> None:
    problem = _load(stem)
    bks = BRANDIMARTE_BKS[stem]

    cpsat = CpSatSolver().solve(problem, time_limit_s=time_limit_s, auto_greedy_warm_start=False)
    assert cpsat.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE, SolverStatus.TIMEOUT)
    if cpsat.status is SolverStatus.OPTIMAL:
        # T-30/KI-F16a: with machine_duration_overrides the loaded instance is
        # the true Brandimarte model. Proven-OPT literature stems must match
        # BKS exactly when CP-SAT claims OPTIMAL; all stems still forbid
        # OPTIMAL above BKS.
        assert cpsat.objective.makespan_minutes <= bks + 1e-6, (
            f"{stem}: claimed OPTIMAL {cpsat.objective.makespan_minutes} > BKS {bks}"
        )
        if stem in BRANDIMARTE_PROVEN_OPTIMAL:
            assert abs(cpsat.objective.makespan_minutes - bks) <= 1e-6, (
                f"{stem}: claimed OPTIMAL {cpsat.objective.makespan_minutes} "
                f"!= literature OPT/BKS {bks}"
            )
    if cpsat.assignments:
        assert not hard_violations(
            FeasibilityChecker().check(problem, cpsat.assignments, exhaustive=True)
        ), f"{stem}: CP-SAT schedule failed the independent feasibility check"
    # The CP-SAT dual bound (when published in makespan minutes) is a lower
    # bound on the relaxed optimum, hence must also sit below BKS.
    if cpsat.metadata.get("objective_bound_units") == "makespan_minutes":
        assert float(cpsat.metadata["best_objective_bound"]) <= bks + 1e-6, (
            f"{stem}: CP-SAT makespan bound above BKS (invalid bound)"
        )

    lbbd = LbbdSolver().solve(problem, time_limit_s=time_limit_s, max_iterations=5, random_seed=42)
    lower_bound = float(lbbd.metadata.get("lower_bound", 0.0))
    assert lower_bound <= bks + 1e-6, (
        f"{stem}: LBBD lower_bound {lower_bound} > BKS {bks} (S1-class invalid bound)"
    )


@pytest.mark.parametrize("stem", ["mk01", "mk02"])
def test_brandimarte_bks_invariants_fast(stem: str) -> None:
    _assert_bks_invariants(stem, time_limit_s=20)


@pytest.mark.slow
@pytest.mark.parametrize("stem", _ALL_STEMS)
def test_brandimarte_bks_invariants_full(stem: str) -> None:
    _assert_bks_invariants(stem, time_limit_s=60)
