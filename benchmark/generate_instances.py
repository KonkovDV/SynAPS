"""Parametric benchmark instance generation for SynAPS.

The generator deliberately targets the current ``ScheduleProblem`` schema rather
than a future richer metadata envelope.  It provides reproducible presets for
academic solver studies and boundary-testing of the deterministic routing
portfolio, especially the LBBD path on large nominal instances.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

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
from synaps.problem_profile import build_problem_profile


@dataclass(frozen=True)
class GenerationSpec:
    """Parameterization for a synthetic ``ScheduleProblem`` instance."""

    n_jobs: int
    n_machines: int
    operations_per_job: tuple[int, int]
    state_count: int
    flexibility: float
    sdst_density: float
    sdst_range: tuple[int, int]
    proc_time_range: tuple[int, int]
    due_date_tightness: float
    aux_resource_probability: float
    aux_resource_types: int = 0
    seed: int = 0
    preset_name: str | None = None

    def __post_init__(self) -> None:
        min_ops, max_ops = self.operations_per_job
        min_setup, max_setup = self.sdst_range
        min_proc, max_proc = self.proc_time_range

        if self.n_jobs <= 0:
            raise ValueError("n_jobs must be positive")
        if self.n_machines <= 0:
            raise ValueError("n_machines must be positive")
        if min_ops <= 0 or max_ops < min_ops:
            raise ValueError("operations_per_job must contain positive ascending bounds")
        if self.state_count < 2:
            raise ValueError("state_count must be at least 2")
        if not 0.0 < self.flexibility <= 1.0:
            raise ValueError("flexibility must be in (0, 1]")
        if not 0.0 <= self.sdst_density <= 1.0:
            raise ValueError("sdst_density must be in [0, 1]")
        if min_setup < 0 or max_setup < min_setup:
            raise ValueError("sdst_range must contain non-negative ascending bounds")
        if min_proc <= 0 or max_proc < min_proc:
            raise ValueError("proc_time_range must contain positive ascending bounds")
        if not 0.0 <= self.due_date_tightness <= 1.0:
            raise ValueError("due_date_tightness must be in [0, 1]")
        if not 0.0 <= self.aux_resource_probability <= 1.0:
            raise ValueError("aux_resource_probability must be in [0, 1]")
        if self.aux_resource_types < 0:
            raise ValueError("aux_resource_types must be non-negative")


_PRESET_SPECS: dict[str, GenerationSpec] = {
    "tiny": GenerationSpec(
        n_jobs=3,
        n_machines=3,
        operations_per_job=(3, 4),
        state_count=3,
        flexibility=0.67,
        sdst_density=0.50,
        sdst_range=(4, 12),
        proc_time_range=(10, 24),
        due_date_tightness=0.60,
        aux_resource_probability=0.0,
        aux_resource_types=0,
        seed=1,
        preset_name="tiny",
    ),
    "small": GenerationSpec(
        n_jobs=10,
        n_machines=5,
        operations_per_job=(3, 5),
        state_count=4,
        flexibility=0.55,
        sdst_density=0.60,
        sdst_range=(6, 18),
        proc_time_range=(12, 30),
        due_date_tightness=0.50,
        aux_resource_probability=0.05,
        aux_resource_types=1,
        seed=1,
        preset_name="small",
    ),
    "medium": GenerationSpec(
        n_jobs=20,
        n_machines=10,
        operations_per_job=(4, 6),
        state_count=6,
        flexibility=0.40,
        sdst_density=0.70,
        sdst_range=(8, 24),
        proc_time_range=(15, 40),
        due_date_tightness=0.45,
        aux_resource_probability=0.20,
        aux_resource_types=3,
        seed=1,
        preset_name="medium",
    ),
    "large": GenerationSpec(
        n_jobs=36,
        n_machines=12,
        operations_per_job=(4, 6),
        state_count=8,
        flexibility=0.35,
        sdst_density=0.75,
        sdst_range=(10, 35),
        proc_time_range=(18, 50),
        due_date_tightness=0.35,
        aux_resource_probability=0.35,
        aux_resource_types=4,
        seed=1,
        preset_name="large",
    ),
    "industrial": GenerationSpec(
        n_jobs=120,
        n_machines=30,
        operations_per_job=(5, 8),
        state_count=10,
        flexibility=0.30,
        sdst_density=0.80,
        sdst_range=(12, 45),
        proc_time_range=(20, 60),
        due_date_tightness=0.30,
        aux_resource_probability=0.40,
        aux_resource_types=6,
        seed=1,
        preset_name="industrial",
    ),
}


def preset_spec(name: str, *, seed: int | None = None) -> GenerationSpec:
    """Return one of the academic benchmark presets."""

    try:
        spec = _PRESET_SPECS[name]
    except KeyError as exc:
        available = ", ".join(sorted(_PRESET_SPECS))
        raise ValueError(f"unknown preset '{name}'; expected one of: {available}") from exc

    if seed is None:
        return spec
    return replace(spec, seed=seed)


def generate_problem(spec: GenerationSpec) -> ScheduleProblem:
    """Generate a deterministic synthetic scheduling instance from ``spec``."""

    rng = random.Random(spec.seed)
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)

    states = [
        State(
            id=_next_uuid(rng),
            code=f"STATE-{index + 1:02d}",
            label=f"State {index + 1}",
        )
        for index in range(spec.state_count)
    ]
    work_centers = [
        WorkCenter(
            id=_next_uuid(rng),
            code=f"WC-{index + 1:02d}",
            capability_group="generic-processing",
            speed_factor=round(0.9 + 0.03 * index, 2),
            max_parallel=2 if spec.n_machines >= 10 and index % 7 == 0 else 1,
        )
        for index in range(spec.n_machines)
    ]

    auxiliary_resources = [
        AuxiliaryResource(
            id=_next_uuid(rng),
            code=f"AUX-{index + 1:02d}",
            resource_type="setup-crew",
            pool_size=1 if index % 2 == 0 else 2,
        )
        for index in range(spec.aux_resource_types)
    ]

    orders: list[Order] = []
    operations: list[Operation] = []
    aux_requirements: list[OperationAuxRequirement] = []
    total_processing_minutes = 0

    for order_index in range(spec.n_jobs):
        order_id = _next_uuid(rng)
        operation_count = rng.randint(*spec.operations_per_job)
        order_operations: list[Operation] = []
        previous_op_id: UUID | None = None
        current_state_index = rng.randrange(len(states))
        order_processing_minutes = 0

        for seq_in_order in range(operation_count):
            if seq_in_order > 0 and rng.random() >= 0.45:
                current_state_index = rng.randrange(len(states))
            duration = rng.randint(*spec.proc_time_range)
            eligible_wc_ids = _pick_eligible_work_centers(rng, work_centers, spec.flexibility)

            operation = Operation(
                id=_next_uuid(rng),
                order_id=order_id,
                seq_in_order=seq_in_order,
                state_id=states[current_state_index].id,
                base_duration_min=duration,
                eligible_wc_ids=eligible_wc_ids,
                predecessor_op_id=previous_op_id,
            )
            order_operations.append(operation)
            previous_op_id = operation.id
            order_processing_minutes += duration

            if auxiliary_resources and rng.random() <= spec.aux_resource_probability:
                resource = auxiliary_resources[rng.randrange(len(auxiliary_resources))]
                aux_requirements.append(
                    OperationAuxRequirement(
                        operation_id=operation.id,
                        aux_resource_id=resource.id,
                        quantity_needed=1,
                    )
                )

        total_processing_minutes += order_processing_minutes
        due_multiplier = 1.1 + spec.due_date_tightness * 1.8
        queue_offset_minutes = (order_index % max(1, spec.n_machines)) * 10
        due_date = horizon_start + timedelta(
            minutes=int(order_processing_minutes * due_multiplier) + queue_offset_minutes,
        )
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{order_index + 1:04d}",
                due_date=due_date,
                priority=300 + (spec.n_jobs - order_index) * 10,
            )
        )
        operations.extend(order_operations)

    if auxiliary_resources and not aux_requirements:
        aux_requirements.append(
            OperationAuxRequirement(
                operation_id=operations[0].id,
                aux_resource_id=auxiliary_resources[0].id,
                quantity_needed=1,
            )
        )

    setup_matrix: list[SetupEntry] = []
    for work_center in work_centers:
        for from_state in states:
            for to_state in states:
                if from_state.id == to_state.id:
                    continue
                if rng.random() > spec.sdst_density:
                    continue
                setup_minutes = rng.randint(*spec.sdst_range)
                material_loss = round(setup_minutes / 100, 3) if rng.random() < 0.55 else 0.0
                energy_kwh = round(setup_minutes / 20, 3) if rng.random() < 0.35 else 0.0
                setup_matrix.append(
                    SetupEntry(
                        id=_next_uuid(rng),
                        work_center_id=work_center.id,
                        from_state_id=from_state.id,
                        to_state_id=to_state.id,
                        setup_minutes=setup_minutes,
                        material_loss=material_loss,
                        energy_kwh=energy_kwh,
                    )
                )

    if not setup_matrix:
        setup_matrix.append(
            SetupEntry(
                id=_next_uuid(rng),
                work_center_id=work_centers[0].id,
                from_state_id=states[0].id,
                to_state_id=states[1].id,
                setup_minutes=spec.sdst_range[0],
                material_loss=round(spec.sdst_range[0] / 100, 3),
                energy_kwh=round(spec.sdst_range[0] / 20, 3),
            )
        )

    planning_horizon_minutes = max(
        int(total_processing_minutes / max(1, spec.n_machines) * 3.0),
        8 * 60,
    )
    planning_horizon_end = horizon_start + timedelta(minutes=planning_horizon_minutes)

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_matrix,
        auxiliary_resources=auxiliary_resources,
        aux_requirements=aux_requirements,
        planning_horizon_start=horizon_start,
        planning_horizon_end=planning_horizon_end,
    )


def write_problem_instance(path: Path, spec: GenerationSpec) -> dict[str, Any]:
    """Generate and write a problem instance to ``path``.

    Returns a compact summary block suitable for CLI output or manifest logging.
    """

    problem = generate_problem(spec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(problem.model_dump(mode="json"), indent=2), encoding="utf-8")
    profile = build_problem_profile(problem).as_dict()
    return {
        "output_path": str(path),
        "preset_name": spec.preset_name,
        "seed": spec.seed,
        "spec": asdict(spec),
        "problem_profile": profile,
    }


def _pick_eligible_work_centers(
    rng: random.Random,
    work_centers: list[WorkCenter],
    flexibility: float,
) -> list[UUID]:
    base_count = max(1, int(round(len(work_centers) * flexibility)))
    jitter = rng.choice([-1, 0, 1]) if len(work_centers) > 2 else 0
    selection_count = min(len(work_centers), max(1, base_count + jitter))
    selected = rng.sample(work_centers, selection_count)
    return [work_center.id for work_center in sorted(selected, key=lambda item: item.code)]


def _next_uuid(rng: random.Random) -> UUID:
    return UUID(int=rng.getrandbits(128), version=4)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate reproducible SynAPS benchmark instances")
    parser.add_argument("output_path", type=Path, help="Path to the JSON file to write")
    parser.add_argument(
        "--preset",
        choices=sorted(_PRESET_SPECS),
        default="medium",
        help="Academic benchmark preset to start from",
    )
    parser.add_argument("--seed", type=int, default=1, help="Deterministic random seed")
    parser.add_argument("--jobs", type=int, help="Override number of jobs")
    parser.add_argument("--machines", type=int, help="Override number of machines")
    parser.add_argument("--operations-min", type=int, help="Override minimum operations per job")
    parser.add_argument("--operations-max", type=int, help="Override maximum operations per job")
    parser.add_argument("--states", type=int, help="Override state count")
    parser.add_argument("--flexibility", type=float, help="Override operation flexibility ratio")
    parser.add_argument("--sdst-density", type=float, help="Override SDST density")
    parser.add_argument("--setup-min", type=int, help="Override minimum setup minutes")
    parser.add_argument("--setup-max", type=int, help="Override maximum setup minutes")
    parser.add_argument("--proc-min", type=int, help="Override minimum processing minutes")
    parser.add_argument("--proc-max", type=int, help="Override maximum processing minutes")
    parser.add_argument("--due-date-tightness", type=float, help="Override due-date tightness")
    parser.add_argument(
        "--aux-resource-probability",
        type=float,
        help="Override probability that an operation needs an auxiliary resource",
    )
    parser.add_argument(
        "--aux-resource-types", type=int, help="Override number of auxiliary resource pools"
    )
    return parser


def _spec_from_args(args: argparse.Namespace) -> GenerationSpec:
    base = preset_spec(args.preset, seed=args.seed)
    operations_per_job = (
        args.operations_min if args.operations_min is not None else base.operations_per_job[0],
        args.operations_max if args.operations_max is not None else base.operations_per_job[1],
    )
    sdst_range = (
        args.setup_min if args.setup_min is not None else base.sdst_range[0],
        args.setup_max if args.setup_max is not None else base.sdst_range[1],
    )
    proc_time_range = (
        args.proc_min if args.proc_min is not None else base.proc_time_range[0],
        args.proc_max if args.proc_max is not None else base.proc_time_range[1],
    )
    return GenerationSpec(
        n_jobs=args.jobs if args.jobs is not None else base.n_jobs,
        n_machines=args.machines if args.machines is not None else base.n_machines,
        operations_per_job=operations_per_job,
        state_count=args.states if args.states is not None else base.state_count,
        flexibility=args.flexibility if args.flexibility is not None else base.flexibility,
        sdst_density=args.sdst_density if args.sdst_density is not None else base.sdst_density,
        sdst_range=sdst_range,
        proc_time_range=proc_time_range,
        due_date_tightness=(
            args.due_date_tightness
            if args.due_date_tightness is not None
            else base.due_date_tightness
        ),
        aux_resource_probability=(
            args.aux_resource_probability
            if args.aux_resource_probability is not None
            else base.aux_resource_probability
        ),
        aux_resource_types=(
            args.aux_resource_types
            if args.aux_resource_types is not None
            else base.aux_resource_types
        ),
        seed=args.seed,
        preset_name=args.preset,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    spec = _spec_from_args(args)
    summary = write_problem_instance(args.output_path, spec)
    json.dump(summary, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


__all__ = [
    "GenerationSpec",
    "generate_problem",
    "main",
    "preset_spec",
    "write_problem_instance",
]


if __name__ == "__main__":
    raise SystemExit(main())
