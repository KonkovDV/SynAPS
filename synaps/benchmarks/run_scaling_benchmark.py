"""Benchmark runner — measure SynAPS solvers at 1K, 5K, 10K, 50K operations.

Usage:
    python -m synaps.benchmarks.run_scaling_benchmark

Output goes to stdout as structured JSON lines for downstream analysis.
"""

from __future__ import annotations

import json
import time
from typing import Any, TypedDict

from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.solvers.alns_solver import AlnsSolver
from synaps.solvers.greedy_dispatch import BeamSearchDispatch, GreedyDispatch
from synaps.solvers.rhc_solver import RhcSolver
from synaps.solvers.sdst_matrix import SdstMatrix
from synaps.validation import verify_schedule_result


class BenchmarkConfig(TypedDict):
    n_ops: int
    n_machines: int
    n_states: int
    solver_name: str
    solver_kwargs: dict[str, Any]


def run_benchmark(
    n_ops: int,
    n_machines: int,
    n_states: int,
    solver_name: str,
    solver_kwargs: dict[str, Any],
    seed: int = 42,
) -> dict[str, Any]:
    """Run a single benchmark configuration and return metrics."""

    # Generate instance
    t_gen = time.monotonic()
    problem = generate_large_instance(
        n_operations=n_ops,
        n_machines=n_machines,
        n_states=n_states,
        setup_density=0.5,
        seed=seed,
    )
    gen_ms = int((time.monotonic() - t_gen) * 1000)

    # Build SDST matrix metrics
    sdst = SdstMatrix.from_problem(problem)

    # Solve
    solver: GreedyDispatch | BeamSearchDispatch | AlnsSolver | RhcSolver
    if solver_name == "greedy":
        solver = GreedyDispatch()
    elif solver_name == "beam-3":
        solver = BeamSearchDispatch(beam_width=3)
    elif solver_name == "alns":
        solver = AlnsSolver()
    elif solver_name == "rhc-alns" or solver_name == "rhc-greedy":
        solver = RhcSolver()
    else:
        raise ValueError(f"Unknown solver: {solver_name}")

    t_solve = time.monotonic()
    result = solver.solve(problem, **solver_kwargs)
    solve_ms = int((time.monotonic() - t_solve) * 1000)

    # Verify
    t_verify = time.monotonic()
    verification = verify_schedule_result(problem, result)
    verify_ms = int((time.monotonic() - t_verify) * 1000)

    return {
        "n_ops": n_ops,
        "n_machines": n_machines,
        "n_states": n_states,
        "solver": solver_name,
        "status": str(result.status),
        "feasible": verification.feasible,
        "violations": verification.violation_count,
        "makespan_min": round(result.objective.makespan_minutes, 2),
        "total_setup_min": round(result.objective.total_setup_minutes, 2),
        "total_tardiness_min": round(result.objective.total_tardiness_minutes, 2),
        "total_material_loss": round(result.objective.total_material_loss, 2),
        "assigned_ops": len(result.assignments),
        "solve_ms": solve_ms,
        "gen_ms": gen_ms,
        "verify_ms": verify_ms,
        "sdst_memory_bytes": sdst.memory_bytes(),
        "metadata": result.metadata,
    }


