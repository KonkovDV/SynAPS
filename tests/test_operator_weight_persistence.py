"""Tests for ALNS operator weight persistence (Task 12.5, 12.6, 12.7).

Covers:
  - 12.5: Unit tests for _normalize_initial_operator_weights
  - 12.6: Property test — weights always sum to 1.0
  - 12.7: Edge-case test — dict persistence aligns by name, list is positional

Validates: Requirements 12.1, 12.2, 12.3
"""

from __future__ import annotations

import math

import pytest

from synaps.solvers.alns_solver import (
    DESTROY_OPERATORS,
    _normalize_initial_operator_weights,
)

# Canonical operator names from the current DESTROY_OPERATORS list.
NAMES: list[str] = [name for name, _ in DESTROY_OPERATORS]
N: int = len(NAMES)


# ─────────────────────────────────────────────────────────────────────────────
# Task 12.5: Unit tests for _normalize_initial_operator_weights
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeInitialOperatorWeightsUnit:
    """Unit tests for dict roundtrip, list roundtrip, fallback, and normalization."""

    def test_none_returns_uniform(self) -> None:
        """raw=None → all weights equal 1/n, sum=1.0."""
        result = _normalize_initial_operator_weights(None, NAMES)
        assert len(result) == N
        expected = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected, abs=1e-12)
        assert sum(result) == pytest.approx(1.0, abs=1e-10)

    def test_dict_full_coverage(self) -> None:
        """raw={name: 2.0 for all names} → all weights equal 1/n, sum=1.0."""
        raw = {name: 2.0 for name in NAMES}
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N
        expected = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected, abs=1e-12)
        assert sum(result) == pytest.approx(1.0, abs=1e-10)

    def test_dict_partial_coverage(self) -> None:
        """raw with only 2 keys → recognized weights higher than filled ones, sum=1.0."""
        raw = {"random": 5.0, "worst": 5.0}
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N
        assert sum(result) == pytest.approx(1.0, abs=1e-10)
        # "random" and "worst" should have higher weight than filled entries
        idx_random = NAMES.index("random")
        idx_worst = NAMES.index("worst")
        # Filled entries get mean of recognized = 5.0, so all are equal here
        # Actually: recognized values are 5.0 each, mean_recognized = 5.0,
        # so all entries get 5.0 → uniform. Let's use asymmetric values instead.
        raw2 = {"random": 10.0, "worst": 2.0}
        result2 = _normalize_initial_operator_weights(raw2, NAMES)
        assert len(result2) == N
        assert sum(result2) == pytest.approx(1.0, abs=1e-10)
        # "random" should have the highest weight
        idx_random = NAMES.index("random")
        assert result2[idx_random] == max(result2)

    def test_dict_extra_keys_ignored(self) -> None:
        """raw with extra keys → only recognized keys used, sum=1.0."""
        raw = {"random": 1.0, "nonexistent_op": 99.0}
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N
        assert sum(result) == pytest.approx(1.0, abs=1e-10)
        # "random" is recognized; others filled with mean of recognized (1.0)
        # So all should be equal (1.0 each before normalization)
        idx_random = NAMES.index("random")
        # All weights should be equal since mean_recognized = 1.0 = the only recognized value
        expected = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected, abs=1e-12)

    def test_dict_all_invalid_falls_back_uniform(self) -> None:
        """raw with all invalid values → uniform."""
        raw = {"random": -1.0, "worst": float("inf")}
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N
        expected = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected, abs=1e-12)
        assert sum(result) == pytest.approx(1.0, abs=1e-10)

    def test_list_correct_length(self) -> None:
        """raw=[1.0]*n → uniform (all equal after normalization), sum=1.0."""
        raw = [1.0] * N
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N
        expected = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected, abs=1e-12)
        assert sum(result) == pytest.approx(1.0, abs=1e-10)

    def test_list_wrong_length_falls_back_uniform(self) -> None:
        """raw=[0.5, 0.5] (wrong length) → uniform."""
        raw = [0.5, 0.5]
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N
        expected = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected, abs=1e-12)
        assert sum(result) == pytest.approx(1.0, abs=1e-10)

    def test_list_negative_value_falls_back_uniform(self) -> None:
        """raw=[-1.0] + [1.0]*(n-1) → uniform (negative triggers fallback)."""
        raw = [-1.0] + [1.0] * (N - 1)
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N
        expected = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected, abs=1e-12)
        assert sum(result) == pytest.approx(1.0, abs=1e-10)

    def test_unrecognized_type_falls_back_uniform(self) -> None:
        """raw="invalid" → uniform."""
        raw = "invalid"
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N
        expected = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected, abs=1e-12)
        assert sum(result) == pytest.approx(1.0, abs=1e-10)


