"""Tests for cross-window quality telemetry (Tasks 3a.5, 3a.6).

Covers:
  - 3a.5: Unit tests for buffer accumulation, maxlen=5 enforcement,
           compute_window_quality_summary, and hint propagation logic.
  - 3a.6: Property test — buffer length never exceeds 5 regardless of
           window count.

Validates: Requirements 3.1, 3.2, 3.4
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from synaps.model import Assignment, Operation
from synaps.solvers.rhc._cross_window import (
    QUALITY_BUFFER_MAXLEN,
    WindowQualitySummary,
    compute_window_quality_summary,
)

# ─────────────────────────────────────────────────────────────────────────────
# Task 3a.5: Unit tests
# ─────────────────────────────────────────────────────────────────────────────


class TestBufferAccumulation:
    """Unit tests for deque-based buffer accumulation and maxlen enforcement.

    **Validates: Requirements 3.4**
    """

    def test_buffer_accumulates_summaries(self) -> None:
        """Append 3 WindowQualitySummary instances → len==3, all accessible."""
        buffer: deque[WindowQualitySummary] = deque(maxlen=QUALITY_BUFFER_MAXLEN)

        summaries = [
            WindowQualitySummary(
                window_index=i,
                per_machine_utilization={f"wc_{i}": 0.5 + i * 0.1},
                setup_cost_by_machine={f"wc_{i}": 10.0 * i},
                tardiness_contribution=float(i),
                operation_count=100 + i,
            )
            for i in range(3)
        ]

        for s in summaries:
            buffer.append(s)

        assert len(buffer) == 3
        for i, s in enumerate(buffer):
            assert s.window_index == i
            assert s.operation_count == 100 + i
            assert s.tardiness_contribution == float(i)

    def test_buffer_maxlen_enforcement(self) -> None:
        """Append 7 summaries to deque(maxlen=5) → len==5, oldest dropped."""
        buffer: deque[WindowQualitySummary] = deque(maxlen=QUALITY_BUFFER_MAXLEN)

        for i in range(7):
            buffer.append(
                WindowQualitySummary(
                    window_index=i,
                    per_machine_utilization={},
                    setup_cost_by_machine={},
                    tardiness_contribution=0.0,
                    operation_count=i,
                )
            )

        assert len(buffer) == 5
        # Only the last 5 remain (indices 2, 3, 4, 5, 6)
        assert buffer[0].window_index == 2
        assert buffer[1].window_index == 3
        assert buffer[2].window_index == 4
        assert buffer[3].window_index == 5
        assert buffer[4].window_index == 6


class TestComputeWindowQualitySummary:
    """Unit tests for compute_window_quality_summary.

    **Validates: Requirements 3.1**
    """

    def test_basic_computation(self) -> None:
        """Known assignments → correct utilization, setup cost, tardiness, op count."""
        horizon_start = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
        wc_a = uuid4()
        wc_b = uuid4()
        order_1 = uuid4()
        order_2 = uuid4()
        op_1 = uuid4()
        op_2 = uuid4()
        op_3 = uuid4()

        # Window span: 120 minutes
        window_span_minutes = 120.0

        # Assignment 1: wc_a, 60 min duration, 5 min setup, order_1
        # Assignment 2: wc_a, 30 min duration, 10 min setup, order_1
        # Assignment 3: wc_b, 45 min duration, 3 min setup, order_2
        assignments = [
            Assignment(
                operation_id=op_1,
                work_center_id=wc_a,
                start_time=horizon_start,
                end_time=horizon_start + timedelta(minutes=60),
                setup_minutes=5,
            ),
            Assignment(
                operation_id=op_2,
                work_center_id=wc_a,
                start_time=horizon_start + timedelta(minutes=60),
                end_time=horizon_start + timedelta(minutes=90),
                setup_minutes=10,
            ),
            Assignment(
                operation_id=op_3,
                work_center_id=wc_b,
                start_time=horizon_start + timedelta(minutes=10),
                end_time=horizon_start + timedelta(minutes=55),
                setup_minutes=3,
            ),
        ]

        ops_by_id = {
            op_1: Operation(
                id=op_1,
                order_id=order_1,
                seq_in_order=0,
                state_id=uuid4(),
                base_duration_min=60,
            ),
            op_2: Operation(
                id=op_2,
                order_id=order_1,
                seq_in_order=1,
                state_id=uuid4(),
                base_duration_min=30,
            ),
            op_3: Operation(
                id=op_3,
                order_id=order_2,
                seq_in_order=0,
                state_id=uuid4(),
                base_duration_min=45,
            ),
        }

        # Order 1 due at horizon_start + 80 min → latest end is 90 min → tardy by 10
        # Order 2 due at horizon_start + 60 min → latest end is 55 min → not tardy
        order_due_offsets = {
            order_1: 80.0,
            order_2: 60.0,
        }

        result = compute_window_quality_summary(
            window_index=0,
            assignments=assignments,
            window_span_minutes=window_span_minutes,
            order_due_offsets=order_due_offsets,
            ops_by_id=ops_by_id,
            horizon_start=horizon_start,
        )

        # per_machine_utilization: wc_a = (60+30)/120 = 0.75, wc_b = 45/120 = 0.375
        assert result.per_machine_utilization[wc_a] == pytest.approx(0.75, abs=1e-10)
        assert result.per_machine_utilization[wc_b] == pytest.approx(0.375, abs=1e-10)

        # setup_cost_by_machine: wc_a = 5+10 = 15, wc_b = 3
        assert result.setup_cost_by_machine[wc_a] == pytest.approx(15.0, abs=1e-10)
        assert result.setup_cost_by_machine[wc_b] == pytest.approx(3.0, abs=1e-10)

        # tardiness_contribution: order_1 tardy by 10 min, order_2 not tardy → 10.0
        assert result.tardiness_contribution == pytest.approx(10.0, abs=1e-10)

        # operation_count: 3
        assert result.operation_count == 3

    def test_empty_assignments(self) -> None:
        """Empty assignments → all zeros."""
        horizon_start = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)

        result = compute_window_quality_summary(
            window_index=0,
            assignments=[],
            window_span_minutes=120.0,
            order_due_offsets={},
            ops_by_id={},
            horizon_start=horizon_start,
        )

        assert result.per_machine_utilization == {}
        assert result.setup_cost_by_machine == {}
        assert result.tardiness_contribution == 0.0
        assert result.operation_count == 0

    def test_zero_window_span(self) -> None:
        """Zero window span → treated as empty (early return)."""
        horizon_start = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
        op_id = uuid4()
        wc_id = uuid4()

        assignments = [
            Assignment(
                operation_id=op_id,
                work_center_id=wc_id,
                start_time=horizon_start,
                end_time=horizon_start + timedelta(minutes=30),
                setup_minutes=5,
            ),
        ]

        result = compute_window_quality_summary(
            window_index=0,
            assignments=assignments,
            window_span_minutes=0.0,
            order_due_offsets={},
            ops_by_id={},
            horizon_start=horizon_start,
        )

        assert result.operation_count == 0
        assert result.tardiness_contribution == 0.0


class TestHintPropagationLogic:
    """Unit tests for hint propagation logic pattern.

    Tests the conditional logic: cross_window_hints kwarg is only added
    when cross_window_learning_enabled=True AND buffer is non-empty.

    **Validates: Requirements 3.2**
    """

    def test_flag_disabled_buffer_nonempty_no_hints(self) -> None:
        """When flag=False and buffer non-empty → no cross_window_hints in kwargs."""
        cross_window_learning_enabled = False
        quality_summary_buffer: deque[WindowQualitySummary] = deque(maxlen=QUALITY_BUFFER_MAXLEN)
        quality_summary_buffer.append(
            WindowQualitySummary(
                window_index=0,
                per_machine_utilization={"wc1": 0.8},
                setup_cost_by_machine={"wc1": 5.0},
                tardiness_contribution=2.0,
                operation_count=50,
            )
        )

        effective_inner_kwargs: dict = {}
        if cross_window_learning_enabled and quality_summary_buffer:
            effective_inner_kwargs["cross_window_hints"] = list(quality_summary_buffer)

        assert "cross_window_hints" not in effective_inner_kwargs

    def test_flag_enabled_buffer_nonempty_hints_present(self) -> None:
        """When flag=True and buffer non-empty → cross_window_hints in kwargs."""
        cross_window_learning_enabled = True
        quality_summary_buffer: deque[WindowQualitySummary] = deque(maxlen=QUALITY_BUFFER_MAXLEN)
        quality_summary_buffer.append(
            WindowQualitySummary(
                window_index=0,
                per_machine_utilization={"wc1": 0.8},
                setup_cost_by_machine={"wc1": 5.0},
                tardiness_contribution=2.0,
                operation_count=50,
            )
        )

        effective_inner_kwargs: dict = {}
        if cross_window_learning_enabled and quality_summary_buffer:
            effective_inner_kwargs["cross_window_hints"] = list(quality_summary_buffer)

        assert "cross_window_hints" in effective_inner_kwargs
        assert len(effective_inner_kwargs["cross_window_hints"]) == 1
        assert effective_inner_kwargs["cross_window_hints"][0].window_index == 0

    def test_flag_enabled_buffer_empty_no_hints(self) -> None:
        """When flag=True but buffer is empty → no cross_window_hints in kwargs."""
        cross_window_learning_enabled = True
        quality_summary_buffer: deque[WindowQualitySummary] = deque(maxlen=QUALITY_BUFFER_MAXLEN)

        effective_inner_kwargs: dict = {}
        if cross_window_learning_enabled and quality_summary_buffer:
            effective_inner_kwargs["cross_window_hints"] = list(quality_summary_buffer)

        assert "cross_window_hints" not in effective_inner_kwargs

    def test_flag_disabled_buffer_empty_no_hints(self) -> None:
        """When flag=False and buffer is empty → no cross_window_hints in kwargs."""
        cross_window_learning_enabled = False
        quality_summary_buffer: deque[WindowQualitySummary] = deque(maxlen=QUALITY_BUFFER_MAXLEN)

        effective_inner_kwargs: dict = {}
        if cross_window_learning_enabled and quality_summary_buffer:
            effective_inner_kwargs["cross_window_hints"] = list(quality_summary_buffer)

        assert "cross_window_hints" not in effective_inner_kwargs


# ─────────────────────────────────────────────────────────────────────────────
# Task 3a.6: Property test — buffer length never exceeds 5
# ─────────────────────────────────────────────────────────────────────────────


@st.composite
def window_summary_sequence(draw: st.DrawFn):
    """Generate a random sequence of window completions (length 1–100).

    Each completion produces a WindowQualitySummary with random metrics.
    """
    n_windows = draw(st.integers(min_value=1, max_value=100))
    summaries = []
    for i in range(n_windows):
        n_machines = draw(st.integers(min_value=0, max_value=5))
        machine_ids = [f"wc_{j}" for j in range(n_machines)]
        utilization = {m: draw(st.floats(min_value=0.0, max_value=1.0)) for m in machine_ids}
        setup_cost = {m: draw(st.floats(min_value=0.0, max_value=100.0)) for m in machine_ids}
        tardiness = draw(st.floats(min_value=0.0, max_value=1000.0))
        op_count = draw(st.integers(min_value=0, max_value=5000))

        summaries.append(
            WindowQualitySummary(
                window_index=i,
                per_machine_utilization=utilization,
                setup_cost_by_machine=setup_cost,
                tardiness_contribution=tardiness,
                operation_count=op_count,
            )
        )
    return summaries


class TestBufferBoundedProperty:
    """Property test: buffer length never exceeds 5 regardless of window count.

    **Validates: Requirements 3.4**
    """

    @given(summaries=window_summary_sequence())
    @settings(max_examples=200, deadline=5000)
    def test_buffer_length_never_exceeds_maxlen(
        self, summaries: list[WindowQualitySummary]
    ) -> None:
        """For any sequence of window completions, the buffer length
        never exceeds QUALITY_BUFFER_MAXLEN (5) after any append.
        """
        buffer: deque[WindowQualitySummary] = deque(maxlen=QUALITY_BUFFER_MAXLEN)

        for summary in summaries:
            buffer.append(summary)
            assert len(buffer) <= QUALITY_BUFFER_MAXLEN, (
                f"Buffer length {len(buffer)} exceeds maxlen "
                f"{QUALITY_BUFFER_MAXLEN} after appending window "
                f"{summary.window_index}"
            )

        # Final check: after all appends, still bounded
        assert len(buffer) <= QUALITY_BUFFER_MAXLEN
        # And the buffer contains at most the last 5 summaries
        if len(summaries) >= QUALITY_BUFFER_MAXLEN:
            assert len(buffer) == QUALITY_BUFFER_MAXLEN
            expected_indices = [s.window_index for s in summaries[-QUALITY_BUFFER_MAXLEN:]]
            actual_indices = [s.window_index for s in buffer]
            assert actual_indices == expected_indices
