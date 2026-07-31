"""P1-3: a release-aware head-tail (Jackson) makespan lower bound.

The existing precedence_critical_path_lb is the longest chain of min-durations
but ignores release dates and successor tails. The head-tail bound is
    Cmax >= max_op (est(op) + p(op) + tail(op))
where est(op) folds in the order's release_date and the predecessor chain, and
tail(op) is the longest successor chain. This is provably valid and dominates
the plain critical path.

The brief's MANDATORY safety test: the aggregated lower bound must never exceed
the proven optimum on small instances -- strengthening a bound is dangerous
without it (an invalid bound is the S1/S2/S3 defect class).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from synaps.model import Operation, Order, ScheduleProblem, State, WorkCenter
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.lower_bounds import compute_relaxed_makespan_lower_bound

_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"
_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _release_chain_problem() -> ScheduleProblem:
    """Order released at H0+500; a single 60-min op -> Cmax >= 560."""
    st = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O1", due_date=_H0 + timedelta(days=1),
                  release_date=_H0 + timedelta(minutes=500))
    op = Operation(order_id=order.id, seq_in_order=1, state_id=st.id, base_duration_min=60,
                   eligible_wc_ids=[wc.id])
    return ScheduleProblem(
        states=[st], orders=[order], operations=[op], work_centers=[wc], setup_matrix=[],
        planning_horizon_start=_H0, planning_horizon_end=_H0 + timedelta(days=1),
    )


def test_head_tail_reflects_release_date() -> None:
    """An op released at 500 with a 60-min duration cannot finish before 560."""
    lb = compute_relaxed_makespan_lower_bound(_release_chain_problem())
    assert lb.value >= 560.0 - 1e-6, f"release-aware bound too weak: {lb.value}"


def test_head_tail_dominates_plain_critical_path() -> None:
    """Head-tail component must be >= the release-free critical path."""
    lb = compute_relaxed_makespan_lower_bound(_release_chain_problem())
    assert lb.head_tail_lb >= lb.precedence_critical_path_lb - 1e-6


def _load(name: str) -> ScheduleProblem:
    return ScheduleProblem.model_validate(json.loads((_INSTANCES / f"{name}.json").read_text()))


def test_lower_bound_never_exceeds_proven_optimum() -> None:
    """MANDATORY (P1-3): LB <= proven optimum on small instances."""
    for problem in (_load("tiny_3x3"), _release_chain_problem()):
        cpsat = CpSatSolver().solve(
            problem, time_limit_s=30, num_workers=1, auto_greedy_warm_start=False,
            enable_symmetry_breaking=False,
        )
        lb = compute_relaxed_makespan_lower_bound(problem)
        # Compare only when CP-SAT actually proved optimality.
        from synaps.model import SolverStatus

        if cpsat.status is SolverStatus.OPTIMAL:
            assert lb.value <= cpsat.objective.makespan_minutes + 1e-6, (
                f"lower bound {lb.value} exceeds proven optimum "
                f"{cpsat.objective.makespan_minutes}"
            )
