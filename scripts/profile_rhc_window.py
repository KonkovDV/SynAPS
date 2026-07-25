"""Profile where per-window time is spent in RHC-ALNS on a 50K instance.

Runs 3 windows and captures inner_window_summaries timing breakdown.
"""

import time

from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.solvers.rhc import RhcPolicy, RhcSolver
from synaps.solvers.rhc._policy import RhcPolicySpec, build_solve_kwargs_from_spec

problem = generate_large_instance(
    n_operations=50_000, n_machines=100, n_states=20, setup_density=0.5, seed=1
)
print(f"Instance: {len(problem.operations)} ops, {len(problem.work_centers)} machines")

spec = RhcPolicySpec.from_preset(RhcPolicy.FAST_50K)
kwargs = build_solve_kwargs_from_spec(spec)
kwargs["time_limit_s"] = 600
kwargs["random_seed"] = 1
kwargs["max_windows"] = 3  # Only 3 windows for profiling
kwargs["fallback_repair_enabled"] = False  # Skip expensive fallback on unscheduled ops

print("\n--- Profiling 3 windows ---")
t0 = time.time()
solver = RhcSolver(policy=RhcPolicy.FAST_50K)
result = solver.solve(problem, **kwargs)
elapsed = time.time() - t0

print(f"Total: {elapsed:.1f}s, windows={result.metadata.get('windows_solved', 0)}")
print(f"Status: {result.status}")
print(f"Fallback ratio: {result.metadata.get('inner_fallback_ratio', 'N/A')}")
print(f"Preprocessing: {result.metadata.get('preprocessing_ms', 0)}ms")

summaries = result.metadata.get("inner_window_summaries", [])
for i, s in enumerate(summaries):
    print(f"\nWindow {i}:")
    print(f"  ops_in_window: {s.get('ops_in_window', '?')}")
    print(f"  resolution_mode: {s.get('resolution_mode', '?')}")
    print(f"  initial_solver: {s.get('initial_solver', '?')}")
    print(f"  initial_solution_ms: {s.get('initial_solution_ms', '?')}")
    print(f"  iterations_completed: {s.get('iterations_completed', '?')}")
    print(f"  improvements: {s.get('improvements', '?')}")
    print(f"  inner_time_limit_s: {s.get('inner_time_limit_s', '?')}")
    print(
        f"  time_limit_exhausted_before_search: {s.get('time_limit_exhausted_before_search', '?')}"
    )
    print(f"  budget_guard_skipped: {s.get('budget_guard_skipped_initial_search', '?')}")
    print(f"  native_initial_seed_used: {s.get('native_initial_seed_used', '?')}")
    print(f"  native_initial_seed_ms: {s.get('native_initial_seed_ms', '?')}")
    print(f"  warm_start_used: {s.get('warm_start_used', '?')}")
    print(f"  fallback_reason: {s.get('fallback_reason', 'none')}")
    print(f"  alns_budget_auto_scaled: {s.get('alns_budget_auto_scaled', '?')}")
    print(f"  alns_effective_max_iterations: {s.get('alns_effective_max_iterations', '?')}")
