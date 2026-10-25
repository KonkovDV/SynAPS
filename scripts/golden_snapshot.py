#!/usr/bin/env python3
"""Golden behavior snapshots for behavior-preserving refactors (audit 2026-10).

Every case runs one registry configuration on a fixed instance with settings
whose search is bounded by iterations or deterministic time, and records
SHA-256 digests of the schedule, the canonical objective and the metadata
with volatile timing keys removed. Two captures taken before and after a
refactor must be identical; a difference is either a behavior change or a
case that is still wall-clock bound on the host (rerun on an idle machine).

Usage (repo root, dev environment active)::

    python scripts/golden_snapshot.py capture before.json --suite fast
    # ... refactor ...
    python scripts/golden_snapshot.py capture after.json --suite fast
    python scripts/golden_snapshot.py compare before.json after.json

``--suite full`` adds the large generated instances (several minutes).
Generated instances are cached under ``--instances-dir``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from synaps.model import ScheduleProblem  # noqa: E402
from synaps.solvers.registry import create_solver  # noqa: E402

REPO_INSTANCES = ROOT / "benchmark" / "instances"

GENERATED: dict[str, dict[str, Any]] = {
    "gen_120": {
        "n_operations": 120,
        "n_machines": 6,
        "n_states": 4,
        "horizon_hours": 96,
        "n_aux_resources": 2,
        "aux_requirement_prob": 0.2,
        "seed": 7,
    },
    "gen_600": {
        "n_operations": 600,
        "n_machines": 12,
        "n_states": 6,
        "horizon_hours": 240,
        "n_aux_resources": 3,
        "aux_requirement_prob": 0.1,
        "seed": 11,
    },
    "gen_2500": {
        "n_operations": 2500,
        "n_machines": 25,
        "n_states": 8,
        "horizon_hours": 480,
        "n_aux_resources": 4,
        "aux_requirement_prob": 0.05,
        "seed": 13,
    },
    "gen_12000": {
        "n_operations": 12000,
        "n_machines": 60,
        "n_states": 10,
        "horizon_hours": 720,
        "n_aux_resources": 5,
        "aux_requirement_prob": 0.05,
        "seed": 17,
    },
}

VOLATILE_SUBSTRINGS = (
    "_ms",
    "elapsed",
    "wall",
    "duration",
    "observed_repair",
    "ema_estimate",
    "ema_observation",
    "ema_repair",
    "seconds",
    "_per_iteration_s",
    "throughput",
    "iterations_per_s",
    "time_used",
    "runtime",
    "pace_ratio",
    "pace_final_ratio",
)

_ALNS_RHC = {
    "time_limit_s": 900,
    "alns_budget_auto_scaling_enabled": False,
    "alns_presearch_budget_guard_enabled": False,
    "coverage_pace_guard_enabled": False,
}

# (case id, instance, registry config, overrides, in fast suite)
CASES: list[tuple[str, str, str, dict[str, Any], bool]] = [
    ("cpsat10_tiny", "tiny_3x3", "CPSAT-10", {}, True),
    ("cpsat10_lanes", "parallel_lanes_setup_2x2", "CPSAT-10", {}, True),
    ("cpsat10_tsp", "medium_4state_tsp_dominance_16x4", "CPSAT-10", {}, False),
    ("cpsat30_medium", "medium_20x10", "CPSAT-30", {}, False),
    (
        "cpsat10_gen120_w",
        "gen_120",
        "CPSAT-10",
        {"objective_weights": {"setup": 1, "tardiness": 2}},
        False,
    ),
    (
        "cpsat10_stress_sym",
        "medium_stress_20x4",
        "CPSAT-10",
        {"enable_symmetry_breaking": True},
        False,
    ),
    ("cpsat_eps_setup", "pareto_setup_tradeoff_4op", "CPSAT-EPS-SETUP-110", {}, True),
    ("cpsat_pareto_sketch", "pareto_setup_tradeoff_4op", "CPSAT-PARETO-SKETCH-SETUP", {}, True),
    ("greed_600", "gen_600", "GREED", {}, True),
    ("greed_stress", "medium_stress_20x4", "GREED", {}, True),
    ("greed_tsp", "medium_4state_tsp_dominance_16x4", "GREED", {}, True),
    ("greed_lanes", "parallel_lanes_setup_2x2", "GREED", {}, True),
    ("greed_k13_2500", "gen_2500", "GREED-K1-3", {}, False),
    ("beam3_medium", "medium_20x10", "BEAM-3", {}, False),
    ("beam5_stress", "medium_stress_20x4", "BEAM-5", {}, True),
    ("beam3_120", "gen_120", "BEAM-3", {}, False),
    ("lbbd10_stress", "medium_stress_20x4", "LBBD-10", {}, True),
    ("lbbd5_120", "gen_120", "LBBD-5", {}, False),
    (
        "lbbd_hd_stress",
        "medium_stress_20x4",
        "LBBD-5-HD",
        {"max_iterations": 4, "max_ops_per_cluster": 8, "time_limit_s": 120},
        True,
    ),
    ("lbbd5hd_600", "gen_600", "LBBD-5-HD", {}, False),
    ("rhc_greedy_600", "gen_600", "RHC-GREEDY", {"time_limit_s": 600}, True),
    (
        "rhc_greedy_2500",
        "gen_2500",
        "RHC-GREEDY",
        {"time_limit_s": 600, "max_ops_per_window": 400},
        False,
    ),
    (
        "rhc_greedy_backtrack_600",
        "gen_600",
        "RHC-GREEDY",
        {
            "time_limit_s": 600,
            "max_ops_per_window": 120,
            "backtracking_enabled": True,
            "backtracking_max_ops": 12,
            "commit_precedence_gate_enabled": True,
            "precedence_ready_candidate_filter_enabled": True,
        },
        True,
    ),
    ("rhc_cover_12000", "gen_12000", "RHC-GREEDY-COVER", {"time_limit_s": 1800}, False),
    (
        "rhc_alns_600",
        "gen_600",
        "RHC-ALNS",
        {
            **_ALNS_RHC,
            "max_ops_per_window": 150,
            "window_minutes": 600,
            "overlap_minutes": 120,
            "inner_kwargs": {
                "max_iterations": 25,
                "repair_time_limit_s": 30,
                "use_cpsat_repair": False,
                "sa_auto_calibration_enabled": True,
            },
        },
        False,
    ),
    (
        "rhc_cpsat_120",
        "gen_120",
        "RHC-CPSAT",
        {"time_limit_s": 900, "max_ops_per_window": 40, "inner_kwargs": {"time_limit_s": 5}},
        True,
    ),
    ("rhc_greedy_medium", "medium_20x10", "RHC-GREEDY", {"time_limit_s": 600}, True),
    ("rhc_greedy_lanes", "parallel_lanes_setup_2x2", "RHC-GREEDY", {"time_limit_s": 600}, True),
    ("alns_medium", "medium_20x10", "ALNS-300", {"time_limit_s": 900, "max_iterations": 60}, False),
    ("alns_120", "gen_120", "ALNS-300", {"time_limit_s": 900, "max_iterations": 40}, True),
    (
        "alns_120_mab",
        "gen_120",
        "ALNS-300",
        {"time_limit_s": 900, "max_iterations": 40, "mab_pair_selection": True},
        True,
    ),
    (
        "alns_600_greedy_repair",
        "gen_600",
        "ALNS-300",
        {"time_limit_s": 900, "max_iterations": 30, "use_cpsat_repair": False},
        False,
    ),
    (
        "alns_tsp",
        "medium_4state_tsp_dominance_16x4",
        "ALNS-300",
        {"time_limit_s": 900, "max_iterations": 50},
        False,
    ),
]


def _volatile(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in VOLATILE_SUBSTRINGS)


def scrub(value: Any) -> Any:
    """Drop volatile timing keys recursively and round floats to 1e-6."""
    if isinstance(value, dict):
        return {
            k: scrub(v)
            for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
            if not _volatile(str(k))
        }
    if isinstance(value, list | tuple):
        return [scrub(v) for v in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def load_instance(name: str, instances_dir: Path) -> ScheduleProblem:
    if name in GENERATED:
        path = instances_dir / f"{name}.json"
        if not path.exists():
            from synaps.benchmarks.instance_generator import generate_large_instance

            instances_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(
                generate_large_instance(**GENERATED[name]).model_dump_json(), encoding="utf-8"
            )
    else:
        path = REPO_INSTANCES / f"{name}.json"
    return ScheduleProblem.model_validate(json.loads(path.read_text(encoding="utf-8")))


def run_case(
    instance: str, config: str, overrides: dict[str, Any], instances_dir: Path
) -> dict[str, Any]:
    problem = load_instance(instance, instances_dir)
    solver, kwargs = create_solver(config)
    merged = {**kwargs, **overrides}
    if "inner_kwargs" in overrides and "inner_kwargs" in kwargs:
        merged["inner_kwargs"] = {**dict(kwargs["inner_kwargs"]), **overrides["inner_kwargs"]}
    started = time.monotonic()
    result = solver.solve(problem, **merged)
    wall = time.monotonic() - started
    schedule = sorted(
        (
            str(a.operation_id),
            str(a.work_center_id),
            a.start_time.isoformat(),
            a.end_time.isoformat(),
            a.setup_minutes,
            str(a.lane_id),
            sorted(map(str, a.aux_resource_ids)),
        )
        for a in result.assignments
    )
    metadata = scrub(result.metadata)
    return {
        "status": str(result.status),
        "n_assign": len(result.assignments),
        "schedule": digest(schedule),
        "objective": digest(scrub(result.objective.model_dump())),
        "metadata": digest(metadata),
        "meta_dump": metadata,
        "wall_s": round(wall, 2),
    }


def capture(args: argparse.Namespace) -> int:
    selected = set(args.cases or [])
    out: dict[str, Any] = {}
    for case_id, instance, config, overrides, fast in CASES:
        if selected and case_id not in selected:
            continue
        if not selected and args.suite == "fast" and not fast:
            continue
        row = run_case(instance, config, overrides, args.instances_dir)
        out[case_id] = row
        print(
            f"{case_id:26s} {row['status']:10s} n={row['n_assign']:6d} "
            f"sched={row['schedule']} meta={row['metadata']} {row['wall_s']:.1f}s",
            flush=True,
        )
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str), encoding="utf-8")
    return 0


def compare(args: argparse.Namespace) -> int:
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    failures = 0
    for case_id in sorted(set(before) & set(after)):
        a, b = before[case_id], after[case_id]
        diffs = [
            f for f in ("status", "n_assign", "schedule", "objective", "metadata") if a[f] != b[f]
        ]
        if diffs and "metadata" in diffs:
            meta_a, meta_b = a["meta_dump"], b["meta_dump"]
            keys = sorted(set(meta_a) ^ set(meta_b))
            values = sorted(k for k in set(meta_a) & set(meta_b) if meta_a[k] != meta_b[k])
            diffs.append(f"metadata keys added/removed={keys} changed={values[:10]}")
        failures += bool(diffs)
        print(f"{case_id:26s} {'IDENTICAL' if not diffs else 'DIFF ' + '; '.join(diffs)}")
    for case_id in sorted(set(before) ^ set(after)):
        print(f"{case_id:26s} only in one capture")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture", help="run the cases and write a snapshot")
    cap.add_argument("out", type=Path)
    cap.add_argument("--suite", choices=("fast", "full"), default="fast")
    cap.add_argument("--cases", nargs="*", help="explicit case ids (override --suite)")
    cap.add_argument(
        "--instances-dir", type=Path, default=ROOT / "benchmark" / "results" / "golden-instances"
    )
    cmp_ = sub.add_parser("compare", help="compare two snapshots (exit 1 on any difference)")
    cmp_.add_argument("before", type=Path)
    cmp_.add_argument("after", type=Path)
    args = parser.parse_args(argv)
    return capture(args) if args.command == "capture" else compare(args)


if __name__ == "__main__":
    sys.exit(main())
