from __future__ import annotations

import importlib
from math import exp, log
import sys
from types import SimpleNamespace
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


def test_compute_rhc_candidate_metrics_batch_matches_python_reference() -> None:
    slacks, pressures = accelerators.compute_rhc_candidate_metrics_batch(
        machine_available_offsets=[10.0, 30.0],
        eligible_machine_indices=[[0, 1], [1], []],
        predecessor_end_offsets=[5.0, 40.0, 2.0],
        due_offsets=[50.0, 80.0, 10.0],
        rpt_tail_minutes=[10.0, 15.0, 3.0],
        order_weights=[2.0, 1.0, 1.0],
        p_tilde_minutes=[8.0, 20.0, 5.0],
        avg_total_p=12.0,
        due_pressure_k1=1.0,
        due_pressure_overdue_boost=1.25,
    )

    expected_slacks = [30.0, 25.0, 5.0]
    expected_pressures = [
        (2.0 / 8.0),
        (1.0 / 20.0),
        (1.0 / 5.0),
    ]
    expected_pressures[0] *= exp(-(30.0 / 12.0))
    expected_pressures[1] *= exp(-(25.0 / 12.0))
    expected_pressures[2] *= exp(-(5.0 / 12.0))

    assert slacks == expected_slacks
    assert pressures == pytest.approx(expected_pressures)


def test_compute_rhc_candidate_metrics_batch_uses_native_backend_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, tuple[object, ...]] = {}

    def fake_native(*args: object) -> tuple[list[float], list[float]]:
        calls["args"] = args
        return [1.0, 2.0], [3.0, 4.0]

    monkeypatch.setattr(
        accelerators,
        "_native_compute_rhc_candidate_metrics_batch",
        fake_native,
    )

    slacks, pressures = accelerators.compute_rhc_candidate_metrics_batch(
        machine_available_offsets=[0.0],
        eligible_machine_indices=[[0], [0]],
        predecessor_end_offsets=[0.0, 0.0],
        due_offsets=[1.0, 2.0],
        rpt_tail_minutes=[1.0, 1.0],
        order_weights=[1.0, 1.0],
        p_tilde_minutes=[1.0, 1.0],
        avg_total_p=1.0,
        due_pressure_k1=1.0,
        due_pressure_overdue_boost=1.0,
    )
    status = accelerators.get_acceleration_status()

    assert slacks == [1.0, 2.0]
    assert pressures == [3.0, 4.0]
    assert calls["args"] == (
        [0.0],
        [[0], [0]],
        [0.0, 0.0],
        [1.0, 2.0],
        [1.0, 1.0],
        [1.0, 1.0],
        [1.0, 1.0],
        1.0,
        1.0,
        1.0,
    )
    assert status["rhc_candidate_metrics_backend"] == "native"


def test_compute_rhc_candidate_metrics_batch_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="identical lengths"):
        accelerators.compute_rhc_candidate_metrics_batch(
            machine_available_offsets=[0.0],
            eligible_machine_indices=[[0], [0]],
            predecessor_end_offsets=[0.0],
            due_offsets=[1.0, 2.0],
            rpt_tail_minutes=[1.0, 1.0],
            order_weights=[1.0, 1.0],
            p_tilde_minutes=[1.0, 1.0],
            avg_total_p=1.0,
            due_pressure_k1=1.0,
            due_pressure_overdue_boost=1.0,
        )


def test_compute_rhc_candidate_metrics_batch_rejects_invalid_machine_index() -> None:
    with pytest.raises(ValueError, match="out of range"):
        accelerators.compute_rhc_candidate_metrics_batch(
            machine_available_offsets=[0.0],
            eligible_machine_indices=[[1]],
            predecessor_end_offsets=[0.0],
            due_offsets=[1.0],
            rpt_tail_minutes=[1.0],
            order_weights=[1.0],
            p_tilde_minutes=[1.0],
            avg_total_p=1.0,
            due_pressure_k1=1.0,
            due_pressure_overdue_boost=1.0,
        )


