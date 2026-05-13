"""Optional hot-path acceleration seams for SynAPS."""

from __future__ import annotations

import importlib
import os
from collections import deque
from math import exp, log
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

try:
    import numpy as np

    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False

_synaps_native: Any | None = None
_native_compute_atcs_log_score: Callable[..., float] | None = None
_native_compute_atcs_log_scores_batch: Callable[..., list[float]] | None = None
_native_resource_capacity_window_is_feasible: Callable[..., bool] | None = None
_native_compute_rhc_candidate_metrics_batch: (
    Callable[..., tuple[list[float], list[float]]] | None
) = None
_native_compute_rhc_candidate_metrics_batch_np: Callable[..., Any] | None = None
_native_compute_rhc_candidate_metrics_batch_np_jagged: Callable[..., Any] | None = None
_native_evaluate_objective_batch: (
    Callable[..., tuple[float, float, float, float, float]] | None
) = None
_native_stabilize_temporal_batch: Callable[..., tuple[int, int, int]] | None = None
_native_NativeSdstBatchLookup: type | None = None
_native_compute_destroy_worst_scores: Callable[..., Any] | None = None
_native_greedy_repair_batch: Callable[..., Any] | None = None

if os.getenv("SYNAPS_DISABLE_NATIVE_ACCELERATION") == "1":
    _native_compute_atcs_log_score = None
    _native_compute_atcs_log_scores_batch = None
    _native_resource_capacity_window_is_feasible = None
    _native_compute_rhc_candidate_metrics_batch = None
    _native_compute_rhc_candidate_metrics_batch_np = None
    _native_compute_rhc_candidate_metrics_batch_np_jagged = None
    _native_evaluate_objective_batch = None
    _native_stabilize_temporal_batch = None
    _native_NativeSdstBatchLookup = None
    _native_compute_destroy_worst_scores = None
    _native_greedy_repair_batch = None
else:
    try:
        _synaps_native = importlib.import_module("synaps_native")
    except Exception:
        _synaps_native = None
        _native_compute_atcs_log_score = None
        _native_compute_atcs_log_scores_batch = None
        _native_resource_capacity_window_is_feasible = None
        _native_compute_rhc_candidate_metrics_batch = None
        _native_compute_rhc_candidate_metrics_batch_np = None
        _native_compute_rhc_candidate_metrics_batch_np_jagged = None
        _native_evaluate_objective_batch = None
        _native_stabilize_temporal_batch = None
        _native_NativeSdstBatchLookup = None
        _native_compute_destroy_worst_scores = None
        _native_greedy_repair_batch = None
    else:
        _native_compute_atcs_log_score = getattr(
            _synaps_native,
            "compute_atcs_log_score",
            None,
        )
        _native_compute_atcs_log_scores_batch = getattr(
            _synaps_native,
            "compute_atcs_log_scores_batch",
            None,
        )
        _native_resource_capacity_window_is_feasible = getattr(
            _synaps_native,
            "resource_capacity_window_is_feasible",
            None,
        )
        _native_compute_rhc_candidate_metrics_batch = getattr(
            _synaps_native,
            "compute_rhc_candidate_metrics_batch",
            None,
        )
        _native_compute_rhc_candidate_metrics_batch_np = getattr(
            _synaps_native,
            "compute_rhc_candidate_metrics_batch_np",
            None,
        )
        _native_compute_rhc_candidate_metrics_batch_np_jagged = getattr(
            _synaps_native,
            "compute_rhc_candidate_metrics_batch_np_jagged",
            None,
        )
        _native_evaluate_objective_batch = getattr(
            _synaps_native,
            "evaluate_objective_batch",
            None,
        )
        _native_stabilize_temporal_batch = getattr(
            _synaps_native,
            "stabilize_temporal_batch",
            None,
        )
        _native_NativeSdstBatchLookup = getattr(
            _synaps_native,
            "NativeSdstBatchLookup",
            None,
        )
        _native_compute_destroy_worst_scores = getattr(
            _synaps_native,
            "compute_destroy_worst_scores",
            None,
        )
        _native_greedy_repair_batch = getattr(
            _synaps_native,
            "greedy_repair_batch",
            None,
        )


