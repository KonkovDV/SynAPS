"""Tests for the shared SynAPS solver portfolio surfaces."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from synaps.model import SolverStatus
from synaps.solvers.coverage_outcome import CoverageClass, classify_coverage
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.lbbd_solver import LbbdSolver
from synaps.solvers.registry import available_solver_configs, create_solver
from synaps.solvers.router import (
    PortfolioPolicy,
    SolveRegime,
    SolverRoutingContext,
    route_solver_config,
    select_solver,
)
from tests.conftest import make_simple_problem

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_registry_create_greed_does_not_import_highspy() -> None:
    """GREED/CPSAT smoke must not require a working highspy wheel at import time."""

    script = """
import sys
from synaps.solvers.registry import create_solver

assert "highspy" not in sys.modules
assert "synaps.solvers.lbbd_solver" not in sys.modules
assert "synaps.solvers.lbbd_hd_solver" not in sys.modules
create_solver("GREED")
assert "highspy" not in sys.modules
assert "synaps.solvers.lbbd_solver" not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


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
        "RHC-ALNS-SEARCH-COVER",
        "RHC-CPSAT",
        "RHC-GREEDY",
        "RHC-GREEDY-COVER",
    ]


def test_every_named_config_declares_time_limit_s() -> None:
    """B3: fail-closed. No public named config may omit a wall box."""
    for name in available_solver_configs():
        _solver, solve_kwargs = create_solver(name)
        limit = solve_kwargs.get("time_limit_s")
        if limit is None and isinstance(solve_kwargs.get("inner_kwargs"), dict):
            limit = solve_kwargs["inner_kwargs"].get("time_limit_s")
        assert limit is not None, name
        assert float(limit) > 0, name


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
    assert solve_kwargs == {"time_limit_s": 120}

    default, default_kwargs = create_solver("GREED")
    assert isinstance(default, GreedyDispatch)
    assert default_kwargs == {"time_limit_s": 120}


def test_create_solver_rhc_alns_defaults_to_greedy_only_inner_repair() -> None:
    solver, solve_kwargs = create_solver("RHC-ALNS")

    assert solver.name == "rhc"
    assert solve_kwargs["inner_solver"] == "alns"
    assert solve_kwargs["progressive_admission_relaxation_enabled"] is True
    assert solve_kwargs["precedence_ready_candidate_filter_enabled"] is False
    assert solve_kwargs["admission_relaxation_min_fill_ratio"] == 0.30
    assert solve_kwargs["due_admission_horizon_factor"] == 6.0
    assert solve_kwargs["admission_full_scan_enabled"] is True
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


def test_route_solver_cover_for_20k_ops_with_latency_budget() -> None:
    """20K-op long-horizon instance with >300s latency routes to RHC-GREEDY-COVER."""
    problem = make_simple_problem(n_orders=5000, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=600,
        ),
    )

    assert decision.solver_config == "RHC-GREEDY-COVER"
    assert "rolling-horizon" in decision.reason


def test_route_solver_cover_for_60k_ops_with_latency_budget() -> None:
    """60K-op instance with >600s latency uses the 50k-feasible cover path."""
    problem = make_simple_problem(n_orders=15000, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=900,
        ),
    )

    assert decision.solver_config == "RHC-GREEDY-COVER"
    assert "rolling-horizon greedy" in decision.reason


def test_route_solver_cover_for_100k_ops_with_latency_budget() -> None:
    """100K-op instance with >600s latency also uses cover, not RHC-ALNS-100K."""
    problem = make_simple_problem(n_orders=25000, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=900,
        ),
    )

    assert decision.solver_config == "RHC-GREEDY-COVER"
    assert "rolling-horizon greedy" in decision.reason


def test_route_feasibility_first_greedy_for_medium_nominal() -> None:
    problem = make_simple_problem(n_orders=40, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            portfolio_policy=PortfolioPolicy.FEASIBILITY_FIRST,
        ),
    )

    assert decision.solver_config == "GREED"
    assert "feasibility-first" in decision.reason


def test_route_feasibility_first_rhc_greedy_for_ultra_large_nominal() -> None:
    problem = make_simple_problem(n_orders=15000, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            portfolio_policy=PortfolioPolicy.FEASIBILITY_FIRST,
        ),
    )

    assert decision.solver_config == "RHC-GREEDY"
    assert "feasibility-first" in decision.reason


