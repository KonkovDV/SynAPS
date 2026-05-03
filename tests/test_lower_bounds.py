"""Unit tests for synaps/solvers/lower_bounds.py.

R15: Dedicated coverage for compute_relaxed_makespan_lower_bound so that
regressions in the bound logic are caught before they silently widen LB gaps
in the solver portfolio.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from synaps.model import Operation, Order, ScheduleProblem, State, WorkCenter
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
        # Each op in its own order в†’ no model_validator auto-chaining
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

    def test_single_op_single_machine_equals_duration(self) -> None:
        problem = _make_problem(n_ops=1, n_machines=1, base_duration_min=45)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.value == pytest.approx(45.0)
        assert result.max_operation_lb == pytest.approx(45.0)

    def test_parallel_ops_single_machine_uses_average_capacity_lb(self) -> None:
        # 4 ops Г— 30 min each on 1 machine в†’ average_capacity_lb = 120 min
        problem = _make_problem(n_ops=4, n_machines=1, base_duration_min=30)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.average_capacity_lb == pytest.approx(120.0)
        assert result.value == pytest.approx(120.0)

    def test_parallel_ops_multiple_machines_divides_load(self) -> None:
        # 4 ops Г— 30 min on 4 machines в†’ average_capacity_lb = 30 min
        problem = _make_problem(n_ops=4, n_machines=4, base_duration_min=30)
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.average_capacity_lb == pytest.approx(30.0)
        assert result.value == pytest.approx(30.0)

    def test_precedence_chain_dominates_average_capacity(self) -> None:
        # 4 ops in a chain Г— 30 min each в†’ critical-path = 120 min even with 4 machines
        problem = _make_problem(
            n_ops=4, n_machines=4, base_duration_min=30, add_predecessor_chain=True
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.precedence_critical_path_lb == pytest.approx(120.0)
        assert result.value == pytest.approx(120.0)

    def test_max_parallel_machines_reduces_average_capacity_lb(self) -> None:
        # 1 machine, max_parallel=2 в†’ total capacity = 2 в†’ lb = (4Г—30)/2 = 60
        problem = _make_problem(
            n_ops=4, n_machines=1, base_duration_min=30, max_parallel=2
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.average_capacity_lb == pytest.approx(60.0)

    def test_speed_factor_reduces_durations(self) -> None:
        # speed_factor=2.0 в†’ effective duration = 30/2 = 15 min per op
        # 4 ops, 1 machine, 1 parallel в†’ lb = 4 Г— 15 = 60
        problem = _make_problem(
            n_ops=4, n_machines=1, base_duration_min=30, speed_factor=2.0
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        assert result.average_capacity_lb == pytest.approx(60.0)

    def test_exclusive_machine_load_when_all_ops_pinned(self) -> None:
        # All ops pinned to the only machine в†’ exclusive_machine_lb = sum of durations
        problem = _make_problem(
            n_ops=3, n_machines=1, base_duration_min=20, pin_to_single_machine=True
        )
        result = compute_relaxed_makespan_lower_bound(problem)
        # exclusive_machine_lb = 3Г—20 / max_parallel=1 = 60
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
