"""Minimal command-line interface for the SynAPS portfolio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from synaps.contracts import (
    RepairRequest,
    SolveRequest,
    execute_repair_request,
    execute_solve_request,
    write_contract_schemas,
)
from synaps.replay import build_runtime_replay_artifact, write_replay_artifact
from synaps import solve_schedule
from synaps.model import ScheduleProblem
from synaps.solvers.registry import available_solver_configs
from synaps.solvers.router import SolveRegime, SolverRoutingContext


def _load_problem(path: Path) -> ScheduleProblem:
    return ScheduleProblem.model_validate_json(path.read_text(encoding="utf-8"))


def _write_runtime_replay(
    *,
    output_dir: Path | None,
    artifact_kind: Literal["runtime-solve", "runtime-repair"],
    artifact_source: str,
    problem: ScheduleProblem,
    result,
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

    solve_request_parser = subparsers.add_parser(
        "solve-request",
        help="Execute a stable solve request JSON contract",
    )
    solve_request_parser.add_argument("request", type=Path, help="Path to a SolveRequest JSON file")
    solve_request_parser.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Directory where runtime replay artifacts should be written",
    )

    repair_request_parser = subparsers.add_parser(
        "repair-request",
        help="Execute a stable repair request JSON contract",
    )
    repair_request_parser.add_argument(
        "request",
        type=Path,
        help="Path to a RepairRequest JSON file",
    )
    repair_request_parser.add_argument(
        "--replay-output-dir",
        type=Path,
        help="Directory where runtime replay artifacts should be written",
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
        json.dump(result.model_dump(mode="json"), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.command == "solve-request":
        request = SolveRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
        response = execute_solve_request(request)
        _write_runtime_replay(
            output_dir=args.replay_output_dir,
            artifact_kind="runtime-solve",
            artifact_source="synaps.cli.solve-request",
            problem=request.problem,
            result=response.result,
            request_summary={
                "request_path": str(args.request),
                "solver_config": request.solver_config,
                "regime": request.context.regime.value,
                "preferred_max_latency_s": request.context.preferred_max_latency_s,
                "exact_required": request.context.exact_required,
                "verify_feasibility": request.verify_feasibility,
                "solve_options": request.solve_options.model_dump(exclude_none=True),
            },
            request_id=request.request_id,
            solver_config=request.solver_config,
            stem_parts=(request.request_id or args.request.stem, request.solver_config or "AUTO", "runtime-solve"),
        )
        json.dump(response.model_dump(mode="json"), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.command == "repair-request":
        request = RepairRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
        response = execute_repair_request(request)
        _write_runtime_replay(
            output_dir=args.replay_output_dir,
            artifact_kind="runtime-repair",
            artifact_source="synaps.cli.repair-request",
            problem=request.problem,
            result=response.result,
            request_summary={
                "request_path": str(args.request),
                "regime": request.regime.value,
                "radius": request.radius,
                "verify_feasibility": request.verify_feasibility,
                "base_assignment_count": len(request.base_assignments),
                "disrupted_operation_count": len(request.disrupted_op_ids),
            },
            request_id=request.request_id,
            solver_config="INCREMENTAL_REPAIR",
            stem_parts=(request.request_id or args.request.stem, "INCREMENTAL_REPAIR", "runtime-repair"),
        )
        json.dump(response.model_dump(mode="json"), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.command == "write-contract-schemas":
        written = write_contract_schemas(args.output_dir)
        json.dump([str(path) for path in written], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


__all__ = ["main"]