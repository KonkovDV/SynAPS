"""Tests for the minimal SynAPS CLI."""

from __future__ import annotations

import json

from synaps.cli import main
from synaps.contracts import RepairRequest, SolveRequest
from synaps.solvers.greedy_dispatch import GreedyDispatch
from synaps.solvers.router import SolveRegime
from tests.conftest import make_simple_problem


def _write_instance(tmp_path) -> str:
    problem = make_simple_problem()
    instance_path = tmp_path / "instance.json"
    instance_path.write_text(
        json.dumps(problem.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    return str(instance_path)


def test_cli_solve_with_explicit_solver_config(tmp_path, capsys) -> None:
    instance_path = _write_instance(tmp_path)

    exit_code = main(["solve", instance_path, "--solver-config", "GREED"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["solver_name"] == "greedy_dispatch"
    assert payload["metadata"]["portfolio"]["solver_config"] == "GREED"
    assert payload["metadata"]["portfolio"]["routed"] is False


def test_cli_solve_uses_routed_portfolio_by_default(tmp_path, capsys) -> None:
    instance_path = _write_instance(tmp_path)

    exit_code = main(["solve", instance_path])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["metadata"]["portfolio"]["solver_config"] == "CPSAT-10"
    assert payload["metadata"]["portfolio"]["routed"] is True


def test_cli_solve_request_executes_contract(tmp_path, capsys) -> None:
    problem = make_simple_problem()
    request = SolveRequest(
        request_id="solve-contract-1",
        problem=problem,
    )
    request_path = tmp_path / "solve-request.json"
    request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

    exit_code = main(["solve-request", str(request_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["request_id"] == "solve-contract-1"
    assert payload["result"]["metadata"]["portfolio"]["solver_config"] == "CPSAT-10"


def test_cli_repair_request_executes_contract(tmp_path, capsys) -> None:
    problem = make_simple_problem()
    base = GreedyDispatch().solve(problem)
    request = RepairRequest(
        request_id="repair-contract-1",
        problem=problem,
        base_assignments=base.assignments,
        disrupted_op_ids=[problem.operations[0].id],
        regime=SolveRegime.BREAKDOWN,
    )
    request_path = tmp_path / "repair-request.json"
    request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

    exit_code = main(["repair-request", str(request_path)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["request_id"] == "repair-contract-1"
    assert payload["result"]["metadata"]["portfolio"]["solver_config"] == "INCREMENTAL_REPAIR"


def test_cli_write_contract_schemas_writes_bundle(tmp_path, capsys) -> None:
    output_dir = tmp_path / "contracts"

    exit_code = main(["write-contract-schemas", "--output-dir", str(output_dir)])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert len(payload) == 4
    assert (output_dir / "solve-request.schema.json").exists()
    assert (output_dir / "solve-response.schema.json").exists()