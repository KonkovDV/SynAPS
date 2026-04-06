"""Optional hot-path acceleration seams for SynAPS."""

from __future__ import annotations

import os
from math import log
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_native_compute_atcs_log_score: Callable[..., float] | None = None

if os.getenv("SYNAPS_DISABLE_NATIVE_ACCELERATION") == "1":
    _native_compute_atcs_log_score = None
else:
    try:
        from synaps_native import (  # type: ignore[import-not-found]
            compute_atcs_log_score as _synaps_native_compute_atcs_log_score,
        )
    except ImportError:
        _native_compute_atcs_log_score = None
    else:
        _native_compute_atcs_log_score = _synaps_native_compute_atcs_log_score


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
        "native_available": _native_compute_atcs_log_score is not None,
        "atcs_log_score_backend": "native"
        if _native_compute_atcs_log_score is not None
        else "python",
        "native_module": "synaps_native" if _native_compute_atcs_log_score is not None else None,
    }


__all__ = ["compute_atcs_log_score", "get_acceleration_status"]
