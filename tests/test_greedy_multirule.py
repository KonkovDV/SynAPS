"""Q5: greedy myopia on a non-metric setup matrix.

A single ATCS priority rule is myopic on non-metric matrices (the audit report:
makespan 120 vs optimum 32). GREEDY is the CP-SAT warm start and the ALNS/RHC
seed, so its myopia propagates. Fix: when the setup matrix is NON-metric (the
N4 flag), GREEDY sweeps several (k1, k2, k3) priority-rule parameterisations and
keeps the best by the canonical objective. Metric matrices keep the exact
single-rule path (no blast radius on the common case).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from synaps.model import Operation, Order, ScheduleProblem, SetupEntry, State, WorkCenter
from synaps.objective import evaluate, objective_sort_key
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.validation import is_setup_matrix_metric

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _non_metric_problem() -> ScheduleProblem:
    """s1->s3 direct (100) >> s1->s2->s3 (1+1): a triangle-inequality violation."""
    s1, s2, s3 = State(code="s1"), State(code="s2"), State(code="s3")
    wc = WorkCenter(code="M", capability_group="G")
    orders, ops = [], []
    for i, st in enumerate((s1, s2, s3, s1, s3)):
        order = Order(external_ref=f"O{i}", due_date=_H0 + timedelta(days=2))
        orders.append(order)
        ops.append(Operation(order_id=order.id, seq_in_order=1, state_id=st.id,
                              base_duration_min=10, eligible_wc_ids=[wc.id]))
    pairs = [(s1, s2, 1), (s2, s3, 1), (s1, s3, 100), (s3, s1, 1), (s2, s1, 1), (s3, s2, 1)]
    setups = [SetupEntry(work_center_id=wc.id, from_state_id=a.id, to_state_id=b.id,
                         setup_minutes=v) for a, b, v in pairs]
    return ScheduleProblem(
        states=[s1, s2, s3], orders=orders, operations=ops, work_centers=[wc],
        setup_matrix=setups, planning_horizon_start=_H0,
        planning_horizon_end=_H0 + timedelta(days=5),
    )


def test_matrix_is_non_metric_precondition() -> None:
    assert is_setup_matrix_metric(_non_metric_problem()) is False


def test_multi_rule_not_worse_than_single_default_on_non_metric() -> None:
    """The swept GREEDY must never be worse than the default single rule."""
    problem = _non_metric_problem()

    default_only = GreedyDispatch()
    single = default_only._solve_core(problem)  # the plain single-rule trajectory
    single_key = objective_sort_key(evaluate(problem, single.assignments))

    swept = GreedyDispatch().solve(problem)
    swept_key = objective_sort_key(evaluate(problem, swept.assignments))

    assert swept_key <= single_key, "the rule sweep must never regress below the default rule"
    assert swept.metadata.get("priority_rule_sweep") is True
    assert swept.metadata.get("priority_rules_evaluated", 0) >= 2


def test_metric_matrix_keeps_single_rule() -> None:
    """A metric instance must NOT trigger the sweep (no blast radius)."""
    st = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_H0 + timedelta(days=1))
    op = Operation(order_id=order.id, seq_in_order=1, state_id=st.id, base_duration_min=10,
                   eligible_wc_ids=[wc.id])
    problem = ScheduleProblem(
        states=[st], orders=[order], operations=[op], work_centers=[wc], setup_matrix=[],
        planning_horizon_start=_H0, planning_horizon_end=_H0 + timedelta(days=1),
    )
    result = GreedyDispatch().solve(problem)
    assert result.metadata.get("priority_rule_sweep") is False
