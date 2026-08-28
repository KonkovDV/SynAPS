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
    ScheduleResult,
    ShiftInterval,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.problem_profile import build_problem_profile
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.registry import CALENDAR_AWARE, CALENDAR_REFUSING, create_solver
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


def test_shift_minute_spans_ceils_open_floors_close() -> None:
    from synaps.calendar import shift_minute_spans

    spans = shift_minute_spans([_night_shift()], H0)
    assert spans == [(8 * 60, 16 * 60)]


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


def test_checker_rejects_setup_occupying_closed_shift() -> None:
    """И3.1: occupancy [start - setup, end] must sit in one published shift.

    Processing is inside 08:00-16:00; a 60-minute setup occupies 07:00-08:00
    (closed). The notary must emit CALENDAR_VIOLATION, not [].
    """

    problem = _one_op_problem(calendar=[_night_shift()])
    wc = problem.work_centers[0]
    op = problem.operations[0]
    start = H0 + timedelta(hours=8)
    assignment = Assignment(
        operation_id=op.id,
        work_center_id=wc.id,
        start_time=start,
        end_time=start + timedelta(hours=1),
        setup_minutes=60,
    )
    kinds = {v.kind for v in FeasibilityChecker().check(problem, [assignment], exhaustive=True)}
    assert "CALENDAR_VIOLATION" in kinds


def test_greed_clips_setup_into_open_shift() -> None:
    """After И3.2/И3.3, GREED occupancy including setup must pass the notary."""

    from synaps.model import SetupEntry

    state_a = State(code="a")
    state_b = State(code="b")
    wc = WorkCenter(code="M", capability_group="G", calendar=[_night_shift()])
    order = Order(external_ref="O", due_date=HE)
    op_a = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=30,
        eligible_wc_ids=[wc.id],
    )
    op_b = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=state_b.id,
        predecessor_op_id=op_a.id,
        base_duration_min=30,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order],
        operations=[op_a, op_b],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=60,
            )
        ],
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )
    solver, kwargs = create_solver("GREED")
    result = solver.solve(problem, **kwargs)
    assert result.assignments
    assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True)


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


def test_calendar_sets_partition_the_portfolio() -> None:
    from synaps.solvers.registry import available_solver_configs

    names = set(available_solver_configs())
    assert names == CALENDAR_AWARE | CALENDAR_REFUSING
    assert CALENDAR_AWARE.isdisjoint(CALENDAR_REFUSING)
    assert len(names) == 25


def test_route_calendar_instance_returns_calendar_aware_whitelist() -> None:
    """И4.2: calendar-only 5k must route inside CALENDAR_AWARE, not merely ¬ALNS.

    Must fail on BALANCED x latency=None while the calendar check still sits
    inside ``if latency is not None`` (LBBD-10-HD is CALENDAR_REFUSING).
    """

    from tests.conftest import make_simple_problem

    problem = make_simple_problem(n_orders=1250, ops_per_order=4)
    payload = problem.model_dump()
    start = payload["planning_horizon_start"]
    end = payload["planning_horizon_end"]
    for work_center in payload["work_centers"]:
        work_center["calendar"] = [{"start": start, "end": end}]
    cal = problem.__class__.model_validate(payload)
    latencies = (None, 1, 60, 180, 400, 900)
    for policy in PortfolioPolicy:
        for latency in latencies:
            decision = route_solver_config(
                cal,
                context=SolverRoutingContext(
                    regime=SolveRegime.NOMINAL,
                    preferred_max_latency_s=latency,
                    portfolio_policy=policy,
                ),
            )
            assert decision.solver_config in CALENDAR_AWARE, (
                policy,
                latency,
                decision.solver_config,
            )
    exact_none = route_solver_config(
        cal,
        context=SolverRoutingContext(exact_required=True, preferred_max_latency_s=None),
    )
    assert exact_none.solver_config in CALENDAR_AWARE, exact_none.solver_config


def test_cpsat_alns_lbbd_encode_nonempty_calendar() -> None:
    """Named exact/ALNS configs encode occupancy; they do not schedule 24/7."""

    problem = _one_op_problem(calendar=[_night_shift()])
    for name in ("CPSAT-10", "ALNS-300", "LBBD-5"):
        solver, kwargs = create_solver(name)
        result = solver.solve(problem, **kwargs, auto_greedy_warm_start=False)
        assert result.assignments, name
        assert result.assignments[0].start_time >= H0 + timedelta(hours=8), name
        assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True), name
        assert result.metadata.get("calendar_unsupported") is not True, name


