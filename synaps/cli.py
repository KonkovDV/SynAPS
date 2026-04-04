"""Minimal command-line interface for the SynAPS portfolio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from synaps.contracts import (
    RepairRequest,
    SolveRequest,
    execute_repair_request,
    execute_solve_request,
    write_contract_schemas,
)
from synaps import solve_schedule
from synaps.model import ScheduleProblem
from synaps.solvers.registry import available_solver_configs
from synaps.solvers.router import SolveRegime, SolverRoutingContext


def _load_problem(path: Path) -> ScheduleProblem:
    return ScheduleProblem.model_validate_json(path.read_text(encoding="utf-8"))


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

    solve_request_parser = subparsers.add_parser(
        "solve-request",
        help="Execute a stable solve request JSON contract",
    )
    solve_request_parser.add_argument("request", type=Path, help="Path to a SolveRequest JSON file")

    repair_request_parser = subparsers.add_parser(
        "repair-request",
        help="Execute a stable repair request JSON contract",
    )
    repair_request_parser.add_argument(
        "request",
        type=Path,
        help="Path to a RepairRequest JSON file",
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
        context = SolverRoutingContext(
            regime=SolveRegime(args.regime),
            preferred_max_latency_s=args.preferred_max_latency_s,
            exact_required=bool(args.exact_required),
        )
        result = solve_schedule(
            problem,
            context=context,
            solver_config=args.solver_config,
            verify_feasibility=not args.no_verify_feasibility,
        )
        json.dump(result.model_dump(mode="json"), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.command == "solve-request":
        request = SolveRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
        response = execute_solve_request(request)
        json.dump(response.model_dump(mode="json"), sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if args.command == "repair-request":
        request = RepairRequest.model_validate_json(args.request.read_text(encoding="utf-8"))
        response = execute_repair_request(request)
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