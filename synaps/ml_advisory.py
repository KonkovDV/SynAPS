"""ML Advisory Layer for solver routing — optional, degradation-safe.

This module encodes scheduling problems into GNN-compatible feature tensors,
predicts solver runtimes, and provides advisory routing recommendations.
When ``torch`` or ``torch_geometric`` are not installed, all functions
operate in **fallback mode** — returning ``None`` for predictions and
deferring to the deterministic router.

Architecture:
    ProblemProfile → feature_encoder → GNN → runtime prediction → advisory

Usage::

    from synaps.ml_advisory import RuntimePredictor, encode_problem_features

    features = encode_problem_features(problem, profile)
    predictor = RuntimePredictor.load("models/runtime_v1.pt")
    advisory = predictor.predict(features)
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

from synaps.logging import get_logger

if TYPE_CHECKING:
    from pathlib import Path

    from synaps.model import ScheduleProblem
    from synaps.problem_profile import ProblemProfile

_log = get_logger("synaps.ml_advisory")

# ── Lazy torch import ──

_TORCH_AVAILABLE = False
try:
    import torch

    _TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]


def torch_available() -> bool:
    """Return ``True`` if PyTorch is importable."""
    return _TORCH_AVAILABLE


# ── Feature encoding ──


@dataclasses.dataclass(frozen=True)
class ProblemFeatures:
    """Encoded feature set for a scheduling problem instance.

    All fields are plain Python types so the dataclass works without torch.
    When torch is available, :meth:`to_tensor` returns a stacked float tensor.
    """

    operation_count: int
    work_center_count: int
    avg_ops_per_order: float
    setup_density: float
    flexibility: float
    precedence_depth: int
    resource_contention: float
    aux_utilization: float
    sdst_ratio: float

    def as_list(self) -> list[float]:
        return [
            float(self.operation_count),
            float(self.work_center_count),
            self.avg_ops_per_order,
            self.setup_density,
            self.flexibility,
            float(self.precedence_depth),
            self.resource_contention,
            self.aux_utilization,
            self.sdst_ratio,
        ]

    def to_tensor(self) -> Any:
        """Return a ``torch.Tensor`` of shape ``(1, 9)``; requires PyTorch."""
        if not _TORCH_AVAILABLE:
            raise RuntimeError("torch is required for tensor conversion")
        return torch.tensor([self.as_list()], dtype=torch.float32)


def encode_problem_features(
    problem: ScheduleProblem,
    profile: ProblemProfile,
) -> ProblemFeatures:
    """Extract feature vector from a problem + its cached profile."""
    ops = problem.operations
    orders = problem.orders

    avg_ops = len(ops) / max(len(orders), 1)

    # Flexibility: avg fraction of eligible WCs per operation (1.0 = fully flexible)
    wc_count = profile.work_center_count
    flexibility = profile.avg_eligible_work_centers / wc_count if wc_count > 0 and ops else 1.0

    # SDST ratio: fraction of setup entries with non-zero cost
    sdst_ratio = (
        profile.setup_nonzero_entry_count / max(profile.setup_entry_count, 1)
    )

    # Auxiliary utilization: fraction of operations with aux requirements
    aux_util = profile.aux_requirement_count / max(len(ops), 1)

    return ProblemFeatures(
        operation_count=profile.operation_count,
        work_center_count=profile.work_center_count,
        avg_ops_per_order=round(avg_ops, 3),
        setup_density=profile.setup_density,
        flexibility=round(flexibility, 3),
        precedence_depth=profile.precedence_depth,
        resource_contention=profile.resource_contention,
        aux_utilization=round(aux_util, 3),
        sdst_ratio=round(sdst_ratio, 3),
    )


# ── Runtime prediction ──


@dataclasses.dataclass(frozen=True)
class RuntimeAdvisory:
    """Advisory output from the ML runtime predictor.

    All times in milliseconds.  ``confidence`` is in [0, 1].
    """

    predicted_ms: dict[str, float]
    recommended_solver: str
    confidence: float
    model_version: str


class RuntimePredictor:
    """GNN-based solver runtime predictor.

    Operates in two modes:
    - **loaded**: real model weights (requires torch)
    - **heuristic**: deterministic fallback using feature-based rules
    """

    def __init__(self, model: Any = None, model_version: str = "heuristic") -> None:
        self._model = model
        self._model_version = model_version

    @classmethod
    def load(cls, path: Path | str) -> RuntimePredictor:
        """Load a trained model from disk.  Raises if torch is unavailable."""
        if not _TORCH_AVAILABLE:
            _log.warning("torch_unavailable", detail="falling back to heuristic predictor")
            return cls(model=None, model_version="heuristic")

        from pathlib import Path as _Path

        model_path = _Path(path)
        if not model_path.exists():
            _log.warning("model_not_found", path=str(path))
            return cls(model=None, model_version="heuristic")

        model = torch.load(model_path, weights_only=True)
        return cls(model=model, model_version=str(model_path.stem))

    @classmethod
    def heuristic(cls) -> RuntimePredictor:
        """Create a pure heuristic predictor (no model needed)."""
        return cls(model=None, model_version="heuristic")

    def predict(self, features: ProblemFeatures) -> RuntimeAdvisory:
        """Predict solver runtimes and recommend the best solver config."""
        if self._model is not None and _TORCH_AVAILABLE:
            return self._predict_with_model(features)
        return self._predict_heuristic(features)

    def _predict_heuristic(self, features: ProblemFeatures) -> RuntimeAdvisory:
        """Deterministic heuristic prediction based on feature values."""
        n = features.operation_count
        density = features.setup_density
        contention = features.resource_contention

        # Rough time complexity models for each solver tier
        greed_ms = n * 0.5 + density * 10
        cpsat_ms = n ** 1.8 * 0.01 * (1 + density) * (1 + contention * 0.5)
        lbbd_ms = n ** 1.4 * 0.05 * (1 + density * 0.3)

        predictions = {
            "GREED": round(greed_ms, 1),
            "CPSAT-30": round(cpsat_ms, 1),
            "LBBD": round(lbbd_ms, 1),
        }

        # Recommend based on predicted feasibility within time budget
        if n <= 80:
            recommended = "CPSAT-30"
            confidence = 0.7
        elif n <= 300:
            recommended = "LBBD" if density > 0.3 else "CPSAT-120"
            confidence = 0.5
        else:
            recommended = "LBBD-HD"
            confidence = 0.4

        return RuntimeAdvisory(
            predicted_ms=predictions,
            recommended_solver=recommended,
            confidence=confidence,
            model_version=self._model_version,
        )

    def _predict_with_model(self, features: ProblemFeatures) -> RuntimeAdvisory:
        """Model-based prediction (when a trained GNN is loaded)."""
        tensor = features.to_tensor()

        with torch.no_grad():
            output = self._model(tensor)

        # Expected output: [greed_ms, cpsat_ms, lbbd_ms, recommended_idx, confidence]
        values = output.squeeze().tolist()
        if len(values) < 5:
            _log.warning("model_output_unexpected", shape=len(values))
            return self._predict_heuristic(features)

        solver_map = {0: "GREED", 1: "CPSAT-30", 2: "LBBD"}
        recommended_idx = int(round(values[3]))
        recommended = solver_map.get(recommended_idx, "CPSAT-30")

        return RuntimeAdvisory(
            predicted_ms={
                "GREED": round(values[0], 1),
                "CPSAT-30": round(values[1], 1),
                "LBBD": round(values[2], 1),
            },
            recommended_solver=recommended,
            confidence=min(max(values[4], 0.0), 1.0),
            model_version=self._model_version,
        )


__all__ = [
    "ProblemFeatures",
    "RuntimeAdvisory",
    "RuntimePredictor",
    "encode_problem_features",
    "torch_available",
]
