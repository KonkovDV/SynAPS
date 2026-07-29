"""Tests for the JSON k-NN advisory model (W4) and the trainer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from benchmark.train_runtime_advisor import _extract_sample, build_model
from synaps.ml_advisory import (
    JSON_KNN_MODEL_SCHEMA,
    JsonKnnRuntimeModel,
    ProblemFeatures,
    RuntimePredictor,
)


def _features(operation_count: int, setup_density: float = 0.2) -> ProblemFeatures:
    return ProblemFeatures(
        operation_count=operation_count,
        work_center_count=4,
        avg_ops_per_order=3.0,
        setup_density=setup_density,
        flexibility=0.5,
        precedence_depth=3,
        resource_contention=5.0,
        aux_utilization=0.0,
        sdst_ratio=0.4,
    )


def _sample(operation_count: int, best_solver: str) -> dict[str, Any]:
    return {
        "features": _features(operation_count).as_list(),
        "best_solver": best_solver,
        "runtime_ms": {best_solver: 100.0 + operation_count},
    }


def _model_payload() -> dict[str, Any]:
    samples = [
        _sample(10, "CPSAT-10"),
        _sample(20, "CPSAT-10"),
        _sample(5000, "ALNS-300"),
        _sample(8000, "ALNS-300"),
    ]
    return build_model(samples, k=3, model_version="knn-test")


class TestJsonKnnRuntimeModel:
    def test_predicts_nearest_class_with_confidence(self) -> None:
        model = JsonKnnRuntimeModel.from_dict(_model_payload())
        small = model.predict(_features(12))
        assert small.recommended_solver == "CPSAT-10"
        assert 0.0 < small.confidence <= 1.0
        large = model.predict(_features(7000))
        assert large.recommended_solver == "ALNS-300"

    def test_deterministic_predictions(self) -> None:
        model = JsonKnnRuntimeModel.from_dict(_model_payload())
        first = model.predict(_features(12))
        second = model.predict(_features(12))
        assert first == second

    def test_rejects_wrong_schema(self) -> None:
        payload = _model_payload()
        payload["schema"] = "other-schema"
        with pytest.raises(ValueError, match="unsupported advisor model schema"):
            JsonKnnRuntimeModel.from_dict(payload)

    def test_rejects_bad_feature_dim(self) -> None:
        payload = _model_payload()
        payload["samples"][0]["features"] = [1.0, 2.0]
        with pytest.raises(ValueError, match="length 9"):
            JsonKnnRuntimeModel.from_dict(payload)

    def test_rejects_empty_samples(self) -> None:
        payload = _model_payload()
        payload["samples"] = []
        with pytest.raises(ValueError, match="at least one sample"):
            JsonKnnRuntimeModel.from_dict(payload)

    def test_rejects_nan_feature_stds(self) -> None:
        payload = _model_payload()
        payload["feature_stds"][0] = float("nan")
        with pytest.raises(ValueError, match="not finite"):
            JsonKnnRuntimeModel.from_dict(payload)

    def test_rejects_nonfinite_sample_feature(self) -> None:
        payload = _model_payload()
        payload["samples"][0]["features"][0] = float("inf")
        with pytest.raises(ValueError, match="not finite"):
            JsonKnnRuntimeModel.from_dict(payload)

    def test_rejects_non_numeric_sample_feature(self) -> None:
        payload = _model_payload()
        payload["samples"][0]["features"][0] = "evil"
        with pytest.raises(ValueError, match="not numeric"):
            JsonKnnRuntimeModel.from_dict(payload)


class TestRuntimePredictorLoadJson:
    def test_load_json_activates_model(self, tmp_path: Path) -> None:
        model_path = tmp_path / "advisor.json"
        model_path.write_text(json.dumps(_model_payload()), encoding="utf-8")
        predictor = RuntimePredictor.load_json(model_path)
        assert predictor.has_loaded_model is True
        advisory = predictor.predict(_features(12))
        assert advisory.model_version == "knn-test"
        assert advisory.recommended_solver == "CPSAT-10"

    def test_missing_file_degrades_to_heuristic(self, tmp_path: Path) -> None:
        predictor = RuntimePredictor.load_json(tmp_path / "missing.json")
        assert predictor.has_loaded_model is False
        # Heuristic predictor stays advisory-only (never overrides router).
        advisory = predictor.predict(_features(12))
        assert advisory.model_version == "heuristic"

    def test_malformed_file_degrades_to_heuristic(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text('{"schema": "nope"}', encoding="utf-8")
        predictor = RuntimePredictor.load_json(bad)
        assert predictor.has_loaded_model is False

    def test_non_dict_payload_degrades_to_heuristic(self, tmp_path: Path) -> None:
        # A JSON list must not raise AttributeError from .get() calls.
        bad = tmp_path / "list.json"
        bad.write_text("[1, 2, 3]", encoding="utf-8")
        predictor = RuntimePredictor.load_json(bad)
        assert predictor.has_loaded_model is False

    def test_non_dict_samples_degrade_to_heuristic(self, tmp_path: Path) -> None:
        payload = _model_payload()
        payload["samples"] = ["evil"]
        bad = tmp_path / "badsamples.json"
        bad.write_text(json.dumps(payload), encoding="utf-8")
        predictor = RuntimePredictor.load_json(bad)
        assert predictor.has_loaded_model is False


class TestTrainer:
    def test_build_model_schema_and_normalization(self) -> None:
        model = build_model(
            [_sample(10, "CPSAT-10"), _sample(100, "CPSAT-30")],
            k=5,
            model_version="v1",
        )
        assert model["schema"] == JSON_KNN_MODEL_SCHEMA
        # k is clamped to the sample count.
        assert model["k"] == 2
        assert len(model["feature_means"]) == 9
        assert len(model["feature_stds"]) == 9

    def test_build_model_requires_samples(self) -> None:
        with pytest.raises(ValueError, match="no usable training samples"):
            build_model([], k=3, model_version="v1")

    def test_extract_sample_requires_verified_feasible(self) -> None:
        profile = {
            "operation_count": 20,
            "work_center_count": 4,
            "order_count": 5,
            "setup_density": 0.1,
            "avg_eligible_work_centers": 2.0,
            "precedence_depth": 4,
            "resource_contention": 5.0,
            "aux_requirement_count": 0,
            "setup_entry_count": 10,
            "setup_nonzero_entry_count": 4,
        }
        report = {
            "problem_profile": profile,
            "comparisons": [
                {
                    "solver_config": "GREED",
                    "results": {"feasible": True, "weighted_sum": 50.0},
                    "verification": {"feasible": False},  # rejected by gate
                    "statistics": {"wall_time_s_mean": 0.01},
                },
                {
                    "solver_config": "CPSAT-30",
                    "results": {"feasible": True, "weighted_sum": 40.0},
                    "verification": {"feasible": True},
                    "statistics": {"wall_time_s_mean": 1.2},
                },
            ],
        }
        sample = _extract_sample(report)
        assert sample is not None
        # GREED was excluded (verification failed) even though its
        # weighted_sum was reported: ADR-006 gate in the labeling rule.
        assert sample["best_solver"] == "CPSAT-30"
        assert len(sample["features"]) == 9

    def test_extract_sample_returns_none_without_feasible_entries(self) -> None:
        report = {
            "problem_profile": {"operation_count": 5, "work_center_count": 2},
            "comparisons": [
                {
                    "solver_config": "GREED",
                    "results": {"feasible": False},
                    "verification": {"feasible": False},
                    "statistics": {},
                }
            ],
        }
        assert _extract_sample(report) is None
