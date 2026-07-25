"""Quick comparative benchmark: FAST_50K vs BALANCED on 50K instance."""

import time

from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.solvers.rhc import RhcPolicy, RhcSolver
from synaps.solvers.rhc._policy import RhcPolicySpec, build_solve_kwargs_from_spec
from synaps.validation import verify_schedule_result

problem = generate_large_instance(
    n_operations=50_000, n_machines=100, n_states=20, setup_density=0.5, seed=1
)
print(f"Instance: {len(problem.operations)} ops, {len(problem.work_centers)} machines")

# FAST_50K run
spec = RhcPolicySpec.from_preset(RhcPolicy.FAST_50K)
kwargs = build_solve_kwargs_from_spec(spec)
kwargs["time_limit_s"] = 1200
kwargs["random_seed"] = 1

print("\n--- FAST_50K ---")
t0 = time.time()
result = RhcSolver().solve(problem, **kwargs)
elapsed = time.time() - t0

v = verify_schedule_result(problem, result)
scheduled = len(result.assignments) / len(problem.operations)
print(f"Wall-time: {elapsed:.1f}s")
print(f"Makespan: {result.objective.makespan_minutes:.1f} min")
print(f"Scheduled: {scheduled:.3f} ({len(result.assignments)}/{len(problem.operations)})")
print(f"Feasible: {v.feasible} (violations: {v.violation_count})")
print(f"Windows: {result.metadata.get('windows_solved', 0)}")
print(f"Fallback ratio: {result.metadata.get('inner_fallback_ratio', 'N/A')}")
print(f"Status: {result.status}")
