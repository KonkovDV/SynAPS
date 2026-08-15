"""Synthetic cable instances: length-based SKUs, reel pre-split, drum aux."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.domains.cable.adapter import (
    CABLE_COLORS,
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
    family_dedicated: bool = False,
    pvc_lines_by_group: dict[str, int] | None = None,
    colour_dedicated: bool = False,
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
        eligible = _eligible_ids_for_sku(
            sku,
            group,
            centers_by_group,
            family_dedicated=family_dedicated,
            pvc_line_count=(pvc_lines_by_group or {}).get(group),
            colour_dedicated=colour_dedicated,
        )
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


def _eligible_ids_for_sku(
    sku: CableSku,
    group: str,
    centers_by_group: dict[str, list[WorkCenter]],
    *,
    family_dedicated: bool,
    pvc_line_count: int | None = None,
    colour_dedicated: bool = False,
) -> list:
    centers = centers_by_group[group]
    family_ids = _family_ids_for_sku(
        sku, centers, family_dedicated=family_dedicated, pvc_line_count=pvc_line_count
    )
    if not colour_dedicated:
        return family_ids
    family_centers = [center for center in centers if center.id in set(family_ids)]
    return _colour_ids_for_sku(sku, family_centers or centers)


def _family_ids_for_sku(
    sku: CableSku,
    centers: list[WorkCenter],
    *,
    family_dedicated: bool,
    pvc_line_count: int | None,
) -> list:
    if not family_dedicated or len(centers) < 2:
        return [center.id for center in centers]
    flex_n = 0 if len(centers) < 3 else 1
    flex = centers[-flex_n:] if flex_n else []
    dedicated = centers[:-flex_n] if flex_n else centers
    split = pvc_line_count if pvc_line_count is not None else (len(dedicated) + 1) // 2
    if len(dedicated) >= 2:
        split = min(max(1, split), len(dedicated) - 1)
    else:
        split = len(dedicated)
    chosen = dedicated[:split] if sku.insulation == "PVC" else dedicated[split:]
    if not chosen:
        chosen = dedicated
    return [center.id for center in chosen + flex]


def _colour_ids_for_sku(sku: CableSku, centers: list[WorkCenter]) -> list:
    """One colour per dedicated machine when n≥6; leftover machines are flex."""

    if len(centers) < 6:
        return [center.id for center in centers]
    flex_n = 0 if len(centers) == 6 else (1 if len(centers) == 7 else 2)
    flex = centers[-flex_n:] if flex_n else []
    dedicated = centers[:-flex_n] if flex_n else centers
    try:
        index = CABLE_COLORS.index(sku.color)
    except ValueError:
        index = 0
    chosen = [
        center for i, center in enumerate(dedicated) if i % len(CABLE_COLORS) == index
    ]
    if not chosen:
        chosen = [dedicated[index % len(dedicated)]]
    return [center.id for center in chosen + flex]


def _pvc_lines_by_group(
    centers_by_group: dict[str, list[WorkCenter]],
    skus: tuple[CableSku, ...],
) -> dict[str, int]:
    """Size PVC vs XLPE dedicated lines by catalog share; flex is extra."""

    pvc = sum(1 for sku in skus if sku.insulation == "PVC")
    total = max(len(skus), 1)
    share = pvc / total
    has_pvc = pvc > 0
    has_other = pvc < len(skus)
    splits: dict[str, int] = {}
    for group, centers in centers_by_group.items():
        n_centers = len(centers)
        dedicated_n = n_centers - 1 if n_centers >= 3 else n_centers
        if dedicated_n < 2 or not has_pvc or not has_other:
            splits[group] = dedicated_n if has_pvc else 0
            continue
        splits[group] = min(max(1, round(dedicated_n * share)), dedicated_n - 1)
    return splits


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
    family_dedicated_lines: bool = False,
    colour_phase: bool = False,
    colour_dedicated_lines: bool = False,
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
    _fill_reel_orders(
        rng,
        n_orders=n_orders,
        chosen_skus=chosen_skus,
        chosen_stages=chosen_stages,
        horizon_start=horizon_start,
        horizon_hours=horizon_hours,
        length_range_m=length_range_m,
        rush_fraction=rush_fraction,
        scatter_releases=scatter_releases,
        shuffle_skus=shuffle_skus,
        reel_capacity_m=reel_capacity_m,
        states=states,
        by_group=by_group,
        drum=drum,
        family_dedicated_lines=family_dedicated_lines,
        colour_dedicated_lines=colour_dedicated_lines,
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
    return apply_campaign_windows(
        problem, slot_hours=campaign_slot_hours, colour_phase=colour_phase,
        colour_cycle=6 if colour_phase and machines_per_stage <= 8 else 3,
    )


def _fill_reel_orders(
    rng: random.Random,
    *,
    n_orders: int,
    chosen_skus: tuple[CableSku, ...],
    chosen_stages: tuple[tuple[str, str, float], ...],
    horizon_start: datetime,
    horizon_hours: int,
    length_range_m: tuple[float, float],
    rush_fraction: float,
    scatter_releases: bool,
    shuffle_skus: bool,
    reel_capacity_m: float,
    states: dict[CableSku, State],
    by_group: dict[str, list[WorkCenter]],
    drum: AuxiliaryResource,
    family_dedicated_lines: bool,
    colour_dedicated_lines: bool,
    orders: list[Order],
    operations: list[Operation],
    aux_requirements: list[OperationAuxRequirement],
) -> None:
    pvc_lines = (
        _pvc_lines_by_group(by_group, chosen_skus) if family_dedicated_lines else None
    )
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
                family_dedicated=family_dedicated_lines,
                pvc_lines_by_group=pvc_lines,
                colour_dedicated=colour_dedicated_lines,
            )


def _states_by_sku(problem: ScheduleProblem) -> dict[CableSku, State]:
    mapping: dict[CableSku, State] = {}
    for state in problem.states:
        if state.domain_attributes.get("domain") != "cable":
            continue
        mapping[
            CableSku(
                str(state.domain_attributes.get("conductor", "Cu")),
                str(state.domain_attributes.get("insulation", "PVC")),
                str(state.domain_attributes.get("color", "BK")),
                int(state.domain_attributes.get("section_mm2", 16)),
            )
        ] = state
    return mapping


def _stages_from_problem(problem: ScheduleProblem) -> tuple[tuple[str, str, float], ...]:
    seen_stages: list[tuple[str, str, float]] = []
    seen_codes: set[str] = set()
    fallback = problem.work_centers[0].capability_group if problem.work_centers else ""
    for operation in problem.operations:
        stage = str(operation.domain_attributes.get("stage", ""))
        if not stage or stage in seen_codes:
            continue
        group = next(
            (
                center.capability_group
                for center in problem.work_centers
                if center.id in operation.eligible_wc_ids
            ),
            fallback,
        )
        speed = float(operation.domain_attributes.get("line_speed_m_per_min", 25.0))
        seen_stages.append((stage, group, speed))
        seen_codes.add(stage)
    return tuple(seen_stages)


def add_rush_orders(
    problem: ScheduleProblem,
    *,
    n_orders: int,
    release: datetime,
    due: datetime,
    seed: int,
    priority: int = 980,
    family_dedicated: bool = False,
    colour_dedicated: bool = False,
) -> ScheduleProblem:
    """Append new parent reels onto an existing shop (mid-month rush dump)."""

    rng = random.Random(seed)
    states_by_sku = _states_by_sku(problem)
    stages = _stages_from_problem(problem)
    if not states_by_sku or not stages or not problem.auxiliary_resources:
        return problem
    skus = tuple(states_by_sku)
    by_group: dict[str, list[WorkCenter]] = {}
    for center in problem.work_centers:
        by_group.setdefault(center.capability_group, []).append(center)
    orders = list(problem.orders)
    operations = list(problem.operations)
    aux_requirements = list(problem.aux_requirements)
    pvc_lines = _pvc_lines_by_group(by_group, skus) if family_dedicated else None
    for index in range(n_orders):
        sku = skus[rng.randrange(len(skus))]
        _append_reel_chain(
            sku=sku,
            length_m=round(rng.uniform(500.0, 900.0), 1),
            reel_id=f"RUSH-{seed}-{index + 1}-R1",
            parent_ref=f"RUSH-{seed}-{index + 1}",
            due=due,
            release=release,
            priority=priority,
            state=states_by_sku[sku],
            centers_by_group=by_group,
            drum=problem.auxiliary_resources[0],
            stages=stages,
            orders=orders,
            operations=operations,
            aux_requirements=aux_requirements,
            family_dedicated=family_dedicated,
            pvc_lines_by_group=pvc_lines,
            colour_dedicated=colour_dedicated,
        )
    return problem.model_copy(
        update={
            "orders": orders,
            "operations": operations,
            "aux_requirements": aux_requirements,
        }
    )
