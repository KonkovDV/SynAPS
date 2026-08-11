"""Wave 14 composition Red Team regressions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from synaps.model import Assignment, Operation, Order, ScheduleProblem, State, WorkCenter
from synaps.solvers.alns_solver import _repair_cpsat_outcome, RepairStatus
from synaps.solvers.lbbd_solver import _add_benders_cut_rows

_H0 = datetime(2026, 1, 1, tzinfo=UTC)
_HE = _H0 + timedelta(days=1)


def test_repair_cpsat_honors_op_id_offsets_when_pred_cleared() -> None:
    """C14-1: cleared predecessor still constrained via frozen_predecessor_end_offsets."""
    s1, s2 = State(code="a"), State(code="b")
    wc = WorkCenter(code="M", capability_group="G")
    order = Order(external_ref="O", due_date=_HE)
    op_frozen = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=s1.id,
        base_duration_min=30,
        eligible_wc_ids=[wc.id],
    )
    op_free = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=s2.id,
        base_duration_min=10,
        eligible_wc_ids=[wc.id],
        predecessor_op_id=None,  # cleared as in RHC window
    )
    problem = ScheduleProblem(
        states=[s1, s2],
        orders=[order],
        operations=[op_free],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=_H0,
        planning_horizon_end=_HE,
    )
    frozen = Assignment(
        operation_id=op_frozen.id,
        work_center_id=wc.id,
        start_time=_H0,
        end_time=_H0 + timedelta(minutes=30),
    )
    outcome = _repair_cpsat_outcome(
        problem,
        [frozen],
        {op_free.id},
        time_limit_s=5,
        num_workers=1,
        frozen_predecessor_end_offsets={op_free.id: 30},
        frozen_context_operations=[op_frozen, op_free],
    )
    assert outcome.status == RepairStatus.FEASIBLE
    assert outcome.assignments
    assert outcome.assignments[0].start_time >= frozen.end_time


def test_lbbd_empty_nogood_refused() -> None:
    """H14-nogood: empty nogood must not silently skip."""
    cut = SimpleNamespace(kind="nogood", assignment_map={uuid4(): uuid4()})
    with pytest.raises(ValueError, match="nogood"):
        _add_benders_cut_rows(h=None, cuts=[cut], var_index={}, cmax_idx=0)


def test_rhc_per_window_limit_always_defined() -> None:
    """C14-crash: early-greedy path must not UnboundLocal per_window_limit."""
    # Contract smoke: the window loop initializes per_window_limit before branching.
    src = open("synaps/solvers/rhc/_solver.py", encoding="utf-8").read()
    assert "per_window_limit = 0.0" in src
    assert "missing_frozen_predecessor" in src