# ─────────────────────────────────────────────────────────────────────────────
# Task 12.6: Property test — weights always sum to 1.0
# Validates: Requirements 12.3
# ─────────────────────────────────────────────────────────────────────────────

import hypothesis.strategies as st
from hypothesis import given, settings


# Strategy: generate random raw inputs (dicts with random subsets of operator
# names and random positive floats, or lists of random length/values, or None).
@st.composite
def raw_weight_inputs(draw: st.DrawFn):
    """Generate random raw inputs for _normalize_initial_operator_weights."""
    choice = draw(st.sampled_from(["none", "dict_valid", "dict_partial", "dict_empty",
                                    "list_correct", "list_wrong_len", "list_with_neg"]))
    if choice == "none":
        return None
    elif choice == "dict_valid":
        # Dict with all operator names and random positive floats
        return {name: draw(st.floats(min_value=0.01, max_value=100.0)) for name in NAMES}
    elif choice == "dict_partial":
        # Dict with a random subset of operator names
        subset = draw(st.lists(st.sampled_from(NAMES), min_size=1, max_size=N, unique=True))
        return {name: draw(st.floats(min_value=0.01, max_value=100.0)) for name in subset}
    elif choice == "dict_empty":
        # Dict with no recognized keys
        return {"fake_op_1": 1.0, "fake_op_2": 2.0}
    elif choice == "list_correct":
        # List of correct length with non-negative values
        return [draw(st.floats(min_value=0.0, max_value=100.0)) for _ in range(N)]
    elif choice == "list_wrong_len":
        # List of wrong length
        wrong_len = draw(st.integers(min_value=1, max_value=20).filter(lambda x: x != N))
        return [draw(st.floats(min_value=0.0, max_value=10.0)) for _ in range(wrong_len)]
    else:  # list_with_neg
        # List with at least one negative value
        vals = [draw(st.floats(min_value=0.01, max_value=10.0)) for _ in range(N)]
        neg_idx = draw(st.integers(min_value=0, max_value=N - 1))
        vals[neg_idx] = -draw(st.floats(min_value=0.01, max_value=10.0))
        return vals


class TestNormalizeWeightsProperty:
    """Property test: after normalization, weights always sum to 1.0.

    **Validates: Requirements 12.3**
    """

    @given(raw=raw_weight_inputs())
    @settings(max_examples=200, deadline=5000)
    def test_weights_sum_to_one_and_valid(self, raw) -> None:
        """For any raw input, the result always has:
        - len == N
        - abs(sum(result) - 1.0) < 1e-10
        - All values >= 0
        """
        result = _normalize_initial_operator_weights(raw, NAMES)
        assert len(result) == N, f"Expected length {N}, got {len(result)}"
        assert abs(sum(result) - 1.0) < 1e-10, (
            f"Weights sum to {sum(result)}, expected ~1.0"
        )
        for i, w in enumerate(result):
            assert w >= 0.0, f"Weight at index {i} is negative: {w}"


# ─────────────────────────────────────────────────────────────────────────────
# Task 12.7: Edge-case test — DESTROY_OPERATORS order changed between windows
# Validates: Requirements 12.1, 12.2
# ─────────────────────────────────────────────────────────────────────────────


