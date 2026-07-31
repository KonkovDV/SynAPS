"""P1-4: frozen_assignments must not be silently dropped under lane virtualization.

CP-SAT virtualizes a ``max_parallel > 1`` work center into independent lanes
before solving. Frozen (fixed) assignments are defined on the ORIGINAL work
center, not the virtual lanes, so the prior ``frozen_assignments if not
virtual_to_original else []`` silently DROPPED them -- letting a repair overlap
frozen work with no signal. The solver now fails loudly instead (an explicit
lane mapping is a future enhancement).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    SetupEntry,
    State,
    WorkCenter,
)
from synaps.solvers.cpsat_solver import CpSatSolver

_H0 = datetime(2026, 1, 1, tzinfo=UTC)


def _parallel_problem_with_setup() -> tuple[ScheduleProblem, Operation]:
    """A max_parallel=2 WC with a setup matrix -> triggers lane virtualization."""
    s1, s2 = State(code="s1"), State(code="s2")
    wc = WorkCenter(code="M2", capability_group="G", max_parallel=2)
    o1 = Order(external_ref="O1", due_date=_H0 + timedelta(days=1))
    o2 = Order(external_ref="O2", due_date=_H0 + timedelta(days=1))
    op1 = Operation(order_id=o1.id, seq_in_order=1, state_id=s1.id, base_duration_min=60,
                    eligible_wc_ids=[wc.id])
    op2 = Operation(order_id=o2.id, seq_in_order=1, state_id=s2.id, base_duration_min=60,
                    eligible_wc_ids=[wc.id])
    problem = ScheduleProblem(
        states=[s1, s2], orders=[o1, o2], operations=[op1, op2], work_centers=[wc],
        setup_matrix=[SetupEntry(work_center_id=wc.id, from_state_id=s1.id, to_state_id=s2.id,
                                 setup_minutes=600, material_loss=1.0)],
        planning_horizon_start=_H0, planning_horizon_end=_H0 + timedelta(days=1),
    )
    return problem, op1


def test_frozen_assignments_with_virtualization_raises() -> None:
    problem, op1 = _parallel_problem_with_setup()
    frozen = [Assignment(operation_id=op1.id, work_center_id=problem.work_centers[0].id,
                         start_time=_H0, end_time=_H0 + timedelta(minutes=60))]
    with pytest.raises(ValueError, match="max_parallel"):
        CpSatSolver().solve(
            problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False,
            frozen_assignments=frozen,
        )


def test_frozen_assignments_without_virtualization_still_work() -> None:
    """A single-lane instance with frozen work solves normally (no regression)."""
    st = State(code="s")
    wc = WorkCenter(code="M", capability_group="G")  # max_parallel=1 -> no virtualization
    o1 = Order(external_ref="O1", due_date=_H0 + timedelta(days=1))
    op1 = Operation(order_id=o1.id, seq_in_order=1, state_id=st.id, base_duration_min=60,
                    eligible_wc_ids=[wc.id])
    problem = ScheduleProblem(
        states=[st], orders=[o1], operations=[op1], work_centers=[wc], setup_matrix=[],
        planning_horizon_start=_H0, planning_horizon_end=_H0 + timedelta(days=1),
    )
    frozen = [Assignment(operation_id=op1.id, work_center_id=wc.id,
                         start_time=_H0, end_time=_H0 + timedelta(minutes=60))]
    result = CpSatSolver().solve(
        problem, time_limit_s=5, num_workers=1, auto_greedy_warm_start=False,
        frozen_assignments=frozen,
    )
    assert result.assignments
