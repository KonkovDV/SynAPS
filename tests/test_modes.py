"""Execution modes: exactly one alternative, with its own duration and demand."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from synaps.model import (
    AuxiliaryResource,
    ModeRequirement,
    Operation,
    OperationAuxRequirement,
    OperationMode,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.portfolio import solve_schedule
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch

START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
END = START + timedelta(hours=8)


def _problem(modes: list[OperationMode], *, aux: bool, setup: bool = False) -> ScheduleProblem:
    state = State(id=uuid4(), code="work")
    machine = WorkCenter(id=uuid4(), code="lane", capability_group="okr")
    resource = AuxiliaryResource(id=uuid4(), code="crew", resource_type="person", pool_size=1)
    order = Order(id=uuid4(), external_ref="job", due_date=END)
    operation = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=999,
        eligible_wc_ids=[machine.id],
        modes=modes,
    )
    setup_matrix = []
    if setup:
        setup_matrix.append(
            SetupEntry(
                work_center_id=machine.id,
                from_state_id=state.id,
                to_state_id=state.id,
                setup_minutes=5,
            )
        )
    requirements = []
    if aux:
        requirements.append(
            OperationAuxRequirement(
                operation_id=operation.id, aux_resource_id=resource.id, quantity_needed=1
            )
        )
    return ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[operation],
        work_centers=[machine],
        auxiliary_resources=[resource],
        aux_requirements=requirements,
        setup_matrix=setup_matrix,
        planning_horizon_start=START,
        planning_horizon_end=END,
    )


def _modes(resource_id) -> list[OperationMode]:
    return [
        OperationMode(
            code="long",
            duration_min=90,
            requirements=[ModeRequirement(aux_resource_id=resource_id)],
        ),
        OperationMode(
            code="short",
            duration_min=30,
            requirements=[ModeRequirement(aux_resource_id=resource_id)],
        ),
    ]


def test_cpsat_picks_the_shorter_mode() -> None:
    resource_id = uuid4()
    # Build with the resource id that the problem will own.
    state = State(id=uuid4(), code="work")
    machine = WorkCenter(id=uuid4(), code="lane", capability_group="okr")
    resource = AuxiliaryResource(id=resource_id, code="crew", resource_type="person", pool_size=1)
    order = Order(id=uuid4(), external_ref="job", due_date=END)
    operation = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=999,
        eligible_wc_ids=[machine.id],
        modes=_modes(resource.id),
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[operation],
        work_centers=[machine],
        auxiliary_resources=[resource],
        setup_matrix=[],
        planning_horizon_start=START,
        planning_horizon_end=END,
    )
    result = CpSatSolver().solve(problem, time_limit_s=10, num_workers=1)
    assert result.status.value == "optimal"
    assert len(result.assignments) == 1
    assignment = result.assignments[0]
    assert assignment.mode_code == "short"
    span = (assignment.end_time - assignment.start_time).total_seconds() / 60
    assert span == 30
    assert FeasibilityChecker().check(problem, result.assignments) == []


def test_the_mode_that_avoids_a_busy_resource_wins() -> None:
    state = State(id=uuid4(), code="work")
    lane_a = WorkCenter(id=uuid4(), code="a", capability_group="okr")
    lane_b = WorkCenter(id=uuid4(), code="b", capability_group="okr")
    crew = AuxiliaryResource(id=uuid4(), code="crew", resource_type="person", pool_size=1)
    order_a = Order(id=uuid4(), external_ref="hold", due_date=END)
    order_b = Order(id=uuid4(), external_ref="choice", due_date=END)
    holder = Operation(
        id=uuid4(),
        order_id=order_a.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=40,
        eligible_wc_ids=[lane_a.id],
    )
    chooser = Operation(
        id=uuid4(),
        order_id=order_b.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=999,
        eligible_wc_ids=[lane_b.id],
        modes=[
            OperationMode(
                code="fast",
                duration_min=10,
                requirements=[ModeRequirement(aux_resource_id=crew.id, quantity_needed=1)],
            ),
            OperationMode(code="alone", duration_min=30, requirements=[]),
        ],
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order_a, order_b],
        operations=[holder, chooser],
        work_centers=[lane_a, lane_b],
        auxiliary_resources=[crew],
        aux_requirements=[
            OperationAuxRequirement(
                operation_id=holder.id, aux_resource_id=crew.id, quantity_needed=1
            )
        ],
        setup_matrix=[],
        planning_horizon_start=START,
        planning_horizon_end=END,
    )
    result = CpSatSolver().solve(problem, time_limit_s=10, num_workers=1)
    assert result.status.value == "optimal"
    chosen = next(item for item in result.assignments if item.operation_id == chooser.id)
    # fast needs the crew the holder already uses, so it starts at minute 40 (makespan 50).
    # alone ignores the crew and finishes at minute 30 (makespan 40).
    assert chosen.mode_code == "alone"
    assert FeasibilityChecker().check(problem, result.assignments) == []


def test_greedy_refuses_modes_instead_of_ignoring_them() -> None:
    state = State(id=uuid4(), code="work")
    machine = WorkCenter(id=uuid4(), code="lane", capability_group="okr")
    crew = AuxiliaryResource(id=uuid4(), code="crew", resource_type="person", pool_size=1)
    order = Order(id=uuid4(), external_ref="job", due_date=END)
    operation = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=10,
        eligible_wc_ids=[machine.id],
        modes=_modes(crew.id),
    )
    problem = ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[operation],
        work_centers=[machine],
        auxiliary_resources=[crew],
        setup_matrix=[],
        planning_horizon_start=START,
        planning_horizon_end=END,
    )
    refused = GreedyDispatch().solve(problem, time_limit_s=5)
    assert refused.status.value == "error"
    assert refused.assignments == []
    assert refused.metadata["unsupported_model"] == "modes"
    via_portfolio = solve_schedule(problem, solver_config="GREED")
    assert via_portfolio.status.value == "error"
    assert via_portfolio.metadata["unsupported_model"] == "modes"


def test_a_missing_mode_and_a_mixed_demand_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate mode"):
        _problem(
            [
                OperationMode(code="a", duration_min=10),
                OperationMode(code="a", duration_min=20),
            ],
            aux=False,
        )
    with pytest.raises(ValueError, match="setup_matrix"):
        state = State(id=uuid4(), code="work")
        machine = WorkCenter(id=uuid4(), code="lane", capability_group="okr")
        order = Order(id=uuid4(), external_ref="job", due_date=END)
        ScheduleProblem(
            states=[state],
            orders=[order],
            operations=[
                Operation(
                    id=uuid4(),
                    order_id=order.id,
                    seq_in_order=0,
                    state_id=state.id,
                    base_duration_min=10,
                    eligible_wc_ids=[machine.id],
                    modes=[OperationMode(code="only", duration_min=10)],
                )
            ],
            work_centers=[machine],
            setup_matrix=[
                SetupEntry(
                    work_center_id=machine.id,
                    from_state_id=state.id,
                    to_state_id=state.id,
                    setup_minutes=5,
                )
            ],
            planning_horizon_start=START,
            planning_horizon_end=END,
        )
    crew = AuxiliaryResource(id=uuid4(), code="crew", resource_type="person", pool_size=1)
    state = State(id=uuid4(), code="work")
    machine = WorkCenter(id=uuid4(), code="lane", capability_group="okr")
    order = Order(id=uuid4(), external_ref="job", due_date=END)
    operation = Operation(
        id=uuid4(),
        order_id=order.id,
        seq_in_order=0,
        state_id=state.id,
        base_duration_min=10,
        eligible_wc_ids=[machine.id],
        modes=_modes(crew.id),
    )
    with pytest.raises(ValueError, match="aux_requirements"):
        ScheduleProblem(
            states=[state],
            orders=[order],
            operations=[operation],
            work_centers=[machine],
            auxiliary_resources=[crew],
            aux_requirements=[
                OperationAuxRequirement(
                    operation_id=operation.id, aux_resource_id=crew.id, quantity_needed=1
                )
            ],
            setup_matrix=[],
            planning_horizon_start=START,
            planning_horizon_end=END,
        )
