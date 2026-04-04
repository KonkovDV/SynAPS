"""Shared test fixtures for SynAPS solver tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)

# Deterministic UUIDs for readability
STATE_A_ID = uuid4()
STATE_B_ID = uuid4()
WC_1_ID = uuid4()
WC_2_ID = uuid4()
ORDER_1_ID = uuid4()
ORDER_2_ID = uuid4()

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 1, 20, 0, tzinfo=UTC)


def make_simple_problem(n_orders: int = 2, ops_per_order: int = 2) -> ScheduleProblem:
    """Build a small FJSP-SDST problem for testing."""
    states = [
        State(id=STATE_A_ID, code="STATE-A", label="State A"),
        State(id=STATE_B_ID, code="STATE-B", label="State B"),
    ]
    work_centers = [
        WorkCenter(id=WC_1_ID, code="WC-1", capability_group="machining", speed_factor=1.0),
        WorkCenter(id=WC_2_ID, code="WC-2", capability_group="machining", speed_factor=1.2),
    ]
    setup_matrix = [
        SetupEntry(
            work_center_id=WC_1_ID,
            from_state_id=STATE_A_ID,
            to_state_id=STATE_B_ID,
            setup_minutes=10,
        ),
        SetupEntry(
            work_center_id=WC_1_ID,
            from_state_id=STATE_B_ID,
            to_state_id=STATE_A_ID,
            setup_minutes=15,
        ),
        SetupEntry(
            work_center_id=WC_2_ID,
            from_state_id=STATE_A_ID,
            to_state_id=STATE_B_ID,
            setup_minutes=8,
        ),
        SetupEntry(
            work_center_id=WC_2_ID,
            from_state_id=STATE_B_ID,
            to_state_id=STATE_A_ID,
            setup_minutes=12,
        ),
    ]

    orders: list[Order] = []
    operations: list[Operation] = []

    for i in range(n_orders):
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{i:04d}",
                due_date=HORIZON_START + timedelta(hours=6 + i),
                priority=500 + i * 100,
            )
        )

        prev_op_id = None
        for j in range(ops_per_order):
            op_id = uuid4()
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=STATE_A_ID if j % 2 == 0 else STATE_B_ID,
                    base_duration_min=30 + j * 10,
                    eligible_wc_ids=[WC_1_ID, WC_2_ID],
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        planning_horizon_start=HORIZON_START,
        planning_horizon_end=HORIZON_END,
    )


@pytest.fixture
def simple_problem() -> ScheduleProblem:
    return make_simple_problem()
