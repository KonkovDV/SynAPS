"""Tests for the shared SynAPS solver portfolio surfaces."""

from __future__ import annotations

from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.lbbd_solver import LbbdSolver
from synaps.solvers.registry import available_solver_configs, create_solver
from synaps.solvers.router import (
    SolveRegime,
    SolverRoutingContext,
    route_solver_config,
    select_solver,
)
from tests.conftest import make_simple_problem


def test_available_solver_configs_matches_public_portfolio() -> None:
    assert available_solver_configs() == [
        "GREED",
        "GREED-K1-3",
        "BEAM-3",
        "BEAM-5",
        "CPSAT-10",
        "CPSAT-30",
        "CPSAT-120",
        "CPSAT-PARETO-SKETCH-SETUP",
        "CPSAT-EPS-SETUP-110",
        "CPSAT-EPS-TARD-110",
        "CPSAT-EPS-MATERIAL-110",
        "LBBD-5",
        "LBBD-10",
        "LBBD-5-HD",
        "LBBD-10-HD",
        "LBBD-20-HD",
        "ALNS-300",
        "ALNS-500",
        "ALNS-1000",
        "RHC-ALNS",
        "RHC-ALNS-100K",
        "RHC-CPSAT",
        "RHC-GREEDY",
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


def test_create_solver_rhc_alns_defaults_to_greedy_only_inner_repair() -> None:
    solver, solve_kwargs = create_solver("RHC-ALNS")

    assert solver.name == "rhc"
    assert solve_kwargs["inner_solver"] == "alns"
    assert solve_kwargs["progressive_admission_relaxation_enabled"] is True
    assert solve_kwargs["precedence_ready_candidate_filter_enabled"] is True
    assert solve_kwargs["admission_relaxation_min_fill_ratio"] == 0.30
    assert solve_kwargs["due_admission_horizon_factor"] == 2.0
    assert solve_kwargs["admission_full_scan_enabled"] is False
    assert solve_kwargs["alns_budget_auto_scaling_enabled"] is True
    assert solve_kwargs["alns_presearch_max_window_ops"] == 5000
    assert solve_kwargs["alns_budget_estimated_repair_s_per_destroyed_op"] == 0.125
    assert solve_kwargs["hybrid_inner_routing_enabled"] is False
    assert solve_kwargs["hybrid_due_pressure_threshold"] == 0.35
    assert solve_kwargs["hybrid_candidate_pressure_threshold"] == 4.0
    assert solve_kwargs["inner_kwargs"]["use_cpsat_repair"] is False
    assert solve_kwargs["inner_kwargs"]["max_no_improve_iters"] == 30
    assert solve_kwargs["inner_kwargs"]["repair_num_workers"] == 1
    assert solve_kwargs["inner_kwargs"]["sa_auto_calibration_enabled"] is True
    assert solve_kwargs["backtracking_enabled"] is True
    assert solve_kwargs["backtracking_tail_minutes"] == 60
    assert solve_kwargs["backtracking_max_ops"] == 24


def test_create_solver_supports_named_rhc_alns_100k_profile() -> None:
    solver, solve_kwargs = create_solver("RHC-ALNS-100K")

    assert solver.name == "rhc"
    assert solve_kwargs["inner_solver"] == "alns"
    assert solve_kwargs["window_minutes"] == 300
    assert solve_kwargs["overlap_minutes"] == 90
    assert solve_kwargs["hybrid_inner_routing_enabled"] is False
    assert solve_kwargs["inner_kwargs"]["use_cpsat_repair"] is False


def test_create_solver_supports_academic_epsilon_profile() -> None:
    solver, solve_kwargs = create_solver("CPSAT-EPS-SETUP-110")

    assert solver.name == "cpsat_pareto_slice"
    assert solve_kwargs["primary_objective"] == "setup"
    assert solve_kwargs["max_makespan_ratio"] == 1.10


def test_create_solver_supports_adaptive_pareto_sketch_profile() -> None:
    solver, solve_kwargs = create_solver("CPSAT-PARETO-SKETCH-SETUP")

    assert solver.name == "cpsat_pareto_slice"
    assert solve_kwargs["primary_objective"] == "setup"
    assert solve_kwargs["epsilon_grid"] == [1.02, 1.05, 1.10]


def test_route_solver_prefers_extended_cpsat_for_medium_dense_setup_instances() -> None:
    """Medium instances (61-120 ops) with dense setups should use CPSAT-120."""
    # Create a problem with enough ops and dense setup matrix
    # (high nonzero_setup_density from 4 nonzero entries / small setup_slots)
    problem = make_simple_problem(n_orders=18, ops_per_order=4)

    decision = route_solver_config(problem)

    # With 72 ops, 2 states, 2 WCs: setup_density is high (4 entries / 8 slots = 0.5)
    # and ops > 60 → should escalate to CPSAT-120 due to dense setups
    assert decision.solver_config == "CPSAT-120"
    assert "dense setups" in decision.reason or "deep precedence" in decision.reason


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

    assert decision.solver_config == "CPSAT-PARETO-SKETCH-SETUP"
    assert "Pareto sketch" in decision.reason


def test_route_solver_treats_material_only_transitions_as_setup_sensitive() -> None:
    problem = make_simple_problem()
    payload = problem.model_dump()
    for entry in payload["setup_matrix"]:
        entry["setup_minutes"] = 0
        entry["energy_kwh"] = 0.0
        entry["material_loss"] = 0.0
    payload["setup_matrix"][0]["material_loss"] = 1.5
    material_only_problem = problem.__class__.model_validate(payload)

    decision = route_solver_config(
        material_only_problem,
        context=SolverRoutingContext(regime=SolveRegime.WHAT_IF),
    )

    assert decision.solver_config == "CPSAT-PARETO-SKETCH-SETUP"


# ═══════════════════════════════════════════════════════════════════════════
# ALNS / RHC routing tests
# ═══════════════════════════════════════════════════════════════════════════


def test_route_solver_alns_300_for_5k_ops_with_latency_budget() -> None:
    """5K-op instance with >120s latency should route to ALNS-300."""
    problem = make_simple_problem(n_orders=1250, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=180,
        ),
    )

    assert decision.solver_config == "ALNS-300"
    assert "ALNS" in decision.reason


