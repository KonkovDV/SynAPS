"""P1-2: model fields with a physical domain must reject invalid values.

Before the fix these fields had no bounds: ``speed_factor=0`` produced a
``ZeroDivisionError`` in the duration grain, a negative one produced negative
durations, and ``max_parallel``/``pool_size``/``quantity_needed``/``quantity``
below their floors were silently accepted. Pydantic ``Field`` constraints now
reject them at construction, closing the source that motivated the defensive
``_clamp_non_negative`` in lower_bounds.py.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from synaps.model import AuxiliaryResource, OperationAuxRequirement, Order, WorkCenter


@pytest.mark.parametrize("bad_speed", [0.0, -1.0, -0.5])
def test_work_center_speed_factor_must_be_positive(bad_speed: float) -> None:
    with pytest.raises(ValidationError):
        WorkCenter(code="M", capability_group="G", speed_factor=bad_speed)


@pytest.mark.parametrize("bad_parallel", [0, -1])
def test_work_center_max_parallel_at_least_one(bad_parallel: int) -> None:
    with pytest.raises(ValidationError):
        WorkCenter(code="M", capability_group="G", max_parallel=bad_parallel)


@pytest.mark.parametrize("bad_pool", [0, -1])
def test_aux_pool_size_at_least_one(bad_pool: int) -> None:
    with pytest.raises(ValidationError):
        AuxiliaryResource(code="R", resource_type="tool", pool_size=bad_pool)


@pytest.mark.parametrize("bad_qty", [0, -1])
def test_aux_quantity_needed_at_least_one(bad_qty: int) -> None:
    from uuid import uuid4

    with pytest.raises(ValidationError):
        OperationAuxRequirement(operation_id=uuid4(), aux_resource_id=uuid4(),
                                quantity_needed=bad_qty)


@pytest.mark.parametrize("bad_quantity", [0.0, -5.0])
def test_order_quantity_must_be_positive(bad_quantity: float) -> None:
    from datetime import UTC, datetime

    with pytest.raises(ValidationError):
        Order(external_ref="O", due_date=datetime(2026, 1, 1, tzinfo=UTC), quantity=bad_quantity)


def test_valid_boundary_values_are_accepted() -> None:
    """The floors themselves (speed>0, parallel>=1, ...) stay valid."""
    WorkCenter(code="M", capability_group="G", speed_factor=0.01, max_parallel=1)
    AuxiliaryResource(code="R", resource_type="tool", pool_size=1)