def compute_atcs_log_score(
    *,
    weight: float,
    processing_minutes: float,
    slack: float,
    ready_p_bar: float,
    setup_minutes: float,
    setup_scale: float,
    k1: float,
    k2: float,
    material_loss: float,
    material_scale: float,
    k3: float,
) -> float:
    """Return the log-space ATCS score using native acceleration when available."""

    if _native_compute_atcs_log_score is not None:
        return float(
            _native_compute_atcs_log_score(
                weight,
                processing_minutes,
                slack,
                ready_p_bar,
                setup_minutes,
                setup_scale,
                k1,
                k2,
                material_loss,
                material_scale,
                k3,
            )
        )

    return (
        log(max(weight, 1e-9))
        - log(max(processing_minutes, 0.1))
        - (slack / (k1 * ready_p_bar))
        - (setup_minutes / (k2 * setup_scale) if setup_minutes > 0 else 0.0)
        - (material_loss / (k3 * material_scale) if material_loss > 0 else 0.0)
    )


def get_acceleration_status() -> dict[str, Any]:
    """Describe which acceleration backend is currently active."""

    return {
        "native_available": any(
            backend is not None
            for backend in (
                _native_compute_atcs_log_score,
                _native_compute_atcs_log_scores_batch,
                _native_resource_capacity_window_is_feasible,
                _native_compute_rhc_candidate_metrics_batch,
            )
        ),
        "atcs_log_score_backend": "native"
        if _native_compute_atcs_log_score is not None
        else "python",
        "atcs_log_score_batch_backend": "native"
        if _native_compute_atcs_log_scores_batch is not None
        else "python",
        "resource_capacity_backend": "native"
        if _native_resource_capacity_window_is_feasible is not None
        else "python",
        "rhc_candidate_metrics_backend": "native"
        if _native_compute_rhc_candidate_metrics_batch is not None
        else "python",
        "rhc_candidate_metrics_np_backend": "native"
        if _native_compute_rhc_candidate_metrics_batch_np is not None
        else "python",
        "rhc_candidate_metrics_np_jagged_backend": "native"
        if _native_compute_rhc_candidate_metrics_batch_np_jagged is not None
        else "python",
        "objective_batch_backend": "native"
        if _native_evaluate_objective_batch is not None
        else "python",
        "stabilize_temporal_batch_backend": "native"
        if _native_stabilize_temporal_batch is not None
        else "python",
        "sdst_batch_lookup_backend": "native"
        if _native_NativeSdstBatchLookup is not None
        else "python",
        "destroy_worst_scores_backend": "native"
        if _native_compute_destroy_worst_scores is not None
        else "python",
        "greedy_repair_batch_backend": "native"
        if _native_greedy_repair_batch is not None
        else "python",
        "native_module": "synaps_native"
        if any(
            backend is not None
            for backend in (
                _native_compute_atcs_log_score,
                _native_compute_atcs_log_scores_batch,
                _native_resource_capacity_window_is_feasible,
                _native_compute_rhc_candidate_metrics_batch,
                _native_evaluate_objective_batch,
                _native_stabilize_temporal_batch,
                _native_NativeSdstBatchLookup,
            )
        )
        else None,
    }


def compute_atcs_log_scores_batch(
    *,
    weights: list[float],
    processing_minutes: list[float],
    slack: list[float],
    ready_p_bar: float,
    setup_minutes: list[float],
    setup_scale: list[float],
    k1: float,
    k2: float,
    material_loss: list[float],
    material_scale: float,
    k3: float,
) -> list[float]:
    """Return log-space ATCS scores for a candidate batch.

    This is a Structure-of-Arrays seam intended for optional native backends
    (PyO3/Rust) while keeping a deterministic Python fallback.
    """

    n = len(weights)
    if not (
        len(processing_minutes) == n
        and len(slack) == n
        and len(setup_minutes) == n
        and len(setup_scale) == n
        and len(material_loss) == n
    ):
        raise ValueError("ATCS batch vectors must have identical lengths")

    if _native_compute_atcs_log_scores_batch is not None:
        return [
            float(value)
            for value in _native_compute_atcs_log_scores_batch(
                weights,
                processing_minutes,
                slack,
                ready_p_bar,
                setup_minutes,
                setup_scale,
                k1,
                k2,
                material_loss,
                material_scale,
                k3,
            )
        ]

    # Prefer numpy vectorized path when available (10–20x faster on large batches).
    if _HAS_NUMPY:
        w_np = np.maximum(np.asarray(weights, dtype=np.float64), 1e-9)
        p_np = np.maximum(np.asarray(processing_minutes, dtype=np.float64), 0.1)
        s_np = np.asarray(slack, dtype=np.float64)
        su_np = np.asarray(setup_minutes, dtype=np.float64)
        sc_np = np.asarray(setup_scale, dtype=np.float64)
        ml_np = np.asarray(material_loss, dtype=np.float64)

        scores = (
            np.log(w_np)
            - np.log(p_np)
            - s_np / (k1 * ready_p_bar)
            - np.where(su_np > 0.0, su_np / (k2 * sc_np), 0.0)
            - np.where(ml_np > 0.0, ml_np / (k3 * material_scale), 0.0)
        )
        return [float(v) for v in scores]

    return [
        (
            log(max(weights[i], 1e-9))
            - log(max(processing_minutes[i], 0.1))
            - (slack[i] / (k1 * ready_p_bar))
            - (
                setup_minutes[i] / (k2 * setup_scale[i])
                if setup_minutes[i] > 0
                else 0.0
            )
            - (
                material_loss[i] / (k3 * material_scale)
                if material_loss[i] > 0
                else 0.0
            )
        )
        for i in range(n)
    ]


