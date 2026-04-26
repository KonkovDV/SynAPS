"""Large-scale FJSP-SDST instance generator for benchmarking.

Generates realistic manufacturing scheduling problems at scales from
1 000 to 100 000+ operations with configurable structure.

Based on Brandimarte (1993) generation methodology extended with SDST,
auxiliary resources, and configurable machine flexibility.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)


def generate_large_instance(
    *,
    n_operations: int = 50_000,
    n_machines: int = 100,
    n_states: int = 20,
    ops_per_order: int = 5,
    machine_flexibility: float = 0.1,
    setup_density: float = 0.7,
    setup_range: tuple[int, int] = (5, 60),
    material_loss_range: tuple[float, float] = (0.0, 5.0),
    n_aux_resources: int = 10,
    aux_pool_size: int = 3,
    aux_requirement_prob: float = 0.1,
    duration_range: tuple[int, int] = (10, 120),
    priority_range: tuple[int, int] = (200, 900),
    horizon_hours: int = 720,
    seed: int = 42,
) -> ScheduleProblem:
    """Generate a large-scale FJSP-SDST instance.

    Args:
        n_operations: Total number of operations.
        n_machines: Number of work centers.
        n_states: Number of distinct product states.
        ops_per_order: Average operations per order.
        machine_flexibility: Fraction of machines eligible per operation (0.05–1.0).
        setup_density: Probability that a state transition has a non-zero setup.
        setup_range: Min/max setup time in minutes.
        material_loss_range: Min/max material loss per transition.
        n_aux_resources: Number of shared auxiliary resources.
        aux_pool_size: Pool size for each auxiliary resource.
        aux_requirement_prob: Probability that an operation needs an aux resource.
        duration_range: Min/max processing time per operation.
        priority_range: Min/max order priority.
        horizon_hours: Planning horizon length in hours.
        seed: Random seed for reproducibility.

    Returns:
        A ScheduleProblem with the specified characteristics.
    """
    rng = random.Random(seed)
    horizon_start = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
    horizon_end = horizon_start + timedelta(hours=horizon_hours)

    # States
    states = [
        State(id=uuid4(), code=f"S-{i:03d}", label=f"State {i}")
        for i in range(n_states)
    ]

    # Work centers
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i:04d}",
            capability_group=f"group-{i % 5}",
            speed_factor=round(rng.uniform(0.8, 1.3), 2),
        )
        for i in range(n_machines)
    ]

    # SDST matrix
    setup_matrix: list[SetupEntry] = []
    for wc in work_centers:
        for i, from_state in enumerate(states):
            for j, to_state in enumerate(states):
                if i == j:
                    continue  # Self-transition = 0 setup
                if rng.random() > setup_density:
                    continue
                setup_matrix.append(
                    SetupEntry(
                        id=uuid4(),
                        work_center_id=wc.id,
                        from_state_id=from_state.id,
                        to_state_id=to_state.id,
                        setup_minutes=rng.randint(*setup_range),
                        material_loss=round(rng.uniform(*material_loss_range), 2),
                    )
                )

    # Auxiliary resources
    auxiliary_resources = [
        AuxiliaryResource(
            id=uuid4(),
            code=f"AUX-{i:03d}",
            resource_type="tool",
            pool_size=aux_pool_size,
        )
        for i in range(n_aux_resources)
    ]

    # Orders and operations
    n_orders = max(1, n_operations // ops_per_order)
    orders: list[Order] = []
    operations: list[Operation] = []
    aux_requirements: list[OperationAuxRequirement] = []
    ops_created = 0

    # Pre-compute eligible machines per operation as indices
    n_eligible = max(1, int(n_machines * machine_flexibility))
    work_center_ids = [work_center.id for work_center in work_centers]
    max_speed_factor = max(
        max(work_center.speed_factor, 1e-6)
        for work_center in work_centers
    )

    for order_idx in range(n_orders):
        if ops_created >= n_operations:
            break

        order_id = uuid4()
        # Sample releases with an early-skewed long tail.
        # Pure uniform sampling over a wide span starves short first-window
        # smoke studies and hides admission-pressure behavior.
        release_span_hours = horizon_hours * 0.55
        release_offset_hours = release_span_hours * (rng.random() ** 3.0)
        release_datetime = horizon_start + timedelta(hours=release_offset_hours)

        # Determine ops for this order
        this_order_ops = min(
            rng.randint(max(1, ops_per_order - 2), ops_per_order + 2),
            n_operations - ops_created,
        )

        prev_op_id = None
        order_min_duration_minutes = 0.0
        for seq in range(this_order_ops):
            op_id = uuid4()
            state = rng.choice(states)
            eligible = rng.sample(
                work_center_ids,
                min(n_eligible, n_machines),
            )
            base_duration_min = rng.randint(*duration_range)
            order_min_duration_minutes += base_duration_min / max_speed_factor

            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=seq,
                    state_id=state.id,
                    base_duration_min=base_duration_min,
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id
            ops_created += 1

            # Auxiliary requirements
            if auxiliary_resources and rng.random() < aux_requirement_prob:
                aux = rng.choice(auxiliary_resources)
                aux_requirements.append(
                    OperationAuxRequirement(
                        operation_id=op_id,
                        aux_resource_id=aux.id,
                        quantity_needed=1,
                    )
                )

        min_process_hours = max(order_min_duration_minutes / 60.0, 0.25)
        due_flow_factor = rng.uniform(1.25, 2.10)
        due_slack_hours = rng.uniform(2.0, 36.0)
        due_offset_hours = (
            release_offset_hours
            + (min_process_hours * due_flow_factor)
            + due_slack_hours
        )
        due_offset_hours = min(due_offset_hours, horizon_hours)

        due_datetime = horizon_start + timedelta(hours=due_offset_hours)
        if due_datetime <= release_datetime:
            due_datetime = min(
                horizon_end,
                release_datetime + timedelta(hours=max(min_process_hours, 0.5)),
            )

        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{order_idx:06d}",
                due_date=due_datetime,
                priority=rng.randint(*priority_range),
                domain_attributes={
                    "release_offset_min": round(release_offset_hours * 60.0, 2),
                },
            )
        )

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        auxiliary_resources=auxiliary_resources,
        aux_requirements=aux_requirements,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )
