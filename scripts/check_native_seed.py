"""Quick check: is native initial seed being used?"""

from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.solvers.alns_solver import AlnsSolver

problem = generate_large_instance(n_operations=100, n_machines=5, n_states=3, seed=42)
solver = AlnsSolver()
result = solver.solve(problem, max_iterations=5, time_limit_s=30, native_initial_seed_enabled=True)
md = result.metadata
print("native_initial_seed_attempted:", md.get("native_initial_seed_attempted"))
print("native_initial_seed_used:", md.get("native_initial_seed_used"))
print("native_initial_seed_ms:", md.get("native_initial_seed_ms"))
print("native_initial_seed_fallback_reason:", md.get("native_initial_seed_fallback_reason"))
print("initial_solver:", md.get("initial_solver"))
print("status:", result.status)
print("assignments:", len(result.assignments))