BENCHMARK_SUITE: list[BenchmarkConfig] = [
    # 1K — all solvers should handle this easily
    {"n_ops": 1000, "n_machines": 20, "n_states": 10, "solver_name": "greedy", "solver_kwargs": {}},
    {"n_ops": 1000, "n_machines": 20, "n_states": 10, "solver_name": "beam-3", "solver_kwargs": {}},
    {"n_ops": 1000, "n_machines": 20, "n_states": 10, "solver_name": "alns", "solver_kwargs": {
        "max_iterations": 100, "time_limit_s": 30, "repair_time_limit_s": 3,
        "min_destroy": 10, "max_destroy": 50,
    }},

    # 5K — ALNS sweet spot
    {"n_ops": 5000, "n_machines": 50, "n_states": 15, "solver_name": "greedy", "solver_kwargs": {}},
    {"n_ops": 5000, "n_machines": 50, "n_states": 15, "solver_name": "alns", "solver_kwargs": {
        "max_iterations": 200, "time_limit_s": 60, "repair_time_limit_s": 5,
        "min_destroy": 20, "max_destroy": 150,
    }},

    # 10K — ALNS + RHC
    {
        "n_ops": 10000, "n_machines": 50, "n_states": 15,
        "solver_name": "greedy", "solver_kwargs": {},
    },
    {"n_ops": 10000, "n_machines": 50, "n_states": 15, "solver_name": "alns", "solver_kwargs": {
        "max_iterations": 300, "time_limit_s": 120, "repair_time_limit_s": 5,
        "min_destroy": 30, "max_destroy": 200,
    }},
    {"n_ops": 10000, "n_machines": 50, "n_states": 15, "solver_name": "rhc-alns", "solver_kwargs": {
        "window_minutes": 480, "overlap_minutes": 120, "inner_solver": "alns",
        "time_limit_s": 120, "max_ops_per_window": 3000,
        "inner_kwargs": {"max_iterations": 100, "time_limit_s": 30, "repair_time_limit_s": 3},
    }},

    # 50K — RHC-ALNS is the primary path
    {
        "n_ops": 50000, "n_machines": 100, "n_states": 20,
        "solver_name": "greedy", "solver_kwargs": {},
    },
    {
        "n_ops": 50000, "n_machines": 100, "n_states": 20,
        "solver_name": "rhc-greedy", "solver_kwargs": {
        "window_minutes": 480, "overlap_minutes": 60, "inner_solver": "greedy",
        "time_limit_s": 120, "max_ops_per_window": 10000,
    }},
    {
        "n_ops": 50000, "n_machines": 100, "n_states": 20,
        "solver_name": "rhc-alns", "solver_kwargs": {
        "window_minutes": 480, "overlap_minutes": 120, "inner_solver": "alns",
        "time_limit_s": 300, "alns_inner_window_time_cap_s": 180, "max_ops_per_window": 5000,
        "inner_kwargs": {
            "max_iterations": 100,
            "destroy_fraction": 0.03,
            "min_destroy": 10,
            "max_destroy": 40,
            "max_no_improve_iters": 30,
            "use_cpsat_repair": True,
            "repair_time_limit_s": 5,
            "repair_num_workers": 1,
            "cpsat_max_destroy_ops": 32,
            "sa_auto_calibration_enabled": True,
        },
    }},
]


def main() -> None:
    """Run the full scaling benchmark suite."""
    print("=" * 70)
    print("SynAPS Scaling Benchmark — ALNS + RHC (April 2026)")
    print("=" * 70)

    results = []
    for i, config in enumerate(BENCHMARK_SUITE):
        n_ops = config["n_ops"]
        solver = config["solver_name"]
        print(
            f"\n[{i + 1}/{len(BENCHMARK_SUITE)}] "
            f"{solver} @ {n_ops:,} ops ... ",
            end="", flush=True,
        )

        try:
            result = run_benchmark(
                n_ops=config["n_ops"],
                n_machines=config["n_machines"],
                n_states=config["n_states"],
                solver_name=config["solver_name"],
                solver_kwargs=config["solver_kwargs"],
            )
            results.append(result)
            status = "✓" if result["feasible"] else "✗"
            print(
                f"{status} makespan={result['makespan_min']:.0f}min "
                f"setup={result['total_setup_min']:.0f}min "
                f"solve={result['solve_ms']}ms "
                f"({result['assigned_ops']}/{n_ops} ops)"
            )
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"n_ops": n_ops, "solver": solver, "error": str(e)})

    # Write JSON results
    print("\n" + "=" * 70)
    print("Results (JSON):")
    for r in results:
        print(json.dumps(r, default=str))


if __name__ == "__main__":
    main()
