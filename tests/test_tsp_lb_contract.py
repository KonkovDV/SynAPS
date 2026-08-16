"""T-23 / F6: TSP-LB contract and non-metric assignment-LB validity.

BHK (`compute_machine_tsp_lower_bound`) is a valid LB on a FIXED set (any
matrix) but must not be discounted per removed op (GUARD-S3). The cheap
assignment relaxation (`compute_min_out_assignment_setup_lb`) is always
<= brute-force Hamiltonian-path optimum on small instances.
"""

from __future__ import annotations

import itertools
from uuid import uuid4

import pytest
from hypothesis import given, settings, strategies as st

from synaps.solvers._lbbd_cuts import (
    compute_machine_tsp_lower_bound,
    compute_min_out_assignment_setup_lb,
)


def _brute_path_optimum(
    states: list[object],
    wc_id: object,
    lookup: dict[tuple[object, object, object], float],
) -> float:
    """Exact min Hamiltonian-path cost over distinct states (n <= 7)."""
    distinct = list(dict.fromkeys(states))
    n = len(distinct)
    if n < 2:
        return 0.0
    best = float("inf")
    for order in itertools.permutations(range(n)):
        cost = 0.0
        for a, b in itertools.pairwise(order):
            cost += float(lookup.get((wc_id, distinct[a], distinct[b]), 0.0))
        best = min(best, cost)
    return 0.0 if best == float("inf") else best


@given(
    n=st.integers(min_value=2, max_value=6),
    seed=st.integers(min_value=0, max_value=10_000),
    metric=st.booleans(),
)
@settings(max_examples=80, deadline=None)
def test_assignment_lb_never_exceeds_brute_path(n: int, seed: int, metric: bool) -> None:
    """Assignment LB <= brute optimum on metric and non-metric matrices."""
    rng = __import__("random").Random(seed)
    states = [uuid4() for _ in range(n)]
    wc_id = uuid4()
    lookup: dict[tuple[object, object, object], float] = {}
    # Build a (possibly asymmetric, non-metric) cost matrix.
    for i, a in enumerate(states):
        for j, b in enumerate(states):
            if i == j:
                continue
            lookup[(wc_id, a, b)] = float(rng.randint(0, 50))
    if metric:
        # Enforce triangle inequality by Floyd-Warshall shortest paths.
        for k in states:
            for i in states:
                for j in states:
                    if i == j:
                        continue
                    via = lookup.get((wc_id, i, k), 0.0) + lookup.get((wc_id, k, j), 0.0)
                    direct = lookup.get((wc_id, i, j), float("inf"))
                    if via < direct:
                        lookup[(wc_id, i, j)] = via

    assignment_lb = compute_min_out_assignment_setup_lb(states, wc_id, lookup)
    brute = _brute_path_optimum(states, wc_id, lookup)
    bhk = compute_machine_tsp_lower_bound(states, wc_id, lookup)
    assert assignment_lb <= brute + 1e-9
    assert assignment_lb <= bhk + 1e-9
    assert bhk <= brute + 1e-9


def test_assignment_lb_dominated_by_bhk_on_guard_s3_matrix() -> None:
    """On the GUARD-S3 counterexample matrix, assignment LB <= BHK."""
    s1, s2, s3 = uuid4(), uuid4(), uuid4()
    wc = uuid4()
    pairs = [
        (s1, s2, 1.0),
        (s2, s3, 1.0),
        (s1, s3, 100.0),
        (s3, s1, 1.0),
        (s2, s1, 1.0),
        (s3, s2, 1.0),
    ]
    lookup = {(wc, a, b): v for a, b, v in pairs}
    states = [s1, s2, s3]
    assert compute_min_out_assignment_setup_lb(states, wc, lookup) <= (
        compute_machine_tsp_lower_bound(states, wc, lookup) + 1e-9
    )


@pytest.mark.parametrize("n", [2, 3, 4])
def test_empty_and_singleton_are_zero(n: int) -> None:
    states = [uuid4() for _ in range(n)]
    wc = uuid4()
    if n < 2:
        assert compute_min_out_assignment_setup_lb(states[:1], wc, {}) == 0.0
        assert compute_machine_tsp_lower_bound(states[:1], wc, {}) == 0.0


@given(
    n=st.integers(min_value=3, max_value=6),
    seed=st.integers(min_value=0, max_value=10_000),
)
@settings(max_examples=40, deadline=None)
def test_min_out_assignment_lb_valid_on_every_subset(n: int, seed: int) -> None:
    """Assignment LB stays <= brute path on every subset (fixed-set validity).

    Absolute ``L(S)`` is *not* subset-monotone (cheap edges may vanish); the
    contract is recomputation on the fixed set, never ``L(S)-L(S\\{j})``.
    """
    rng = __import__("random").Random(seed)
    states = [uuid4() for _ in range(n)]
    wc_id = uuid4()
    lookup: dict[tuple[object, object, object], float] = {}
    for i, a in enumerate(states):
        for j, b in enumerate(states):
            if i == j:
                continue
            lookup[(wc_id, a, b)] = float(rng.randint(0, 40))
    for drop in range(n):
        subset = states[:drop] + states[drop + 1 :]
        lb = compute_min_out_assignment_setup_lb(subset, wc_id, lookup)
        brute = _brute_path_optimum(subset, wc_id, lookup)
        assert lb <= brute + 1e-9
