"""Debug: why is native initial seed failing?"""

import traceback

from synaps.accelerators import _native_greedy_repair_batch
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.solvers.alns_solver import _try_native_initial_seed

print("_native_greedy_repair_batch available:", _native_greedy_repair_batch is not None)

problem = generate_large_instance(n_operations=20, n_machines=3, n_states=3, seed=42)
ops_by_id = {op.id: op for op in problem.operations}
frozen_assignments_by_op = {}

try:
    result = _try_native_initial_seed(
        problem,
        frozen_assignments=[],
        ops_by_id=ops_by_id,
        frozen_assignments_by_op=frozen_assignments_by_op,
    )
    print("Result:", result)
    if result is not None:
        print("Assignments:", len(result))
    else:
        print("Result is None — native seed failed")
except Exception as e:
    print("Exception:", e)
    traceback.print_exc()
