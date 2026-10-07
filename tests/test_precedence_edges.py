"""Generalized precedence edges: model contract, CP-SAT, greedy, checker parity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from synaps.model import (
    Assignment,
    AuxiliaryResource,
    Operation,
    OperationAuxRequirement,
    Order,
    ScheduleProblem,
    SolverStatus,
    State,
    WorkCenter,
)
from synaps.precedence import PrecedenceEdge, PrecedenceType
from synaps.solvers.cpsat_solver import CpSatSolver
from synaps.solvers.feasibility_checker import FeasibilityChecker
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.registry import create_solver

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def _problem(
    durations: list[int],
    edges: list[tuple[int, int, PrecedenceType, int, int | None]],
    *,
    earliest: dict[int, int] | None = None,
    shared_aux: bool = False,
    horizon: int = 500,
) -> tuple[ScheduleProblem, list[UUID]]:
    """One order + one unary work center per operation: only edges couple them."""
    state = State(code="S")
    orders = [
        Order(external_ref=f"o{i}", due_date=T0 + timedelta(minutes=horizon)) for i in durations
    ]
    centers = [WorkCenter(code=f"wc{i}", capability_group="g") for i, _ in enumerate(durations)]
    op_ids = [uuid4() for _ in durations]
    operations = [
        Operation(
            id=op_ids[i],
            order_id=orders[i].id,
            seq_in_order=0,
            state_id=state.id,
            base_duration_min=duration,
            eligible_wc_ids=[centers[i].id],
            earliest_start=(
                T0 + timedelta(minutes=earliest[i]) if earliest and i in earliest else None
            ),
        )
        for i, duration in enumerate(durations)
    ]
    aux: list[AuxiliaryResource] = []
    reqs: list[OperationAuxRequirement] = []
    if shared_aux:
        resource = AuxiliaryResource(code="stand", resource_type="stand", pool_size=1)
        aux.append(resource)
        reqs = [
            OperationAuxRequirement(operation_id=op_id, aux_resource_id=resource.id)
            for op_id in op_ids
        ]
    problem = ScheduleProblem(
        states=[state],
        orders=orders,
        operations=operations,
        work_centers=centers,
        setup_matrix=[],
        auxiliary_resources=aux,
        aux_requirements=reqs,
        precedence_edges=[
            PrecedenceEdge(
                src_op_id=op_ids[src],
                dst_op_id=op_ids[dst],
                type=kind,
                min_lag=lag,
                max_lag=max_lag,
            )
            for src, dst, kind, lag, max_lag in edges
        ],
        planning_horizon_start=T0,
        planning_horizon_end=T0 + timedelta(minutes=horizon),
    )
    return problem, op_ids


def _offsets(result: object, op_id: UUID) -> tuple[int, int]:
    row = next(a for a in result.assignments if a.operation_id == op_id)  # type: ignore[attr-defined]
    return (
        int((row.start_time - T0).total_seconds() // 60),
        int((row.end_time - T0).total_seconds() // 60),
    )


def _solve_cpsat(problem: ScheduleProblem) -> object:
    return CpSatSolver().solve(
        problem, time_limit_s=10, auto_greedy_warm_start=False, num_workers=1
    )


# ---------- model contract ----------


def test_cross_order_edge_is_admissible() -> None:
    problem, _ = _problem([5, 3], [(0, 1, PrecedenceType.FS, 0, None)])
    assert len(problem.precedence_edges) == 1


def test_edge_rejects_unknown_ops_and_self_loop() -> None:
    problem, ids = _problem([5, 3], [])
    payload = problem.model_dump(mode="python")
    payload["precedence_edges"] = [{"src_op_id": ids[0], "dst_op_id": uuid4()}]
    with pytest.raises(ValidationError, match="unknown dst_op_id"):
        ScheduleProblem.model_validate(payload)
    payload["precedence_edges"] = [{"src_op_id": ids[0], "dst_op_id": ids[0]}]
    with pytest.raises(ValidationError, match="to itself"):
        ScheduleProblem.model_validate(payload)


def test_edge_rejects_cycle_and_inverted_lags() -> None:
    with pytest.raises(ValidationError, match="cycle"):
        _problem(
            [5, 3, 2],
            [
                (0, 1, PrecedenceType.FS, 0, None),
                (1, 2, PrecedenceType.SS, 0, None),
                (2, 0, PrecedenceType.FF, 0, None),
            ],
        )
    with pytest.raises(ValidationError, match="max_lag must be >= min_lag"):
        PrecedenceEdge(src_op_id=uuid4(), dst_op_id=uuid4(), min_lag=3, max_lag=2)


def test_duplicate_edge_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate precedence edge"):
        _problem([5, 3], [(0, 1, PrecedenceType.FS, 0, None), (0, 1, PrecedenceType.FS, 2, None)])


def test_classic_problem_unchanged_without_edges() -> None:
    problem, _ = _problem([5, 3], [])
    assert problem.precedence_edges == []
    assert "precedence_edges" in ScheduleProblem.model_json_schema()["properties"]


# ---------- CP-SAT known answers ----------


@pytest.mark.parametrize(
    ("kind", "lag", "expected_makespan"),
    [
        (PrecedenceType.FS, 2, 10),  # B starts at 5+2
        (PrecedenceType.SS, 2, 5),  # B in [2,5)
        (PrecedenceType.FF, 1, 6),  # B ends at 5+1
        (PrecedenceType.SF, 4, 5),  # B ends >= 0+4
        (PrecedenceType.FS, -2, 6),  # lead: B starts at 3
    ],
)
def test_cpsat_encodes_each_type(kind: PrecedenceType, lag: int, expected_makespan: int) -> None:
    problem, _ids = _problem([5, 3], [(0, 1, kind, lag, None)])
    result = _solve_cpsat(problem)
    assert result.status is SolverStatus.OPTIMAL  # type: ignore[attr-defined]
    assert result.objective.makespan_minutes == expected_makespan  # type: ignore[attr-defined]
    assert FeasibilityChecker().check(problem, result.assignments) == []  # type: ignore[attr-defined]


def test_cpsat_enforces_max_lag() -> None:
    # SS with lag exactly 0: B must start together with A even though A is late.
    problem, ids = _problem([5, 3], [(0, 1, PrecedenceType.SS, 0, 0)], earliest={0: 4})
    result = _solve_cpsat(problem)
    assert result.status is SolverStatus.OPTIMAL  # type: ignore[attr-defined]
    assert _offsets(result, ids[1])[0] == _offsets(result, ids[0])[0] == 4


def test_cpsat_infeasible_on_contradictory_max_lag() -> None:
    # B can start only after A ends (FS) yet must start within 1 of A's start.
    problem, _ = _problem(
        [5, 3], [(0, 1, PrecedenceType.FS, 0, None), (0, 1, PrecedenceType.SS, 0, 1)]
    )
    result = _solve_cpsat(problem)
    assert result.status is SolverStatus.INFEASIBLE  # type: ignore[attr-defined]


def test_cross_order_edge_with_shared_resource() -> None:
    problem, _ids = _problem([4, 4, 4], [(0, 2, PrecedenceType.FS, 1, None)], shared_aux=True)
    result = _solve_cpsat(problem)
    assert result.status is SolverStatus.OPTIMAL  # type: ignore[attr-defined]
    assert result.objective.makespan_minutes == 12  # type: ignore[attr-defined]
    assert FeasibilityChecker().check(problem, result.assignments) == []  # type: ignore[attr-defined]


# ---------- greedy + fail-closed ----------


def test_greedy_respects_min_lag_edges() -> None:
    problem, ids = _problem(
        [5, 3, 2],
        [
            (0, 1, PrecedenceType.FS, 2, None),
            (1, 2, PrecedenceType.FF, 1, None),
            (0, 2, PrecedenceType.SF, 9, None),
        ],
    )
    result = GreedyDispatch().solve(problem)
    assert result.status in (SolverStatus.FEASIBLE, SolverStatus.OPTIMAL)
    assert FeasibilityChecker().check(problem, result.assignments) == []
    assert _offsets(result, ids[1])[0] == 7


@pytest.mark.parametrize("config", ["LBBD-5", "BEAM-3", "ALNS-300"])
def test_unsupported_solver_fails_closed(config: str) -> None:
    problem, _ = _problem([5, 3], [(0, 1, PrecedenceType.FS, 0, None)])
    solver, kwargs = create_solver(config)
    result = solver.solve(problem, **kwargs)
    assert result.status is SolverStatus.ERROR
    assert result.assignments == []
    assert result.metadata["error"] == "precedence_edges_unsupported"


# ---------- checker ----------


def test_checker_flags_each_broken_bound() -> None:
    problem, ids = _problem([5, 3], [(0, 1, PrecedenceType.FF, 1, 2)])
    wcs = [op.eligible_wc_ids[0] for op in problem.operations]

    def plan(b_start: int) -> list[Assignment]:
        return [
            Assignment(
                operation_id=ids[0],
                work_center_id=wcs[0],
                start_time=T0,
                end_time=T0 + timedelta(minutes=5),
            ),
            Assignment(
                operation_id=ids[1],
                work_center_id=wcs[1],
                start_time=T0 + timedelta(minutes=b_start),
                end_time=T0 + timedelta(minutes=b_start + 3),
            ),
        ]

    checker = FeasibilityChecker()
    assert checker.check(problem, plan(3)) == []
    assert checker.check(problem, plan(4)) == []
    for bad in (2, 5):
        kinds = [v.kind for v in checker.check(problem, plan(bad))]
        assert kinds == ["PRECEDENCE_EDGE_VIOLATION"]


_EDGE_KINDS = st.sampled_from(list(PrecedenceType))


@settings(max_examples=25, deadline=None)
@given(
    durations=st.lists(st.integers(min_value=0, max_value=6), min_size=2, max_size=5),
    raw_edges=st.lists(
        st.tuples(st.integers(0, 4), st.integers(0, 4), _EDGE_KINDS, st.integers(-3, 4)),
        max_size=6,
    ),
)
def test_property_checker_accepts_solver_and_rejects_mutation(
    durations: list[int], raw_edges: list[tuple[int, int, PrecedenceType, int]]
) -> None:
    n = len(durations)
    seen: set[tuple[int, int, PrecedenceType]] = set()
    edges: list[tuple[int, int, PrecedenceType, int, int | None]] = []
    for src, dst, kind, lag in raw_edges:
        src, dst = src % n, dst % n
        if src >= dst or (src, dst, kind) in seen:  # forward-only keeps it acyclic
            continue
        seen.add((src, dst, kind))
        edges.append((src, dst, kind, lag, None))
    problem, _ids = _problem(durations, edges, earliest={0: 20}, horizon=200)
    result = _solve_cpsat(problem)
    assert result.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)  # type: ignore[attr-defined]
    checker = FeasibilityChecker()
    assert checker.check(problem, result.assignments) == []  # type: ignore[attr-defined]
    for edge in problem.precedence_edges:
        mutated = []
        for row in result.assignments:  # type: ignore[attr-defined]
            if row.operation_id == edge.dst_op_id:
                row = row.model_copy(
                    update={
                        "start_time": row.start_time - timedelta(minutes=500),
                        "end_time": row.end_time - timedelta(minutes=500),
                    }
                )
            mutated.append(row)
        kinds = {v.kind for v in checker.check(problem, mutated)}
        assert "PRECEDENCE_EDGE_VIOLATION" in kinds