def test_route_feasibility_first_cover_for_ultra_large_with_latency() -> None:
    problem = make_simple_problem(n_orders=15000, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            portfolio_policy=PortfolioPolicy.FEASIBILITY_FIRST,
            preferred_max_latency_s=900,
        ),
    )

    assert decision.solver_config == "RHC-GREEDY-COVER"
    assert "coverage-complete" in decision.reason


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


def test_route_solver_exact_required_beats_interactive_and_latency() -> None:
    """A15-P1-1: exact_required is not shadowed by INTERACTIVE or latency<=1."""
    problem = make_simple_problem()

    interactive = route_solver_config(
        problem,
        context=SolverRoutingContext(regime=SolveRegime.INTERACTIVE, exact_required=True),
    )
    assert interactive.solver_config.startswith("CPSAT")

    tight = route_solver_config(
        problem,
        context=SolverRoutingContext(preferred_max_latency_s=1, exact_required=True),
    )
    assert tight.solver_config.startswith("CPSAT")


def test_route_solver_alns_500_for_5k_ops_with_400s_budget() -> None:
    """A15-P1-3: 5k ops @ 400s must not be shadowed by the ALNS-300 branch."""
    problem = make_simple_problem(n_orders=1250, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=400,
        ),
    )

    assert decision.solver_config == "ALNS-500"


def test_route_solver_skips_alns_500_when_hard_windows() -> None:
    """N1: 5k@400s with a per-op window is not a coverage route through ALNS-500."""
    problem = make_simple_problem(n_orders=1250, ops_per_order=4)
    payload = problem.model_dump()
    payload["operations"][0]["latest_finish"] = payload["planning_horizon_end"]
    windowed = problem.__class__.model_validate(payload)

    decision = route_solver_config(
        windowed,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=400,
        ),
    )

    assert decision.solver_config == "RHC-GREEDY"
    assert "window" in decision.reason or "calendar" in decision.reason


def test_route_solver_skips_alns_500_on_3k_and_9k_windowed() -> None:
    """E1: 3k-9k with hard windows must not default to ALNS-500."""
    for n_orders in (750, 2250):
        problem = make_simple_problem(n_orders=n_orders, ops_per_order=4)
        payload = problem.model_dump()
        payload["operations"][0]["latest_finish"] = payload["planning_horizon_end"]
        windowed = problem.__class__.model_validate(payload)
        decision = route_solver_config(
            windowed,
            context=SolverRoutingContext(
                regime=SolveRegime.NOMINAL,
                preferred_max_latency_s=400,
            ),
        )
        assert decision.solver_config == "RHC-GREEDY", (n_orders, decision.solver_config)


def test_default_cheap_routes_schedule_at_least_one_op() -> None:
    """E3: GREED / CPSAT-10 on the tiny fixture must not return an empty success."""
    problem = make_simple_problem()
    for name in ("GREED", "CPSAT-10"):
        solver, kwargs = create_solver(name)
        result = solver.solve(problem, **kwargs)
        coverage = classify_coverage(
            n_operations=len(problem.operations),
            n_assigned=len(result.assignments),
        )
        assert coverage is not CoverageClass.EMPTY, name
        assert result.status not in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL} or (
            len(result.assignments) > 0
        )


def test_route_feasibility_first_skips_alns_500_when_hard_windows() -> None:
    problem = make_simple_problem(n_orders=1250, ops_per_order=4)
    payload = problem.model_dump()
    payload["operations"][0]["latest_finish"] = payload["planning_horizon_end"]
    windowed = problem.__class__.model_validate(payload)

    decision = route_solver_config(
        windowed,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=400,
            portfolio_policy=PortfolioPolicy.FEASIBILITY_FIRST,
        ),
    )

    assert decision.solver_config == "RHC-GREEDY"


def test_route_solver_cover_for_50k_ops_without_latency_budget() -> None:
    """50K ops without a latency hint must not fall through to unvalidated LBBD-HD."""
    problem = make_simple_problem(n_orders=12500, ops_per_order=4)

    decision = route_solver_config(problem)

    assert decision.solver_config == "RHC-GREEDY-COVER"


def test_route_solver_cover_for_50k_ops_with_400s_budget() -> None:
    """50K ops @ 400s must not be swallowed by monolithic ALNS-500."""
    problem = make_simple_problem(n_orders=12500, ops_per_order=4)

    decision = route_solver_config(
        problem,
        context=SolverRoutingContext(
            regime=SolveRegime.NOMINAL,
            preferred_max_latency_s=400,
        ),
    )

    assert decision.solver_config == "RHC-GREEDY-COVER"
