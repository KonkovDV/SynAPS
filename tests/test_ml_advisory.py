"""Tests for the ML advisory layer: feature encoding, heuristic prediction, and router hooks."""

from __future__ import annotations

from synaps.ml_advisory import (
    ProblemFeatures,
    RuntimeAdvisory,
    RuntimePredictor,
    encode_problem_features,
    torch_available,
)
from synaps.problem_profile import build_problem_profile
from synaps.solvers.router import (
    select_solver,
)
from tests.conftest import make_simple_problem

# ── Feature encoding ──


def test_encode_problem_features_produces_correct_shape() -> None:
    problem = make_simple_problem()
    profile = build_problem_profile(problem)

    features = encode_problem_features(problem, profile)

    assert len(features.as_list()) == 9
    assert features.operation_count == 4
    assert features.work_center_count == 2


def test_encode_problem_features_flexibility_is_one_when_all_eligible() -> None:
    """When every op is eligible for every WC, flexibility should be 1.0."""
    problem = make_simple_problem()
    profile = build_problem_profile(problem)

    features = encode_problem_features(problem, profile)

    assert features.flexibility == 1.0


def test_encode_problem_features_sdst_ratio_is_one_when_all_nonzero() -> None:
    """make_simple_problem has all nonzero setup entries."""
    problem = make_simple_problem()
    profile = build_problem_profile(problem)

    features = encode_problem_features(problem, profile)

    assert features.sdst_ratio == 1.0


def test_encode_problem_features_aux_utilization_zero_without_aux() -> None:
    problem = make_simple_problem()
    profile = build_problem_profile(problem)

    features = encode_problem_features(problem, profile)

    assert features.aux_utilization == 0.0


def test_encode_problem_features_scales_with_larger_problems() -> None:
    small = make_simple_problem(n_orders=2, ops_per_order=2)
    large = make_simple_problem(n_orders=20, ops_per_order=3)

    small_features = encode_problem_features(small, build_problem_profile(small))
    large_features = encode_problem_features(large, build_problem_profile(large))

    assert large_features.operation_count > small_features.operation_count
    assert large_features.resource_contention > small_features.resource_contention


# ── Heuristic predictor ──


def test_heuristic_predictor_returns_advisory() -> None:
    problem = make_simple_problem()
    profile = build_problem_profile(problem)
    features = encode_problem_features(problem, profile)

    predictor = RuntimePredictor.heuristic()
    advisory = predictor.predict(features)

    assert isinstance(advisory, RuntimeAdvisory)
    assert advisory.model_version == "heuristic"
    assert 0 <= advisory.confidence <= 1
    assert "GREED" in advisory.predicted_ms
    assert advisory.recommended_solver


def test_heuristic_predictor_recommends_cpsat_for_small_problems() -> None:
    problem = make_simple_problem(n_orders=3, ops_per_order=2)
    profile = build_problem_profile(problem)
    features = encode_problem_features(problem, profile)

    advisory = RuntimePredictor.heuristic().predict(features)

    assert advisory.recommended_solver == "CPSAT-30"


def test_heuristic_predictor_recommends_lbbd_for_larger_problems() -> None:
    problem = make_simple_problem(n_orders=50, ops_per_order=4)
    profile = build_problem_profile(problem)
    features = encode_problem_features(problem, profile)

    advisory = RuntimePredictor.heuristic().predict(features)

    assert "LBBD" in advisory.recommended_solver


def test_problem_features_as_list_roundtrips_correctly() -> None:
    features = ProblemFeatures(
        operation_count=100,
        work_center_count=10,
        avg_ops_per_order=5.0,
        setup_density=0.3,
        flexibility=0.8,
        precedence_depth=4,
        resource_contention=10.0,
        aux_utilization=0.1,
        sdst_ratio=0.5,
    )
    values = features.as_list()
    assert len(values) == 9
    assert values[0] == 100.0
    assert values[3] == 0.3


# ── Router advisory hook ──


def test_select_solver_ignores_advisory_when_none() -> None:
    """Without advisory, select_solver behaves as before."""
    problem = make_simple_problem()

    solver, kwargs, decision = select_solver(problem)

    assert decision.solver_config == "CPSAT-10"
    assert "ML advisory" not in decision.reason


def test_select_solver_does_not_use_heuristic_advisory_even_when_confident() -> None:
    """Heuristic-only predictors are placeholders and must not override routing."""
    problem = make_simple_problem()

    predictor = RuntimePredictor.heuristic()
    _, _, decision = select_solver(
        problem,
        advisory_predictor=predictor,
        advisory_confidence_threshold=0.3,  # low threshold so heuristic overrides
    )

    assert decision.solver_config == "CPSAT-10"
    assert "ML advisory" not in decision.reason


def test_select_solver_uses_loaded_model_advisory_when_confident() -> None:
    """Only predictors backed by a loaded model may override routing."""

    class StubLoadedPredictor(RuntimePredictor):
        def __init__(self) -> None:
            super().__init__(model=object(), model_version="stub-runtime-v1")

        def predict(self, features: ProblemFeatures) -> RuntimeAdvisory:
            return RuntimeAdvisory(
                predicted_ms={"GREED": 20.0, "CPSAT-30": 10.0, "LBBD": 40.0},
                recommended_solver="CPSAT-30",
                confidence=0.95,
                model_version="stub-runtime-v1",
            )

    problem = make_simple_problem()

    _, _, decision = select_solver(
        problem,
        advisory_predictor=StubLoadedPredictor(),
        advisory_confidence_threshold=0.3,
    )

    assert decision.solver_config == "CPSAT-30"
    assert "ML advisory" in decision.reason


def test_select_solver_falls_back_when_advisory_low_confidence() -> None:
    """Advisory with confidence below threshold should fall back to deterministic."""
    problem = make_simple_problem()

    predictor = RuntimePredictor.heuristic()
    solver, kwargs, decision = select_solver(
        problem,
        advisory_predictor=predictor,
        advisory_confidence_threshold=0.99,  # very high — heuristic won't reach
    )

    assert decision.solver_config == "CPSAT-10"
    assert "ML advisory" not in decision.reason


def test_select_solver_handles_non_predictor_gracefully() -> None:
    """Passing a non-RuntimePredictor object should not crash."""
    problem = make_simple_problem()

    solver, kwargs, decision = select_solver(
        problem,
        advisory_predictor="not_a_predictor",
    )

    assert decision.solver_config == "CPSAT-10"


# ── Torch availability ──


def test_torch_available_returns_bool() -> None:
    result = torch_available()
    assert isinstance(result, bool)
