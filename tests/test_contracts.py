"""Tests for the stable SynAPS runtime contract."""

from __future__ import annotations

from pathlib import Path

from synaps.contracts import (
    RepairRequest,
    RoutingContextContract,
    SolveOptions,
    SolveRequest,
    build_contract_schema_bundle,
    execute_repair_request,
    execute_solve_request,
    write_contract_schemas,
)
from synaps.model import SolverStatus
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.router import SolveRegime
from tests.conftest import make_simple_problem


def test_execute_solve_request_returns_contract_response() -> None:
    problem = make_simple_problem()
    request = SolveRequest(
        request_id="req-1",
        problem=problem,
        context=RoutingContextContract(regime=SolveRegime.INTERACTIVE),
        solve_options=SolveOptions(),
    )

    response = execute_solve_request(request)

    assert response.request_id == "req-1"
    assert response.result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}
    assert response.result.metadata["portfolio"]["regime"] == SolveRegime.INTERACTIVE.value


def test_execute_repair_request_returns_contract_response() -> None:
    problem = make_simple_problem()
    base = GreedyDispatch().solve(problem)
    request = RepairRequest(
        request_id="repair-1",
        problem=problem,
        base_assignments=base.assignments,
        disrupted_op_ids=[problem.operations[0].id],
        regime=SolveRegime.BREAKDOWN,
    )

    response = execute_repair_request(request)

    assert response.request_id == "repair-1"
    assert response.result.status == SolverStatus.FEASIBLE
    assert response.result.metadata["portfolio"]["solver_config"] == "INCREMENTAL_REPAIR"


def test_build_contract_schema_bundle_contains_all_public_contracts() -> None:
    bundle = build_contract_schema_bundle()

    assert set(bundle) == {
        "solve-request.schema.json",
        "solve-response.schema.json",
        "repair-request.schema.json",
        "repair-response.schema.json",
    }
    assert bundle["solve-request.schema.json"]["title"] == "SolveRequest"


def test_write_contract_schemas_writes_schema_files(tmp_path: Path) -> None:
    written = write_contract_schemas(tmp_path)

    assert len(written) == 4
    assert {path.name for path in written} == {
        "solve-request.schema.json",
        "solve-response.schema.json",
        "repair-request.schema.json",
        "repair-response.schema.json",
    }
    assert all(path.exists() for path in written)