def test_route_solver_alns_500_for_20k_ops_with_latency_budget() -> None:
    """20K-op instance with >300s latency should route to ALNS-500."""
    problem = make_simple_problem(n_orders=5000, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=600,
        ),
    )

    assert decision.solver_config == "ALNS-500"
    assert "ALNS" in decision.reason


def test_route_solver_rhc_alns_for_60k_ops_with_latency_budget() -> None:
    """60K-op instance with >600s latency should route to RHC-ALNS."""
    problem = make_simple_problem(n_orders=15000, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=900,
        ),
    )

    assert decision.solver_config == "RHC-ALNS"
    assert "Receding Horizon" in decision.reason


def test_route_solver_rhc_alns_100k_profile_for_100k_ops_with_latency_budget() -> None:
    """100K-op instance with >600s latency should route to the named 100K RHC profile."""
    problem = make_simple_problem(n_orders=25000, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=900,
        ),
    )

    assert decision.solver_config == "RHC-ALNS-100K"
    assert "100k" in decision.reason.lower() or "300/90" in decision.reason


def test_route_solver_lbbd_for_large_ops_without_latency_budget() -> None:
    """Large instance without explicit latency budget should still route to LBBD-HD."""
    problem = make_simple_problem(n_orders=2500, ops_per_order=4)

    decision = route_solver_config(problem)

    assert decision.solver_config == "LBBD-10-HD"


def test_route_solver_exact_required_bypasses_alns() -> None:
    """Exact requirement should skip ALNS even with generous latency budget."""
    problem = make_simple_problem(n_orders=1250, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            exact_required=True,
            preferred_max_latency_s=600,
        ),
    )

    # exact_required should route to LBBD, not ALNS
    assert "LBBD" in decision.solver_config
