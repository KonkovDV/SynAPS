from __future__ import annotations

import copy

import pytest

from synaps.accelerators import stabilize_temporal_batch


def _make_sdst(n_wc: int, n_states: int) -> list[float]:
    """Return flat SDST setup matrix with deterministic test values."""
    size = n_wc * n_states * n_states
    setup = [0.0] * size
    for m in range(n_wc):
        for s1 in range(n_states):
            for s2 in range(n_states):
                idx = m * n_states * n_states + s1 * n_states + s2
                setup[idx] = float((s1 + 1) * (s2 + 1))
    return setup


def test_stabilize_temporal_batch_python_fallback() -> None:
    """Smoke-test the pure-Python fallback path."""
    n_wc = 1
    n_states = 2
    start_offsets = [0.0, 5.0, 3.0]
    end_offsets = [5.0, 8.0, 6.0]
    wc_indices = [0, 0, 0]
    state_ids = [0, 1, 0]
    predecessor_ids = [-1, 0, -1]
    sdst_setup = _make_sdst(n_wc, n_states)

    passes, precedence_shifts, machine_shifts = stabilize_temporal_batch(
        start_offsets=start_offsets,
        end_offsets=end_offsets,
        wc_indices=wc_indices,
        state_ids=state_ids,
        predecessor_ids=predecessor_ids,
        sdst_setup_flat=sdst_setup,
        n_wc=n_wc,
        n_states=n_states,
        max_passes=8,
    )

    # Op 1 has predecessor 0 ending at 5.0, but starts at 5.0 -> no shift
    # Op 2 starts at 3.0, prev on machine is op 0 ending 5.0 + setup(0->1)=1*2=2 -> min_start=7.0
    # Wait, machine sort by start: [0(0-5), 2(3-6), 1(5-8)]
    # After sorting: [0, 2, 1]
    # 0->2: prev=0 end=5, setup 0->0 = 1*1=1, min_start=6, curr start=3 -> shift by 3
    # 2->1: prev=2 end=6+3=9, setup 0->1 = 1*2=2, min_start=11, curr start=5 -> shift by 6
    assert passes >= 1
    assert start_offsets[0] == 0.0  # unchanged
    assert end_offsets[0] == 5.0  # unchanged
    assert start_offsets[2] >= 6.0
    assert start_offsets[1] >= 11.0


def test_stabilize_temporal_batch_native_parity() -> None:
    """If the native module is available, results must match the Python fallback exactly."""
    from synaps.accelerators import _native_stabilize_temporal_batch

    if _native_stabilize_temporal_batch is None:
        pytest.skip("native stabilize_temporal_batch not available")

    n_wc = 1
    n_states = 2
    start_offsets = [0.0, 5.0, 3.0]
    end_offsets = [5.0, 8.0, 6.0]
    wc_indices = [0, 0, 0]
    state_ids = [0, 1, 0]
    predecessor_ids = [-1, 0, -1]
    sdst_setup = _make_sdst(n_wc, n_states)

    py_start = copy.deepcopy(start_offsets)
    py_end = copy.deepcopy(end_offsets)
    py_result = stabilize_temporal_batch(
        start_offsets=py_start,
        end_offsets=py_end,
        wc_indices=wc_indices,
        state_ids=state_ids,
        predecessor_ids=predecessor_ids,
        sdst_setup_flat=sdst_setup,
        n_wc=n_wc,
        n_states=n_states,
        max_passes=8,
    )

    import numpy as np

    native_start = np.asarray(start_offsets, dtype=np.float64)
    native_end = np.asarray(end_offsets, dtype=np.float64)
    native_result = _native_stabilize_temporal_batch(
        native_start,
        native_end,
        np.asarray(wc_indices, dtype=np.int64),
        np.asarray(state_ids, dtype=np.int64),
        np.asarray(predecessor_ids, dtype=np.int64),
        np.asarray(sdst_setup, dtype=np.float64),
        n_wc,
        n_states,
        8,
    )

    assert list(native_start) == pytest.approx(py_start, abs=1e-9)
    assert list(native_end) == pytest.approx(py_end, abs=1e-9)
    assert native_result == pytest.approx(py_result, abs=1e-9)
