"""Stable JSON contracts for TypeScript-to-Python SynAPS integration."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final, Literal
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, Field

from synaps.model import (  # noqa: TC001
    Assignment,
    ScheduleProblem,
    ScheduleResult,
    normalize_schedule_problem_data,
)
from synaps.portfolio import repair_schedule, solve_schedule
from synaps.solvers.router import SolveRegime, SolverRoutingContext

if TYPE_CHECKING:
    from pathlib import Path

CONTRACT_VERSION: Final = "2026-04-03"


class RoutingContextContract(BaseModel):
    """JSON-serializable routing context for external callers."""

    regime: SolveRegime = SolveRegime.NOMINAL
    preferred_max_latency_s: int | None = None
    exact_required: bool = False

    def to_runtime(self) -> SolverRoutingContext:
        return SolverRoutingContext(
            regime=self.regime,
            preferred_max_latency_s=self.preferred_max_latency_s,
            exact_required=self.exact_required,
        )


class SolveOptions(BaseModel):
    """Stable solve-option subset exposed to external runtimes."""

    time_limit_s: int | None = None
    random_seed: int | None = None
    num_workers: int | None = None
    max_iterations: int | None = None
    material_loss_scale: int | None = None
    objective_weights: dict[str, int] | None = None
    epsilon_constraints: dict[str, int] | None = None

    def to_runtime_kwargs(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class SolveRequest(BaseModel):
    """Canonical request contract for routed or explicit solve execution."""

    contract_version: Literal["2026-04-03"] = CONTRACT_VERSION
    request_id: str | None = None
    problem: ScheduleProblem
    context: RoutingContextContract = Field(default_factory=RoutingContextContract)
    solver_config: str | None = None
    verify_feasibility: bool = True
    solve_options: SolveOptions = Field(default_factory=SolveOptions)


class RepairRequest(BaseModel):
    """Canonical request contract for bounded repair execution."""

    contract_version: Literal["2026-04-03"] = CONTRACT_VERSION
    request_id: str | None = None
    problem: ScheduleProblem
    base_assignments: list[Assignment]
    disrupted_op_ids: list[UUID]
    radius: int | None = None
    regime: SolveRegime = SolveRegime.BREAKDOWN
    verify_feasibility: bool = True


class SolveResponse(BaseModel):
    """Canonical response contract for solve execution."""

    contract_version: Literal["2026-04-03"] = CONTRACT_VERSION
    request_id: str | None = None
    result: ScheduleResult


class RepairResponse(BaseModel):
    """Canonical response contract for repair execution."""

    contract_version: Literal["2026-04-03"] = CONTRACT_VERSION
    request_id: str | None = None
    result: ScheduleResult


def _normalize_contract_payload(payload: object) -> object:
    if not isinstance(payload, dict):
        return payload
    if "problem" not in payload:
        return payload

    normalized_problem = normalize_schedule_problem_data(payload["problem"])
    if normalized_problem is payload["problem"]:
        return payload

    normalized = dict(payload)
    normalized["problem"] = normalized_problem
    return normalized


def parse_solve_request_json(payload: str) -> SolveRequest:
    """Parse and normalize a SolveRequest JSON payload."""

    return SolveRequest.model_validate(_normalize_contract_payload(json.loads(payload)))


def parse_repair_request_json(payload: str) -> RepairRequest:
    """Parse and normalize a RepairRequest JSON payload."""

    return RepairRequest.model_validate(_normalize_contract_payload(json.loads(payload)))


def execute_solve_request(request: SolveRequest) -> SolveResponse:
    """Execute a stable solve contract against the SynAPS portfolio API."""

    result = solve_schedule(
        request.problem,
        context=request.context.to_runtime(),
        solver_config=request.solver_config,
        solve_kwargs=request.solve_options.to_runtime_kwargs(),
        verify_feasibility=request.verify_feasibility,
    )
    return SolveResponse(request_id=request.request_id, result=result)


def execute_repair_request(request: RepairRequest) -> RepairResponse:
    """Execute a stable repair contract against the SynAPS portfolio API."""

    result = repair_schedule(
        request.problem,
        base_assignments=request.base_assignments,
        disrupted_op_ids=request.disrupted_op_ids,
        radius=request.radius,
        regime=request.regime,
        verify_feasibility=request.verify_feasibility,
    )
    return RepairResponse(request_id=request.request_id, result=result)


def build_contract_schema_bundle() -> dict[str, dict[str, object]]:
    """Return all public JSON Schema documents for control-plane integration."""

    return {
        "solve-request.schema.json": SolveRequest.model_json_schema(),
        "solve-response.schema.json": SolveResponse.model_json_schema(),
        "repair-request.schema.json": RepairRequest.model_json_schema(),
        "repair-response.schema.json": RepairResponse.model_json_schema(),
    }


def write_contract_schemas(output_dir: Path) -> list[Path]:
    """Write the public contract schemas to *output_dir*."""

    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    for filename, schema in build_contract_schema_bundle().items():
        target = output_dir / filename
        target.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")
        written_paths.append(target)
    return written_paths


__all__ = [
    "CONTRACT_VERSION",
    "parse_repair_request_json",
    "parse_solve_request_json",
    "RepairRequest",
    "RepairResponse",
    "RoutingContextContract",
    "SolveOptions",
    "SolveRequest",
    "SolveResponse",
    "build_contract_schema_bundle",
    "execute_repair_request",
    "execute_solve_request",
    "write_contract_schemas",
]
