"""Tests for the minimal SynAPS CLI."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_cli_solve_request_can_write_runtime_replay_artifact(tmp_path, capsys) -> None:
    problem = make_simple_problem()
    request = SolveRequest(
        request_id="solve-contract-replay-1",
        problem=problem,
    )
    request_path = tmp_path / "solve-request.json"
    replay_dir = tmp_path / "replay"
    request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

    exit_code = main([
        "solve-request",
        str(request_path),
        "--replay-output-dir",
        str(replay_dir),
    ])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    files = list(replay_dir.glob("*.json"))

    assert exit_code == 0
    assert payload["request_id"] == "solve-contract-replay-1"
    assert len(files) == 1
    replay = json.loads(files[0].read_text(encoding="utf-8"))
    manifest = [
        json.loads(line)
        for line in (replay_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert replay["artifact_kind"] == "runtime-solve"
    assert replay["request_id"] == "solve-contract-replay-1"
    assert replay["verification"]["performed"] is True
    assert manifest[0]["artifact_kind"] == "runtime-solve"
    assert manifest[0]["request_id"] == "solve-contract-replay-1"


def test_cli_solve_can_write_runtime_replay_artifact(tmp_path, capsys) -> None:
    instance_path = _write_instance(tmp_path)
    replay_dir = tmp_path / "replay"

    exit_code = main([
        "solve",
        instance_path,
        "--solver-config",
        "GREED",
        "--replay-output-dir",
        str(replay_dir),
    ])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    files = list(replay_dir.glob("*.json"))
    manifest = [
        json.loads(line)
        for line in (replay_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert exit_code == 0
    assert payload["solver_name"] == "greedy_dispatch"
    assert len(files) == 1
    replay = json.loads(files[0].read_text(encoding="utf-8"))
    assert replay["artifact_kind"] == "runtime-solve"
    assert replay["solver_config"] == "GREED"
    assert replay["request_summary"]["verify_feasibility"] is True
    assert manifest[0]["artifact_kind"] == "runtime-solve"
    assert manifest[0]["solver_config"] == "GREED"


def test_cli_repair_request_can_write_runtime_replay_artifact(tmp_path, capsys) -> None:
    problem = make_simple_problem()
    base = GreedyDispatch().solve(problem)
    request = RepairRequest(
        request_id="repair-contract-replay-1",
        problem=problem,
        base_assignments=base.assignments,
        disrupted_op_ids=[problem.operations[0].id],
        regime=SolveRegime.BREAKDOWN,
    )
    request_path = tmp_path / "repair-request.json"
    replay_dir = tmp_path / "replay"
    request_path.write_text(request.model_dump_json(indent=2), encoding="utf-8")

    exit_code = main([
        "repair-request",
        str(request_path),
        "--replay-output-dir",
        str(replay_dir),
    ])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    files = list(replay_dir.glob("*.json"))

    assert exit_code == 0
    assert payload["request_id"] == "repair-contract-replay-1"
    assert len(files) == 1
    replay = json.loads(files[0].read_text(encoding="utf-8"))
    manifest = [
        json.loads(line)
        for line in (replay_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert replay["artifact_kind"] == "runtime-repair"
    assert replay["request_id"] == "repair-contract-replay-1"
    assert replay["request_summary"]["disrupted_operation_count"] == 1
    assert manifest[0]["artifact_kind"] == "runtime-repair"
    assert manifest[0]["request_id"] == "repair-contract-replay-1"