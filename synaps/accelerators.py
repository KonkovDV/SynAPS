"""Optional hot-path acceleration seams for SynAPS."""

from __future__ import annotations

import os
from math import log
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_native_compute_atcs_log_score: Callable[..., float] | None = None
_native_resource_capacity_window_is_feasible: Callable[..., bool] | None = None

if os.getenv("SYNAPS_DISABLE_NATIVE_ACCELERATION") == "1":
    _native_compute_atcs_log_score = None
else:
    try:
        from synaps_native import (  # type: ignore[import-not-found]
            compute_atcs_log_score as _synaps_native_compute_atcs_log_score,
            resource_capacity_window_is_feasible as _synaps_native_resource_capacity_window_is_feasible,
        )
    except ImportError:
        _native_compute_atcs_log_score = None
        _native_resource_capacity_window_is_feasible = None
    else:
        _native_compute_atcs_log_score = _synaps_native_compute_atcs_log_score
        _native_resource_capacity_window_is_feasible = (
            _synaps_native_resource_capacity_window_is_feasible
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
                _native_resource_capacity_window_is_feasible,
            )
        ),
        "atcs_log_score_backend": "native"
        if _native_compute_atcs_log_score is not None
        else "python",
        "resource_capacity_backend": "native"
        if _native_resource_capacity_window_is_feasible is not None
        else "python",
        "native_module": "synaps_native"
        if any(
            backend is not None
            for backend in (
                _native_compute_atcs_log_score,
                _native_resource_capacity_window_is_feasible,
            )
        )
        else None,
    }


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


__all__ = [
    "compute_atcs_log_score",
    "get_acceleration_status",
    "resource_capacity_window_is_feasible",
]
