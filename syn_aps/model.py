"""Domain model — Pydantic v2 dataclasses for the scheduling problem."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class State(BaseModel):
    """Product / process state used in SDST transitions."""

    id: UUID = Field(default_factory=uuid4)
    code: str
    label: str = ""
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class Order(BaseModel):
    """Production or service order to schedule."""

    id: UUID = Field(default_factory=uuid4)
    external_ref: str
    due_date: datetime
    priority: int = 500
    quantity: float = 1.0
    unit: str = "pcs"
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class WorkCenter(BaseModel):
    """Machine, station, or processing unit."""

    id: UUID = Field(default_factory=uuid4)
    code: str
    capability_group: str
    speed_factor: float = 1.0
    max_parallel: int = 1
    domain_attributes: dict[str, Any] = Field(default_factory=dict)


class Operation(BaseModel):
    """Single processing step within an order."""

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


class SolverStatus(str, Enum):
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
