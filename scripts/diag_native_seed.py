"""Diagnostic: why does native initial seed fail on RHC sub-problems?"""

import time

from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.solvers.alns_solver import AlnsSolver

# Simulate what RHC does: generate a 600-op sub-problem (typical window size)
problem = generate_large_instance(n_operations=600, n_machines=100, n_states=20, seed=1)
print(f"Sub-problem: {len(problem.operations)} ops, {len(problem.work_centers)} machines")

solver = AlnsSolver()
t0 = time.time()
result = solver.solve(
    problem,
    max_iterations=10,
    time_limit_s=60,
    native_initial_seed_enabled=True,
    use_cpsat_repair=False,
)
elapsed = time.time() - t0

md = result.metadata
print(f"Elapsed: {elapsed:.1f}s")
print(f"Status: {result.status}")
print(f"initial_solver: {md.get('initial_solver')}")
print(f"native_initial_seed_attempted: {md.get('native_initial_seed_attempted')}")
print(f"native_initial_seed_used: {md.get('native_initial_seed_used')}")
print(f"native_initial_seed_ms: {md.get('native_initial_seed_ms')}")
print(f"native_initial_seed_fallback_reason: {md.get('native_initial_seed_fallback_reason')}")
print(f"initial_solution_ms: {md.get('initial_solution_ms')}")
print(f"iterations_completed: {md.get('iterations_completed')}")
print(f"assignments: {len(result.assignments)}")