def resource_capacity_window_is_feasible(
    *,
    window_starts: list[float],
    window_ends: list[float],
    window_quantities: list[int],
    candidate_start: float,
    candidate_end: float,
    requested_quantity: int,
    pool_size: int,
) -> bool:
    """Return whether a candidate window fits inside a pooled resource capacity."""

    if _native_resource_capacity_window_is_feasible is not None:
        return bool(
            _native_resource_capacity_window_is_feasible(
                window_starts,
                window_ends,
                window_quantities,
                candidate_start,
                candidate_end,
                requested_quantity,
                pool_size,
            )
        )

    active_demand = 0
    events: list[tuple[float, int]] = []
    for other_start, other_end, quantity in zip(
        window_starts,
        window_ends,
        window_quantities,
        strict=False,
    ):
        if other_start >= candidate_end or other_end <= candidate_start:
            continue

        if other_start <= candidate_start < other_end:
            active_demand += quantity
        else:
            events.append((other_start, quantity))

        if candidate_start < other_end < candidate_end:
            events.append((other_end, -quantity))

    if active_demand + requested_quantity > pool_size:
        return False

    for _, delta in sorted(events, key=lambda item: (item[0], 0 if item[1] < 0 else 1)):
        active_demand += delta
        if active_demand + requested_quantity > pool_size:
            return False

    return True


def compute_rhc_candidate_metrics_batch(
    *,
    machine_available_offsets: list[float],
    eligible_machine_indices: list[list[int]],
    predecessor_end_offsets: list[float],
    due_offsets: list[float],
    rpt_tail_minutes: list[float],
    order_weights: list[float],
    p_tilde_minutes: list[float],
    avg_total_p: float,
    due_pressure_k1: float,
    due_pressure_overdue_boost: float,
) -> tuple[list[float], list[float]]:
    """Return (slack, pressure) vectors for RHC window candidates.

    Intended as an optional native seam for the hot candidate scoring loop in
    ``RhcSolver`` while keeping a deterministic Python fallback.

    Note: the native backend is allowed to use a monotone fast-exp
    approximation for the pressure term. Callers should treat pressure as a
    ranking heuristic, not as a bit-for-bit scientific reference value.
    """

    n = len(eligible_machine_indices)
    if not (
        len(predecessor_end_offsets) == n
        and len(due_offsets) == n
        and len(rpt_tail_minutes) == n
        and len(order_weights) == n
        and len(p_tilde_minutes) == n
    ):
        raise ValueError("RHC candidate metric vectors must have identical lengths")

    machine_count = len(machine_available_offsets)
    for machine_indices in eligible_machine_indices:
        for machine_idx in machine_indices:
            if machine_idx < 0 or machine_idx >= machine_count:
                raise ValueError("eligible machine index is out of range")

    if _native_compute_rhc_candidate_metrics_batch is not None:
        native_slacks, native_pressures = _native_compute_rhc_candidate_metrics_batch(
            machine_available_offsets,
            eligible_machine_indices,
            predecessor_end_offsets,
            due_offsets,
            rpt_tail_minutes,
            order_weights,
            p_tilde_minutes,
            avg_total_p,
            due_pressure_k1,
            due_pressure_overdue_boost,
        )
        return (
            [float(value) for value in native_slacks],
            [float(value) for value in native_pressures],
        )

    safe_pressure_denominator = max(due_pressure_k1 * avg_total_p, 1e-6)
    slacks: list[float] = []
    pressures: list[float] = []
    for i, machine_indices in enumerate(eligible_machine_indices):
        if machine_indices:
            earliest_machine_ready = min(
                machine_available_offsets[machine_idx]
                for machine_idx in machine_indices
            )
        else:
            earliest_machine_ready = 0.0

        est_offset = max(predecessor_end_offsets[i], earliest_machine_ready)
        slack = due_offsets[i] - (est_offset + rpt_tail_minutes[i])
        pressure = (order_weights[i] / max(p_tilde_minutes[i], 1e-6)) * exp(
            -max(0.0, slack) / safe_pressure_denominator
        )
        if slack <= 0.0:
            pressure *= due_pressure_overdue_boost
        slacks.append(slack)
        pressures.append(pressure)

    return slacks, pressures


