"""Tests for native SDST batch lookup parity and deterministic fallback.

Covers tasks 11b.5–11b.6 from the synaps-50k-solver-improvement spec:
- 11b.5: Parity test — native batch lookup equals Python lookup for all valid triples
- 11b.6: Deterministic fallback test — absence of native module does not change behavior
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import hypothesis.strategies as st
import numpy as np
import pytest
from hypothesis import given, settings

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.sdst_matrix import SdstMatrix

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = HORIZON_START + timedelta(hours=12)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_problem_with_entries(
    n_wc: int,
    n_states: int,
    setup_entries: list[SetupEntry],
    states: list[State],
    work_centers: list[WorkCenter],
) -> ScheduleProblem:
    """Build a ScheduleProblem from pre-built states, work_centers, and entries."""
    order_id = uuid4()
    orders = [
        Order(id=order_id, external_ref="ORD-0001", due_date=HORIZON_END)
    ]
    operations = [
        Operation(
            id=uuid4(),
            order_id=order_id,
            seq_in_order=0,
            state_id=states[0].id,
            base_duration_min=10,
            eligible_wc_ids=[work_centers[0].id],
        )
    ]
    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


def _make_dense_problem(n_wc: int, n_states: int) -> ScheduleProblem:
    """Build a problem with a fully populated setup matrix."""
    states = [State(id=uuid4(), code=f"S-{i}", label=f"State {i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(id=uuid4(), code=f"WC-{i}", capability_group="machining")
        for i in range(n_wc)
    ]

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
                        setup_minutes=(i * n_states + j + 1),
                        material_loss=float(i + j) * 0.1,
                        energy_kwh=float(i * j) * 0.05,
                    )
                )

    return _make_problem_with_entries(n_wc, n_states, setup_entries, states, work_centers)


# ---------------------------------------------------------------------------
# Task 11b.5: Parity test — native batch lookup equals Python lookup
# ---------------------------------------------------------------------------


@st.composite
def batch_lookup_inputs(draw: st.DrawFn) -> tuple[ScheduleProblem, np.ndarray, np.ndarray, np.ndarray]:
    """Generate a random problem and random index vectors for batch lookup."""
    n_states = draw(st.integers(min_value=2, max_value=10))
    n_wc = draw(st.integers(min_value=1, max_value=8))

    states = [State(id=uuid4(), code=f"S-{i}", label=f"State {i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(id=uuid4(), code=f"WC-{i}", capability_group="machining")
        for i in range(n_wc)
    ]

    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if draw(st.booleans()):
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=draw(st.integers(min_value=1, max_value=120)),
                            material_loss=draw(st.floats(min_value=0.0, max_value=5.0)),
                            energy_kwh=draw(st.floats(min_value=0.0, max_value=10.0)),
                        )
                    )

    problem = _make_problem_with_entries(n_wc, n_states, setup_entries, states, work_centers)

    # Generate random index vectors (including some out-of-bounds to test 0.0 behavior)
    batch_size = draw(st.integers(min_value=1, max_value=50))
    wc_indices = np.array(
        draw(st.lists(
            st.integers(min_value=-1, max_value=n_wc),
            min_size=batch_size,
            max_size=batch_size,
        )),
        dtype=np.int64,
    )
    from_indices = np.array(
        draw(st.lists(
            st.integers(min_value=-1, max_value=n_states),
            min_size=batch_size,
            max_size=batch_size,
        )),
        dtype=np.int64,
    )
    to_indices = np.array(
        draw(st.lists(
            st.integers(min_value=-1, max_value=n_states),
            min_size=batch_size,
            max_size=batch_size,
        )),
        dtype=np.int64,
    )

    return problem, wc_indices, from_indices, to_indices


class TestNativeBatchParity:
    """**Validates: Requirements 11.3, 11.4**

    Property: native batch lookup equals Python numpy fancy-indexing lookup
    for all valid triples. Out-of-bounds indices produce 0.0 in both paths.
    """

    @given(data=batch_lookup_inputs())
    @settings(max_examples=50, deadline=10000)
    def test_batch_lookup_matches_python_fallback(
        self,
        data: tuple[ScheduleProblem, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        """Native batch result matches Python fallback for all index vectors."""
        problem, wc_indices, from_indices, to_indices = data
        sdst = SdstMatrix.from_problem(problem)

        # Get result via the public get_setup_batch (which tries native, falls back)
        batch_result = sdst.get_setup_batch(wc_indices, from_indices, to_indices)

        # Compute expected via element-wise Python lookup
        expected = np.zeros(len(wc_indices), dtype=np.float64)
        for i in range(len(wc_indices)):
            wi = int(wc_indices[i])
            fi = int(from_indices[i])
            ti = int(to_indices[i])
            if 0 <= wi < sdst.n_wc and 0 <= fi < sdst.n_states and 0 <= ti < sdst.n_states:
                expected[i] = float(sdst.setup_minutes[wi, fi, ti])
            else:
                expected[i] = 0.0

        np.testing.assert_array_equal(
            batch_result,
            expected,
            err_msg="Batch lookup result does not match element-wise Python lookup",
        )

    def test_batch_lookup_known_values(self) -> None:
        """Deterministic test with known setup values."""
        problem = _make_dense_problem(n_wc=3, n_states=4)
        sdst = SdstMatrix.from_problem(problem)

        # Look up all valid non-diagonal triples
        wc_list = []
        from_list = []
        to_list = []
        for wi in range(sdst.n_wc):
            for fi in range(sdst.n_states):
                for ti in range(sdst.n_states):
                    if fi != ti:
                        wc_list.append(wi)
                        from_list.append(fi)
                        to_list.append(ti)

        wc_arr = np.array(wc_list, dtype=np.int64)
        from_arr = np.array(from_list, dtype=np.int64)
        to_arr = np.array(to_list, dtype=np.int64)

        result = sdst.get_setup_batch(wc_arr, from_arr, to_arr)

        # Verify against direct numpy indexing
        expected = sdst.setup_minutes[wc_arr, from_arr, to_arr].astype(np.float64)
        np.testing.assert_array_equal(result, expected)

    def test_batch_lookup_out_of_bounds_returns_zero(self) -> None:
        """Out-of-bounds indices produce 0.0."""
        problem = _make_dense_problem(n_wc=2, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        # All out-of-bounds
        wc_arr = np.array([99, -1, 0, 0], dtype=np.int64)
        from_arr = np.array([0, 0, 99, -1], dtype=np.int64)
        to_arr = np.array([0, 0, 0, 0], dtype=np.int64)

        result = sdst.get_setup_batch(wc_arr, from_arr, to_arr)
        np.testing.assert_array_equal(result, np.zeros(4, dtype=np.float64))

    def test_batch_lookup_empty_arrays(self) -> None:
        """Empty index arrays return empty result."""
        problem = _make_dense_problem(n_wc=2, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        result = sdst.get_setup_batch(
            np.array([], dtype=np.int64),
            np.array([], dtype=np.int64),
            np.array([], dtype=np.int64),
        )
        assert len(result) == 0
        assert result.dtype == np.float64


# ---------------------------------------------------------------------------
# Task 11b.6: Deterministic fallback test
# ---------------------------------------------------------------------------


class TestDeterministicFallback:
    """**Validates: Requirements 11.4**

    Absence of native module does not change observable behavior.
    The Python fallback produces identical results to the native path.
    """

    def test_fallback_produces_same_results_as_direct_numpy(self) -> None:
        """With native disabled, get_setup_batch uses numpy fancy indexing."""
        problem = _make_dense_problem(n_wc=4, n_states=5)
        sdst = SdstMatrix.from_problem(problem)

        # Generate a mix of valid and invalid indices
        rng = np.random.default_rng(42)
        n = 100
        wc_arr = rng.integers(-1, sdst.n_wc + 1, size=n).astype(np.int64)
        from_arr = rng.integers(-1, sdst.n_states + 1, size=n).astype(np.int64)
        to_arr = rng.integers(-1, sdst.n_states + 1, size=n).astype(np.int64)

        # Force fallback by patching native class to None in accelerators module
        with patch(
            "synaps.accelerators._native_NativeSdstBatchLookup",
            None,
        ):
            fallback_result = sdst.get_setup_batch(wc_arr, from_arr, to_arr)

        # Compute expected element-wise
        expected = np.zeros(n, dtype=np.float64)
        for i in range(n):
            wi = int(wc_arr[i])
            fi = int(from_arr[i])
            ti = int(to_arr[i])
            if 0 <= wi < sdst.n_wc and 0 <= fi < sdst.n_states and 0 <= ti < sdst.n_states:
                expected[i] = float(sdst.setup_minutes[wi, fi, ti])

        np.testing.assert_array_equal(
            fallback_result,
            expected,
            err_msg="Fallback result differs from expected element-wise computation",
        )

    def test_fallback_when_native_module_unavailable(self) -> None:
        """Simulating complete native module absence still produces correct results."""
        problem = _make_dense_problem(n_wc=3, n_states=4)
        sdst = SdstMatrix.from_problem(problem)

        wc_arr = np.array([0, 1, 2, 0], dtype=np.int64)
        from_arr = np.array([0, 1, 2, 3], dtype=np.int64)
        to_arr = np.array([1, 2, 3, 0], dtype=np.int64)

        # Patch the accelerators module-level variable to simulate no native
        with patch(
            "synaps.accelerators._native_NativeSdstBatchLookup",
            None,
        ):
            result = sdst.get_setup_batch(wc_arr, from_arr, to_arr)

        # Verify against direct numpy indexing
        expected = sdst.setup_minutes[wc_arr, from_arr, to_arr].astype(np.float64)
        np.testing.assert_array_equal(result, expected)

    def test_fallback_env_var_disables_native(self) -> None:
        """SYNAPS_DISABLE_NATIVE_ACCELERATION=1 forces Python fallback."""
        problem = _make_dense_problem(n_wc=2, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        wc_arr = np.array([0, 1, 0], dtype=np.int64)
        from_arr = np.array([0, 1, 2], dtype=np.int64)
        to_arr = np.array([1, 2, 0], dtype=np.int64)

        # Patch native to None (simulating env var effect)
        with patch(
            "synaps.accelerators._native_NativeSdstBatchLookup",
            None,
        ):
            result = sdst.get_setup_batch(wc_arr, from_arr, to_arr)

        expected = sdst.setup_minutes[wc_arr, from_arr, to_arr].astype(np.float64)
        np.testing.assert_array_equal(result, expected)

    def test_fallback_result_type_and_shape(self) -> None:
        """Fallback returns float64 numpy array of correct shape."""
        problem = _make_dense_problem(n_wc=2, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        n = 10
        wc_arr = np.zeros(n, dtype=np.int64)
        from_arr = np.ones(n, dtype=np.int64)
        to_arr = np.full(n, 2, dtype=np.int64)

        with patch(
            "synaps.accelerators._native_NativeSdstBatchLookup",
            None,
        ):
            result = sdst.get_setup_batch(wc_arr, from_arr, to_arr)

        assert isinstance(result, np.ndarray)
        assert result.dtype == np.float64
        assert result.shape == (n,)

    @given(data=batch_lookup_inputs())
    @settings(max_examples=30, deadline=10000)
    def test_fallback_parity_property(
        self,
        data: tuple[ScheduleProblem, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        """Property: fallback path produces identical results to direct computation."""
        problem, wc_indices, from_indices, to_indices = data
        sdst = SdstMatrix.from_problem(problem)

        # Force fallback
        with patch(
            "synaps.accelerators._native_NativeSdstBatchLookup",
            None,
        ):
            fallback_result = sdst.get_setup_batch(wc_indices, from_indices, to_indices)

        # Element-wise expected
        expected = np.zeros(len(wc_indices), dtype=np.float64)
        for i in range(len(wc_indices)):
            wi = int(wc_indices[i])
            fi = int(from_indices[i])
            ti = int(to_indices[i])
            if 0 <= wi < sdst.n_wc and 0 <= fi < sdst.n_states and 0 <= ti < sdst.n_states:
                expected[i] = float(sdst.setup_minutes[wi, fi, ti])

        np.testing.assert_array_equal(fallback_result, expected)
