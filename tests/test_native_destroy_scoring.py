"""Tests for native ALNS destroy worst scoring parity and performance.

Covers tasks 4.5–4.6 from the synaps-50k-solver-improvement spec:
- 4.5: Parity test — native and Python score vectors match within 1e-10 tolerance
- 4.6: Benchmark test — < 10 ms for 50K operations across 100 machines
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import numpy as np
import pytest

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.sdst_matrix import SdstMatrix

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = HORIZON_START + timedelta(hours=24)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_deterministic_problem(
    n_machines: int,
    n_states: int,
    ops_per_machine: int,
    seed: int = 42,
) -> tuple[ScheduleProblem, list[Assignment], dict]:
    """Build a deterministic problem with known setup costs and assignments.

    Returns (problem, assignments, ops_by_id) for testing.
    """
    rng = np.random.default_rng(seed)

    states = [State(id=uuid4(), code=f"S-{i}", label=f"State {i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(id=uuid4(), code=f"WC-{i}", capability_group="machining")
        for i in range(n_machines)
    ]

    # Build setup entries with deterministic values
    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                setup_entries.append(
                    SetupEntry(
                        work_center_id=wc.id,
                        from_state_id=s_from.id,
                        to_state_id=s_to.id,
                        setup_minutes=int(rng.integers(1, 60)),
                        material_loss=0.0,
                        energy_kwh=0.0,
                    )
                )

    # Build operations and assignments
    order_id = uuid4()
    orders = [Order(id=order_id, external_ref="ORD-0001", due_date=HORIZON_END)]

    operations: list[Operation] = []
    assignments: list[Assignment] = []

    n_machines * ops_per_machine
    for m_idx in range(n_machines):
        wc = work_centers[m_idx]
        for op_idx in range(ops_per_machine):
            state_idx = int(rng.integers(0, n_states))
            op = Operation(
                id=uuid4(),
                order_id=order_id,
                seq_in_order=m_idx * ops_per_machine + op_idx,
                state_id=states[state_idx].id,
                base_duration_min=10,
                eligible_wc_ids=[wc.id],
            )
            operations.append(op)

            # Create assignment sorted by time within each machine
            start_time = HORIZON_START + timedelta(minutes=op_idx * 15)
            end_time = start_time + timedelta(minutes=10)
            assignments.append(
                Assignment(
                    operation_id=op.id,
                    work_center_id=wc.id,
                    start_time=start_time,
                    end_time=end_time,
                    setup_minutes=0,
                )
            )

    problem = ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )

    ops_by_id = {op.id: op for op in operations}
    return problem, assignments, ops_by_id


def _compute_python_reference_scores(
    assignments: list[Assignment],
    sdst: SdstMatrix,
    ops_by_id: dict,
) -> dict:
    """Compute setup-cost scores using the Python reference algorithm.

    This mirrors the Python loop in _destroy_worst but computes only
    setup_minutes (not material_loss) to match the native implementation.
    """
    by_machine: dict = {}
    for a in assignments:
        by_machine.setdefault(a.work_center_id, []).append(a)

    op_cost: dict = {}
    for wc_id, machine_assignments in by_machine.items():
        machine_assignments.sort(key=lambda a: a.start_time)
        wi = sdst.wc_id_to_idx.get(wc_id)
        if wi is None:
            for a in machine_assignments:
                op_cost[a.operation_id] = 0.0
            continue

        for i, a in enumerate(machine_assignments):
            cost = 0.0
            op = ops_by_id[a.operation_id]
            fi_curr = sdst.state_id_to_idx.get(op.state_id, -1)

            if fi_curr < 0:
                op_cost[a.operation_id] = 0.0
                continue

            # Setup from predecessor to current
            if i > 0:
                prev_op = ops_by_id[machine_assignments[i - 1].operation_id]
                fi_prev = sdst.state_id_to_idx.get(prev_op.state_id, -1)
                if fi_prev >= 0:
                    cost += float(sdst.setup_minutes[wi, fi_prev, fi_curr])

            # Setup from current to successor
            if i < len(machine_assignments) - 1:
                next_op = ops_by_id[machine_assignments[i + 1].operation_id]
                fi_next = sdst.state_id_to_idx.get(next_op.state_id, -1)
                if fi_next >= 0:
                    cost += float(sdst.setup_minutes[wi, fi_curr, fi_next])

            # Subtract direct predecessor→successor cost
            if i > 0 and i < len(machine_assignments) - 1:
                prev_op = ops_by_id[machine_assignments[i - 1].operation_id]
                next_op = ops_by_id[machine_assignments[i + 1].operation_id]
                fi_prev = sdst.state_id_to_idx.get(prev_op.state_id, -1)
                fi_next = sdst.state_id_to_idx.get(next_op.state_id, -1)
                if fi_prev >= 0 and fi_next >= 0:
                    cost -= float(sdst.setup_minutes[wi, fi_prev, fi_next])

            op_cost[a.operation_id] = cost

    return op_cost


def _compute_native_scores(
    assignments: list[Assignment],
    sdst: SdstMatrix,
    ops_by_id: dict,
) -> np.ndarray | None:
    """Compute scores via the native accelerator seam."""
    from synaps.accelerators import compute_destroy_worst_scores_native

    n_assignments = len(assignments)

    # Build CSR machine grouping sorted by start_time
    by_machine: dict = {}
    for idx, a in enumerate(assignments):
        by_machine.setdefault(a.work_center_id, []).append((idx, a))

    n_machines = len(by_machine)
    machine_offsets = np.zeros(n_machines + 1, dtype=np.int64)
    assignment_indices_list: list[int] = []

    for m_idx, (_wc_id, machine_assigns) in enumerate(by_machine.items()):
        machine_assigns.sort(key=lambda x: x[1].start_time)
        machine_offsets[m_idx + 1] = machine_offsets[m_idx] + len(machine_assigns)
        for orig_idx, _a in machine_assigns:
            assignment_indices_list.append(orig_idx)

    assignment_indices = np.array(assignment_indices_list, dtype=np.int64)

    # Build per-assignment state and wc indices
    state_ids = np.zeros(n_assignments, dtype=np.int64)
    wc_indices = np.zeros(n_assignments, dtype=np.int64)

    for idx, a in enumerate(assignments):
        op = ops_by_id[a.operation_id]
        si = sdst.state_id_to_idx.get(op.state_id, -1)
        wi = sdst.wc_id_to_idx.get(a.work_center_id, -1)
        state_ids[idx] = si
        wc_indices[idx] = wi

    sdst_setup_flat = sdst.setup_minutes.astype(np.float64).ravel()

    return compute_destroy_worst_scores_native(
        machine_offsets=machine_offsets,
        assignment_indices=assignment_indices,
        state_ids=state_ids,
        sdst_setup_flat=sdst_setup_flat,
        wc_indices=wc_indices,
        n_wc=sdst.n_wc,
        n_states=sdst.n_states,
    )


# ---------------------------------------------------------------------------
# Task 4.5: Parity test — native and Python score vectors match within 1e-10
# ---------------------------------------------------------------------------


class TestNativeDestroyScoreParity:
    """**Validates: Requirements 4.1, 4.3**

    Property: native destroy worst scores match Python reference within 1e-10
    tolerance on deterministic numeric inputs.
    """

    def test_parity_small_problem(self) -> None:
        """Native scores match Python reference on a small deterministic problem."""
        problem, assignments, ops_by_id = _build_deterministic_problem(
            n_machines=5, n_states=4, ops_per_machine=10, seed=42
        )
        sdst = SdstMatrix.from_problem(problem)

        # Compute Python reference
        python_scores = _compute_python_reference_scores(assignments, sdst, ops_by_id)

        # Compute native scores
        native_result = _compute_native_scores(assignments, sdst, ops_by_id)
        if native_result is None:
            pytest.skip("Native module not available")

        # Compare element-wise
        for idx, a in enumerate(assignments):
            expected = python_scores[a.operation_id]
            actual = float(native_result[idx])
            assert abs(actual - expected) < 1e-10, (
                f"Mismatch at assignment {idx} (op {a.operation_id}): "
                f"native={actual}, python={expected}, diff={abs(actual - expected)}"
            )

    def test_parity_medium_problem(self) -> None:
        """Native scores match Python reference on a medium problem."""
        problem, assignments, ops_by_id = _build_deterministic_problem(
            n_machines=20, n_states=8, ops_per_machine=50, seed=123
        )
        sdst = SdstMatrix.from_problem(problem)

        python_scores = _compute_python_reference_scores(assignments, sdst, ops_by_id)
        native_result = _compute_native_scores(assignments, sdst, ops_by_id)
        if native_result is None:
            pytest.skip("Native module not available")

        for idx, a in enumerate(assignments):
            expected = python_scores[a.operation_id]
            actual = float(native_result[idx])
            assert abs(actual - expected) < 1e-10, (
                f"Mismatch at assignment {idx}: native={actual}, python={expected}"
            )

    def test_parity_single_op_per_machine(self) -> None:
        """Single operation per machine should have score 0.0."""
        problem, assignments, ops_by_id = _build_deterministic_problem(
            n_machines=10, n_states=5, ops_per_machine=1, seed=99
        )
        sdst = SdstMatrix.from_problem(problem)

        python_scores = _compute_python_reference_scores(assignments, sdst, ops_by_id)
        native_result = _compute_native_scores(assignments, sdst, ops_by_id)
        if native_result is None:
            pytest.skip("Native module not available")

        for idx, a in enumerate(assignments):
            expected = python_scores[a.operation_id]
            actual = float(native_result[idx])
            assert expected == 0.0, "Python score should be 0.0 for single-op machine"
            assert actual == 0.0, "Native score should be 0.0 for single-op machine"

    def test_parity_two_ops_per_machine(self) -> None:
        """Two operations per machine: first and last edge cases."""
        problem, assignments, ops_by_id = _build_deterministic_problem(
            n_machines=8, n_states=6, ops_per_machine=2, seed=77
        )
        sdst = SdstMatrix.from_problem(problem)

        python_scores = _compute_python_reference_scores(assignments, sdst, ops_by_id)
        native_result = _compute_native_scores(assignments, sdst, ops_by_id)
        if native_result is None:
            pytest.skip("Native module not available")

        for idx, a in enumerate(assignments):
            expected = python_scores[a.operation_id]
            actual = float(native_result[idx])
            assert abs(actual - expected) < 1e-10, (
                f"Mismatch at assignment {idx}: native={actual}, python={expected}"
            )

    def test_parity_varied_seeds(self) -> None:
        """Parity holds across multiple random seeds."""
        for seed in [1, 17, 42, 100, 999]:
            problem, assignments, ops_by_id = _build_deterministic_problem(
                n_machines=10, n_states=5, ops_per_machine=20, seed=seed
            )
            sdst = SdstMatrix.from_problem(problem)

            python_scores = _compute_python_reference_scores(assignments, sdst, ops_by_id)
            native_result = _compute_native_scores(assignments, sdst, ops_by_id)
            if native_result is None:
                pytest.skip("Native module not available")

            for idx, a in enumerate(assignments):
                expected = python_scores[a.operation_id]
                actual = float(native_result[idx])
                assert abs(actual - expected) < 1e-10, (
                    f"Seed {seed}, assignment {idx}: native={actual}, python={expected}"
                )

    def test_fallback_when_native_unavailable(self) -> None:
        """When native is disabled, compute_destroy_worst_scores_native returns None."""
        problem, assignments, ops_by_id = _build_deterministic_problem(
            n_machines=5, n_states=4, ops_per_machine=10, seed=42
        )
        sdst = SdstMatrix.from_problem(problem)

        with patch(
            "synaps.accelerators._native_compute_destroy_worst_scores",
            None,
        ):
            from synaps.accelerators import compute_destroy_worst_scores_native

            n_assignments = len(assignments)
            machine_offsets = np.array([0, 10, 20, 30, 40, 50], dtype=np.int64)
            assignment_indices = np.arange(n_assignments, dtype=np.int64)
            state_ids = np.zeros(n_assignments, dtype=np.int64)
            wc_indices = np.zeros(n_assignments, dtype=np.int64)
            sdst_flat = sdst.setup_minutes.astype(np.float64).ravel()

            result = compute_destroy_worst_scores_native(
                machine_offsets=machine_offsets,
                assignment_indices=assignment_indices,
                state_ids=state_ids,
                sdst_setup_flat=sdst_flat,
                wc_indices=wc_indices,
                n_wc=sdst.n_wc,
                n_states=sdst.n_states,
            )
            assert result is None


# ---------------------------------------------------------------------------
# Task 4.6: Benchmark test — < 10 ms for 50K operations across 100 machines
# ---------------------------------------------------------------------------


class TestNativeDestroyScoreBenchmark:
    """**Validates: Requirements 4.4**

    Performance: native scoring for 50K operations across 100 machines
    completes in less than 10 ms on a single core.
    """

    def test_50k_operations_under_10ms(self) -> None:
        """50K operations across 100 machines scores in < 10 ms."""
        from synaps.accelerators import compute_destroy_worst_scores_native

        n_machines = 100
        n_states = 20
        ops_per_machine = 500  # 100 * 500 = 50,000 operations
        n_assignments = n_machines * ops_per_machine

        rng = np.random.default_rng(42)

        # Build CSR machine offsets (uniform distribution)
        machine_offsets = np.zeros(n_machines + 1, dtype=np.int64)
        for m in range(n_machines):
            machine_offsets[m + 1] = machine_offsets[m] + ops_per_machine

        # Assignment indices: sequential within each machine
        assignment_indices = np.arange(n_assignments, dtype=np.int64)

        # Random state IDs and wc indices
        state_ids = rng.integers(0, n_states, size=n_assignments).astype(np.int64)
        wc_indices = np.repeat(np.arange(n_machines, dtype=np.int64), ops_per_machine)

        # Random SDST setup matrix
        n_wc = n_machines
        sdst_setup_flat = rng.uniform(0.0, 60.0, size=n_wc * n_states * n_states)

        # Warm-up call
        result = compute_destroy_worst_scores_native(
            machine_offsets=machine_offsets,
            assignment_indices=assignment_indices,
            state_ids=state_ids,
            sdst_setup_flat=sdst_setup_flat,
            wc_indices=wc_indices,
            n_wc=n_wc,
            n_states=n_states,
        )
        if result is None:
            pytest.skip("Native module not available")

        # Timed run (best of 5)
        times = []
        for _ in range(5):
            start = time.perf_counter()
            compute_destroy_worst_scores_native(
                machine_offsets=machine_offsets,
                assignment_indices=assignment_indices,
                state_ids=state_ids,
                sdst_setup_flat=sdst_setup_flat,
                wc_indices=wc_indices,
                n_wc=n_wc,
                n_states=n_states,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            times.append(elapsed_ms)

        best_ms = min(times)
        median_ms = sorted(times)[len(times) // 2]

        # Assert < 10 ms (generous threshold for CI variability)
        assert best_ms < 10.0, (
            f"Native destroy scoring too slow: best={best_ms:.2f} ms, "
            f"median={median_ms:.2f} ms (threshold: 10 ms)"
        )

    def test_result_shape_and_type(self) -> None:
        """Native result has correct shape and dtype."""
        from synaps.accelerators import compute_destroy_worst_scores_native

        n_machines = 10
        n_states = 5
        ops_per_machine = 100
        n_assignments = n_machines * ops_per_machine

        rng = np.random.default_rng(7)

        machine_offsets = np.zeros(n_machines + 1, dtype=np.int64)
        for m in range(n_machines):
            machine_offsets[m + 1] = machine_offsets[m] + ops_per_machine

        assignment_indices = np.arange(n_assignments, dtype=np.int64)
        state_ids = rng.integers(0, n_states, size=n_assignments).astype(np.int64)
        wc_indices = np.repeat(np.arange(n_machines, dtype=np.int64), ops_per_machine)
        sdst_setup_flat = rng.uniform(0.0, 30.0, size=n_machines * n_states * n_states)

        result = compute_destroy_worst_scores_native(
            machine_offsets=machine_offsets,
            assignment_indices=assignment_indices,
            state_ids=state_ids,
            sdst_setup_flat=sdst_setup_flat,
            wc_indices=wc_indices,
            n_wc=n_machines,
            n_states=n_states,
        )
        if result is None:
            pytest.skip("Native module not available")

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float64
        assert result.shape == (n_assignments,)
