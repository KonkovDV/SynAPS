"""Empirical impact of the machine_tsp Benders cut on LBBD master strength.

R5 (audit-2026-05-03): the Wave 3 commit shipped the BHK machine-TSP cut and
its master-LB telemetry but did not quantify the per-iteration LB tightening
on a real instance. This script runs LBBD twice on each medium fixture
(`enable_machine_tsp_cuts=False` baseline vs `True`) and dumps the master-LB
trajectory plus cut-pool composition to disk. The accompanying SUMMARY.md
table is generated from the same JSON artefacts.

Run (the artefact directory leading digit and dash forbid `python -m`):
    python benchmark/studies/2026-05-03-lbbd-machine-tsp-impact/run.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
# The artefact directory is non-importable (the dashed/numeric leading name is
# not a valid Python identifier), so the script is launched with `python
# path/to/run.py` rather than `python -m`. Stitch the repo root onto sys.path
# so the `benchmark` and `synaps` packages resolve.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchmark.run_benchmark import load_problem  # noqa: E402
from synaps.solvers.lbbd_solver import LbbdSolver  # noqa: E402

INSTANCES_DIR = REPO_ROOT / "benchmark" / "instances"
ARTIFACT_DIR = Path(__file__).resolve().parent

# R5: single fixture with setup matrix stress pattern. medium_20x10 excluded
# because CP-SAT subproblems stall under the default sub_time_limit_s
# derived from time_limit_s // max_iterations.
INSTANCE_NAMES = ["medium_stress_20x4"]
TIME_LIMIT_S = 20
MAX_ITERATIONS = 10
RANDOM_SEED = 42


def _condense_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Keep only the fields that quantify master-strength evolution."""

    return {
        "iterations": metadata.get("iterations"),
        "lower_bound": metadata.get("lower_bound"),
        "upper_bound": metadata.get("upper_bound"),
        "gap": metadata.get("gap"),
        "lb_evolution": metadata.get("lb_evolution"),
        "cut_kind_lb_contribution": metadata.get("cut_kind_lb_contribution"),
        "cut_pool": metadata.get("cut_pool"),
        "iteration_log": [
            {
                key: entry.get(key)
                for key in (
                    "iteration",
                    "master_bound",
                    "sub_makespan",
                    "lb_delta",
                    "cut_kinds_attributed",
                    "status",
                )
                if key in entry
            }
            for entry in metadata.get("iteration_log", [])
        ],
    }


def _run_one(instance_name: str, *, enable_tsp: bool) -> dict[str, Any]:
    instance_path = INSTANCES_DIR / f"{instance_name}.json"
    problem = load_problem(instance_path)

    t0 = time.monotonic()
    result = LbbdSolver().solve(
        problem,
        time_limit_s=TIME_LIMIT_S,
        max_iterations=MAX_ITERATIONS,
        random_seed=RANDOM_SEED,
        setup_relaxation=False,  # focus the master on cut-driven tightening
        enable_machine_tsp_cuts=enable_tsp,
        # Run sub-problems serially: we have observed parallel CP-SAT
        # workers stalling on the larger fixture under sub_time_limit_s
        # bounds derived from `time_limit_s // max_iterations`. The benchmark
        # only needs deterministic LB telemetry, not throughput.
        parallel_subproblems=False,
        use_greedy_warm_start=True,
    )
    wall_clock_s = time.monotonic() - t0

    return {
        "instance": instance_name,
        "config": "with_machine_tsp" if enable_tsp else "baseline_without_tsp",
        "enable_machine_tsp_cuts": enable_tsp,
        "status": result.status.value,
        "wall_clock_s": round(wall_clock_s, 3),
        "duration_ms": result.duration_ms,
        "metadata": _condense_metadata(result.metadata),
    }


def _format_lb_evolution(values: list[float]) -> str:
    if not values:
        return "_(no master solves)_"
    return ", ".join(f"{v:.2f}" for v in values)


