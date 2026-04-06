"""Domain model — Pydantic v2 dataclasses for the scheduling problem."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class State(BaseModel):
    """Product / process state used in SDST transitions."""

    id: UUID = Field(default_factory=uuid4)
    code: str
    label: str = ""
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class Order(BaseModel):
    """Work item or service request to schedule."""

    id: UUID = Field(default_factory=uuid4)
    external_ref: str
    due_date: datetime
    priority: int = 500
    quantity: float = 1.0
    unit: str = "pcs"
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class WorkCenter(BaseModel):
    """Execution resource, station, or processing unit."""

    id: UUID = Field(default_factory=uuid4)
    code: str
    capability_group: str
    speed_factor: float = 1.0
    max_parallel: int = 1
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class Operation(BaseModel):
    """Single processing step within a work item."""

    id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    seq_in_order: int
    state_id: UUID
    base_duration_min: int
    eligible_wc_ids: list[UUID] = Field(default_factory=list)
    predecessor_op_id: UUID | None = None
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class SetupEntry(BaseModel):
    """One cell in the SDST graph: changeover from state A to B on a work center."""

    id: UUID = Field(default_factory=uuid4)
    work_center_id: UUID
    from_state_id: UUID
    to_state_id: UUID
    setup_minutes: int
    material_loss: float = 0.0
    energy_kwh: float = 0.0
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class AuxiliaryResource(BaseModel):
    """Shared resource (tool, fixture, operator, etc.)."""

    id: UUID = Field(default_factory=uuid4)
    code: str
    resource_type: str
    pool_size: int = 1
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class OperationAuxRequirement(BaseModel):
    """Operation → auxiliary resource requirement link."""

    operation_id: UUID
    aux_resource_id: UUID
    quantity_needed: int = 1


# ---------- Scheduling problem & result ----------


class ScheduleProblem(BaseModel):
    """Complete input to any solver."""

    states: list[State]
    orders: list[Order]
    operations: list[Operation]
    work_centers: list[WorkCenter]
    setup_matrix: list[SetupEntry]
    auxiliary_resources: list[AuxiliaryResource] = Field(default_factory=list)
    aux_requirements: list[OperationAuxRequirement] = Field(default_factory=list)
    planning_horizon_start: datetime
    planning_horizon_end: datetime

    @staticmethod
    def _duplicate_keys(values: list[Any]) -> set[Any]:
        seen: set[Any] = set()
        duplicates: set[Any] = set()
        for value in values:
            if value in seen:
                duplicates.add(value)
            else:
                seen.add(value)
        return duplicates

    @model_validator(mode="after")
    def validate_cross_references(self) -> Self:
        issues: list[str] = []

        if self.planning_horizon_end <= self.planning_horizon_start:
            issues.append("planning_horizon_end must be later than planning_horizon_start")

        state_ids = [state.id for state in self.states]
        order_ids = [order.id for order in self.orders]
        operation_ids = [operation.id for operation in self.operations]
        work_center_ids = [work_center.id for work_center in self.work_centers]
        aux_resource_ids = [resource.id for resource in self.auxiliary_resources]

        duplicate_root_sets = {
            "state ids": self._duplicate_keys(state_ids),
            "order ids": self._duplicate_keys(order_ids),
            "operation ids": self._duplicate_keys(operation_ids),
            "work center ids": self._duplicate_keys(work_center_ids),
            "auxiliary resource ids": self._duplicate_keys(aux_resource_ids),
        }
        for label, duplicates in duplicate_root_sets.items():
            if duplicates:
                issues.append(f"duplicate {label}: {sorted(str(value) for value in duplicates)}")

        state_id_set = set(state_ids)
        order_id_set = set(order_ids)
        operation_id_set = set(operation_ids)
        work_center_id_set = set(work_center_ids)
        aux_resource_id_set = set(aux_resource_ids)
        operations_by_id = {operation.id: operation for operation in self.operations}
        operations_by_order: dict[UUID, list[Operation]] = {}
        for operation in self.operations:
            operations_by_order.setdefault(operation.order_id, []).append(operation)

        setup_keys = [
            (entry.work_center_id, entry.from_state_id, entry.to_state_id)
            for entry in self.setup_matrix
        ]
        duplicate_setup_keys = self._duplicate_keys(setup_keys)
        if duplicate_setup_keys:
            issues.append(
                "duplicate setup_matrix key(s): "
                + ", ".join(str(key) for key in sorted(duplicate_setup_keys, key=str))
            )

        requirement_keys = [
            (requirement.operation_id, requirement.aux_resource_id)
            for requirement in self.aux_requirements
        ]
        duplicate_requirement_keys = self._duplicate_keys(requirement_keys)
        if duplicate_requirement_keys:
            issues.append(
                "duplicate aux_requirement key(s): "
                + ", ".join(str(key) for key in sorted(duplicate_requirement_keys, key=str))
            )

        for operation in self.operations:
            if operation.order_id not in order_id_set:
                issues.append(
                    f"operation {operation.id} references unknown order_id {operation.order_id}"
                )
            if operation.state_id not in state_id_set:
                issues.append(
                    f"operation {operation.id} references unknown state_id {operation.state_id}"
                )
            missing_work_centers = [
                work_center_id
                for work_center_id in operation.eligible_wc_ids
                if work_center_id not in work_center_id_set
            ]
            if missing_work_centers:
                issues.append(
                    "operation "
                    f"{operation.id} references unknown eligible_wc_ids "
                    f"{missing_work_centers}"
                )
            if operation.predecessor_op_id == operation.id:
                issues.append(
                    f"operation {operation.id} cannot reference itself as predecessor"
                )
            elif (
                operation.predecessor_op_id is not None
                and operation.predecessor_op_id not in operation_id_set
            ):
                issues.append(
                    "operation "
                    f"{operation.id} references unknown predecessor_op_id "
                    f"{operation.predecessor_op_id}"
                )

        for order_id, order_operations in operations_by_order.items():
            duplicate_seq_in_order = self._duplicate_keys(
                [operation.seq_in_order for operation in order_operations]
            )
            if duplicate_seq_in_order:
                issues.append(
                    f"duplicate seq_in_order values for order {order_id}: "
                    f"{sorted(duplicate_seq_in_order)}"
                )
                continue

            previous_operation: Operation | None = None
            for operation in sorted(order_operations, key=lambda item: item.seq_in_order):
                predecessor = (
                    operations_by_id.get(operation.predecessor_op_id)
                    if operation.predecessor_op_id is not None
                    else None
                )
                if predecessor is not None and predecessor.order_id != order_id:
                    issues.append(
                        "operation "
                        f"{operation.id} cannot reference predecessor {predecessor.id} "
                        "from a different order"
                    )
                    previous_operation = operation
                    continue

                if previous_operation is None:
                    if predecessor is not None:
                        issues.append(
                            "first operation "
                            f"{operation.id} in order {order_id} cannot declare "
                            f"predecessor_op_id {predecessor.id}"
                        )
                    previous_operation = operation
                    continue

                expected_predecessor_id = previous_operation.id
                if operation.predecessor_op_id is None:
                    operation.predecessor_op_id = expected_predecessor_id
                elif operation.predecessor_op_id != expected_predecessor_id:
                    issues.append(
                        "operation "
                        f"{operation.id} must reference predecessor_op_id "
                        f"{expected_predecessor_id} based on seq_in_order within "
                        f"order {order_id}"
                    )

                previous_operation = operation

        for entry in self.setup_matrix:
            if entry.work_center_id not in work_center_id_set:
                issues.append(
                    "setup entry "
                    f"{entry.id} references unknown work_center_id "
                    f"{entry.work_center_id}"
                )
            if entry.from_state_id not in state_id_set:
                issues.append(
                    "setup entry "
                    f"{entry.id} references unknown from_state_id "
                    f"{entry.from_state_id}"
                )
            if entry.to_state_id not in state_id_set:
                issues.append(
                    "setup entry "
                    f"{entry.id} references unknown to_state_id "
                    f"{entry.to_state_id}"
                )

        for requirement in self.aux_requirements:
            if requirement.operation_id not in operation_id_set:
                issues.append(
                    "aux requirement references unknown operation_id "
                    f"{requirement.operation_id}"
                )
            if requirement.aux_resource_id not in aux_resource_id_set:
                issues.append(
                    "aux requirement references unknown aux_resource_id "
                    f"{requirement.aux_resource_id}"
                )

        if issues:
            raise ValueError("; ".join(issues))

        return self


class SolverStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    TIMEOUT = "timeout"
    ERROR = "error"


class Assignment(BaseModel):
    """One operation → machine assignment in the result."""

    operation_id: UUID
    work_center_id: UUID
    start_time: datetime
    end_time: datetime
    setup_minutes: int = 0
    aux_resource_ids: list[UUID] = Field(default_factory=list)


class ObjectiveValues(BaseModel):
    """Multi-objective value vector."""

    makespan_minutes: float = 0.0
    total_setup_minutes: float = 0.0
    total_material_loss: float = 0.0
    total_tardiness_minutes: float = 0.0
    weighted_sum: float = 0.0


class ScheduleResult(BaseModel):
    """Output of any solver."""

    solver_name: str
    status: SolverStatus
    assignments: list[Assignment] = Field(default_factory=list)
    objective: ObjectiveValues = Field(default_factory=ObjectiveValues)
    duration_ms: int = 0
    random_seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
