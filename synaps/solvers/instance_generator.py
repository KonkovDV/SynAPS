"""Scalable instance generator for benchmarking SynAPS solvers at 50K+ operations.

Generates realistic FJSP-SDST instances with configurable:
  - operation count (50K+)
  - work center count
  - state count (for SDST matrix)
  - predecessor chain depth (ops per order)
  - SDST rule density

Academic basis:
    - Taillard (1993): benchmark generator methodology for job-shop
    - Brandimarte (1993): flexible job-shop generation with machine eligibility
    - Hurink et al. (1994): problem structure parameters for FJSP
    - Vallada et al. (2015, EJOR): SDST generation for unrelated parallel machines
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)


def generate_large_instance(
    num_operations: int = 50_000,
    num_work_centers: int = 100,
    num_states: int = 50,
    ops_per_order: int = 3,
    eligible_wc_ratio: float = 0.05,
    sdst_density: float = 0.10,
    duration_range: tuple[int, int] = (5, 120),
    setup_range: tuple[int, int] = (2, 30),
    material_loss_range: tuple[float, float] = (0.0, 5.0),
    seed: int | None = None,
) -> ScheduleProblem:
    """Generate a large FJSP-SDST instance for benchmarking.

    Parameters
    ----------
    num_operations:
        Target number of operations (approximate due to rounding).
    num_work_centers:
        Number of work centers (machines).
    num_states:
        Number of distinct machine states for SDST matrix.
    ops_per_order:
        Ops per order (creates predecessor chains).
    eligible_wc_ratio:
        Fraction of WCs each op is eligible for (0.05 = 5%).
    sdst_density:
        Fraction of state pairs that have non-zero SDST rules.
    duration_range:
        (min, max) for base_duration_min.
    setup_range:
        (min, max) for setup minutes in SDST rules.
    material_loss_range:
        (min, max) for material loss in SDST rules.
    seed:
        Random seed for reproducibility.
    """
    rng = random.Random(seed)

    # -- Work centers --
    work_centers = [
        WorkCenter(id=uuid4(), code=f"WC-{i:04d}", capability_group=f"G{i % 10}")
        for i in range(num_work_centers)
    ]
    wc_ids = [wc.id for wc in work_centers]

    # -- States --
    states = [
        State(id=uuid4(), code=f"S-{i:03d}", label=f"State {i}")
        for i in range(num_states)
    ]
    state_ids = [s.id for s in states]

    # -- Setup matrix (SDST entries) --
    setup_matrix: list[SetupEntry] = []
    num_sdst_pairs = int(num_states * num_states * sdst_density)
    sdst_pairs: set[tuple] = set()
    while len(sdst_pairs) < num_sdst_pairs and len(sdst_pairs) < num_states * num_states:
        from_s = rng.choice(state_ids)
        to_s = rng.choice(state_ids)
        wc_id = rng.choice(wc_ids)
        key = (wc_id, from_s, to_s)
        if from_s != to_s and key not in sdst_pairs:
            sdst_pairs.add(key)
            setup_matrix.append(
                SetupEntry(
                    work_center_id=wc_id,
                    from_state_id=from_s,
                    to_state_id=to_s,
                    setup_minutes=rng.randint(*setup_range),
                    material_loss=round(rng.uniform(*material_loss_range), 2),
                    energy_kwh=round(rng.uniform(0.0, 2.0), 2),
                )
            )

    # -- Orders and operations --
    num_orders = num_operations // ops_per_order
    min_eligible = max(1, int(num_work_centers * eligible_wc_ratio))
    max_eligible = max(min_eligible + 1, int(num_work_centers * eligible_wc_ratio * 3))
    max_eligible = min(max_eligible, num_work_centers)

    horizon_start = datetime(2026, 1, 1)
    horizon_end = horizon_start + timedelta(days=30)

    orders: list[Order] = []
    operations: list[Operation] = []

    for oi in range(num_orders):
        order_id = uuid4()
        order_due = horizon_start + timedelta(
            minutes=rng.randint(480, 43200)  # 8h to 30d
        )
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{oi:06d}",
                priority=rng.randint(1, 10),
                due_date=order_due,
                quantity=rng.randint(1, 100),
            )
        )

        prev_op_id = None
        for step in range(ops_per_order):
            op_id = uuid4()
            n_eligible = rng.randint(min_eligible, max_eligible)
            eligible = rng.sample(wc_ids, n_eligible)
            state_id = rng.choice(state_ids)

            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=step,
                    state_id=state_id,
                    base_duration_min=rng.randint(*duration_range),
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id

    return ScheduleProblem(
        operations=operations,
        orders=orders,
        work_centers=work_centers,
        states=states,
        setup_matrix=setup_matrix,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )
