"""Minimal command-line interface for the SynAPS portfolio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from synaps import solve_schedule
from synaps.contracts import (
    execute_repair_request,
    execute_solve_request,
    parse_repair_request_json,
    parse_solve_request_json,
    write_contract_schemas,
)
from synaps.model import ScheduleProblem, ScheduleResult, normalize_schedule_problem_data
from synaps.replay import build_runtime_replay_artifact, write_replay_artifact
from synaps.solvers.registry import available_solver_configs, build_solver_registry_manifest
from synaps.solvers.router import SolveRegime, SolverRoutingContext


def _load_problem(path: Path) -> ScheduleProblem:
    raw_problem = json.loads(path.read_text(encoding="utf-8"))
    return ScheduleProblem.model_validate(normalize_schedule_problem_data(raw_problem))


def _load_json_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def _write_json_output(payload: object, output_file: Path | None) -> None:
    rendered = json.dumps(payload, indent=2)
    if output_file is not None:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(rendered + "\n", encoding="utf-8")
        return

    sys.stdout.write(rendered)
    sys.stdout.write("\n")


def _write_runtime_replay(
    *,
    output_dir: Path | None,
    artifact_kind: Literal["runtime-solve", "runtime-repair"],
    artifact_source: str,
    problem: ScheduleProblem,
    result: ScheduleResult,
    request_summary: dict[str, object],
    request_id: str | None,
    solver_config: str | None,
    stem_parts: tuple[str, ...],
) -> None:
    if output_dir is None:
        return

    artifact = build_runtime_replay_artifact(
        artifact_kind=artifact_kind,
        artifact_source=artifact_source,
        problem=problem,
        result=result,
        request_summary=request_summary,
        request_id=request_id,
        solver_config=solver_config,
    )
    write_replay_artifact(output_dir, artifact, stem_parts=stem_parts)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SynAPS portfolio CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    solve_parser = subparsers.add_parser("solve", help="Solve one scheduling instance")
    solve_parser.add_argument("instance", type=Path, help="Path to an instance JSON file")
    solve_parser.add_argument(
        "--solver-config",
        choices=available_solver_configs(),
        help="Explicit solver configuration override",
    )
    solve_parser.add_argument(
        "--regime",
        choices=[regime.value for regime in SolveRegime],
        default=SolveRegime.NOMINAL.value,
        help="Operational regime for routed execution",
    )
    solve_parser.add_argument(
        "--preferred-max-latency-s",
        type=int,
        help="Preferred latency ceiling used by the deterministic router",
    )
    solve_parser.add_argument(
        "--exact-required",
        action="store_true",
        help="Prefer exact portfolio members where possible",
    )
    solve_parser.add_argument(
        "--no-verify-feasibility",
        action="store_true",
        help="Skip post-solve feasibility verification in the high-level portfolio API",
    )
    solve_parser.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Directory where runtime replay artifacts should be written",
    )
    solve_parser.add_argument(
        "--output-file",
        type=Path,
        help="Optional path where the JSON result should be written instead of stdout",
    )

    solve_request_parser = subparsers.add_parser(
        "solve-request",
        help="Execute a stable solve request JSON contract",
    )
    solve_request_parser.add_argument(
        "request",
        help="Path to a SolveRequest JSON file, or '-' to read the request from stdin",
    )
    solve_request_parser.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Directory where runtime replay artifacts should be written",
    )
    solve_request_parser.add_argument(
        "--output-file",
        type=Path,
        help="Optional path where the JSON response should be written instead of stdout",
    )

    repair_request_parser = subparsers.add_parser(
        "repair-request",
        help="Execute a stable repair request JSON contract",
    )
    repair_request_parser.add_argument(
        "request",
        help="Path to a RepairRequest JSON file, or '-' to read the request from stdin",
    )
    repair_request_parser.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Directory where runtime replay artifacts should be written",
    )
    repair_request_parser.add_argument(
        "--output-file",
        type=Path,
        help="Optional path where the JSON response should be written instead of stdout",
    )

    schema_parser = subparsers.add_parser(
        "write-contract-schemas",
        help="Write JSON Schema files for the public SynAPS runtime contract",
    )
    schema_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("schema/contracts"),
        help="Directory where contract schema files will be written",
    )

    registry_parser = subparsers.add_parser(
        "list-solver-configs",
        help="Emit the public solver portfolio as machine-readable JSON",
    )
    registry_parser.add_argument(
        "--output-file",
        type=Path,
        help="Optional path where the JSON manifest should be written instead of stdout",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "solve":
        problem = _load_problem(args.instance)
        verify_feasibility = not args.no_verify_feasibility
        context = SolverRoutingContext(
            regime=SolveRegime(args.regime),
            preferred_max_latency_s=args.preferred_max_latency_s,
            exact_required=bool(args.exact_required),
        )
        result = solve_schedule(
            problem,
            context=context,
            solver_config=args.solver_config,
            verify_feasibility=verify_feasibility,
        )
        _write_runtime_replay(
            output_dir=args.replay_output_dir,
            artifact_kind="runtime-solve",
            artifact_source="synaps.cli.solve",
            problem=problem,
            result=result,
            request_summary={
                "instance_path": str(args.instance),
                "solver_config": args.solver_config,
                "regime": args.regime,
                "preferred_max_latency_s": args.preferred_max_latency_s,
                "exact_required": bool(args.exact_required),
                "verify_feasibility": verify_feasibility,
            },
            request_id=None,
            solver_config=args.solver_config,
            stem_parts=(args.instance.stem, args.solver_config or "AUTO", "runtime-solve"),
        )
        _write_json_output(result.model_dump(mode="json"), args.output_file)
        return 0

    elif args.command == "solve-request":
        solve_request = parse_solve_request_json(_load_json_source(args.request))
        solve_response = execute_solve_request(solve_request)
        request_stem = "stdin" if args.request == "-" else Path(args.request).stem
        _write_runtime_replay(
            output_dir=args.replay_output_dir,
            artifact_kind="runtime-solve",
            artifact_source="synaps.cli.solve-request",
            problem=solve_request.problem,
            result=solve_response.result,
            request_summary={
                "request_path": str(args.request),
                "solver_config": solve_request.solver_config,
                "regime": solve_request.context.regime.value,
                "preferred_max_latency_s": solve_request.context.preferred_max_latency_s,
                "exact_required": solve_request.context.exact_required,
                "verify_feasibility": solve_request.verify_feasibility,
                "solve_options": solve_request.solve_options.model_dump(exclude_none=True),
            },
            request_id=solve_request.request_id,
            solver_config=solve_request.solver_config,
            stem_parts=(
                solve_request.request_id or request_stem,
                solve_request.solver_config or "AUTO",
                "runtime-solve",
            ),
        )
        _write_json_output(solve_response.model_dump(mode="json"), args.output_file)
        return 0

    elif args.command == "repair-request":
        repair_request = parse_repair_request_json(_load_json_source(args.request))
        repair_response = execute_repair_request(repair_request)
        request_stem = "stdin" if args.request == "-" else Path(args.request).stem
        _write_runtime_replay(
            output_dir=args.replay_output_dir,
            artifact_kind="runtime-repair",
            artifact_source="synaps.cli.repair-request",
            problem=repair_request.problem,
            result=repair_response.result,
            request_summary={
                "request_path": str(args.request),
                "regime": repair_request.regime.value,
                "radius": repair_request.radius,
                "verify_feasibility": repair_request.verify_feasibility,
                "base_assignment_count": len(repair_request.base_assignments),
                "disrupted_operation_count": len(repair_request.disrupted_op_ids),
            },
            request_id=repair_request.request_id,
            solver_config="INCREMENTAL_REPAIR",
            stem_parts=(
                repair_request.request_id or request_stem,
                "INCREMENTAL_REPAIR",
                "runtime-repair",
            ),
        )
        _write_json_output(repair_response.model_dump(mode="json"), args.output_file)
        return 0

    elif args.command == "write-contract-schemas":
        written = write_contract_schemas(args.output_dir)
        json.dump([str(path) for path in written], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    elif args.command == "list-solver-configs":
        _write_json_output(build_solver_registry_manifest(), args.output_file)
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


__all__ = ["main"]
