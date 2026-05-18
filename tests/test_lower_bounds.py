"""Unit tests for synaps/solvers/lower_bounds.py.

R15: Dedicated coverage for compute_relaxed_makespan_lower_bound so that
regressions in the bound logic are caught before they silently widen LB gaps
in the solver portfolio.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, given, settings

from synaps.model import (
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    SetupEntry,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.lower_bounds import MakespanLowerBound, compute_relaxed_makespan_lower_bound

_HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
_HORIZON_END = datetime(2026, 4, 2, 8, 0, tzinfo=UTC)  # 24-hour window


def _make_problem(
    n_ops: int,
    n_machines: int,
    base_duration_min: int = 30,
    max_parallel: int = 1,
    speed_factor: float = 1.0,
    add_predecessor_chain: bool = False,
    pin_to_single_machine: bool = False,
) -> ScheduleProblem:
    """Minimal helper вЂ” builds a fully flexible problem (all ops eligible everywhere).

    When ``add_predecessor_chain=False``, each operation is placed in its own
    order so that the ScheduleProblem model_validator does NOT auto-assign
    predecessor_op_id (which it does for same-order ops sorted by seq_in_order).
    When ``add_predecessor_chain=True``, all ops share one order and the chain
    is built via explicit predecessor_op_id assignments.
    """
    state = State(id=uuid4(), code="S0", label="State 0")
    wcs = [
        WorkCenter(
            id=uuid4(),
            code=f"WC{i}",
            capability_group="machining",
            max_parallel=max_parallel,
            speed_factor=speed_factor,
        )
        for i in range(n_machines)
    ]
    wc_ids = [wc.id for wc in wcs]

    ops: list[Operation] = []
    orders: list[Order] = []

    if add_predecessor_chain:
        # All ops share one order; predecessor chain built explicitly
        order = Order(id=uuid4(), external_ref="ORD-CHAIN", due_date=_HORIZON_END)
        orders.append(order)
        prev_id = None
        for k in range(n_ops):
            op = Operation(
                id=uuid4(),
                order_id=order.id,
                seq_in_order=k,
                state_id=state.id,
                base_duration_min=base_duration_min,
                eligible_wc_ids=[wc_ids[0]] if pin_to_single_machine else wc_ids,
                predecessor_op_id=prev_id,
            )
            ops.append(op)
            prev_id = op.id
    else:
        # Each op in its own order → no model_validator auto-chaining
        for k in range(n_ops):
            order = Order(id=uuid4(), external_ref=f"ORD-{k:04d}", due_date=_HORIZON_END)
            orders.append(order)
            op = Operation(
                id=uuid4(),
                order_id=order.id,
                seq_in_order=0,
                state_id=state.id,
                base_duration_min=base_duration_min,
                eligible_wc_ids=[wc_ids[0]] if pin_to_single_machine else wc_ids,
            )
            ops.append(op)

    return ScheduleProblem(
        states=[state],
        orders=orders,
        operations=ops,
        work_centers=wcs,
        setup_matrix=[],
        planning_horizon_start=_HORIZON_START,
        planning_horizon_end=_HORIZON_END,
    )


class TestComputeRelaxedMakespanLowerBound:
    def test_empty_problem_returns_zero_bound(self) -> None:
        state = State(id=uuid4(), code="S0", label="State 0")
        wc = WorkCenter(id=uuid4(), code="WC0", capability_group="machining")
        problem = ScheduleProblem(
            states=[state],
            orders=[],
            operations=[],
            work_centers=[wc],
            setup_matrix=[],
            planning_horizon_start=_HORIZON_START,
            planning_horizon_end=_HORIZON_END,
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert isinstance(result, MakespanLowerBound)
        assert result.value == 0.0
        assert result.precedence_critical_path_lb == 0.0
        assert result.average_capacity_lb == 0.0
        assert result.exclusive_machine_lb == 0.0
        assert result.max_operation_lb == 0.0
        assert result.auxiliary_resource_lb == 0.0

    def test_single_op_single_machine_equals_duration(self) -> None:
        problem = _make_problem(n_ops=1, n_machines=1, base_duration_min=45)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.value == pytest.approx(45.0)
        assert result.max_operation_lb == pytest.approx(45.0)

    def test_parallel_ops_single_machine_uses_average_capacity_lb(self) -> None:
        # 4 ops x 30 min each on 1 machine -> average_capacity_lb = 120 min
        problem = _make_problem(n_ops=4, n_machines=1, base_duration_min=30)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.average_capacity_lb == pytest.approx(120.0)
        assert result.value == pytest.approx(120.0)

    def test_parallel_ops_multiple_machines_divides_load(self) -> None:
        # 4 ops x 30 min on 4 machines -> average_capacity_lb = 30 min
        problem = _make_problem(n_ops=4, n_machines=4, base_duration_min=30)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.average_capacity_lb == pytest.approx(30.0)
        assert result.value == pytest.approx(30.0)

    def test_precedence_chain_dominates_average_capacity(self) -> None:
        # 4 ops in a chain x 30 min each -> critical-path = 120 min even with 4 machines
        problem = _make_problem(
            n_ops=4, n_machines=4, base_duration_min=30, add_predecessor_chain=True
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.precedence_critical_path_lb == pytest.approx(120.0)
        assert result.value == pytest.approx(120.0)

    def test_max_parallel_machines_reduces_average_capacity_lb(self) -> None:
        # 1 machine, max_parallel=2 -> total capacity = 2 -> lb = (4x30)/2 = 60
        problem = _make_problem(n_ops=4, n_machines=1, base_duration_min=30, max_parallel=2)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.average_capacity_lb == pytest.approx(60.0)

    def test_speed_factor_reduces_durations(self) -> None:
        # speed_factor=2.0 -> effective duration = 30/2 = 15 min per op
        # 4 ops, 1 machine, 1 parallel -> lb = 4 x 15 = 60
        problem = _make_problem(n_ops=4, n_machines=1, base_duration_min=30, speed_factor=2.0)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.average_capacity_lb == pytest.approx(60.0)

    def test_exclusive_machine_load_when_all_ops_pinned(self) -> None:
        # All ops pinned to the only machine -> exclusive_machine_lb = sum of durations
        problem = _make_problem(
            n_ops=3, n_machines=1, base_duration_min=20, pin_to_single_machine=True
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        # exclusive_machine_lb = 3x20 / max_parallel=1 = 60
        assert result.exclusive_machine_lb == pytest.approx(60.0)
        assert result.value == pytest.approx(60.0)

    def test_lower_bound_is_max_of_components(self) -> None:
        # Components: max_op=30, avg=30 (4 ops, 4 machines), critical_path depends on chain
        problem = _make_problem(n_ops=4, n_machines=4, base_duration_min=30)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.value == max(
            result.precedence_critical_path_lb,
            result.average_capacity_lb,
            result.exclusive_machine_lb,
            result.max_operation_lb,
            result.auxiliary_resource_lb,
        )

    def test_as_metadata_returns_all_components_as_floats(self) -> None:
        problem = _make_problem(n_ops=2, n_machines=2, base_duration_min=10)
        result = compute_relaxed_makespan_lower_bound(problem)
        meta = result.as_metadata()
        expected_keys = {
            "precedence_critical_path_lb",
            "average_capacity_lb",
            "exclusive_machine_lb",
            "max_operation_lb",
            "auxiliary_resource_lb",
        }
        assert set(meta.keys()) == expected_keys
        for v in meta.values():
            assert isinstance(v, float)

    def test_lower_bound_never_exceeds_serial_schedule(self) -> None:
        # The LB should never exceed the total processing time (no-overlap serial schedule)
        problem = _make_problem(n_ops=6, n_machines=2, base_duration_min=15)
        result = compute_relaxed_makespan_lower_bound(problem)
        serial_ub = 6 * 15.0
        assert result.value <= serial_ub

    def test_no_operations_non_zero_machines_returns_zero(self) -> None:
        state = State(id=uuid4(), code="S0", label="State 0")
        wcs = [WorkCenter(id=uuid4(), code="WC0", capability_group="machining")]
        problem = ScheduleProblem(
            states=[state],
            orders=[],
            operations=[],
            work_centers=wcs,
            setup_matrix=[],
            planning_horizon_start=_HORIZON_START,
            planning_horizon_end=_HORIZON_END,
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.value == 0.0


def _make_problem_with_aux_resource(
    *,
    n_ops: int,
    n_machines: int,
    base_duration_min: int,
    aux_pool_size: int,
    quantity_needed: int = 1,
    ops_consuming_aux: int | None = None,
) -> ScheduleProblem:
    """Build a fully flexible problem where the first ``ops_consuming_aux``
    operations all hold one shared auxiliary resource of pool ``aux_pool_size``.
    ``ops_consuming_aux`` defaults to ``n_ops`` (every operation consumes the
    pool), which is the standard setup for the ARC lower-bound regression.
    """

    if ops_consuming_aux is None:
        ops_consuming_aux = n_ops

    state = State(id=uuid4(), code="S0", label="State 0")
    wcs = [
        WorkCenter(
            id=uuid4(),
            code=f"WC{i}",
            capability_group="machining",
        )
        for i in range(n_machines)
    ]
    wc_ids = [wc.id for wc in wcs]

    orders: list[Order] = []
    ops: list[Operation] = []
    for k in range(n_ops):
        order = Order(id=uuid4(), external_ref=f"ORD-{k:04d}", due_date=_HORIZON_END)
        orders.append(order)
        ops.append(
            Operation(
                id=uuid4(),
                order_id=order.id,
                seq_in_order=0,
                state_id=state.id,
                base_duration_min=base_duration_min,
                eligible_wc_ids=wc_ids,
            )
        )

    fixture = AuxiliaryResource(
        id=uuid4(),
        code="FIX-1",
        resource_type="fixture",
        pool_size=aux_pool_size,
    )
    requirements = [
        OperationAuxRequirement(
            operation_id=ops[i].id,
            aux_resource_id=fixture.id,
            quantity_needed=quantity_needed,
        )
        for i in range(ops_consuming_aux)
    ]

    return ScheduleProblem(
        states=[state],
        orders=orders,
        operations=ops,
        work_centers=wcs,
        setup_matrix=[],
        auxiliary_resources=[fixture],
        aux_requirements=requirements,
        planning_horizon_start=_HORIZON_START,
        planning_horizon_end=_HORIZON_END,
    )


class TestAuxiliaryResourceLowerBound:
    """R4 (2026-05-03): cumulative-load lower bound on shared aux resources.

    Each `OperationAuxRequirement` contributes `quantity_needed` units of
    auxiliary capacity for the operation's duration; the makespan must be at
    least the per-resource cumulative resource-time divided by the pool size.
    """

    def test_arc_bound_is_zero_when_no_auxiliary_resources(self) -> None:
        # Pure machine problem: no aux resources, no aux requirements.
        problem = _make_problem(n_ops=4, n_machines=4, base_duration_min=30)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.auxiliary_resource_lb == pytest.approx(0.0)

    def test_arc_bound_serializes_three_ops_through_pool_size_one(self) -> None:
        # 3 ops x 60 min on 4 machines (avg_capacity = 45) but all three
        # require a single-unit fixture pool -> ARC LB = 3 * 60 / 1 = 180,
        # dominating every machine-only component and lifting the global bound.
        problem = _make_problem_with_aux_resource(
            n_ops=3, n_machines=4, base_duration_min=60, aux_pool_size=1
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.auxiliary_resource_lb == pytest.approx(180.0)
        assert result.value == pytest.approx(180.0)
        # Sanity: the machine-only bounds are strictly weaker on this fixture.
        assert result.average_capacity_lb < result.auxiliary_resource_lb
        assert result.max_operation_lb < result.auxiliary_resource_lb

    def test_arc_bound_divides_by_pool_size(self) -> None:
        # 4 ops x 30 min sharing a pool of size 2 -> ARC LB = 4 * 30 / 2 = 60.
        problem = _make_problem_with_aux_resource(
            n_ops=4, n_machines=4, base_duration_min=30, aux_pool_size=2
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.auxiliary_resource_lb == pytest.approx(60.0)

    def test_arc_bound_scales_with_quantity_needed(self) -> None:
        # 2 ops x 30 min, pool=4, each op requires 2 units -> ARC LB = 2*30*2/4 = 30.
        problem = _make_problem_with_aux_resource(
            n_ops=2,
            n_machines=4,
            base_duration_min=30,
            aux_pool_size=4,
            quantity_needed=2,
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.auxiliary_resource_lb == pytest.approx(30.0)

    def test_arc_bound_ignores_operations_without_requirements(self) -> None:
        # 4 ops, only 2 of them consume the pool -> ARC LB = 2 * 30 / 1 = 60,
        # not 4 * 30 / 1 = 120.
        problem = _make_problem_with_aux_resource(
            n_ops=4,
            n_machines=4,
            base_duration_min=30,
            aux_pool_size=1,
            ops_consuming_aux=2,
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.auxiliary_resource_lb == pytest.approx(60.0)

    def test_arc_lb_uses_min_proc_time_over_eligible_machines(self) -> None:
        """R4 audit: ARC LB must use min(duration) over eligible machines.

        If an operation is flexible (eligible on multiple machines with
        different speed_factors), the lower bound should use the fastest
        possible duration, not any fixed machine's duration. Otherwise the
        bound would be artificially inflated (invalid LB).
        """
        from synaps.model import AuxiliaryResource, OperationAuxRequirement

        # Two machines: WC0 (speed=1.0, duration=60), WC1 (speed=2.0, duration=30)
        state = State(id=uuid4(), code="S0", label="State 0")
        wc0 = WorkCenter(id=uuid4(), code="WC0", capability_group="machining", speed_factor=1.0)
        wc1 = WorkCenter(id=uuid4(), code="WC1", capability_group="machining", speed_factor=2.0)

        # One operation, eligible on BOTH machines
        order = Order(id=uuid4(), external_ref="ORD-0", due_date=_HORIZON_END)
        op = Operation(
            id=uuid4(),
            order_id=order.id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=60,  # 60 min on WC1, 30 min effective on WC2
            eligible_wc_ids=[wc0.id, wc1.id],  # flexible
        )

        fixture = AuxiliaryResource(id=uuid4(), code="FIX-1", resource_type="fixture", pool_size=1)
        requirement = OperationAuxRequirement(
            operation_id=op.id,
            aux_resource_id=fixture.id,
            quantity_needed=1,
        )

        problem = ScheduleProblem(
            states=[state],
            orders=[order],
            operations=[op],
            work_centers=[wc0, wc1],
            setup_matrix=[],
            auxiliary_resources=[fixture],
            aux_requirements=[requirement],
            planning_horizon_start=_HORIZON_START,
            planning_horizon_end=_HORIZON_END,
        )

        result = compute_relaxed_makespan_lower_bound(problem)
        # ARC LB = (min_duration * qty) / pool_size = 30 * 1 / 1 = 30
        # If the implementation incorrectly used a fixed machine (WC1), it would be 60.
        assert result.auxiliary_resource_lb == pytest.approx(30.0)
        assert result.max_operation_lb == pytest.approx(30.0)  # same logic


# ─────────────────────────────────────────────────────────────────────────────
# Task 6.4 — Regression tests: lower bound clamped to non-negative values
# ─────────────────────────────────────────────────────────────────────────────


class TestNonNegativeClampingRegression:
    """Regression tests ensuring the lower-bound module never surfaces negative
    values, even under degenerate or conflicting inputs.

    Validates: Requirement 6.4 — lower bound is clamped to non-negative values
    when components conflict.
    """

    def test_normal_case_all_components_non_negative(self) -> None:
        """Minimal problem produces non-negative `value` and all 5 `as_metadata()`
        components non-negative."""
        problem = _make_problem(n_ops=3, n_machines=2, base_duration_min=20)
        result = compute_relaxed_makespan_lower_bound(problem)

        assert result.value >= 0.0
        meta = result.as_metadata()
        for key, val in meta.items():
            assert val >= 0.0, f"Component {key} is negative: {val}"

    def test_empty_operations_returns_zero_with_all_components_zero(self) -> None:
        """problem.operations == [] returns value=0.0 with all components at 0.0."""
        state = State(id=uuid4(), code="S0", label="State 0")
        wcs = [
            WorkCenter(id=uuid4(), code="WC0", capability_group="machining"),
            WorkCenter(id=uuid4(), code="WC1", capability_group="machining"),
        ]
        problem = ScheduleProblem(
            states=[state],
            orders=[],
            operations=[],
            work_centers=wcs,
            setup_matrix=[],
            planning_horizon_start=_HORIZON_START,
            planning_horizon_end=_HORIZON_END,
        )
        result = compute_relaxed_makespan_lower_bound(problem)

        assert result.value == 0.0
        meta = result.as_metadata()
        for key, val in meta.items():
            assert val == 0.0, f"Component {key} should be 0.0 for empty ops, got {val}"

    def test_no_machines_returns_zero_with_all_components_zero(self) -> None:
        """problem.work_centers == [] returns value=0.0 with all components at 0.0."""
        state = State(id=uuid4(), code="S0", label="State 0")
        problem = ScheduleProblem(
            states=[state],
            orders=[],
            operations=[],
            work_centers=[],
            setup_matrix=[],
            planning_horizon_start=_HORIZON_START,
            planning_horizon_end=_HORIZON_END,
        )
        result = compute_relaxed_makespan_lower_bound(problem)

        assert result.value == 0.0
        meta = result.as_metadata()
        for key, val in meta.items():
            assert val == 0.0, f"Component {key} should be 0.0 for no machines, got {val}"

    def test_clamp_non_negative_negative_input_returns_zero_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """_clamp_non_negative: negative -> 0.0 plus WARNING log containing
        `lower_bound_component_clamped`; positive pass-through."""
        from synaps.solvers.lower_bounds import _clamp_non_negative

        # Negative input: should clamp to 0.0 and emit WARNING
        with caplog.at_level(logging.WARNING, logger="synaps.solvers.lower_bounds"):
            clamped = _clamp_non_negative(
                "test_component",
                -42.5,
                operation_count=10,
                machine_count=3,
            )
        assert clamped == 0.0
        assert any("lower_bound_component_clamped" in record.message for record in caplog.records)

        # Positive input: pass-through unchanged, no additional warning
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="synaps.solvers.lower_bounds"):
            passed = _clamp_non_negative(
                "test_component",
                99.9,
                operation_count=10,
                machine_count=3,
            )
        assert passed == 99.9
        assert not any(
            "lower_bound_component_clamped" in record.message for record in caplog.records
        )

    def test_as_metadata_surfaces_only_rounded_non_negative_floats(self) -> None:
        """as_metadata surfaces only rounded non-negative floats when constructed
        with clamped values."""
        # Construct a MakespanLowerBound directly with values that are already
        # clamped (as the production code guarantees). Verify as_metadata()
        # returns only non-negative rounded floats.
        lb = MakespanLowerBound(
            value=42.123456789,
            precedence_critical_path_lb=42.123456789,
            average_capacity_lb=0.0,
            exclusive_machine_lb=0.0001,
            max_operation_lb=15.999999,
            auxiliary_resource_lb=0.0,
        )
        meta = lb.as_metadata()

        assert len(meta) == 5
        for key, val in meta.items():
            assert isinstance(val, float), f"{key} is not a float: {type(val)}"
            assert val >= 0.0, f"{key} is negative: {val}"
            # Verify rounding to 4 decimal places
            assert val == round(val, 4), f"{key} not rounded to 4 decimals: {val}"

        # Spot-check specific rounding
        assert meta["precedence_critical_path_lb"] == 42.1235
        assert meta["exclusive_machine_lb"] == 0.0001
        assert meta["max_operation_lb"] == 16.0


# ─────────────────────────────────────────────────────────────────────────────
# Task 6.5 — Property test: lower bound ≤ actual makespan for feasible schedules
# ─────────────────────────────────────────────────────────────────────────────


@st.composite
def _random_schedule_problems(
    draw: st.DrawFn,
    min_ops: int = 10,
    max_ops: int = 100,
    min_machines: int = 2,
    max_machines: int = 10,
) -> ScheduleProblem:
    """Composite Hypothesis strategy generating valid ScheduleProblem instances.

    Builds problems with:
    - n_ops in [min_ops, max_ops]
    - n_machines in [min_machines, max_machines]
    - Random base_duration_min in [1, 120]
    - ~30% chance of each op depending on a prior op (within same order)
    - Sparse random SDST entries
    - Long planning horizon to avoid horizon-bound violations in greedy dispatch
    """
    horizon_start = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
    horizon_end = horizon_start + timedelta(days=30)

    n_states = draw(st.integers(min_value=2, max_value=5))
    n_machines = draw(st.integers(min_value=min_machines, max_value=max_machines))

    states = [State(id=uuid4(), code=f"S-{i}", label=f"State {i}") for i in range(n_states)]
    work_centers = [
        WorkCenter(
            id=uuid4(),
            code=f"WC-{i}",
            capability_group="machining",
            speed_factor=draw(st.floats(min_value=0.8, max_value=2.0)),
        )
        for i in range(n_machines)
    ]

    # Sparse random setup matrix (~50% fill)
    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i == j:
                    continue
                if draw(st.booleans()):
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=draw(st.integers(min_value=1, max_value=30)),
                        )
                    )

    # Build operations grouped into orders with predecessor chains
    target_ops = draw(st.integers(min_value=min_ops, max_value=max_ops))
    orders: list[Order] = []
    operations: list[Operation] = []
    n_ops_built = 0
    order_idx = 0

    while n_ops_built < target_ops:
        order_id = uuid4()
        orders.append(
            Order(
                id=order_id,
                external_ref=f"ORD-{order_idx:04d}",
                due_date=horizon_start
                + timedelta(hours=draw(st.integers(min_value=24, max_value=72))),
                priority=draw(st.integers(min_value=100, max_value=1000)),
            )
        )
        # Chain length: 1-5 ops per order, capped by remaining budget
        chain_len = draw(
            st.integers(min_value=1, max_value=min(5, max(1, target_ops - n_ops_built)))
        )
        prev_op_id = None
        for j in range(chain_len):
            op_id = uuid4()
            n_eligible = draw(st.integers(min_value=1, max_value=n_machines))
            eligible = [wc.id for wc in work_centers[:n_eligible]]
            # ~30% chance of depending on the previous op in the chain
            use_predecessor = (
                prev_op_id is not None and draw(st.floats(min_value=0.0, max_value=1.0)) < 0.3
            )
            operations.append(
                Operation(
                    id=op_id,
                    order_id=order_id,
                    seq_in_order=j,
                    state_id=draw(st.sampled_from(states)).id,
                    base_duration_min=draw(st.integers(min_value=1, max_value=120)),
                    eligible_wc_ids=eligible,
                    predecessor_op_id=prev_op_id if use_predecessor else None,
                )
            )
            prev_op_id = op_id
            n_ops_built += 1
        order_idx += 1

    return ScheduleProblem(
        states=states,
        orders=orders,
        operations=operations,
        work_centers=work_centers,
        setup_matrix=setup_entries,
        planning_horizon_start=horizon_start,
        planning_horizon_end=horizon_end,
    )


class TestLowerBoundProperty:
    """Property test: compute_relaxed_makespan_lower_bound(problem).value ≤ actual_makespan.

    **Validates: Requirements 6.5**

    For any valid ScheduleProblem and any feasible schedule (set of Assignment
    objects), the relaxed lower bound must not exceed the actual makespan.
    This is the fundamental soundness property of any valid lower bound.
    """

    @given(problem=_random_schedule_problems())
    @settings(
        max_examples=50,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    )
    def test_lower_bound_le_actual_makespan(self, problem: ScheduleProblem) -> None:
        """For all feasible greedy-generated schedules, LB ≤ actual makespan."""
        # Generate a feasible schedule via greedy dispatch
        result = GreedyDispatch().solve(problem)

        # Skip problems where greedy fails (rare with our long horizon)
        if result.status != SolverStatus.FEASIBLE:
            return

        assignments = result.assignments
        if not assignments:
            return

        # Compute actual makespan in minutes from the assignments
        earliest_start = min(a.start_time for a in assignments)
        latest_end = max(a.end_time for a in assignments)
        actual_makespan_minutes = (latest_end - earliest_start).total_seconds() / 60.0

        # Compute the relaxed lower bound
        lb = compute_relaxed_makespan_lower_bound(problem)

        # The lower bound must not exceed the actual makespan (with FP tolerance)
        assert lb.value <= actual_makespan_minutes + 1e-6, (
            f"Lower bound ({lb.value:.6f}) exceeds actual makespan "
            f"({actual_makespan_minutes:.6f}) by "
            f"{lb.value - actual_makespan_minutes:.6e} minutes.\n"
            f"Components: precedence_cp={lb.precedence_critical_path_lb:.4f}, "
            f"avg_capacity={lb.average_capacity_lb:.4f}, "
            f"exclusive_machine={lb.exclusive_machine_lb:.4f}, "
            f"max_op={lb.max_operation_lb:.4f}, "
            f"aux_resource={lb.auxiliary_resource_lb:.4f}\n"
            f"n_ops={len(problem.operations)}, "
            f"n_machines={len(problem.work_centers)}"
        )
