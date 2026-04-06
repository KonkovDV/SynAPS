from __future__ import annotations

from math import log
from typing import TYPE_CHECKING

from synaps import accelerators

if TYPE_CHECKING:
    import pytest


def test_compute_atcs_log_score_matches_python_reference() -> None:
    result = accelerators.compute_atcs_log_score(
        weight=2.0,
        processing_minutes=12.0,
        slack=5.0,
        ready_p_bar=10.0,
        setup_minutes=3.0,
        setup_scale=4.0,
        k1=2.0,
        k2=0.5,
        material_loss=1.5,
        material_scale=2.0,
        k3=0.5,
    )

    expected = (
        log(2.0) - log(12.0) - (5.0 / (2.0 * 10.0)) - (3.0 / (0.5 * 4.0)) - (1.5 / (0.5 * 2.0))
    )

    assert result == expected


def test_compute_atcs_log_score_uses_native_backend_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, tuple[object, ...]] = {}

    def fake_native(*args: object) -> float:
        calls["args"] = args
        return 123.456

    monkeypatch.setattr(accelerators, "_native_compute_atcs_log_score", fake_native)

    result = accelerators.compute_atcs_log_score(
        weight=1.0,
        processing_minutes=2.0,
        slack=3.0,
        ready_p_bar=4.0,
        setup_minutes=5.0,
        setup_scale=6.0,
        k1=7.0,
        k2=8.0,
        material_loss=9.0,
        material_scale=10.0,
        k3=11.0,
    )

    status = accelerators.get_acceleration_status()

    assert result == 123.456
    assert calls["args"] == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0)
    assert status["native_available"] is True
    assert status["atcs_log_score_backend"] == "native"