def test_cpsat_clips_setup_into_open_shift() -> None:
    from synaps.model import SetupEntry

    state_a = State(code="a")
    state_b = State(code="b")
    wc = WorkCenter(code="M", capability_group="G", calendar=[_night_shift()])
    order = Order(external_ref="O", due_date=HE)
    op_a = Operation(
        order_id=order.id,
        seq_in_order=1,
        state_id=state_a.id,
        base_duration_min=30,
        eligible_wc_ids=[wc.id],
    )
    op_b = Operation(
        order_id=order.id,
        seq_in_order=2,
        state_id=state_b.id,
        predecessor_op_id=op_a.id,
        base_duration_min=30,
        eligible_wc_ids=[wc.id],
    )
    problem = ScheduleProblem(
        states=[state_a, state_b],
        orders=[order],
        operations=[op_a, op_b],
        work_centers=[wc],
        setup_matrix=[
            SetupEntry(
                work_center_id=wc.id,
                from_state_id=state_a.id,
                to_state_id=state_b.id,
                setup_minutes=60,
            )
        ],
        planning_horizon_start=H0,
        planning_horizon_end=HE,
    )
    solver, kwargs = create_solver("CPSAT-10")
    result = solver.solve(problem, **kwargs, auto_greedy_warm_start=False)
    assert result.assignments
    assert not FeasibilityChecker().check(problem, result.assignments, exhaustive=True)


def test_cli_calendar_cpsat_exits_0(tmp_path: Path) -> None:
    from synaps.cli import main

    problem = _one_op_problem(calendar=[_night_shift()])
    instance = tmp_path / "cal.json"
    instance.write_text(problem.model_dump_json(), encoding="utf-8")
    code = main(["solve", str(instance), "--solver-config", "CPSAT-10", "--no-verify-feasibility"])
    assert code == 0


def test_verify_error_with_assignments_still_runs_notary() -> None:
    """ERROR + nonempty assignments must not skip the checker (KI-N15)."""

    from synaps.validation import verify_schedule_result

    problem = _one_op_problem(calendar=[_night_shift()])
    wc = problem.work_centers[0]
    op = problem.operations[0]
    result = ScheduleResult(
        solver_name="GREED",
        status=SolverStatus.ERROR,
        assignments=[
            Assignment(
                operation_id=op.id,
                work_center_id=wc.id,
                start_time=H0,
                end_time=H0 + timedelta(hours=1),
                setup_minutes=0,
            )
        ],
    )
    verification = verify_schedule_result(problem, result)
    assert verification.feasible is False
    assert "CALENDAR_VIOLATION" in verification.violation_kinds


def test_verify_timeout_with_assignments_still_runs_notary() -> None:
    from synaps.validation import verify_schedule_result

    problem = _one_op_problem(calendar=[_night_shift()])
    wc = problem.work_centers[0]
    op = problem.operations[0]
    result = ScheduleResult(
        solver_name="BEAM-3",
        status=SolverStatus.TIMEOUT,
        assignments=[
            Assignment(
                operation_id=op.id,
                work_center_id=wc.id,
                start_time=H0,
                end_time=H0 + timedelta(hours=1),
                setup_minutes=0,
            )
        ],
    )
    verification = verify_schedule_result(problem, result)
    assert verification.feasible is False
    assert "CALENDAR_VIOLATION" in verification.violation_kinds


def test_verify_error_without_assignments_stays_empty_kinds() -> None:
    from synaps.validation import verify_schedule_result

    problem = _one_op_problem(calendar=[_night_shift()])
    result = ScheduleResult(solver_name="GREED", status=SolverStatus.ERROR)
    verification = verify_schedule_result(problem, result)
    assert verification.feasible is False
    assert verification.violation_kinds == []
    assert verification.violations == []


def test_verify_error_with_clean_assignments_is_not_verified_feasible() -> None:
    from synaps.validation import verify_schedule_result

    problem = _one_op_problem(calendar=[])
    wc = problem.work_centers[0]
    op = problem.operations[0]
    result = ScheduleResult(
        solver_name="GREED",
        status=SolverStatus.ERROR,
        assignments=[
            Assignment(
                operation_id=op.id,
                work_center_id=wc.id,
                start_time=H0,
                end_time=H0 + timedelta(hours=1),
                setup_minutes=0,
            )
        ],
    )
    verification = verify_schedule_result(problem, result)
    assert verification.feasible is False