def _render_summary(records: list[dict[str, Any]]) -> str:
    lines: list[str] = [
        "# LBBD machine_tsp cut — empirical impact",
        "",
        "**Date:** 2026-05-03  ",
        "**Audit ID:** R5  ",
        f"**Solver config:** time_limit_s={TIME_LIMIT_S}, max_iterations={MAX_ITERATIONS}, "
        f"random_seed={RANDOM_SEED}, setup_relaxation=False  ",
        "",
        "Each instance was solved twice with the only varying input being",
        "`enable_machine_tsp_cuts`. The baseline reuses the legacy",
        "sequence-independent `setup_cost` floor; the experimental run prefers",
        "the Bellman-Held-Karp `machine_tsp` bound when it applies.",
        "",
        "## Headline metrics",
        "",
        "| Instance | Config | LB | UB | Gap | Iter | Wall (s) | Cuts | Skipped dup |",
        "|---|---|---:|---:|---:|---:|---:|---|---:|",
    ]

    for record in records:
        meta = record["metadata"]
        cuts = meta.get("cut_pool") or {}
        kinds_str = ", ".join(
            f"{kind}={count}" for kind, count in sorted((cuts.get("kinds") or {}).items())
        ) or "_none_"
        gap = meta.get("gap")
        gap_str = f"{gap:.4f}" if isinstance(gap, (int, float)) else "-"
        lb_str = (
            f"{meta['lower_bound']:.2f}"
            if isinstance(meta.get("lower_bound"), (int, float))
            else "-"
        )
        ub_str = (
            f"{meta['upper_bound']:.2f}"
            if isinstance(meta.get("upper_bound"), (int, float))
            and meta["upper_bound"] != float("inf")
            else "-"
        )
        lines.append(
            f"| {record['instance']} | {record['config']} | {lb_str} | {ub_str} | "
            f"{gap_str} | {meta.get('iterations', 0)} | {record['wall_clock_s']} | "
            f"{kinds_str} | {cuts.get('skipped_duplicate', 0)} |"
        )

    lines.extend(["", "## Per-iteration master LB trajectory", ""])
    for record in records:
        lines.append(f"### {record['instance']} — {record['config']}")
        meta = record["metadata"]
        lines.append("")
        lines.append("- **lb_evolution:** " + _format_lb_evolution(meta.get("lb_evolution") or []))
        contribution = meta.get("cut_kind_lb_contribution") or {}
        if contribution:
            attribution = ", ".join(
                f"{kind}={value:.2f}" for kind, value in sorted(contribution.items())
            )
        else:
            attribution = "_(no positive deltas attributed)_"
        lines.append(f"- **cut_kind_lb_contribution:** {attribution}")
        lines.append("")

    lines.extend(
        [
            "## Reading the table",
            "",
            "- **LB / UB / Gap** are the final master lower bound, best feasible upper",
            "  bound, and `(UB - LB) / max(UB, eps)` reported by the solver.",
            "- **lb_evolution** is the master LB after each iteration's HiGHS solve.",
            "- **cut_kind_lb_contribution** attributes each iteration's positive",
            "  ΔLB to the cut kinds added in the previous iteration; mixed-kind",
            "  iterations split the delta equally.",
            "- **Skipped dup** counts cuts suppressed by the R3 fingerprint dedup.",
            "",
            "Reproduce: `python benchmark/studies/2026-05-03-lbbd-machine-tsp-impact/run.py`.",
        ]
    )

    return "\n".join(lines) + "\n"


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for instance_name in INSTANCE_NAMES:
        for enable_tsp in (False, True):
            print(
                f"[run] instance={instance_name} "
                f"enable_machine_tsp_cuts={enable_tsp}",
                flush=True,
            )
            record = _run_one(instance_name, enable_tsp=enable_tsp)
            records.append(record)
            artefact_path = ARTIFACT_DIR / (
                f"{instance_name}__"
                f"{'tsp' if enable_tsp else 'baseline'}.json"
            )
            artefact_path.write_text(
                json.dumps(record, indent=2, default=str), encoding="utf-8"
            )
            print(
                f"      LB={record['metadata'].get('lower_bound')} "
                f"UB={record['metadata'].get('upper_bound')} "
                f"iter={record['metadata'].get('iterations')} "
                f"wall={record['wall_clock_s']}s",
                flush=True,
            )

    summary_path = ARTIFACT_DIR / "SUMMARY.md"
    summary_path.write_text(_render_summary(records), encoding="utf-8")
    print(f"[done] summary -> {summary_path}", flush=True)


if __name__ == "__main__":
    main()
