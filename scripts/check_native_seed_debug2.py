"""Debug: call greedy_repair_batch_native directly to see the error."""

from collections import deque

import numpy as np

from synaps.accelerators import greedy_repair_batch_native
from synaps.benchmarks.instance_generator import generate_large_instance

problem = generate_large_instance(n_operations=10, n_machines=3, n_states=3, seed=42)

# Build topological order
ops_by_id = {op.id: op for op in problem.operations}
wc_id_to_idx = {wc.id: idx for idx, wc in enumerate(problem.work_centers)}
state_id_to_idx = {s.id: idx for idx, s in enumerate(problem.states)}
n_wc = len(problem.work_centers)
n_states = len(problem.states)

# Topological sort
indegree = {op.id: 0 for op in problem.operations}
successors = {}
for op in problem.operations:
    if op.predecessor_op_id is not None and op.predecessor_op_id in indegree:
        indegree[op.id] += 1
        successors.setdefault(op.predecessor_op_id, []).append(op.id)

queue = deque([op_id for op_id, deg in indegree.items() if deg == 0])
topo_order = []
while queue:
    node = queue.popleft()
    topo_order.append(node)
    for succ in successors.get(node, []):
        indegree[succ] -= 1
        if indegree[succ] == 0:
            queue.append(succ)

print(f"Topo order: {len(topo_order)} ops (expected {len(problem.operations)})")

# Build arrays
n = len(topo_order)
local_idx = {op_id: i for i, op_id in enumerate(topo_order)}

base_durations = np.empty(n, dtype=np.float64)
predecessor_indices = np.full(n, -1, dtype=np.int64)
state_ids = np.empty(n, dtype=np.int64)
eligible_offsets = np.empty(n + 1, dtype=np.int64)
eligible_flat = []
eligible_offsets[0] = 0

for i, op_id in enumerate(topo_order):
    op = ops_by_id[op_id]
    base_durations[i] = float(op.base_duration_min)
    state_ids[i] = state_id_to_idx.get(op.state_id, -1)
    if op.predecessor_op_id is not None:
        pred_local = local_idx.get(op.predecessor_op_id)
        if pred_local is not None:
            predecessor_indices[i] = pred_local
    for wc_id in op.eligible_wc_ids or [wc.id for wc in problem.work_centers]:
        wc_idx = wc_id_to_idx.get(wc_id)
        if wc_idx is not None:
            eligible_flat.append(wc_idx)
    eligible_offsets[i + 1] = len(eligible_flat)

eligible_indices = np.array(eligible_flat, dtype=np.int64)
sdst_setup_flat = np.zeros(n_wc * n_states * n_states, dtype=np.float64)
for entry in problem.setup_matrix:
    wi = wc_id_to_idx.get(entry.work_center_id)
    fi = state_id_to_idx.get(entry.from_state_id)
    ti = state_id_to_idx.get(entry.to_state_id)
    if wi is not None and fi is not None and ti is not None:
        sdst_setup_flat[wi * n_states * n_states + fi * n_states + ti] = float(entry.setup_minutes)

speed_factors = np.array([wc.speed_factor for wc in problem.work_centers], dtype=np.float64)

print(f"Arrays built: n={n}, n_wc={n_wc}, n_states={n_states}")
print(
    f"eligible_offsets shape: {eligible_offsets.shape}, "
    f"eligible_indices shape: {eligible_indices.shape}"
)

result = greedy_repair_batch_native(
    base_durations=base_durations,
    predecessor_indices=predecessor_indices,
    eligible_offsets=eligible_offsets,
    eligible_indices=eligible_indices,
    state_ids=state_ids,
    sdst_setup_flat=sdst_setup_flat,
    n_wc=n_wc,
    n_states=n_states,
    speed_factors=speed_factors,
)

if result is None:
    print("ERROR: greedy_repair_batch_native returned None!")
else:
    starts, ends, machines = result
    print(f"SUCCESS: {len(starts)} assignments")
    print(f"  starts: {starts[:5]}")
    print(f"  ends: {ends[:5]}")
    print(f"  machines: {machines[:5]}")
