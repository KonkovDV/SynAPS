"""Shared solver portfolio registry for SynAPS runtime surfaces.

This module centralizes the solver configuration names used by the benchmark
runner and future orchestration layers.  Keeping the registry inside the package
avoids configuration drift between CLI tooling, tests, and runtime routing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.lbbd_hd_solver import LbbdHdSolver
from synaps.solvers.lbbd_solver import LbbdSolver
from synaps.solvers.pareto_slice_solver import ParetoSliceCpSatSolver

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from synaps.solvers import BaseSolver


@dataclass(frozen=True)
class SolverRegistration:
    """One named solver configuration in the SynAPS portfolio."""

    factory: Callable[[], BaseSolver]
    solve_kwargs: Mapping[str, object]
    description: str


def _build_greed_default() -> BaseSolver:
    return GreedyDispatch()


def _build_greed_k1_3() -> BaseSolver:
    return GreedyDispatch(k1=3.0)


def _build_cpsat() -> BaseSolver:
    return CpSatSolver()


def _build_lbbd() -> BaseSolver:
    return LbbdSolver()


def _build_lbbd_hd() -> BaseSolver:
    return LbbdHdSolver()


def _build_pareto_slice_cpsat() -> BaseSolver:
    return ParetoSliceCpSatSolver()


_SOLVER_REGISTRY: dict[str, SolverRegistration] = {
    "GREED": SolverRegistration(
        factory=_build_greed_default,
        solve_kwargs={},
        description="Greedy ATCS constructive heuristic (default latency-first path)",
    ),
    "GREED-K1-3": SolverRegistration(
        factory=_build_greed_k1_3,
        solve_kwargs={},
        description="Greedy ATCS constructive heuristic with extended tardiness look-ahead",
    ),
    "CPSAT-10": SolverRegistration(
        factory=_build_cpsat,
        solve_kwargs={"time_limit_s": 10},
        description="Exact CP-SAT solve with a 10-second time box",
    ),
    "CPSAT-30": SolverRegistration(
        factory=_build_cpsat,
        solve_kwargs={"time_limit_s": 30},
        description="Exact CP-SAT solve with a 30-second time box",
    ),
    "CPSAT-120": SolverRegistration(
        factory=_build_cpsat,
        solve_kwargs={"time_limit_s": 120},
        description="Exact CP-SAT solve with a 120-second time box",
    ),
    "CPSAT-EPS-SETUP-110": SolverRegistration(
        factory=_build_pareto_slice_cpsat,
        solve_kwargs={
            "time_limit_s": 30,
            "stage1_time_limit_s": 10,
            "primary_objective": "setup",
            "max_makespan_ratio": 1.10,
        },
        description=(
            "Two-stage CP-SAT epsilon profile: minimise setup under a 10% "
            "near-optimal makespan cap"
        ),
    ),
    "CPSAT-EPS-TARD-110": SolverRegistration(
        factory=_build_pareto_slice_cpsat,
        solve_kwargs={
            "time_limit_s": 30,
            "stage1_time_limit_s": 10,
            "primary_objective": "tardiness",
            "max_makespan_ratio": 1.10,
        },
        description=(
            "Two-stage CP-SAT epsilon profile: minimise tardiness under a 10% "
            "near-optimal makespan cap"
        ),
    ),
    "CPSAT-EPS-MATERIAL-110": SolverRegistration(
        factory=_build_pareto_slice_cpsat,
        solve_kwargs={
            "time_limit_s": 30,
            "stage1_time_limit_s": 10,
            "primary_objective": "material_loss",
            "max_makespan_ratio": 1.10,
        },
        description=(
            "Two-stage CP-SAT epsilon profile: minimise material loss under a 10% "
            "near-optimal makespan cap"
        ),
    ),
    "LBBD-5": SolverRegistration(
        factory=_build_lbbd,
        solve_kwargs={"max_iterations": 5, "time_limit_s": 30},
        description="LBBD decomposition with 5 Benders iterations and 30-second budget",
    ),
    "LBBD-10": SolverRegistration(
        factory=_build_lbbd,
        solve_kwargs={"max_iterations": 10, "time_limit_s": 60},
        description="LBBD decomposition with 10 Benders iterations and 60-second budget",
    ),
    # ---- Hierarchical Decomposition variants (10k–50k+ operations) ----
    "LBBD-5-HD": SolverRegistration(
        factory=_build_lbbd_hd,
        solve_kwargs={
            "max_iterations": 5,
            "time_limit_s": 120,
            "max_ops_per_cluster": 200,
            "num_workers": 8,
            "use_warm_start": True,
        },
        description=(
            "Hierarchical LBBD with balanced partitioning (≤200 ops/cluster), "
            "greedy warm-start, parallel subproblems. 5 iterations, 120s budget."
        ),
    ),
    "LBBD-10-HD": SolverRegistration(
        factory=_build_lbbd_hd,
        solve_kwargs={
            "max_iterations": 10,
            "time_limit_s": 300,
            "max_ops_per_cluster": 200,
            "num_workers": 8,
            "use_warm_start": True,
        },
        description=(
            "Hierarchical LBBD with balanced partitioning (≤200 ops/cluster), "
            "greedy warm-start, parallel subproblems. 10 iterations, 300s budget. "
            "Industrial scale: 10 000–50 000 operations."
        ),
    ),
    "LBBD-20-HD": SolverRegistration(
        factory=_build_lbbd_hd,
        solve_kwargs={
            "max_iterations": 20,
            "time_limit_s": 600,
            "max_ops_per_cluster": 150,
            "num_workers": 8,
            "use_warm_start": True,
            "gap_threshold": 0.005,
        },
        description=(
            "Extended Hierarchical LBBD for 50 000+ operations. "
            "Tighter gap (0.5%), smaller clusters (≤150 ops), 20 iterations, 10min budget."
        ),
    ),
}


def available_solver_configs() -> list[str]:
    """Return the stable list of public solver configuration names."""

    return list(_SOLVER_REGISTRY)


def get_solver_registration(name: str) -> SolverRegistration:
    """Return the registration for *name* or raise a helpful error."""

    try:
        return _SOLVER_REGISTRY[name]
    except KeyError as exc:
        known = ", ".join(available_solver_configs())
        raise ValueError(f"Unknown solver config '{name}'. Expected one of: {known}") from exc


def create_solver(name: str) -> tuple[BaseSolver, dict[str, object]]:
    """Instantiate a configured solver and return its default solve kwargs."""

    registration = get_solver_registration(name)
    return registration.factory(), dict(registration.solve_kwargs)


__all__ = [
    "SolverRegistration",
    "available_solver_configs",
    "create_solver",
    "get_solver_registration",
]