def _build_csr_from_jagged(
    jagged: list[list[int]],
) -> tuple[Any, Any]:
    """Convert a jagged list-of-lists into CSR (offsets, indices) numpy arrays.

    Returns plain Python lists when numpy is unavailable (fallback path only).
    """
    offsets: list[int] = [0]
    flat: list[int] = []
    for row in jagged:
        flat.extend(row)
        offsets.append(len(flat))
    if _HAS_NUMPY:
        return np.array(offsets, dtype=np.int64), np.array(flat, dtype=np.int64)
    return offsets, flat  # pragma: no cover


def compute_rhc_candidate_metrics_batch_np(
    *,
    machine_available_offsets: list[float],
    eligible_machine_indices: list[list[int]],
    predecessor_end_offsets: list[float],
    due_offsets: list[float],
    rpt_tail_minutes: list[float],
    order_weights: list[float],
    p_tilde_minutes: list[float],
    avg_total_p: float,
    due_pressure_k1: float,
    due_pressure_overdue_boost: float,
) -> tuple[list[float], list[float]]:
    """Zero-copy numpy + CSR path for RHC candidate metrics at 50k+ scale.

    Prefers the _np_jagged variant (CSR built in Rust, avoids Python loop),
    then falls back to the _np variant (pre-built CSR from Python), then
    to the legacy Vec path, then to pure-Python.

    Native backends may use the same monotone fast-exp approximation as the
    list-based API, so pressure should be treated as a ranking signal rather
    than a bit-for-bit scientific reference value.
    """
    # P3: CSR-in-Rust path — fastest, no Python loop.
    if _native_compute_rhc_candidate_metrics_batch_np_jagged is not None and _HAS_NUMPY:
        np_slacks, np_pressures = _native_compute_rhc_candidate_metrics_batch_np_jagged(
            np.asarray(machine_available_offsets, dtype=np.float64),
            eligible_machine_indices,
            np.asarray(predecessor_end_offsets, dtype=np.float64),
            np.asarray(due_offsets, dtype=np.float64),
            np.asarray(rpt_tail_minutes, dtype=np.float64),
            np.asarray(order_weights, dtype=np.float64),
            np.asarray(p_tilde_minutes, dtype=np.float64),
            avg_total_p,
            due_pressure_k1,
            due_pressure_overdue_boost,
        )
        return np_slacks.tolist(), np_pressures.tolist()

    # Fallback: pre-built CSR from Python.
    if _native_compute_rhc_candidate_metrics_batch_np is not None and _HAS_NUMPY:
        emi_offsets, emi_indices = _build_csr_from_jagged(eligible_machine_indices)
        np_slacks, np_pressures = _native_compute_rhc_candidate_metrics_batch_np(
            np.asarray(machine_available_offsets, dtype=np.float64),
            emi_offsets,
            emi_indices,
            np.asarray(predecessor_end_offsets, dtype=np.float64),
            np.asarray(due_offsets, dtype=np.float64),
            np.asarray(rpt_tail_minutes, dtype=np.float64),
            np.asarray(order_weights, dtype=np.float64),
            np.asarray(p_tilde_minutes, dtype=np.float64),
            avg_total_p,
            due_pressure_k1,
            due_pressure_overdue_boost,
        )
        return np_slacks.tolist(), np_pressures.tolist()

    # Transparent fallback to the legacy path.
    return compute_rhc_candidate_metrics_batch(
        machine_available_offsets=machine_available_offsets,
        eligible_machine_indices=eligible_machine_indices,
        predecessor_end_offsets=predecessor_end_offsets,
        due_offsets=due_offsets,
        rpt_tail_minutes=rpt_tail_minutes,
        order_weights=order_weights,
        p_tilde_minutes=p_tilde_minutes,
        avg_total_p=avg_total_p,
        due_pressure_k1=due_pressure_k1,
        due_pressure_overdue_boost=due_pressure_overdue_boost,
    )


