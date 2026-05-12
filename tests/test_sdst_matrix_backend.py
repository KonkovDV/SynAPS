"""Tests for SDST matrix backend selection, metadata, and interface consistency.

Covers tasks 11.5–11.7 from the synaps-50k-solver-improvement spec:
- 11.5: Property test — backend-to-backend lookup equivalence for all valid triples
- 11.6: Memory-accounting test — sdst_memory_bytes within target for large matrices
- 11.7: Unit test — unknown triples return 0.0 (not KeyError, not NaN)
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import hypothesis.strategies as st
import numpy as np
from hypothesis import given, settings

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.sdst_matrix import SdstMatrix

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = HORIZON_START + timedelta(hours=12)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_problem(
    n_wc: int,
    n_states: int,
    setup_entries: list[SetupEntry] | None = None,
) -> ScheduleProblem:
    """Build a minimal ScheduleProblem with given work centers and states."""
    states = [State(id=uuid4(), code=f"S-{i}", label=f"State {i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(id=uuid4(), code=f"WC-{i}", capability_group="machining")
        for i in range(n_wc)
    ]

    # Need at least one order and operation for a valid problem
    order_id = uuid4()
    orders = [
        Order(
            id=order_id,
            external_ref="ORD-0001",
            due_date=HORIZON_END,
        )
    ]
    operations = [
        Operation(
            id=uuid4(),
            order_id=order_id,
            seq_in_order=0,
            state_id=states[0].id,
            base_duration_min=10,
            eligible_wc_ids=[work_centers[0].id],
        )
    ]

    if setup_entries is None:
        setup_entries = []

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


def _make_dense_problem(n_wc: int, n_states: int) -> ScheduleProblem:
    """Build a problem with a fully populated setup matrix (all transitions)."""
    states = [State(id=uuid4(), code=f"S-{i}", label=f"State {i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(id=uuid4(), code=f"WC-{i}", capability_group="machining")
        for i in range(n_wc)
    ]

    order_id = uuid4()
    orders = [
        Order(id=order_id, external_ref="ORD-0001", due_date=HORIZON_END)
    ]
    operations = [
        Operation(
            id=uuid4(),
            order_id=order_id,
            seq_in_order=0,
            state_id=states[0].id,
            base_duration_min=10,
            eligible_wc_ids=[work_centers[0].id],
        )
    ]

    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                setup_entries.append(
                    SetupEntry(
                        work_center_id=wc.id,
                        from_state_id=s_from.id,
                        to_state_id=s_to.id,
                        setup_minutes=(i * n_states + j + 1),
                        material_loss=float(i + j) * 0.1,
                        energy_kwh=float(i * j) * 0.05,
                    )
                )

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


# ---------------------------------------------------------------------------
# Task 11.5: Property test — backend-to-backend lookup equivalence
# ---------------------------------------------------------------------------


@st.composite
def schedule_problems_with_sdst(
    draw: st.DrawFn,
    max_wc: int = 10,
    max_states: int = 8,
) -> ScheduleProblem:
    """Generate a random ScheduleProblem with a random subset of SDST entries."""
    n_states = draw(st.integers(min_value=2, max_value=max_states))
    n_wc = draw(st.integers(min_value=1, max_value=max_wc))

    states = [State(id=uuid4(), code=f"S-{i}", label=f"State {i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(id=uuid4(), code=f"WC-{i}", capability_group="machining")
        for i in range(n_wc)
    ]

    order_id = uuid4()
    orders = [Order(id=order_id, external_ref="ORD-0001", due_date=HORIZON_END)]
    operations = [
        Operation(
            id=uuid4(),
            order_id=order_id,
            seq_in_order=0,
            state_id=states[0].id,
            base_duration_min=10,
            eligible_wc_ids=[work_centers[0].id],
        )
    ]

    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if draw(st.booleans()):
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=draw(st.integers(min_value=1, max_value=60)),
                            material_loss=draw(st.floats(min_value=0.0, max_value=5.0)),
                            energy_kwh=draw(st.floats(min_value=0.0, max_value=10.0)),
                        )
                    )

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


class TestBackendLookupEquivalence:
    """**Validates: Requirements 11.1, 11.4**

    Property: SdstMatrix.from_problem(problem).get_setup(wc, from_s, to_s)
    matches the original SetupEntry values for all valid triples, and returns
    0.0 for triples not in the setup_matrix.

    Since only one backend (dense_numpy) is currently implemented, this test
    verifies that the matrix faithfully represents the source data — the same
    property that must hold for any future backend.
    """

    @given(problem=schedule_problems_with_sdst())
    @settings(max_examples=50, deadline=5000)
    def test_lookup_matches_source_entries(self, problem: ScheduleProblem) -> None:
        """All setup_matrix entries are retrievable via get_setup."""
        sdst = SdstMatrix.from_problem(problem)

        # Every entry in the source must be retrievable
        for entry in problem.setup_matrix:
            result = sdst.get_setup(entry.work_center_id, entry.from_state_id, entry.to_state_id)
            assert result == float(entry.setup_minutes), (
                f"Mismatch for ({entry.work_center_id}, {entry.from_state_id}, "
                f"{entry.to_state_id}): expected {entry.setup_minutes}, got {result}"
            )

    @given(problem=schedule_problems_with_sdst())
    @settings(max_examples=50, deadline=5000)
    def test_missing_triples_return_zero(self, problem: ScheduleProblem) -> None:
        """Triples NOT in setup_matrix return 0.0."""
        sdst = SdstMatrix.from_problem(problem)

        # Build set of populated triples
        populated = {
            (e.work_center_id, e.from_state_id, e.to_state_id)
            for e in problem.setup_matrix
        }

        # Check all possible triples — those not populated must return 0.0
        for wc in problem.work_centers:
            for s_from in problem.states:
                for s_to in problem.states:
                    triple = (wc.id, s_from.id, s_to.id)
                    if triple not in populated:
                        result = sdst.get_setup(wc.id, s_from.id, s_to.id)
                        assert result == 0.0, (
                            f"Expected 0.0 for unpopulated triple {triple}, got {result}"
                        )


# ---------------------------------------------------------------------------
# Task 11.6: Memory-accounting test
# ---------------------------------------------------------------------------


class TestMemoryAccounting:
    """**Validates: Requirements 11.3, 11.4**

    Verify sdst_memory_bytes for a 100×20 matrix is within the 20 MB target.
    Dense array: 100 wc × 20 states × 20 states × (4 + 4 + 4) bytes = 480,000 bytes.
    """

    def test_memory_within_target_100x20(self) -> None:
        """A 100 work-center × 20 state dense matrix stays under 20 MB."""
        problem = _make_dense_problem(n_wc=100, n_states=20)
        sdst = SdstMatrix.from_problem(problem)

        target_bytes = 20 * 1024 * 1024  # 20 MB
        actual_bytes = sdst.sdst_memory_bytes

        # Expected: 100 * 20 * 20 * (4 + 4 + 4) = 480,000 bytes ≈ 0.46 MB
        assert actual_bytes <= target_bytes, (
            f"Memory {actual_bytes:,} bytes exceeds 20 MB target ({target_bytes:,} bytes)"
        )
        # Sanity: should be roughly 480KB for this configuration
        assert actual_bytes > 0

    def test_memory_bytes_matches_property(self) -> None:
        """sdst_memory_bytes property equals memory_bytes() method."""
        problem = _make_dense_problem(n_wc=10, n_states=5)
        sdst = SdstMatrix.from_problem(problem)

        assert sdst.sdst_memory_bytes == sdst.memory_bytes()

    def test_memory_scales_with_dimensions(self) -> None:
        """Memory grows with n_wc and n_states as expected for dense backend."""
        small = SdstMatrix.from_problem(_make_problem(n_wc=5, n_states=3))
        large = SdstMatrix.from_problem(_make_problem(n_wc=50, n_states=10))

        # 50*10*10*12 = 60,000 vs 5*3*3*12 = 540
        assert large.memory_bytes() > small.memory_bytes()


# ---------------------------------------------------------------------------
# Task 11.7: Unit test — unknown triples return 0.0
# ---------------------------------------------------------------------------


class TestUnknownTriplesReturnZero:
    """**Validates: Requirements 11.4**

    Unknown (wc, from_state, to_state) triples return 0.0 in every backend.
    Must not raise KeyError, must not return NaN.
    """

    def test_completely_unknown_uuids(self) -> None:
        """All three UUIDs are unknown to the matrix."""
        problem = _make_dense_problem(n_wc=3, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        unknown_wc = uuid4()
        unknown_from = uuid4()
        unknown_to = uuid4()

        result = sdst.get_setup(unknown_wc, unknown_from, unknown_to)
        assert result == 0.0
        assert not math.isnan(result)

    def test_valid_wc_unknown_states(self) -> None:
        """Work center is valid but states are unknown."""
        problem = _make_dense_problem(n_wc=3, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        valid_wc = problem.work_centers[0].id
        unknown_from = uuid4()
        unknown_to = uuid4()

        result = sdst.get_setup(valid_wc, unknown_from, unknown_to)
        assert result == 0.0
        assert not math.isnan(result)

    def test_valid_states_unknown_wc(self) -> None:
        """States are valid but work center is unknown."""
        problem = _make_dense_problem(n_wc=3, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        unknown_wc = uuid4()
        valid_from = problem.states[0].id
        valid_to = problem.states[1].id

        result = sdst.get_setup(unknown_wc, valid_from, valid_to)
        assert result == 0.0
        assert not math.isnan(result)

    def test_valid_wc_valid_from_unknown_to(self) -> None:
        """Work center and from_state are valid, to_state is unknown."""
        problem = _make_dense_problem(n_wc=3, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        valid_wc = problem.work_centers[0].id
        valid_from = problem.states[0].id
        unknown_to = uuid4()

        result = sdst.get_setup(valid_wc, valid_from, unknown_to)
        assert result == 0.0
        assert not math.isnan(result)

    def test_self_transition_returns_zero(self) -> None:
        """Same from_state and to_state (self-transition) returns 0.0."""
        problem = _make_dense_problem(n_wc=3, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        # Self-transitions are never populated in _make_dense_problem
        valid_wc = problem.work_centers[0].id
        valid_state = problem.states[0].id

        result = sdst.get_setup(valid_wc, valid_state, valid_state)
        assert result == 0.0
        assert not math.isnan(result)

    def test_return_type_is_float(self) -> None:
        """get_setup always returns a float, never int or other type."""
        problem = _make_dense_problem(n_wc=3, n_states=3)
        sdst = SdstMatrix.from_problem(problem)

        # Known triple
        valid_wc = problem.work_centers[0].id
        valid_from = problem.states[0].id
        valid_to = problem.states[1].id
        result_known = sdst.get_setup(valid_wc, valid_from, valid_to)
        assert isinstance(result_known, float)

        # Unknown triple
        result_unknown = sdst.get_setup(uuid4(), uuid4(), uuid4())
        assert isinstance(result_unknown, float)


# ---------------------------------------------------------------------------
# Task 11.3: Backend metadata fields
# ---------------------------------------------------------------------------


class TestBackendMetadata:
    """Verify backend metadata attributes are present and correct."""

    def test_sdst_backend_is_dense_numpy(self) -> None:
        """Default backend is 'dense_numpy'."""
        problem = _make_problem(n_wc=2, n_states=2)
        sdst = SdstMatrix.from_problem(problem)
        assert sdst.sdst_backend == "dense_numpy"

    def test_sdst_backend_in_slots(self) -> None:
        """sdst_backend is declared in __slots__."""
        assert "sdst_backend" in SdstMatrix.__slots__

    def test_sdst_memory_bytes_positive(self) -> None:
        """sdst_memory_bytes returns a positive integer."""
        problem = _make_problem(n_wc=2, n_states=3)
        sdst = SdstMatrix.from_problem(problem)
        assert sdst.sdst_memory_bytes > 0
        assert isinstance(sdst.sdst_memory_bytes, int)
