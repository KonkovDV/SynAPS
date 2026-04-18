from __future__ import annotations

from math import log
from typing import TYPE_CHECKING

import pytest
from synaps import accelerators

if TYPE_CHECKING:
    pass


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


def test_compute_atcs_log_scores_batch_matches_python_reference() -> None:
    result = accelerators.compute_atcs_log_scores_batch(
        weights=[2.0, 1.5],
        processing_minutes=[12.0, 8.0],
        slack=[5.0, 0.0],
        ready_p_bar=10.0,
        setup_minutes=[3.0, 0.0],
        setup_scale=[4.0, 4.0],
        k1=2.0,
        k2=0.5,
        material_loss=[1.5, 0.0],
        material_scale=2.0,
        k3=0.5,
    )

    expected = [
        (
            log(2.0)
            - log(12.0)
            - (5.0 / (2.0 * 10.0))
            - (3.0 / (0.5 * 4.0))
            - (1.5 / (0.5 * 2.0))
        ),
        (
            log(1.5)
            - log(8.0)
            - (0.0 / (2.0 * 10.0))
            - 0.0
            - 0.0
        ),
    ]

    assert result == expected


def test_compute_atcs_log_scores_batch_uses_native_backend_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, tuple[object, ...]] = {}

    def fake_native(*args: object) -> list[float]:
        calls["args"] = args
        return [7.0, 8.0]

    monkeypatch.setattr(
        accelerators,
        "_native_compute_atcs_log_scores_batch",
        fake_native,
    )

    result = accelerators.compute_atcs_log_scores_batch(
        weights=[1.0, 2.0],
        processing_minutes=[2.0, 4.0],
        slack=[3.0, 6.0],
        ready_p_bar=4.0,
        setup_minutes=[5.0, 1.0],
        setup_scale=[6.0, 6.0],
        k1=7.0,
        k2=8.0,
        material_loss=[9.0, 0.0],
        material_scale=10.0,
        k3=11.0,
    )

    status = accelerators.get_acceleration_status()

    assert result == [7.0, 8.0]
    assert calls["args"] == (
        [1.0, 2.0],
        [2.0, 4.0],
        [3.0, 6.0],
        4.0,
        [5.0, 1.0],
        [6.0, 6.0],
        7.0,
        8.0,
        [9.0, 0.0],
        10.0,
        11.0,
    )
    assert status["atcs_log_score_batch_backend"] == "native"


def test_compute_atcs_log_scores_batch_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="identical lengths"):
        accelerators.compute_atcs_log_scores_batch(
            weights=[1.0, 2.0],
            processing_minutes=[2.0],
            slack=[0.0, 0.0],
            ready_p_bar=4.0,
            setup_minutes=[1.0, 1.0],
            setup_scale=[1.0, 1.0],
            k1=2.0,
            k2=0.5,
            material_loss=[0.0, 0.0],
            material_scale=1.0,
            k3=0.5,
        )


def test_resource_capacity_window_matches_python_reference() -> None:
    feasible = accelerators.resource_capacity_window_is_feasible(
        window_starts=[0.0, 18.0],
        window_ends=[15.0, 36.0],
        window_quantities=[1, 1],
        candidate_start=15.0,
        candidate_end=18.0,
        requested_quantity=1,
        pool_size=1,
    )

    infeasible = accelerators.resource_capacity_window_is_feasible(
        window_starts=[0.0, 18.0],
        window_ends=[15.0, 36.0],
        window_quantities=[1, 1],
        candidate_start=10.0,
        candidate_end=20.0,
        requested_quantity=1,
        pool_size=1,
    )

    assert feasible is True
    assert infeasible is False


def test_resource_capacity_window_uses_native_backend_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, tuple[object, ...]] = {}

    def fake_native(*args: object) -> bool:
        calls["args"] = args
        return True

    monkeypatch.setattr(
        accelerators,
        "_native_resource_capacity_window_is_feasible",
        fake_native,
    )

    result = accelerators.resource_capacity_window_is_feasible(
        window_starts=[0.0],
        window_ends=[5.0],
        window_quantities=[1],
        candidate_start=5.0,
        candidate_end=10.0,
        requested_quantity=1,
        pool_size=1,
    )
    status = accelerators.get_acceleration_status()

    assert result is True
    assert calls["args"] == ([0.0], [5.0], [1], 5.0, 10.0, 1, 1)
    assert status["resource_capacity_backend"] == "native"