class TestOperatorWeightPersistenceOrderChange:
    """Edge-case: DESTROY_OPERATORS order changed between windows.

    Dict persistence aligns by name regardless of position.
    List persistence is positional and cannot adapt to reordering.
    """

    def test_dict_persistence_aligns_by_name(self) -> None:
        """Dict weights align correctly by NAME, not by position.

        Simulate: Window 1 produces final weights as a dict. Window 2 has
        a hypothetically reordered operator_names. The dict-based normalization
        should still assign the correct weight to each operator by name.
        """
        # Window 1 final weights (dict)
        window1_weights: dict[str, float] = {
            "random": 0.3,
            "worst": 0.2,
            "related": 0.1,
            "machine_segment": 0.1,
            "precedence_chain": 0.1,
            "critical_path": 0.1,
            "due_pressure": 0.1,
        }

        # Window 2 has reversed operator order
        reversed_names = list(reversed(NAMES))

        result = _normalize_initial_operator_weights(window1_weights, reversed_names)

        assert len(result) == N
        assert abs(sum(result) - 1.0) < 1e-10

        # Verify alignment: "random" should still get the highest weight
        # regardless of its position in reversed_names
        idx_random_in_reversed = reversed_names.index("random")
        idx_worst_in_reversed = reversed_names.index("worst")

        # "random" had 0.3 (highest), "worst" had 0.2 (second highest)
        assert result[idx_random_in_reversed] > result[idx_worst_in_reversed], (
            f"'random' weight ({result[idx_random_in_reversed]}) should be > "
            f"'worst' weight ({result[idx_worst_in_reversed]}) after dict alignment"
        )

        # Verify the ratio is preserved: random/worst should be 0.3/0.2 = 1.5
        ratio = result[idx_random_in_reversed] / result[idx_worst_in_reversed]
        assert ratio == pytest.approx(1.5, abs=1e-10), (
            f"Weight ratio random/worst should be 1.5, got {ratio}"
        )

    def test_dict_persistence_with_shuffled_names(self) -> None:
        """Dict persistence works correctly with arbitrarily shuffled names."""
        import random as stdlib_random

        window1_weights = {
            "random": 0.30,
            "worst": 0.20,
            "related": 0.15,
            "machine_segment": 0.10,
            "precedence_chain": 0.10,
            "critical_path": 0.08,
            "due_pressure": 0.07,
        }

        # Shuffle names deterministically
        shuffled_names = list(NAMES)
        stdlib_random.Random(123).shuffle(shuffled_names)

        result = _normalize_initial_operator_weights(window1_weights, shuffled_names)

        assert len(result) == N
        assert abs(sum(result) - 1.0) < 1e-10

        # Each operator should get its proportional weight regardless of position
        total_input = sum(window1_weights.values())
        for i, name in enumerate(shuffled_names):
            expected_normalized = window1_weights[name] / total_input
            assert result[i] == pytest.approx(expected_normalized, abs=1e-10), (
                f"Operator '{name}' at position {i}: expected {expected_normalized}, "
                f"got {result[i]}"
            )

    def test_list_persistence_is_positional(self) -> None:
        """List persistence is positional — it cannot adapt to operator reordering.

        This documents the limitation: if DESTROY_OPERATORS order changes between
        windows and weights are stored as a list, the weights will be applied to
        the wrong operators. The function still normalizes correctly (sum=1.0),
        but semantic alignment is lost.
        """
        # Window 1 produced weights as a list (positional)
        # Position 0 = "random" (0.3), position 1 = "worst" (0.2), etc.
        raw_list = [0.3, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1]

        # If operator_names order is the same, it works correctly
        result_same_order = _normalize_initial_operator_weights(raw_list, NAMES)
        assert len(result_same_order) == N
        assert abs(sum(result_same_order) - 1.0) < 1e-10
        # Position 0 should have the highest weight
        assert result_same_order[0] == max(result_same_order)

        # If operator_names order is reversed, the list is still applied positionally
        reversed_names = list(reversed(NAMES))
        result_reversed = _normalize_initial_operator_weights(raw_list, reversed_names)
        assert len(result_reversed) == N
        assert abs(sum(result_reversed) - 1.0) < 1e-10
        # Position 0 still gets 0.3's share — but now position 0 is "due_pressure"
        # (the last element of NAMES reversed). This documents the limitation.
        assert result_reversed[0] == max(result_reversed), (
            "List persistence is positional: position 0 always gets the highest "
            "weight regardless of which operator is at that position"
        )

    def test_list_wrong_length_falls_back_to_uniform(self) -> None:
        """If operator count changes (e.g., new operator added), list length
        mismatches and the function falls back to uniform weights.
        """
        # Simulate: old window had 6 operators, new window has 7
        old_weights_list = [0.2, 0.2, 0.15, 0.15, 0.15, 0.15]  # length 6
        result = _normalize_initial_operator_weights(old_weights_list, NAMES)
        assert len(result) == N
        expected_uniform = 1.0 / N
        for w in result:
            assert w == pytest.approx(expected_uniform, abs=1e-12)
        assert abs(sum(result) - 1.0) < 1e-10