def test_compute_rhc_candidate_metrics_batch_overdue_applies_boost() -> None:
    """When slack <= 0 the overdue boost multiplier must be applied."""
    slacks, pressures = accelerators.compute_rhc_candidate_metrics_batch(
        machine_available_offsets=[0.0],
        eligible_machine_indices=[[0]],
        predecessor_end_offsets=[0.0],
        due_offsets=[5.0],
        rpt_tail_minutes=[10.0],
        order_weights=[1.0],
        p_tilde_minutes=[4.0],
        avg_total_p=8.0,
        due_pressure_k1=1.0,
        due_pressure_overdue_boost=1.5,
    )

    # slack = 5.0 - (max(0, 0) + 10) = -5.0
    assert slacks == [-5.0]
    # pressure = (1/4) * exp(-max(0,-5)/8) * 1.5 = 0.25 * 1.0 * 1.5 = 0.375
    expected = (1.0 / 4.0) * exp(0.0) * 1.5
    assert pressures == pytest.approx([expected])


def test_compute_rhc_candidate_metrics_batch_empty_candidates() -> None:
    """n=0 edge case must return empty lists without error."""
    slacks, pressures = accelerators.compute_rhc_candidate_metrics_batch(
        machine_available_offsets=[0.0, 1.0],
        eligible_machine_indices=[],
        predecessor_end_offsets=[],
        due_offsets=[],
        rpt_tail_minutes=[],
        order_weights=[],
        p_tilde_minutes=[],
        avg_total_p=1.0,
        due_pressure_k1=1.0,
        due_pressure_overdue_boost=1.0,
    )
    assert slacks == []
    assert pressures == []


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


def test_reload_discovers_native_rhc_candidate_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_native_module = SimpleNamespace(
        compute_rhc_candidate_metrics_batch=lambda *args: ([1.0], [2.0]),
    )

    monkeypatch.delenv("SYNAPS_DISABLE_NATIVE_ACCELERATION", raising=False)
    monkeypatch.setitem(sys.modules, "synaps_native", fake_native_module)

    importlib.reload(accelerators)
    try:
        status = accelerators.get_acceleration_status()
        slacks, pressures = accelerators.compute_rhc_candidate_metrics_batch(
            machine_available_offsets=[0.0],
            eligible_machine_indices=[[0]],
            predecessor_end_offsets=[0.0],
            due_offsets=[1.0],
            rpt_tail_minutes=[1.0],
            order_weights=[1.0],
            p_tilde_minutes=[1.0],
            avg_total_p=1.0,
            due_pressure_k1=1.0,
            due_pressure_overdue_boost=1.0,
        )

        assert status["native_available"] is True
        assert status["rhc_candidate_metrics_backend"] == "native"
        assert slacks == [1.0]
        assert pressures == [2.0]
    finally:
        monkeypatch.delitem(sys.modules, "synaps_native", raising=False)
        importlib.reload(accelerators)


def test_disable_native_acceleration_env_wins_over_available_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_native_module = SimpleNamespace(
        compute_atcs_log_score=lambda *args: 1.0,
        compute_atcs_log_scores_batch=lambda *args: [1.0],
        resource_capacity_window_is_feasible=lambda *args: True,
        compute_rhc_candidate_metrics_batch=lambda *args: ([1.0], [2.0]),
    )

    monkeypatch.setenv("SYNAPS_DISABLE_NATIVE_ACCELERATION", "1")
    monkeypatch.setitem(sys.modules, "synaps_native", fake_native_module)

    importlib.reload(accelerators)
    try:
        status = accelerators.get_acceleration_status()

        assert status["native_available"] is False
        assert status["atcs_log_score_backend"] == "python"
        assert status["atcs_log_score_batch_backend"] == "python"
        assert status["resource_capacity_backend"] == "python"
        assert status["rhc_candidate_metrics_backend"] == "python"
        assert status["native_module"] is None
    finally:
        monkeypatch.delenv("SYNAPS_DISABLE_NATIVE_ACCELERATION", raising=False)
        monkeypatch.delitem(sys.modules, "synaps_native", raising=False)
        importlib.reload(accelerators)
