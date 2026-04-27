"""Stable JSON contracts for TypeScript-to-Python SynAPS integration."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from typing import Final, Literal
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel, ConfigDict, Field, model_validator

from synaps.model import (  # noqa: TC001
    Assignment,
    MAX_SCHEDULE_OPERATIONS,
    ScheduleProblem,
    ScheduleResult,
    normalize_schedule_problem_data,
)
from synaps.portfolio import repair_schedule, solve_schedule
from synaps.solvers.router import SolveRegime, SolverRoutingContext

CONTRACT_VERSION: Final = "2026-04-03"

# Supported contract versions for backward compatibility.
SUPPORTED_CONTRACT_VERSIONS: Final[tuple[str, ...]] = ("2026-04-03",)


class ContractVersionError(ValueError):
    """Raised when a request uses an unsupported contract version."""


def check_contract_version(version: str) -> None:
    """Validate that *version* is supported by this runtime.

    Raises :class:`ContractVersionError` if the version is not in the
    supported set.
    """
    if version not in SUPPORTED_CONTRACT_VERSIONS:
        raise ContractVersionError(
            f"Contract version {version!r} is not supported. "
            f"Supported versions: {', '.join(SUPPORTED_CONTRACT_VERSIONS)}"
        )


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


class ProblemInstanceSlice(BaseModel):
    """Order-complete slice descriptor applied before ScheduleProblem validation."""

    order_ids: list[UUID] | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_SCHEDULE_OPERATIONS,
    )
    order_offset: int = Field(default=0, ge=0)
    max_operations: int | None = Field(
        default=None,
        ge=1,
        le=MAX_SCHEDULE_OPERATIONS,
    )

    @model_validator(mode="after")
    def validate_selection_mode(self) -> ProblemInstanceSlice:
        if self.order_ids is not None:
            if self.order_offset != 0 or self.max_operations is not None:
                raise ValueError(
                    "problem_slice supports either explicit order_ids or "
                    "order_offset/max_operations, not both"
                )
            return self

        if self.max_operations is None:
            raise ValueError("problem_slice requires order_ids or max_operations")

        return self


class SolveRequest(BaseModel):
    """Canonical request contract for routed or explicit solve execution."""

    model_config = ConfigDict(
        json_schema_extra={
            "oneOf": [
                {"required": ["problem"]},
                {"required": ["problem_instance_ref"]},
            ]
        }
    )

    contract_version: Literal["2026-04-03"] = CONTRACT_VERSION
    request_id: str | None = None
    problem: ScheduleProblem | None = None
    problem_instance_ref: str | None = Field(default=None, min_length=1)
    problem_slice: ProblemInstanceSlice | None = None
    context: RoutingContextContract = Field(default_factory=RoutingContextContract)
    solver_config: str | None = None
    verify_feasibility: bool = True
    solve_options: SolveOptions = Field(default_factory=SolveOptions)

    @model_validator(mode="after")
    def validate_problem_source(self) -> SolveRequest:
        has_inline_problem = self.problem is not None
        has_instance_ref = self.problem_instance_ref is not None
        if has_inline_problem == has_instance_ref:
            raise ValueError(
                "SolveRequest requires exactly one of problem or problem_instance_ref"
            )
        if self.problem_slice is not None and not has_instance_ref:
            raise ValueError("problem_slice requires problem_instance_ref")
        return self


class RepairRequest(BaseModel):
    """Canonical request contract for bounded repair execution."""

    contract_version: Literal["2026-04-03"] = CONTRACT_VERSION
    request_id: str | None = None
    problem: ScheduleProblem
    base_assignments: list[Assignment] = Field(max_length=MAX_SCHEDULE_OPERATIONS)
    disrupted_op_ids: list[UUID] = Field(max_length=MAX_SCHEDULE_OPERATIONS)
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
    if "problem" not in payload or payload["problem"] is None:
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


def _require_object_list(
    problem_payload: dict[str, object],
    key: str,
) -> list[dict[str, object]]:
    value = problem_payload.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"Problem payload field {key!r} must be a list")
    if any(not isinstance(item, dict) for item in value):
        raise ValueError(f"Problem payload field {key!r} must contain JSON objects")
    return value


def _resolve_problem_instance_path(
    problem_instance_ref: str,
    *,
    instance_dir: Path | None,
) -> Path:
    base_dir = (instance_dir or Path.cwd()).resolve()
    relative_path = Path(problem_instance_ref)
    if relative_path.is_absolute():
        raise ValueError("problem_instance_ref must be relative to the configured instance_dir")

    resolved_path = (base_dir / relative_path).resolve()
    try:
        resolved_path.relative_to(base_dir)
    except ValueError as exc:
        raise ValueError("problem_instance_ref must stay within instance_dir") from exc

    if resolved_path.suffix.lower() != ".json":
        raise ValueError("problem_instance_ref must target a JSON file")
    if not resolved_path.is_file():
        raise FileNotFoundError(f"Problem instance file not found: {resolved_path}")
    return resolved_path


def _select_order_ids_for_slice(
    *,
    problem_payload: dict[str, object],
    slice_spec: ProblemInstanceSlice,
) -> list[str]:
    orders = _require_object_list(problem_payload, "orders")
    operations = _require_object_list(problem_payload, "operations")

    operations_by_order: dict[str, list[dict[str, object]]] = defaultdict(list)
    for operation in operations:
        order_id = operation.get("order_id")
        if isinstance(order_id, str):
            operations_by_order[order_id].append(operation)

    if slice_spec.order_ids is not None:
        requested_order_ids = {str(order_id) for order_id in slice_spec.order_ids}
        selected_order_ids = [
            str(order["id"])
            for order in orders
            if isinstance(order.get("id"), str) and str(order["id"]) in requested_order_ids
        ]
        missing_order_ids = requested_order_ids.difference(selected_order_ids)
        if missing_order_ids:
            missing_summary = ", ".join(sorted(missing_order_ids))
            raise ValueError(
                f"problem_slice.order_ids contains unknown orders: {missing_summary}"
            )
        return selected_order_ids

    selected_order_ids: list[str] = []
    selected_operation_count = 0
    for order in orders[slice_spec.order_offset :]:
        order_id = order.get("id")
        if not isinstance(order_id, str):
            continue
        order_operation_count = len(operations_by_order.get(order_id, []))
        if (
            slice_spec.max_operations is not None
            and selected_operation_count + order_operation_count > slice_spec.max_operations
        ):
            if not selected_order_ids:
                raise ValueError(
                    "problem_slice.max_operations is smaller than the first selected order; "
                    "use explicit order_ids or increase max_operations"
                )
            break
        selected_order_ids.append(order_id)
        selected_operation_count += order_operation_count

    if not selected_order_ids:
        raise ValueError("problem_slice did not select any orders")

    return selected_order_ids


def _slice_problem_payload(
    problem_payload: object,
    slice_spec: ProblemInstanceSlice | None,
) -> object:
    if slice_spec is None:
        return problem_payload
    if not isinstance(problem_payload, dict):
        raise ValueError("Problem payload must be a JSON object")

    orders = _require_object_list(problem_payload, "orders")
    operations = _require_object_list(problem_payload, "operations")
    states = _require_object_list(problem_payload, "states")
    work_centers = _require_object_list(problem_payload, "work_centers")
    setup_matrix = _require_object_list(problem_payload, "setup_matrix")
    auxiliary_resources = _require_object_list(problem_payload, "auxiliary_resources")
    aux_requirements = _require_object_list(problem_payload, "aux_requirements")

    selected_order_ids = set(
        _select_order_ids_for_slice(problem_payload=problem_payload, slice_spec=slice_spec)
    )
    selected_orders = [
        order
        for order in orders
        if isinstance(order.get("id"), str) and str(order["id"]) in selected_order_ids
    ]
    selected_operations = [
        operation
        for operation in operations
        if isinstance(operation.get("order_id"), str)
        and str(operation["order_id"]) in selected_order_ids
    ]
    if not selected_operations:
        raise ValueError("problem_slice did not select any operations")

    selected_operation_ids = {
        str(operation["id"])
        for operation in selected_operations
        if isinstance(operation.get("id"), str)
    }
    selected_state_ids = {
        str(operation["state_id"])
        for operation in selected_operations
        if isinstance(operation.get("state_id"), str)
    }
    selected_work_center_ids = {
        str(work_center_id)
        for operation in selected_operations
        for work_center_id in operation.get("eligible_wc_ids", [])
        if isinstance(work_center_id, str)
    }
    selected_aux_requirements = [
        requirement
        for requirement in aux_requirements
        if isinstance(requirement.get("operation_id"), str)
        and str(requirement["operation_id"]) in selected_operation_ids
    ]
    selected_aux_resource_ids = {
        str(requirement["aux_resource_id"])
        for requirement in selected_aux_requirements
        if isinstance(requirement.get("aux_resource_id"), str)
    }

    sliced_payload = dict(problem_payload)
    sliced_payload["orders"] = selected_orders
    sliced_payload["operations"] = selected_operations
    sliced_payload["states"] = [
        state
        for state in states
        if isinstance(state.get("id"), str) and str(state["id"]) in selected_state_ids
    ]
    sliced_payload["work_centers"] = [
        work_center
        for work_center in work_centers
        if isinstance(work_center.get("id"), str)
        and str(work_center["id"]) in selected_work_center_ids
    ]
    sliced_payload["setup_matrix"] = [
        setup
        for setup in setup_matrix
        if isinstance(setup.get("work_center_id"), str)
        and isinstance(setup.get("from_state_id"), str)
        and isinstance(setup.get("to_state_id"), str)
        and str(setup["work_center_id"]) in selected_work_center_ids
        and str(setup["from_state_id"]) in selected_state_ids
        and str(setup["to_state_id"]) in selected_state_ids
    ]
    sliced_payload["aux_requirements"] = selected_aux_requirements
    sliced_payload["auxiliary_resources"] = [
        resource
        for resource in auxiliary_resources
        if isinstance(resource.get("id"), str)
        and str(resource["id"]) in selected_aux_resource_ids
    ]
    return sliced_payload


def resolve_solve_request_problem(
    request: SolveRequest,
    *,
    instance_dir: Path | None = None,
) -> ScheduleProblem:
    """Resolve inline or file-backed problem input into a validated ScheduleProblem."""

    if request.problem is not None:
        return request.problem

    assert request.problem_instance_ref is not None
    problem_path = _resolve_problem_instance_path(
        request.problem_instance_ref,
        instance_dir=instance_dir,
    )
    raw_problem = json.loads(problem_path.read_text(encoding="utf-8"))
    sliced_problem = _slice_problem_payload(raw_problem, request.problem_slice)
    return ScheduleProblem.model_validate(normalize_schedule_problem_data(sliced_problem))


def execute_solve_request(
    request: SolveRequest,
    *,
    instance_dir: Path | None = None,
    resolved_problem: ScheduleProblem | None = None,
) -> SolveResponse:
    """Execute a stable solve contract against the SynAPS portfolio API."""

    check_contract_version(request.contract_version)
    problem = resolved_problem or resolve_solve_request_problem(
        request,
        instance_dir=instance_dir,
    )
    result = solve_schedule(
        problem,
        context=request.context.to_runtime(),
        solver_config=request.solver_config,
        solve_kwargs=request.solve_options.to_runtime_kwargs(),
        verify_feasibility=request.verify_feasibility,
    )
    return SolveResponse(request_id=request.request_id, result=result)


def execute_repair_request(request: RepairRequest) -> RepairResponse:
    """Execute a stable repair contract against the SynAPS portfolio API."""

    check_contract_version(request.contract_version)
    result = repair_schedule(
        request.problem,
        base_assignments=request.base_assignments,
        disrupted_op_ids=request.disrupted_op_ids,
        radius=request.radius,
        regime=request.regime,
        verify_feasibility=request.verify_feasibility,
    )
    return RepairResponse(request_id=request.request_id, result=result)


def _strip_schema_defaults(schema: object) -> None:
    if isinstance(schema, dict):
        schema.pop("default", None)
        for value in schema.values():
            _strip_schema_defaults(value)
        return
    if isinstance(schema, list):
        for item in schema:
            _strip_schema_defaults(item)


def build_contract_schema_bundle() -> dict[str, dict[str, object]]:
    """Return all public JSON Schema documents for control-plane integration."""

    solve_request_schema = SolveRequest.model_json_schema()
    solve_request_defs = solve_request_schema.get("$defs")
    if isinstance(solve_request_defs, dict):
        problem_slice_schema = solve_request_defs.get("ProblemInstanceSlice")
        _strip_schema_defaults(problem_slice_schema)

    solve_request_properties = solve_request_schema.get("properties")
    if isinstance(solve_request_properties, dict):
        _strip_schema_defaults(solve_request_properties.get("problem_instance_ref"))
        _strip_schema_defaults(solve_request_properties.get("problem_slice"))

    return {
        "solve-request.schema.json": solve_request_schema,
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
    "ContractVersionError",
    "SUPPORTED_CONTRACT_VERSIONS",
    "check_contract_version",
    "parse_repair_request_json",
    "parse_solve_request_json",
    "RepairRequest",
    "RepairResponse",
    "RoutingContextContract",
    "SolveOptions",
    "ProblemInstanceSlice",
    "SolveRequest",
    "SolveResponse",
    "build_contract_schema_bundle",
    "execute_repair_request",
    "execute_solve_request",
    "resolve_solve_request_problem",
    "write_contract_schemas",
]
