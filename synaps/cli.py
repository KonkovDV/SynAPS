"""Minimal command-line interface for the SynAPS portfolio."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

from synaps import solve_schedule
from synaps.contracts import (
    execute_repair_request,
    execute_solve_request,
    parse_repair_request_json,
    parse_solve_request_json,
    resolve_solve_request_problem,
    write_contract_schemas,
)
from synaps.model import ScheduleProblem, ScheduleResult, normalize_schedule_problem_data
from synaps.replay import build_runtime_replay_artifact, write_replay_artifact
from synaps.solvers.registry import available_solver_configs, build_solver_registry_manifest
from synaps.solvers.router import PortfolioPolicy, SolveRegime, SolverRoutingContext


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
        "--portfolio-policy",
        choices=[policy.value for policy in PortfolioPolicy],
        default=PortfolioPolicy.BALANCED.value,
        help="Routing policy that biases the non-exact portfolio path",
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
        "--instance-dir",
        type=Path,
        help="Allowed base directory for relative problem_instance_ref files",
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
    _add_cable_demo_parser(subparsers)
    _add_cable_nervous_parser(subparsers)
    return parser


def _add_cable_demo_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "cable-demo",
        help="Synthetic cable instance → GREEDY → cable KPIs (not a factory plan)",
    )
    parser.add_argument("--orders", type=int, default=4, help="Parent sales orders before reel split")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument(
        "--output-file",
        type=Path,
        help="Optional path where the JSON result should be written instead of stdout",
    )


def _run_cable_demo(args: argparse.Namespace) -> int:
    from synaps.domains.cable import (
        CABLE_PVC_CPSAT_WEIGHTS,
        CABLE_PVC_WEIGHTS,
        cable_kpis,
        generate_cable_instance,
    )
    from synaps.objective import evaluate, scalarize
    from synaps.solvers.feasibility_checker import FeasibilityChecker, proven_hard_violations
    from synaps.solvers.greedy_dispatch import GreedyDispatch

    problem = generate_cable_instance(n_orders=args.orders, seed=args.seed)
    result = GreedyDispatch().solve(problem)
    hard = proven_hard_violations(
        FeasibilityChecker().check(problem, result.assignments, exhaustive=True)
    )
    objective = evaluate(problem, result.assignments)
    payload = {
        "status": result.status.value,
        "operations": len(problem.operations),
        "orders": len(problem.orders),
        "notary_hard_violations": len(hard),
        "kpis": cable_kpis(problem, result.assignments),
        "scalar_default": scalarize(objective),
        "scalar_cable_pvc": scalarize(objective, CABLE_PVC_WEIGHTS),
        "cpsat_weight_vector": CABLE_PVC_CPSAT_WEIGHTS,
        "claim": "synthetic encode-first cable demo; not Moskabelmet MES data",
    }
    _write_json_output(payload, args.output_file)
    return 0 if result.status.value == "feasible" and not hard else 1


def _add_cable_nervous_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "cable-nervous-month",
        help="Harsh synthetic 30-day cable month: cover-solve + freeze/rush waves",
    )
    parser.add_argument("--orders", type=int, default=1600, help="Parent sales orders")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--waves", type=int, default=4)
    parser.add_argument("--disruptions", type=int, default=20)
    parser.add_argument("--machines-per-stage", type=int, default=16)
    parser.add_argument("--drum-pool", type=int, default=96)
    parser.add_argument(
        "--cover-ready-rule",
        choices=("fifo", "atcs"),
        default="atcs",
        help="COVER ready pop: atcs scores inside a floor window "
        "(nervous default window 0 = non-delay); fifo is the 50k/500k registry default",
    )
    parser.add_argument(
        "--cover-atcs-window",
        type=float,
        default=0.0,
        help="ATCS may wait this many minutes past the earliest ready floor "
        "(0 = non-delay; one SMED of delay on any job collapsed 16-stage coverage)",
    )
    parser.add_argument(
        "--cover-atcs-exhaust",
        type=float,
        default=None,
        help="Wait this many minutes only for a zero-setup continuation "
        "(default 240 at ≤8 machines/stage, 0 at 16; not a general ATCS window)",
    )
    family = parser.add_mutually_exclusive_group()
    family.add_argument(
        "--family-lines",
        action="store_true",
        help="Dedicate machine subsets per family (PVC vs XLPE), sized by "
        "SKU-catalog share, with one flex overflow machine when n≥3 "
        "(default on when machines/stage is 3–8)",
    )
    family.add_argument(
        "--no-family-lines",
        action="store_true",
        help="Disable family-dedicated lines (default off at 16/stage)",
    )
    colour = parser.add_mutually_exclusive_group()
    colour.add_argument(
        "--colour-lines",
        action="store_true",
        help="Split colours inside the family machine list when a stage has "
        "≥6 machines (2 flex at n≥8); opt-in — drops 8-stage coverage",
    )
    colour.add_argument(
        "--no-colour-lines",
        action="store_true",
        help="Disable colour-dedicated lines (default off)",
    )
    phase = parser.add_mutually_exclusive_group()
    phase.add_argument(
        "--colour-phase",
        action="store_true",
        help="Force the colour campaign wheel (default on when colour lines are off)",
    )
    phase.add_argument(
        "--no-colour-phase",
        action="store_true",
        help="Disable colour campaign wheel",
    )
    _add_cable_nervous_experiment_flags(parser)


def _add_cable_nervous_experiment_flags(parser: Any) -> None:
    parser.add_argument(
        "--new-rush",
        type=int,
        default=2,
        help="New parent orders inserted after cover (0 disables N-R3 wave)",
    )
    parser.add_argument("--seeds", help="Comma-separated seeds; overrides --seed")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--freeze-pair", action="store_true")
    mode.add_argument(
        "--weighted-residual",
        action="store_true",
        help="C6c: COVER then ALNS makespan vs CABLE_PVC_WEIGHTS residual",
    )
    parser.add_argument("--residual-time-limit", type=float, default=120.0)
    parser.add_argument("--residual-max-iterations", type=int, default=300)
    parser.add_argument(
        "--residual-no-cpsat",
        action="store_true",
        help="Greedy ALNS repair only (CI). Probe keeps micro-CP-SAT.",
    )
    parser.add_argument("--output-file", type=Path, help="Write JSON report here")


def _tri_state(on: bool, off: bool) -> bool | None:
    if off:
        return False
    if on:
        return True
    return None


def _nervous_shop_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "n_orders": args.orders,
        "waves": args.waves,
        "disruptions_per_wave": args.disruptions,
        "machines_per_stage": args.machines_per_stage,
        "drum_pool_size": args.drum_pool,
        "family_dedicated_lines": _tri_state(args.family_lines, args.no_family_lines),
        "colour_phase": _tri_state(args.colour_phase, args.no_colour_phase),
        "colour_dedicated_lines": _tri_state(args.colour_lines, args.no_colour_lines),
        "cover_ready_rule": args.cover_ready_rule,
        "cover_atcs_floor_window": args.cover_atcs_window,
        "cover_atcs_exhaust_window": args.cover_atcs_exhaust,
        "new_rush_orders": args.new_rush,
    }


def _cover_only_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    return {
        key: kwargs[key]
        for key in kwargs
        if key not in {"waves", "disruptions_per_wave", "new_rush_orders"}
    }


def _run_freeze_pair_cli(
    seeds: tuple[int, ...], args: argparse.Namespace, kwargs: dict[str, Any]
) -> int:
    from synaps.domains.cable import run_freeze_insert_pair

    pair_kwargs = _cover_only_kwargs(kwargs)
    pair_kwargs["n_rush"] = args.new_rush
    pair_kwargs["n_steal"] = args.disruptions
    reports = [run_freeze_insert_pair(seed=item, **pair_kwargs) for item in seeds]
    report: dict[str, Any] = reports[0] if len(reports) == 1 else {
        "claim": reports[0]["claim"],
        "seeds": list(seeds),
        "runs": reports,
        "all_feasible": all(item["all_feasible"] for item in reports),
    }
    ok = bool(report["all_feasible"])
    _write_json_output(report, args.output_file)
    return 0 if ok else 1


def _run_weighted_residual_cli(
    seeds: tuple[int, ...], args: argparse.Namespace, kwargs: dict[str, Any]
) -> int:
    from synaps.domains.cable import (
        run_weighted_residual_multiseed,
        run_weighted_residual_pair,
    )

    residual_kwargs = _cover_only_kwargs(kwargs)
    residual_kwargs["residual_time_limit_s"] = args.residual_time_limit
    residual_kwargs["residual_max_iterations"] = args.residual_max_iterations
    residual_kwargs["residual_use_cpsat_repair"] = not args.residual_no_cpsat
    if len(seeds) == 1:
        report = run_weighted_residual_pair(seed=seeds[0], **residual_kwargs)
    else:
        report = run_weighted_residual_multiseed(seeds, **residual_kwargs)
    _write_json_output(report, args.output_file)
    return 0 if report["all_feasible"] else 1


def _run_cable_nervous(args: argparse.Namespace) -> int:
    from synaps.domains.cable import (
        nervous_report_ok,
        parse_nervous_seeds,
        run_nervous_month,
        run_nervous_month_multiseed,
    )

    seeds = parse_nervous_seeds(args.seeds, args.seed)
    kwargs = _nervous_shop_kwargs(args)
    if args.freeze_pair:
        return _run_freeze_pair_cli(seeds, args, kwargs)
    if args.weighted_residual:
        return _run_weighted_residual_cli(seeds, args, kwargs)
    if len(seeds) == 1:
        report = run_nervous_month(seed=seeds[0], **kwargs)
    else:
        report = run_nervous_month_multiseed(seeds, **kwargs)
    _write_json_output(report, args.output_file)
    return 0 if nervous_report_ok(report) else 1


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
            portfolio_policy=PortfolioPolicy(args.portfolio_policy),
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
                "portfolio_policy": args.portfolio_policy,
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
        instance_dir = args.instance_dir
        if instance_dir is None and args.request != "-":
            instance_dir = Path(args.request).resolve().parent

        resolved_problem = resolve_solve_request_problem(
            solve_request,
            instance_dir=instance_dir,
        )
        solve_response = execute_solve_request(
            solve_request,
            instance_dir=instance_dir,
            resolved_problem=resolved_problem,
        )
        request_stem = "stdin" if args.request == "-" else Path(args.request).stem
        _write_runtime_replay(
            output_dir=args.replay_output_dir,
            artifact_kind="runtime-solve",
            artifact_source="synaps.cli.solve-request",
            problem=resolved_problem,
            result=solve_response.result,
            request_summary={
                "request_path": str(args.request),
                "problem_instance_ref": solve_request.problem_instance_ref,
                "solver_config": solve_request.solver_config,
                "regime": solve_request.context.regime.value,
                "preferred_max_latency_s": solve_request.context.preferred_max_latency_s,
                "exact_required": solve_request.context.exact_required,
                "portfolio_policy": solve_request.context.portfolio_policy.value,
                "verify_feasibility": solve_request.verify_feasibility,
                "problem_slice": (
                    solve_request.problem_slice.model_dump(mode="json", exclude_none=True)
                    if solve_request.problem_slice is not None
                    else None
                ),
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

    elif args.command == "cable-demo":
        return _run_cable_demo(args)

    elif args.command == "cable-nervous-month":
        return _run_cable_nervous(args)

    parser.error(f"Unsupported command: {args.command}")


__all__ = ["main"]
