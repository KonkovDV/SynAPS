"""Quick manual verification for Task 12.1: initial_operator_weights kwarg."""
from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from synaps.model import (
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.alns_solver import AlnsSolver, DESTROY_OPERATORS

HORIZON_START = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)
HORIZON_END = datetime(2026, 4, 3, 20, 0, tzinfo=UTC)


def _make_small_problem(seed: int = 42) -> ScheduleProblem:
    rng = random.Random(seed)
    states = [State(id=uuid4(), code=f"S{i}", label=f"State {i}") for i in range(3)]
    state_ids = [s.id for s in states]
    work_centers = [
        WorkCenter(id=uuid4(), code=f"M{i}", capability_group="grp", speed_factor=1.0)
        for i in range(3)
    ]
    wc_ids = [wc.id for wc in work_centers]
    setup_entries: list[SetupEntry] = []
    for wc in work_centers:
        for i, s_from in enumerate(states):
            for j, s_to in enumerate(states):
                if i != j and rng.random() < 0.7:
                    setup_entries.append(
                        SetupEntry(
                            work_center_id=wc.id,
                            from_state_id=s_from.id,
                            to_state_id=s_to.id,
                            setup_minutes=rng.randint(5, 25),
                        )
                    )
    orders: list[Order] = []
    operations: list[Operation] = []
    for i in range(5):
        order_id = uuid4()
        orders.append(
            Order(id=order_id, external_ref=f"ORD-{i:04d}",
                  due_date=HORIZON_START + timedelta(hours=8 + i * 4), priority=500)
        )
        prev_op_id = None
        for j in range(3):
            op_id = uuid4()
            eligible = rng.sample(wc_ids, rng.randint(2, 3))
            operations.append(
                Operation(
                    id=op_id, order_id=order_id, seq_in_order=j,
                    state_id=rng.choice(state_ids), base_duration_min=rng.randint(15, 60),
                    eligible_wc_ids=eligible, predecessor_op_id=prev_op_id,
                )
            )
            prev_op_id = op_id
    return ScheduleProblem(
        states=states, orders=orders, operations=operations,
        work_centers=work_centers, setup_matrix=setup_entries,
        planning_horizon_start=HORIZON_START, planning_horizon_end=HORIZON_END,
    )


def test_dict_initial_weights_boosted():
    """Pass initial_operator_weights={"critical_path": 0.5} and verify metadata."""
    problem = _make_small_problem()
    solver = AlnsSolver()
    result = solver.solve(
        problem,
        max_iterations=10,
        time_limit_s=30,
        destroy_fraction=0.2,
        min_destroy=2,
        max_destroy=5,
        repair_time_limit_s=5,
        initial_operator_weights={"critical_path": 0.5},
    )
    md = result.metadata
    # Check new metadata fields
    assert "alns_operator_names" in md
    assert "alns_initial_operator_weights" in md
    names = md["alns_operator_names"]
    initial_w = md["alns_initial_operator_weights"]
    print(f"Operator names: {names}")
    print(f"Initial weights: {initial_w}")
    # critical_path should be boosted above uniform (1/7 ≈ 0.143)
    assert initial_w["critical_path"] > 1.0 / len(DESTROY_OPERATORS)
    # All weights should sum to ~1.0 (allowing for round(w, 6) rounding)
    assert abs(sum(initial_w.values()) - 1.0) < 1e-4
    print("✓ Dict-based initial weights work correctly")


def test_list_initial_weights():
    """Pass initial_operator_weights as a list of correct length."""
    problem = _make_small_problem()
    solver = AlnsSolver()
    n = len(DESTROY_OPERATORS)
    weights = [0.3] + [0.7 / (n - 1)] * (n - 1)
    result = solver.solve(
        problem,
        max_iterations=10,
        time_limit_s=30,
        destroy_fraction=0.2,
        min_destroy=2,
        max_destroy=5,
        repair_time_limit_s=5,
        initial_operator_weights=weights,
    )
    md = result.metadata
    initial_w = md["alns_initial_operator_weights"]
    print(f"List-based initial weights: {initial_w}")
    assert abs(sum(initial_w.values()) - 1.0) < 1e-4
    print("✓ List-based initial weights work correctly")


def test_list_length_mismatch():
    """Pass initial_operator_weights with wrong length — should fall back to uniform."""
    problem = _make_small_problem()
    solver = AlnsSolver()
    result = solver.solve(
        problem,
        max_iterations=10,
        time_limit_s=30,
        destroy_fraction=0.2,
        min_destroy=2,
        max_destroy=5,
        repair_time_limit_s=5,
        initial_operator_weights=[0.5, 0.5],  # wrong length
    )
    md = result.metadata
    initial_w = md["alns_initial_operator_weights"]
    n = len(DESTROY_OPERATORS)
    expected_uniform = round(1.0 / n, 6)
    for name, w in initial_w.items():
        assert w == expected_uniform, f"Expected uniform {expected_uniform}, got {w} for {name}"
    print(f"Mismatch fallback weights: {initial_w}")
    print("✓ List-length mismatch falls back to uniform correctly")


def test_none_initial_weights():
    """Pass initial_operator_weights=None — should produce uniform."""
    problem = _make_small_problem()
    solver = AlnsSolver()
    result = solver.solve(
        problem,
        max_iterations=10,
        time_limit_s=30,
        destroy_fraction=0.2,
        min_destroy=2,
        max_destroy=5,
        repair_time_limit_s=5,
        initial_operator_weights=None,
    )
    md = result.metadata
    initial_w = md["alns_initial_operator_weights"]
    n = len(DESTROY_OPERATORS)
    expected_uniform = round(1.0 / n, 6)
    for name, w in initial_w.items():
        assert w == expected_uniform, f"Expected uniform {expected_uniform}, got {w} for {name}"
    print(f"None (default) weights: {initial_w}")
    print("✓ None produces uniform weights correctly")


if __name__ == "__main__":
    test_dict_initial_weights_boosted()
    test_list_initial_weights()
    test_list_length_mismatch()
    test_none_initial_weights()
    print("\n✓ All Task 12.1 verifications passed!")