def evaluate_objective_batch(
    *,
    end_offsets: list[float],
    wc_indices: list[int],
    state_ids: list[int],
    order_indices: list[int],
    sdst_setup_flat: list[float],
    sdst_loss_flat: list[float],
    n_wc: int,
    n_states: int,
    order_due_offsets: list[float],
    w_makespan: float,
    w_setup: float,
    w_loss: float,
    w_tardiness: float,
) -> tuple[float, float, float, float, float]:
    """Evaluate aggregated objective from flat assignment arrays.

    Native seam with a deterministic Python fallback that mirrors the
    Rust ``machine_objective_kernel`` logic exactly.
    """
    if _native_evaluate_objective_batch is not None and _HAS_NUMPY:
        return _native_evaluate_objective_batch(
            np.asarray(end_offsets, dtype=np.float64),
            np.asarray(wc_indices, dtype=np.int64),
            np.asarray(state_ids, dtype=np.int64),
            np.asarray(order_indices, dtype=np.int64),
            np.asarray(sdst_setup_flat, dtype=np.float64),
            np.asarray(sdst_loss_flat, dtype=np.float64),
            n_wc,
            n_states,
            np.asarray(order_due_offsets, dtype=np.float64),
            w_makespan,
            w_setup,
            w_loss,
            w_tardiness,
        )

    n = len(end_offsets)
    by_machine: list[list[int]] = [[] for _ in range(n_wc)]
    for i in range(n):
        m = wc_indices[i]
        if 0 <= m < n_wc:
            by_machine[m].append(i)

    total_makespan = 0.0
    total_setup = 0.0
    total_loss = 0.0

    for m, indices in enumerate(by_machine):
        if not indices:
            continue
        indices_sorted = sorted(indices, key=lambda i: end_offsets[i])
        makespan = end_offsets[indices_sorted[-1]]
        total_makespan = max(total_makespan, makespan)
        wc_offset = m * n_states * n_states
        for a, b in zip(indices_sorted, indices_sorted[1:], strict=False):
            ps = state_ids[a]
            cs = state_ids[b]
            if ps >= 0 and cs >= 0:
                ps_u = int(ps)
                cs_u = int(cs)
                if ps_u < n_states and cs_u < n_states:
                    idx = wc_offset + ps_u * n_states + cs_u
                    total_setup += sdst_setup_flat[idx]
                    total_loss += sdst_loss_flat[idx]

    n_orders = len(order_due_offsets)
    order_completion = [0.0] * n_orders
    for i in range(n):
        oi = order_indices[i]
        if 0 <= oi < n_orders and end_offsets[i] > order_completion[oi]:
            order_completion[oi] = end_offsets[i]

    total_tardiness = 0.0
    for j in range(n_orders):
        tard = order_completion[j] - order_due_offsets[j]
        if tard > 0.0:
            total_tardiness += tard

    cost = (
        w_makespan * total_makespan
        + w_setup * total_setup
        + w_loss * total_loss
        + w_tardiness * total_tardiness
    )
    return (cost, total_makespan, total_setup, total_loss, total_tardiness)


def stabilize_temporal_batch(
    *,
    start_offsets: list[float],
    end_offsets: list[float],
    wc_indices: list[int],
    state_ids: list[int],
    predecessor_ids: list[int],
    sdst_setup_flat: list[float],
    n_wc: int,
    n_states: int,
    max_passes: int = 8,
) -> tuple[int, int, int]:
    """Repair temporal consistency in-place on flat offset arrays.

    Native seam with a deterministic Python fallback that mirrors the
    Rust ``stabilize_temporal_batch`` logic exactly.
    """
    if _native_stabilize_temporal_batch is not None and _HAS_NUMPY:
        start_arr = np.asarray(start_offsets, dtype=np.float64)
        end_arr = np.asarray(end_offsets, dtype=np.float64)
        result = _native_stabilize_temporal_batch(
            start_arr,
            end_arr,
            np.asarray(wc_indices, dtype=np.int64),
            np.asarray(state_ids, dtype=np.int64),
            np.asarray(predecessor_ids, dtype=np.int64),
            np.asarray(sdst_setup_flat, dtype=np.float64),
            n_wc,
            n_states,
            max_passes,
        )
        # Copy mutated values back into Python lists so the caller sees
        # the same side-effect as the native path.
        start_offsets[:] = start_arr.tolist()
        end_offsets[:] = end_arr.tolist()
        return result

    n = len(start_offsets)
    indegree = [0] * n
    successors: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        p = predecessor_ids[i]
        if p >= 0:
            p_u = int(p)
            if p_u < n:
                indegree[i] += 1
                successors[p_u].append(i)

    queue = deque([i for i in range(n) if indegree[i] == 0])
    topo_order: list[int] = []
    while queue:
        node = queue.popleft()
        topo_order.append(node)
        for succ in successors[node]:
            indegree[succ] -= 1
            if indegree[succ] == 0:
                queue.append(succ)

    visited = [False] * n
    for node in topo_order:
        visited[node] = True
    for i in range(n):
        if not visited[i]:
            topo_order.append(i)

    precedence_shifts = 0
    machine_shifts = 0
    passes = 0

    for pass_idx in range(max_passes):
        changed = False
        passes = pass_idx + 1

        for i in topo_order:
            p = predecessor_ids[i]
            if p < 0:
                continue
            p_u = int(p)
            if p_u >= n:
                continue
            if start_offsets[i] < end_offsets[p_u]:
                delta = end_offsets[p_u] - start_offsets[i]
                start_offsets[i] += delta
                end_offsets[i] += delta
                precedence_shifts += 1
                changed = True

        by_machine: list[list[int]] = [[] for _ in range(n_wc)]
        for i in range(n):
            m = wc_indices[i]
            if 0 <= m < n_wc:
                by_machine[m].append(i)

        for machine_indices in by_machine:
            machine_indices.sort(key=lambda i: start_offsets[i])
            for prev, curr in zip(machine_indices, machine_indices[1:], strict=False):
                required_setup = 0.0
                ps = state_ids[prev]
                cs = state_ids[curr]
                m = wc_indices[curr]
                if ps >= 0 and cs >= 0 and 0 <= m < n_wc:
                    ps_u = int(ps)
                    cs_u = int(cs)
                    if ps_u < n_states and cs_u < n_states:
                        required_setup = sdst_setup_flat[
                            m * n_states * n_states + ps_u * n_states + cs_u
                        ]

                min_start = end_offsets[prev] + required_setup
                if start_offsets[curr] < min_start:
                    delta = min_start - start_offsets[curr]
                    start_offsets[curr] += delta
                    end_offsets[curr] += delta
                    machine_shifts += 1
                    changed = True

        if not changed:
            break

    return (passes, precedence_shifts, machine_shifts)


def native_sdst_batch_lookup(
    setup_values_flat: np.ndarray,
    n_wc: int,
    n_states: int,
    wc_indices: np.ndarray,
    from_state_indices: np.ndarray,
    to_state_indices: np.ndarray,
) -> np.ndarray | None:
    """Try native batch SDST lookup. Returns None if native unavailable.

    This is the acceleration seam for SdstMatrix.get_setup_batch(). When the
    native module is available, it constructs a NativeSdstBatchLookup instance
    and performs the batch lookup in a single FFI call. When unavailable,
    returns None so the caller can fall back to numpy fancy indexing.

    Args:
        setup_values_flat: flattened [n_wc, n_states, n_states] float64 array
        n_wc: number of work centers
        n_states: number of states
        wc_indices: int64 array of work center indices
        from_state_indices: int64 array of from-state indices
        to_state_indices: int64 array of to-state indices

    Returns:
        numpy float64 array of setup values, or None if native is unavailable.
    """
    if _native_NativeSdstBatchLookup is None or not _HAS_NUMPY:
        return None

    try:
        lookup = _native_NativeSdstBatchLookup(
            setup_values_flat.ravel().tolist(),
            n_wc,
            n_states,
        )
        result = lookup.get_setup_batch(
            np.ascontiguousarray(wc_indices, dtype=np.int64),
            np.ascontiguousarray(from_state_indices, dtype=np.int64),
            np.ascontiguousarray(to_state_indices, dtype=np.int64),
        )
        return np.asarray(result, dtype=np.float64)
    except Exception:
        return None


def compute_destroy_worst_scores_native(
    machine_offsets: np.ndarray,
    assignment_indices: np.ndarray,
    state_ids: np.ndarray,
    sdst_setup_flat: np.ndarray,
    wc_indices: np.ndarray,
    n_wc: int,
    n_states: int,
) -> np.ndarray | None:
    """Try native destroy worst scoring. Returns None if native unavailable.

    This is the acceleration seam for _destroy_worst setup-cost scoring.
    When the native module is available, it computes per-operation setup-cost
    contributions in a single FFI call using rayon parallelism. When unavailable,
    returns None so the caller can fall back to the Python reference loop.

    Args:
        machine_offsets: int64 CSR row pointers [n_machines + 1]
        assignment_indices: int64 flat sorted assignment indices per machine
        state_ids: int64 per-assignment state indices [n_assignments]
        sdst_setup_flat: float64 flattened [n_wc, n_states, n_states] setup values
        wc_indices: int64 per-assignment work center indices [n_assignments]
        n_wc: number of work centers
        n_states: number of states

    Returns:
        numpy float64 array of per-assignment scores, or None if native is unavailable.
    """
    if _native_compute_destroy_worst_scores is None or not _HAS_NUMPY:
        return None

    try:
        result = _native_compute_destroy_worst_scores(
            np.ascontiguousarray(machine_offsets, dtype=np.int64),
            np.ascontiguousarray(assignment_indices, dtype=np.int64),
            np.ascontiguousarray(state_ids, dtype=np.int64),
            np.ascontiguousarray(sdst_setup_flat, dtype=np.float64),
            np.ascontiguousarray(wc_indices, dtype=np.int64),
            n_wc,
            n_states,
        )
        return np.asarray(result, dtype=np.float64)
    except Exception:
        return None


def greedy_repair_batch_native(
    base_durations: np.ndarray,
    predecessor_indices: np.ndarray,
    eligible_offsets: np.ndarray,
    eligible_indices: np.ndarray,
    state_ids: np.ndarray,
    sdst_setup_flat: np.ndarray,
    n_wc: int,
    n_states: int,
    speed_factors: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Try native greedy repair. Returns None if native unavailable.

    Dispatches operations in topological order to earliest-available machines,
    respecting predecessor constraints, SDST setup times, and machine speed
    factors. This is a simplified greedy (no aux resources, no gap insertion)
    intended for ALNS inner repair where speed matters more than optimality.

    Args:
        base_durations: [N] float64 operation durations in minutes
        predecessor_indices: [N] int64, -1 = no predecessor
        eligible_offsets: [N+1] int64 CSR row pointers for eligible machines
        eligible_indices: flat int64 eligible machine indices
        state_ids: [N] int64 state index per operation
        sdst_setup_flat: [n_wc * n_states * n_states] float64 setup matrix
        n_wc: number of work centers (machines)
        n_states: number of states
        speed_factors: [n_wc] float64 machine speed factors

    Returns:
        (start_offsets, end_offsets, assigned_machine_indices) as numpy arrays,
        or None if native is unavailable.
    """
    if _native_greedy_repair_batch is None or not _HAS_NUMPY:
        return None

    try:
        starts, ends, machines = _native_greedy_repair_batch(
            np.ascontiguousarray(base_durations, dtype=np.float64),
            np.ascontiguousarray(predecessor_indices, dtype=np.int64),
            np.ascontiguousarray(eligible_offsets, dtype=np.int64),
            np.ascontiguousarray(eligible_indices, dtype=np.int64),
            np.ascontiguousarray(state_ids, dtype=np.int64),
            np.ascontiguousarray(sdst_setup_flat, dtype=np.float64),
            n_wc,
            n_states,
            np.ascontiguousarray(speed_factors, dtype=np.float64),
        )
        return (
            np.asarray(starts, dtype=np.float64),
            np.asarray(ends, dtype=np.float64),
            np.asarray(machines, dtype=np.int64),
        )
    except Exception:
        return None


__all__ = [
    "compute_atcs_log_score",
    "compute_atcs_log_scores_batch",
    "compute_destroy_worst_scores_native",
    "compute_rhc_candidate_metrics_batch",
    "compute_rhc_candidate_metrics_batch_np",
    "evaluate_objective_batch",
    "get_acceleration_status",
    "greedy_repair_batch_native",
    "native_sdst_batch_lookup",
    "resource_capacity_window_is_feasible",
    "stabilize_temporal_batch",
]
