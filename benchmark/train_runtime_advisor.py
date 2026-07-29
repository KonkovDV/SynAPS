"""Train a torch-free JSON k-NN solver advisor from benchmark reports.

Reads one or more benchmark report JSON files produced by
``python -m benchmark.run_benchmark ... --compare`` and emits a
``synaps-knn-advisor-v1`` model artifact loadable via
``RuntimePredictor.load_json()``.

Labeling rule (deterministic): for each instance, the *best* solver is the
comparison entry with verified feasibility and the lowest
``(weighted_sum, wall_time_s_mean)`` tuple. Instances without at least one
feasible verified entry are skipped — the advisor must never learn from
unverified schedules (ADR-006: no advisory bypasses the feasibility gate).

Usage::

    python -m benchmark.train_runtime_advisor \
        reports/*.json --output models/knn_advisor.json --k 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from synaps.ml_advisory import JSON_KNN_MODEL_SCHEMA

#: Feature keys in ProblemFeatures.as_list() order — must stay in sync with
#: synaps.ml_advisory.ProblemFeatures.
FEATURE_KEYS: tuple[str, ...] = (
    "operation_count",
    "work_center_count",
    "avg_ops_per_order",
    "setup_density",
    "flexibility",
    "precedence_depth",
    "resource_contention",
    "aux_utilization",
    "sdst_ratio",
)


def _profile_to_features(profile: dict[str, Any]) -> list[float] | None:
    """Map a benchmark ``problem_profile`` block to the 9-dim feature vector.

    Profile keys differ slightly from feature names; missing derivable
    fields are computed, otherwise the report is skipped (return None).
    """
    try:
        operation_count = float(profile["operation_count"])
        work_center_count = float(profile["work_center_count"])
        order_count = float(profile.get("order_count", 0.0))
        avg_ops = operation_count / order_count if order_count > 0 else operation_count
        setup_density = float(profile.get("setup_density", 0.0))
        avg_eligible = float(profile.get("avg_eligible_work_centers", work_center_count))
        flexibility = avg_eligible / work_center_count if work_center_count > 0 else 1.0
        precedence_depth = float(profile.get("precedence_depth", 0.0))
        resource_contention = float(profile.get("resource_contention", 0.0))
        aux_requirement_count = float(profile.get("aux_requirement_count", 0.0))
        aux_utilization = (
            aux_requirement_count / operation_count if operation_count > 0 else 0.0
        )
        setup_entry_count = float(profile.get("setup_entry_count", 0.0))
        setup_nonzero = float(profile.get("setup_nonzero_entry_count", 0.0))
        sdst_ratio = setup_nonzero / setup_entry_count if setup_entry_count > 0 else 0.0
    except (KeyError, TypeError, ValueError):
        return None
    return [
        operation_count,
        work_center_count,
        round(avg_ops, 3),
        setup_density,
        round(flexibility, 3),
        precedence_depth,
        resource_contention,
        round(aux_utilization, 3),
        round(sdst_ratio, 3),
    ]


def _extract_sample(report: dict[str, Any]) -> dict[str, Any] | None:
    """Turn one benchmark report (with ``comparisons``) into a training sample."""
    profile = report.get("problem_profile")
    comparisons = report.get("comparisons")
    if not isinstance(profile, dict) or not isinstance(comparisons, list):
        return None

    features = _profile_to_features(profile)
    if features is None:
        return None

    candidates: list[tuple[float, float, str]] = []
    runtime_ms: dict[str, float] = {}
    for entry in comparisons:
        if not isinstance(entry, dict):
            continue
        solver_config = entry.get("solver_config")
        results = entry.get("results", {})
        verification = entry.get("verification", {})
        stats = entry.get("statistics", {})
        if not isinstance(solver_config, str):
            continue
        wall_mean_s = float(stats.get("wall_time_s_mean", 0.0))
        runtime_ms[solver_config] = round(wall_mean_s * 1000.0, 1)
        if not (results.get("feasible") and verification.get("feasible")):
            continue
        candidates.append(
            (float(results.get("weighted_sum", float("inf"))), wall_mean_s, solver_config)
        )

    if not candidates:
        return None
    candidates.sort()
    best_solver = candidates[0][2]
    return {"features": features, "best_solver": best_solver, "runtime_ms": runtime_ms}


def build_model(samples: list[dict[str, Any]], *, k: int, model_version: str) -> dict[str, Any]:
    """Assemble the JSON artifact: normalisation stats + raw samples."""
    if not samples:
        raise ValueError("no usable training samples (need verified feasible comparisons)")
    columns = list(zip(*(sample["features"] for sample in samples), strict=True))
    feature_means = [round(statistics.fmean(column), 6) for column in columns]
    feature_stds = [
        round(statistics.pstdev(column), 6) if len(column) > 1 else 1.0 for column in columns
    ]
    return {
        "schema": JSON_KNN_MODEL_SCHEMA,
        "model_version": model_version,
        "k": max(1, min(k, len(samples))),
        "feature_keys": list(FEATURE_KEYS),
        "feature_means": feature_means,
        "feature_stds": feature_stds,
        "samples": samples,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the SynAPS JSON k-NN solver advisor")
    parser.add_argument("reports", nargs="+", type=Path, help="Benchmark report JSON files")
    parser.add_argument("--output", type=Path, required=True, help="Output model path")
    parser.add_argument("--k", type=int, default=3, help="Number of neighbours (default 3)")
    parser.add_argument(
        "--model-version",
        default="knn-local",
        help="Version string embedded into the artifact",
    )
    args = parser.parse_args()

    samples: list[dict[str, Any]] = []
    skipped = 0
    for report_path in args.reports:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        reports = payload if isinstance(payload, list) else [payload]
        for report in reports:
            sample = _extract_sample(report)
            if sample is None:
                skipped += 1
                continue
            samples.append(sample)

    try:
        model = build_model(samples, k=args.k, model_version=args.model_version)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.output} ({len(samples)} samples, k={model['k']}, "
        f"skipped {skipped} unusable reports)"
    )


if __name__ == "__main__":
    main()
