from __future__ import annotations

import pytest

from synaps.accelerators import evaluate_objective_batch


def _make_sdst(n_wc: int, n_states: int) -> tuple[list[float], list[float]]:
    """Return flat SDST matrices filled with deterministic test values."""
    size = n_wc * n_states * n_states
    setup = [0.0] * size
    loss = [0.0] * size
    for m in range(n_wc):
        for s1 in range(n_states):
            for s2 in range(n_states):
                idx = m * n_states * n_states + s1 * n_states + s2
                setup[idx] = float((s1 + 1) * (s2 + 1) * (m + 1))
                loss[idx] = float(idx) * 0.1
    return setup, loss


def test_evaluate_objective_batch_python_fallback() -> None:
    """Smoke-test the pure-Python fallback path."""
    n_wc = 2
    n_states = 2
    end_offsets = [10.0, 20.0, 5.0, 25.0]
    wc_indices = [0, 0, 1, 1]
    state_ids = [0, 1, 0, 1]
    order_indices = [0, 0, 1, 1]
    sdst_setup, sdst_loss = _make_sdst(n_wc, n_states)
    order_due_offsets = [15.0, 30.0]

    cost, ms, su, lo, ta = evaluate_objective_batch(
        end_offsets=end_offsets,
        wc_indices=wc_indices,
        state_ids=state_ids,
        order_indices=order_indices,
        sdst_setup_flat=sdst_setup,
        sdst_loss_flat=sdst_loss,
        n_wc=n_wc,
        n_states=n_states,
        order_due_offsets=order_due_offsets,
        w_makespan=1.0,
        w_setup=1.0,
        w_loss=1.0,
        w_tardiness=1.0,
    )

    # Machine 0: indices [0,1], sorted by end -> [0(10), 1(20)]
    #   makespan=20, setup idx 0: s1=0,s2=1 -> setup=2, loss=0.1
    # Machine 1: indices [2,3], sorted by end -> [2(5), 3(25)]
    #   makespan=25, setup idx 1: s1=0,s2=1 -> setup=4, loss=0.5
    assert ms == 25.0
    assert su == pytest.approx(6.0)
    assert lo == pytest.approx(0.6)

    # Order 0 completion = max(10,20)=20; due=15 -> tard=5
    # Order 1 completion = max(5,25)=25; due=30 -> tard=0
    assert ta == pytest.approx(5.0)
    assert cost == pytest.approx(ms + su + lo + ta)


def test_evaluate_objective_batch_native_parity() -> None:
    """If the native module is available, results must match the Python fallback exactly."""
    from synaps.accelerators import _native_evaluate_objective_batch

    if _native_evaluate_objective_batch is None:
        pytest.skip("native evaluate_objective_batch not available")

    n_wc = 2
    n_states = 2
    end_offsets = [10.0, 20.0, 5.0, 25.0]
    wc_indices = [0, 0, 1, 1]
    state_ids = [0, 1, 0, 1]
    order_indices = [0, 0, 1, 1]
    sdst_setup, sdst_loss = _make_sdst(n_wc, n_states)
    order_due_offsets = [15.0, 30.0]

    py_result = evaluate_objective_batch(
        end_offsets=end_offsets,
        wc_indices=wc_indices,
        state_ids=state_ids,
        order_indices=order_indices,
        sdst_setup_flat=sdst_setup,
        sdst_loss_flat=sdst_loss,
        n_wc=n_wc,
        n_states=n_states,
        order_due_offsets=order_due_offsets,
        w_makespan=1.0,
        w_setup=1.0,
        w_loss=1.0,
        w_tardiness=1.0,
    )

    import numpy as np

    native_result = _native_evaluate_objective_batch(
        np.asarray(end_offsets, dtype=np.float64),
        np.asarray(wc_indices, dtype=np.int64),
        np.asarray(state_ids, dtype=np.int64),
        np.asarray(order_indices, dtype=np.int64),
        np.asarray(sdst_setup, dtype=np.float64),
        np.asarray(sdst_loss, dtype=np.float64),
        n_wc,
        n_states,
        np.asarray(order_due_offsets, dtype=np.float64),
        1.0,
        1.0,
        1.0,
        1.0,
    )

    assert py_result == pytest.approx(native_result, abs=1e-9)
