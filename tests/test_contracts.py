"""Tests for the stable SynAPS runtime contract."""

from __future__ import annotations

from pathlib import Path
import json

from synaps.contracts import (
    ProblemInstanceSlice,
    RepairRequest,
    RepairResponse,
    RoutingContextContract,
    SolveOptions,
    SolveRequest,
    SolveResponse,
    build_contract_schema_bundle,
    execute_repair_request,
    execute_solve_request,
    resolve_solve_request_problem,
    write_contract_schemas,
)
from synaps.model import MAX_SCHEDULE_OPERATIONS, SolverStatus
from synaps.replay import build_runtime_replay_artifact
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


def test_execute_solve_request_supports_problem_instance_ref_slice(tmp_path: Path) -> None:
    problem = make_simple_problem()
    problem_path = tmp_path / "problem.json"
    problem_path.write_text(json.dumps(problem.model_dump(mode="json")), encoding="utf-8")

    request = SolveRequest(
        request_id="req-ref-1",
        problem_instance_ref=problem_path.name,
        problem_slice=ProblemInstanceSlice(max_operations=2),
        context=RoutingContextContract(regime=SolveRegime.INTERACTIVE),
        solve_options=SolveOptions(),
    )

    resolved_problem = resolve_solve_request_problem(request, instance_dir=tmp_path)
    response = execute_solve_request(
        request,
        instance_dir=tmp_path,
        resolved_problem=resolved_problem,
    )

    assert len(resolved_problem.operations) == 2
    assert response.request_id == "req-ref-1"
    assert response.result.status in {SolverStatus.FEASIBLE, SolverStatus.OPTIMAL}


def test_solve_request_requires_exactly_one_problem_source() -> None:
    problem = make_simple_problem()

    try:
        SolveRequest(problem=problem, problem_instance_ref="problem.json")
    except ValueError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("expected SolveRequest to reject dual problem sources")

    try:
        SolveRequest()
    except ValueError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("expected SolveRequest to require a problem source")


def test_problem_instance_ref_stays_within_instance_dir(tmp_path: Path) -> None:
    request = SolveRequest(
        problem_instance_ref="../outside.json",
        problem_slice=ProblemInstanceSlice(max_operations=2),
    )

    try:
        resolve_solve_request_problem(request, instance_dir=tmp_path)
    except ValueError as exc:
        assert "within instance_dir" in str(exc)
    else:
        raise AssertionError("expected instance-dir traversal to be rejected")


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


def test_runtime_replay_artifact_can_be_built_from_contract_response() -> None:
    problem = make_simple_problem()
    request = SolveRequest(
        request_id="req-replay-1",
        problem=problem,
        context=RoutingContextContract(regime=SolveRegime.INTERACTIVE),
    )

    response = execute_solve_request(request)
    artifact = build_runtime_replay_artifact(
        artifact_kind="runtime-solve",
        artifact_source="tests.contracts",
        problem=problem,
        result=response.result,
        request_summary={"verify_feasibility": request.verify_feasibility},
        request_id=request.request_id,
        solver_config=request.solver_config,
    )

    assert artifact.request_id == "req-replay-1"
    assert artifact.selected_solver_config == response.result.metadata["portfolio"]["solver_config"]
    assert artifact.verification.performed is True
    assert artifact.verification.violation_count == 0
    assert artifact.routing.regime == SolveRegime.INTERACTIVE.value


def test_build_contract_schema_bundle_contains_all_public_contracts() -> None:
    bundle = build_contract_schema_bundle()

    assert set(bundle) == {
        "solve-request.schema.json",
        "solve-response.schema.json",
        "repair-request.schema.json",
        "repair-response.schema.json",
    }
    assert bundle["solve-request.schema.json"]["title"] == "SolveRequest"
    assert bundle["solve-request.schema.json"]["oneOf"] == [
        {"required": ["problem"]},
        {"required": ["problem_instance_ref"]},
    ]
    assert "ProblemInstanceSlice" in bundle["solve-request.schema.json"]["$defs"]
    assert (
        "default"
        not in bundle["solve-request.schema.json"]["$defs"]["ProblemInstanceSlice"]["properties"][
            "max_operations"
        ]
    )
    solve_problem_schema = bundle["solve-request.schema.json"]["$defs"]["ScheduleProblem"]
    assert solve_problem_schema["properties"]["operations"]["maxItems"] == MAX_SCHEDULE_OPERATIONS
    repair_schema = bundle["repair-request.schema.json"]
    assert repair_schema["properties"]["base_assignments"]["maxItems"] == MAX_SCHEDULE_OPERATIONS
    assert repair_schema["properties"]["disrupted_op_ids"]["maxItems"] == MAX_SCHEDULE_OPERATIONS


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


def test_contract_examples_are_valid_models() -> None:
    examples_dir = Path("schema/contracts/examples")

    solve_request = SolveRequest.model_validate_json(
        (examples_dir / "solve-request.example.json").read_text(encoding="utf-8")
    )
    solve_request_instance_ref = SolveRequest.model_validate_json(
        (examples_dir / "solve-request.instance-ref.example.json").read_text(encoding="utf-8")
    )
    solve_response = SolveResponse.model_validate_json(
        (examples_dir / "solve-response.example.json").read_text(encoding="utf-8")
    )
    repair_request = RepairRequest.model_validate_json(
        (examples_dir / "repair-request.example.json").read_text(encoding="utf-8")
    )
    repair_response = RepairResponse.model_validate_json(
        (examples_dir / "repair-response.example.json").read_text(encoding="utf-8")
    )

    assert solve_request.contract_version == solve_response.contract_version
    assert solve_request_instance_ref.problem_instance_ref == "benchmark/instances/tiny_3x3.json"
    assert repair_request.contract_version == repair_response.contract_version
