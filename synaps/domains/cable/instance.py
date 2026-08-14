"""Synthetic cable instances: length-based SKUs, reel pre-split, drum aux."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.domains.cable.adapter import (
    STAGES,
    CableSku,
    duration_minutes_from_length,
    setup_transition,
    split_length_into_reels,
    state_code,
)
from synaps.domains.cable.campaign import apply_campaign_windows
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

_DEFAULT_SKUS: tuple[CableSku, ...] = (
    CableSku("Cu", "PVC", "BK", 16),
    CableSku("Cu", "PVC", "RD", 16),
    CableSku("Cu", "PVC", "BK", 35),
    CableSku("Al", "XLPE", "BK", 50),
)


def _states_for(skus: tuple[CableSku, ...]) -> dict[CableSku, State]:
    mapping: dict[CableSku, State] = {}
    for sku in skus:
        mapping[sku] = State(
            id=uuid4(),
            code=state_code(sku),
            label=f"{sku.conductor} {sku.insulation} {sku.color} {sku.section_mm2}mm2",
            domain_attributes={
                "conductor": sku.conductor,
                "insulation": sku.insulation,
                "color": sku.color,
                "section_mm2": sku.section_mm2,
                "domain": "cable",
            },
        )
    return mapping


def _work_centers(
    machines_per_stage: int,
    stages: tuple[tuple[str, str, float], ...],
) -> list[WorkCenter]:
    centers: list[WorkCenter] = []
    for stage_code, group, _speed in stages:
        for index in range(machines_per_stage):
            centers.append(
                WorkCenter(
                    id=uuid4(),
                    code=f"{stage_code}-{index + 1:02d}",
                    capability_group=group,
                    speed_factor=1.0,
                    domain_attributes={"stage": stage_code, "domain": "cable"},
                )
            )
    return centers


def _setup_matrix(
    states: dict[CableSku, State],
    work_centers: list[WorkCenter],
) -> list[SetupEntry]:
    entries: list[SetupEntry] = []
    skus = list(states)
    for work_center in work_centers:
        for from_sku in skus:
            for to_sku in skus:
                minutes, loss, energy = setup_transition(from_sku, to_sku)
                if minutes <= 0:
                    continue
                entries.append(
                    SetupEntry(
                        id=uuid4(),
                        work_center_id=work_center.id,
                        from_state_id=states[from_sku].id,
                        to_state_id=states[to_sku].id,
                        setup_minutes=minutes,
                        material_loss=loss,
                        energy_kwh=energy,
                    )
                )
    return entries


def _append_reel_chain(
    *,
    sku: CableSku,
    length_m: float,
    reel_id: str,
    parent_ref: str,
    due: datetime,
    release: datetime | None,
    priority: int,
    state: State,
    centers_by_group: dict[str, list[WorkCenter]],
    drum: AuxiliaryResource,
    stages: tuple[tuple[str, str, float], ...],
    orders: list[Order],
    operations: list[Operation],
    aux_requirements: list[OperationAuxRequirement],
) -> None:
    order = Order(
        id=uuid4(),
        external_ref=reel_id,
        release_date=release,
        due_date=due,
        priority=priority,
        quantity=length_m,
        unit="m",
        domain_attributes={
            "length_m": length_m,
            "reel_id": reel_id,
            "parent_order_ref": parent_ref,
            "sku": state_code(sku),
            "domain": "cable",
        },
    )
    orders.append(order)
    predecessor_id = None
    for seq, (stage_code, group, speed) in enumerate(stages, start=1):
        eligible = [center.id for center in centers_by_group[group]]
        operation = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=seq,
            state_id=state.id,
            base_duration_min=duration_minutes_from_length(length_m, speed),
            eligible_wc_ids=eligible,
            predecessor_op_id=predecessor_id,
            domain_attributes={
                "stage": stage_code,
                "reel_id": reel_id,
                "length_m": length_m,
                "line_speed_m_per_min": speed,
            },
        )
        operations.append(operation)
        aux_requirements.append(
            OperationAuxRequirement(
                operation_id=operation.id,
                aux_resource_id=drum.id,
                quantity_needed=1,
            )
        )
        predecessor_id = operation.id


def _parent_jobs(
    rng: random.Random,
    *,
    n_orders: int,
    skus: tuple[CableSku, ...],
    horizon_start: datetime,
    horizon_hours: int,
    length_range_m: tuple[float, float],
    rush_fraction: float,
    scatter_releases: bool,
    shuffle_skus: bool,
) -> list[tuple[CableSku, float, datetime | None, datetime, int, str]]:
    """Sales orders: SKU, length, release, due, priority, parent_ref."""

    jobs: list[tuple[CableSku, float, datetime | None, datetime, int, str]] = []
    last_release_hour = max(1, horizon_hours - 120)
    horizon_end = horizon_start + timedelta(hours=horizon_hours)
    for parent_index in range(n_orders):
        sku = rng.choice(skus) if shuffle_skus else skus[parent_index % len(skus)]
        rush = rng.random() < rush_fraction
        release = (
            horizon_start + timedelta(hours=rng.randint(0, last_release_hour))
            if scatter_releases
            else None
        )
        anchor = release or horizon_start
        slack = rng.randint(24, 48) if rush else rng.randint(72, min(168, max(72, horizon_hours)))
        due = min(anchor + timedelta(hours=slack), horizon_end)
        priority = rng.randint(850, 980) if rush else rng.randint(250, 700)
        jobs.append(
            (
                sku,
                round(rng.uniform(*length_range_m), 1),
                release,
                due,
                priority,
                f"ORD-{parent_index + 1:04d}",
            )
        )
    return jobs


def generate_cable_instance(
    *,
    n_orders: int = 4,
    machines_per_stage: int = 2,
    reel_capacity_m: float = 1000.0,
    drum_pool_size: int | None = None,
    length_range_m: tuple[float, float] = (400.0, 2200.0),
    horizon_hours: int = 168,
    campaign_slot_hours: int = 8,
    seed: int = 1,
    skus: tuple[CableSku, ...] | None = None,
    stages: tuple[tuple[str, str, float], ...] | None = None,
    rush_fraction: float = 0.0,
    scatter_releases: bool = False,
    shuffle_skus: bool = False,
) -> ScheduleProblem:
    """Make-to-order cable instance. Child orders are pre-split reels, not lots."""

    rng = random.Random(seed)
    chosen_skus = skus or _DEFAULT_SKUS
    chosen_stages = stages or STAGES
    horizon_start = datetime(2026, 8, 1, tzinfo=UTC)
    horizon_end = horizon_start + timedelta(hours=horizon_hours)
    states = _states_for(chosen_skus)
    work_centers = _work_centers(machines_per_stage, chosen_stages)
    by_group: dict[str, list[WorkCenter]] = {}
    for center in work_centers:
        by_group.setdefault(center.capability_group, []).append(center)
    drum = AuxiliaryResource(
        id=uuid4(),
        code="drum_std",
        resource_type="drum",
        pool_size=max(8, drum_pool_size or machines_per_stage * len(chosen_stages) * 2),
        domain_attributes={"domain": "cable", "hold_semantics": "processing_only"},
    )
    orders: list[Order] = []
    operations: list[Operation] = []
    aux_requirements: list[OperationAuxRequirement] = []
    for sku, length_m, release, due, priority, parent_ref in _parent_jobs(
        rng,
        n_orders=n_orders,
        skus=chosen_skus,
        horizon_start=horizon_start,
        horizon_hours=horizon_hours,
        length_range_m=length_range_m,
        rush_fraction=rush_fraction,
        scatter_releases=scatter_releases,
        shuffle_skus=shuffle_skus,
    ):
        pieces = split_length_into_reels(length_m, reel_capacity_m)
        for reel_index, piece in enumerate(pieces, start=1):
            _append_reel_chain(
                sku=sku,
                length_m=piece,
                reel_id=f"{parent_ref}-R{reel_index}",
                parent_ref=parent_ref,
                due=due,
                release=release,
                priority=priority,
                state=states[sku],
                centers_by_group=by_group,
                drum=drum,
                stages=chosen_stages,
                orders=orders,
                operations=operations,
                aux_requirements=aux_requirements,
            )
    problem = ScheduleProblem(
        states=list(states.values()),
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=_setup_matrix(states, work_centers),
        auxiliary_resources=[drum],
        aux_requirements=aux_requirements,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )
    return apply_campaign_windows(problem, slot_hours=campaign_slot_hours)
