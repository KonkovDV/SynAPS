"""Optional hot-path acceleration seams for SynAPS."""

from __future__ import annotations

import importlib
import os
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

if os.getenv("SYNAPS_DISABLE_NATIVE_ACCELERATION") == "1":
    _native_compute_atcs_log_score = None
    _native_compute_atcs_log_scores_batch = None
    _native_resource_capacity_window_is_feasible = None
    _native_compute_rhc_candidate_metrics_batch = None
    _native_compute_rhc_candidate_metrics_batch_np = None
    _native_compute_rhc_candidate_metrics_batch_np_jagged = None
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
        "native_module": "synaps_native"
        if any(
            backend is not None
            for backend in (
                _native_compute_atcs_log_score,
                _native_compute_atcs_log_scores_batch,
                _native_resource_capacity_window_is_feasible,
                _native_compute_rhc_candidate_metrics_batch,
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


__all__ = [
    "compute_atcs_log_score",
    "compute_atcs_log_scores_batch",
    "compute_rhc_candidate_metrics_batch",
    "compute_rhc_candidate_metrics_batch_np",
    "get_acceleration_status",
    "resource_capacity_window_is_feasible",
]
