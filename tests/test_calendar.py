"""Work-center shift calendar (KI-N7): checker, greedy clip, native skip."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    from pathlib import Path

from synaps.calendar import (
    delay_start_to_open_shift,
    processing_fits_calendar,
    work_centers_have_calendar,
)
from synaps.model import (
    Assignment,
    Operation,
    Order,
    ScheduleProblem,
    ShiftInterval,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.problem_profile import build_problem_profile
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.registry import create_solver
from synaps.solvers.router import (
    PortfolioPolicy,
    SolveRegime,
    SolverRoutingContext,
    route_solver_config,
)

H0 = datetime(2026, 1, 1, tzinfo=UTC)
HE = H0 + timedelta(days=1)


def _night_shift() -> ShiftInterval:
    return ShiftInterval(start=H0 + timedelta(hours=8), end=H0 + timedelta(hours=16))


def _one_op_problem(*, calendar: list[ShiftInterval]) -> ScheduleProblem:
    state = State(code="s")
    wc = WorkCenter(code="M", capability_group="G", calendar=calendar)
    order = Order(external_ref="O", due_date=HE)
    op = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state.id,
        base_duration_min=60,
        eligible_wc_ids=[wc.id],
    )
    return ScheduleProblem(
        states=[state],
        orders=[order],
        operations=[op],
        work_centers=[wc],
        setup_matrix=[],
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )


def test_empty_calendar_is_open() -> None:
    start = H0
    end = H0 + timedelta(hours=1)
    assert processing_fits_calendar(start, end, []) is True
    assert delay_start_to_open_shift(0.0, 60.0, [], H0) == 0.0


def test_delay_start_jumps_to_shift_open() -> None:
    shift = _night_shift()
    delayed = delay_start_to_open_shift(0.0, 60.0, [shift], H0)
    assert delayed == 8 * 60


def test_delay_start_none_when_duration_exceeds_shift() -> None:
    shift = _night_shift()
    assert delay_start_to_open_shift(0.0, 9 * 60, [shift], H0) is None


def test_checker_emits_calendar_violation() -> None:
    problem = _one_op_problem(calendar=[_night_shift()])
    wc = problem.work_centers[0]
    op = problem.operations[0]
    assignment = Assignment(
        operation_id=op.id,
        work_center_id=wc.id,
        start_time=H0,
        end_time=H0 + timedelta(hours=1),
        setup_minutes=0,
    )
    kinds = {v.kind for v in FeasibilityChecker().check(problem, [assignment], exhaustive=True)}
    assert "CALENDAR_VIOLATION" in kinds


def test_checker_accepts_assignment_inside_shift() -> None:
    problem = _one_op_problem(calendar=[_night_shift()])
    wc = problem.work_centers[0]
    op = problem.operations[0]
    start = H0 + timedelta(hours=8)
    assignment = Assignment(
        operation_id=op.id,
        work_center_id=wc.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        setup_minutes=0,
    )
    assert FeasibilityChecker().check(problem, [assignment], exhaustive=True) == []


def test_greed_clips_to_shift() -> None:
    problem = _one_op_problem(calendar=[_night_shift()])
    solver, kwargs = create_solver("GREED")
    result = solver.solve(problem, **kwargs)
    assert result.assignments
    assert result.assignments[0].start_time >= H0 + timedelta(hours=8)
    assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True)


def test_profile_and_router_see_machine_calendar() -> None:
    problem = _one_op_problem(calendar=[_night_shift()])
    assert build_problem_profile(problem).has_hard_time_windows is True
    assert build_problem_profile(problem).has_machine_calendar is True
    assert build_problem_profile(problem).has_per_op_windows is False
    assert work_centers_have_calendar(problem.work_centers) is True

    large = _one_op_problem(calendar=[_night_shift()])
    # Router uses op count, not this tiny instance. Calendar flag on 5k is in
    # test_solver_portfolio; here the profile bit is the contract.
    decision = route_solver_config(
        large,
        context=SolverRoutingContext(regime=SolveRegime.NOMINAL),
    )
    assert decision.solver_config  # smoke: calendar instances still route


def test_shift_interval_rejects_empty_span() -> None:
    with pytest.raises(ValidationError):
        ShiftInterval(start=H0, end=H0)


def test_route_never_selects_alns_on_calendar_without_windows() -> None:
    """Ж4.2: calendar-only 5k is not an ALNS-500/300 route under any policy."""
    from tests.conftest import make_simple_problem

    problem = make_simple_problem(n_orders=1250, ops_per_order=4)
    payload = problem.model_dump()
    start = payload["planning_horizon_start"]
    end = payload["planning_horizon_end"]
    for work_center in payload["work_centers"]:
        work_center["calendar"] = [{"start": start, "end": end}]
    cal = problem.__class__.model_validate(payload)
    profile = build_problem_profile(cal)
    assert profile.has_machine_calendar is True
    assert profile.has_per_op_windows is False
    for policy in PortfolioPolicy:
        for latency in (None, 1, 180, 400, 900):
            decision = route_solver_config(
                cal,
                context=SolverRoutingContext(
                    regime=SolveRegime.NOMINAL,
                    preferred_max_latency_s=latency,
                    portfolio_policy=policy,
                ),
            )
            assert decision.solver_config not in {"ALNS-500", "ALNS-300"}, (
                policy,
                latency,
                decision.solver_config,
            )
    exact = route_solver_config(
        cal,
        context=SolverRoutingContext(exact_required=True, preferred_max_latency_s=400),
    )
    assert exact.solver_config not in {"ALNS-500", "ALNS-300"}


def test_cpsat_alns_lbbd_refuse_nonempty_calendar() -> None:
    problem = _one_op_problem(calendar=[_night_shift()])
    for name in ("CPSAT-10", "ALNS-300", "LBBD-5"):
        solver, kwargs = create_solver(name)
        result = solver.solve(problem, **kwargs)
        assert result.status is SolverStatus.ERROR, name
        assert result.assignments == []
        assert result.metadata.get("calendar_unsupported") is True


def test_cli_calendar_cpsat_exits_3(tmp_path: Path) -> None:
    from synaps.cli import main

    problem = _one_op_problem(calendar=[_night_shift()])
    instance = tmp_path / "cal.json"
    instance.write_text(problem.model_dump_json(), encoding="utf-8")
    code = main(["solve", str(instance), "--solver-config", "CPSAT-10", "--no-verify-feasibility"])
    assert code == 3
