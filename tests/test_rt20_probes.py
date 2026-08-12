"""RT-20 probes: the notary must reject references to unknown entities."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from synaps.model import Assignment
from synaps.solvers.feasibility_checker import FeasibilityChecker
from tests.conftest import HORIZON_START, make_simple_problem


def test_probe_unknown_operation_assignment() -> None:
    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    op = problem.operations[0]
    wc = problem.work_centers[0]
    good = Assignment(
        operation_id=op.id,
        work_center_id=wc.id,
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(hours=1),
    )
    phantom = Assignment(
        operation_id=uuid4(),  # not in problem.operations
        work_center_id=wc.id,
        start_time=HORIZON_START + timedelta(hours=2),
        end_time=HORIZON_START + timedelta(hours=3),
    )
    violations = FeasibilityChecker().check(problem, [good, phantom])
    kinds = [v.kind for v in violations]
    assert any("UNKNOWN" in k for k in kinds), f"phantom op passed the notary: {kinds}"


def test_probe_unknown_work_center_assignment() -> None:
    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    op = problem.operations[0]
    bogus_wc = Assignment(
        operation_id=op.id,
        work_center_id=uuid4(),  # not in problem.work_centers
        start_time=HORIZON_START,
        end_time=HORIZON_START + timedelta(hours=1),
    )
    violations = FeasibilityChecker().check(problem, [bogus_wc])
    kinds = [v.kind for v in violations]
    assert any("UNKNOWN" in k for k in kinds), f"phantom machine passed the notary: {kinds}"


def test_rhc_never_places_op_before_order_release() -> None:
    """RT-20 F1: both RHC greedy fallback paths must floor slots by the
    release-propagated earliest start, not just by the predecessor's end."""
    from datetime import timedelta as _td

    from synaps.solvers.feasibility_checker import FeasibilityChecker as _FC
    from synaps.solvers.rhc import RhcSolver  # noqa: PLC0415

    problem = make_simple_problem(n_orders=2, ops_per_order=2)
    release = HORIZON_START + _td(minutes=500)
    order0 = problem.orders[0]
    problem.orders[0] = order0.model_copy(update={"release_date": release})

    result = RhcSolver().solve(problem)
    assert result.status.value in {"feasible", "optimal"}, result.status
    order0_op_ids = {op.id for op in problem.operations if op.order_id == order0.id}
    for assignment in result.assignments:
        if assignment.operation_id in order0_op_ids:
            assert assignment.start_time >= release, (
                f"RHC placed op {assignment.operation_id} at "
                f"{assignment.start_time} before release {release}"
            )
    assert _FC().check(problem, result.assignments) == []


def test_repair_schedule_rejects_identity_override_via_kwargs() -> None:
    """RT-20 F2: solve_kwargs must not silently replace what is being repaired."""
    from synaps.portfolio import repair_schedule

    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    try:
        repair_schedule(
            problem,
            base_assignments=[],
            disrupted_op_ids=[],
            solve_kwargs={"radius": 99},
        )
    except ValueError as exc:
        assert "radius" in str(exc)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("identity override via solve_kwargs was accepted")


def test_solver_time_limit_label_published_in_metadata() -> None:
    """RT-20 F4: the solver's own time-box must be visible in metadata."""
    from synaps.portfolio import solve_schedule

    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    capped = solve_schedule(problem, solver_config="CPSAT-30", verify_feasibility=False)
    assert capped.metadata["portfolio"]["solver_time_limit_s"] == 30
    uncapped = solve_schedule(problem, solver_config="GREED", verify_feasibility=False)
    assert "solver_time_limit_s" in uncapped.metadata["portfolio"]


def test_resource_capacity_zip_is_strict() -> None:
    """RT-20 F11: mismatched window lists must raise, not silently truncate."""
    import pytest

    from synaps.accelerators import resource_capacity_window_is_feasible

    with pytest.raises(ValueError, match="zip|identical lengths"):
        resource_capacity_window_is_feasible(
            window_starts=[0.0, 10.0],
            window_ends=[5.0],  # shorter — must not truncate
            window_quantities=[1, 1],
            candidate_start=6.0,
            candidate_end=8.0,
            requested_quantity=1,
            pool_size=1,
        )
