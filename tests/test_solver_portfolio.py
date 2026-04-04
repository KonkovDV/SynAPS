"""Tests for the shared SynAPS solver portfolio surfaces."""

from __future__ import annotations

from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.lbbd_solver import LbbdSolver
from synaps.solvers.registry import available_solver_configs, create_solver
from synaps.solvers.router import SolveRegime, SolverRoutingContext, route_solver_config, select_solver
from tests.conftest import make_simple_problem


def test_available_solver_configs_matches_public_portfolio() -> None:
    assert available_solver_configs() == [
        "GREED",
        "GREED-K1-3",
        "CPSAT-10",
        "CPSAT-30",
        "CPSAT-120",
        "CPSAT-EPS-SETUP-110",
        "CPSAT-EPS-TARD-110",
        "LBBD-5",
        "LBBD-10",
    ]


def test_create_solver_returns_solver_instance_and_default_solve_kwargs() -> None:
    solver, solve_kwargs = create_solver("CPSAT-10")

    assert isinstance(solver, CpSatSolver)
    assert solve_kwargs == {"time_limit_s": 10}


def test_route_solver_prefers_greedy_for_interactive_regime() -> None:
    problem = make_simple_problem()

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(regime=SolveRegime.INTERACTIVE),
    )

    assert decision.solver_config == "GREED"
    assert "interactive regime" in decision.reason


def test_route_solver_prefers_exact_cp_sat_for_small_nominal_instances() -> None:
    problem = make_simple_problem()

    decision = route_solver_config(problem)

    assert decision.solver_config == "CPSAT-10"
    assert "small nominal instance" in decision.reason


def test_route_solver_prefers_lbbd_for_large_nominal_instances() -> None:
    problem = make_simple_problem(n_orders=40, ops_per_order=4)

    decision = route_solver_config(problem)

    assert decision.solver_config == "LBBD-10"
    assert "larger nominal instance" in decision.reason


def test_select_solver_returns_routed_solver_and_kwargs() -> None:
    problem = make_simple_problem(n_orders=40, ops_per_order=4)

    solver, solve_kwargs, decision = select_solver(
        problem,
        context=SolverRoutingContext(exact_required=True),
    )

    assert isinstance(solver, LbbdSolver)
    assert solve_kwargs == {"max_iterations": 10, "time_limit_s": 60}
    assert decision.solver_config == "LBBD-10"


def test_create_solver_supports_greedy_variant() -> None:
    solver, solve_kwargs = create_solver("GREED-K1-3")

    assert isinstance(solver, GreedyDispatch)
    assert solve_kwargs == {}


def test_create_solver_supports_academic_epsilon_profile() -> None:
    solver, solve_kwargs = create_solver("CPSAT-EPS-SETUP-110")

    assert solver.name == "cpsat_pareto_slice"
    assert solve_kwargs["primary_objective"] == "setup"
    assert solve_kwargs["max_makespan_ratio"] == 1.10


def test_create_solver_supports_tardiness_epsilon_profile() -> None:
    solver, solve_kwargs = create_solver("CPSAT-EPS-TARD-110")

    assert solver.name == "cpsat_pareto_slice"
    assert solve_kwargs["primary_objective"] == "tardiness"
    assert solve_kwargs["max_makespan_ratio"] == 1.10


def test_route_solver_prefers_epsilon_setup_for_what_if_small_with_setups() -> None:
    """WHAT_IF regime on a small instance with nonzero setups should route
    to the Pareto-slice epsilon profile (D5 regression)."""
    problem = make_simple_problem()  # 4 ops, 2 WC, has nonzero setups

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(regime=SolveRegime.WHAT_IF),
    )

    assert decision.solver_config == "CPSAT-EPS-SETUP-110"
    assert "Pareto-slice" in decision.reason