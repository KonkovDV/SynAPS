"""Microbenchmark: scalar vs batch vs native ATCS acceleration paths.

This script compares three execution modes for the ATCS log-score hot path:
1) scalar_python: per-candidate scalar calls with native scalar disabled
2) batch_python: SoA batch call with native batch disabled
3) batch_active: SoA batch call using active backend (native if installed)

The output is a JSON report suitable for CI artifact storage.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import platform
from random import Random
import statistics
import sys
import time
from typing import TYPE_CHECKING, Any

from synaps import accelerators

if TYPE_CHECKING:
    from collections.abc import Iterator


def _parse_sizes(raw: str) -> list[int]:
    sizes: list[int] = []
    for chunk in raw.split(","):
        value = int(chunk.strip())
        if value <= 0:
            raise ValueError(f"size must be positive, got {value}")
        sizes.append(value)
    if not sizes:
        raise ValueError("at least one size is required")
    return sizes


def _mean_nonzero(values: list[float]) -> float:
    nonzero = [value for value in values if value > 0.0]
    if not nonzero:
        return 1.0
    return max(sum(nonzero) / len(nonzero), 1.0)


def _generate_vectors(size: int, seed: int) -> dict[str, Any]:
    rng = Random(seed)

    weights = [rng.uniform(0.5, 3.0) for _ in range(size)]
    processing = [rng.uniform(0.5, 120.0) for _ in range(size)]

    # Slack mixes overdue and non-overdue cases.
    slack = [rng.uniform(-180.0, 720.0) for _ in range(size)]

    setup_minutes = [
        0.0 if rng.random() < 0.7 else rng.uniform(1.0, 45.0)
        for _ in range(size)
    ]
    material_loss = [
        0.0 if rng.random() < 0.8 else rng.uniform(0.1, 5.0)
        for _ in range(size)
    ]

    ready_p_bar = max(sum(processing) / max(size, 1), 1.0)
    setup_scale = [_mean_nonzero(setup_minutes)] * size
    material_scale = _mean_nonzero(material_loss)

    return {
        "weights": weights,
        "processing_minutes": processing,
        "slack": slack,
        "ready_p_bar": ready_p_bar,
        "setup_minutes": setup_minutes,
        "setup_scale": setup_scale,
        "material_loss": material_loss,
        "material_scale": material_scale,
    }


@contextmanager
def _force_python_backend(*, disable_scalar: bool, disable_batch: bool) -> Iterator[None]:
    original_scalar = accelerators._native_compute_atcs_log_score
    original_batch = accelerators._native_compute_atcs_log_scores_batch
    try:
        if disable_scalar:
            accelerators._native_compute_atcs_log_score = None
        if disable_batch:
            accelerators._native_compute_atcs_log_scores_batch = None
        yield
    finally:
        accelerators._native_compute_atcs_log_score = original_scalar
        accelerators._native_compute_atcs_log_scores_batch = original_batch


def _run_scalar(vectors: dict[str, Any]) -> list[float]:
    n = len(vectors["weights"])
    return [
        accelerators.compute_atcs_log_score(
            weight=vectors["weights"][index],
            processing_minutes=vectors["processing_minutes"][index],
            slack=vectors["slack"][index],
            ready_p_bar=vectors["ready_p_bar"],
            setup_minutes=vectors["setup_minutes"][index],
            setup_scale=vectors["setup_scale"][index],
            k1=2.0,
            k2=0.5,
            material_loss=vectors["material_loss"][index],
            material_scale=vectors["material_scale"],
            k3=0.5,
        )
        for index in range(n)
    ]


def _run_batch(vectors: dict[str, Any]) -> list[float]:
    return accelerators.compute_atcs_log_scores_batch(
        weights=vectors["weights"],
        processing_minutes=vectors["processing_minutes"],
        slack=vectors["slack"],
        ready_p_bar=vectors["ready_p_bar"],
        setup_minutes=vectors["setup_minutes"],
        setup_scale=vectors["setup_scale"],
        k1=2.0,
        k2=0.5,
        material_loss=vectors["material_loss"],
        material_scale=vectors["material_scale"],
        k3=0.5,
    )


def _benchmark_mode(
    *,
    label: str,
    repeats: int,
    runner: Any,
    vectors: dict[str, Any],
) -> dict[str, Any]:
    timings_ms: list[float] = []
    checksum = 0.0

    for _ in range(repeats):
        start = time.perf_counter()
        scores = runner(vectors)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings_ms.append(elapsed_ms)
        checksum = sum(scores)

    return {
        "mode": label,
        "runs": repeats,
        "min_ms": round(min(timings_ms), 6),
        "median_ms": round(statistics.median(timings_ms), 6),
        "mean_ms": round(statistics.mean(timings_ms), 6),
        "checksum": round(checksum, 6),
    }


def _max_abs_diff(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("cannot compare vectors of different lengths")
    if not left:
        return 0.0
    return max(abs(a - b) for a, b in zip(left, right, strict=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare scalar/batch/native ATCS paths")
    parser.add_argument(
        "--sizes",
        type=str,
        default="5000,50000",
        help="Comma-separated candidate vector sizes",
    )
    parser.add_argument("--repeats", type=int, default=5, help="Repetitions per mode")
    parser.add_argument("--seed", type=int, default=20260418, help="Base random seed")
    parser.add_argument(
        "--output",
        type=str,
        default="benchmark/results/native-atcs-acceleration.json",
        help="JSON output path",
    )
    args = parser.parse_args()

    if args.repeats <= 0:
        raise ValueError("--repeats must be positive")

    sizes = _parse_sizes(args.sizes)

    report: dict[str, Any] = {
        "python": {
            "version": sys.version,
            "implementation": platform.python_implementation(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "backend_status": accelerators.get_acceleration_status(),
        "sizes": [],
    }

    for offset, size in enumerate(sizes):
        vectors = _generate_vectors(size=size, seed=args.seed + offset)

        with _force_python_backend(disable_scalar=True, disable_batch=True):
            scalar_python = _benchmark_mode(
                label="scalar_python",
                repeats=args.repeats,
                runner=_run_scalar,
                vectors=vectors,
            )
            scalar_reference = _run_scalar(vectors)

        with _force_python_backend(disable_scalar=False, disable_batch=True):
            batch_python = _benchmark_mode(
                label="batch_python",
                repeats=args.repeats,
                runner=_run_batch,
                vectors=vectors,
            )
            batch_python_reference = _run_batch(vectors)

        batch_active = _benchmark_mode(
            label="batch_active",
            repeats=args.repeats,
            runner=_run_batch,
            vectors=vectors,
        )
        batch_active_reference = _run_batch(vectors)

        report["sizes"].append(
            {
                "size": size,
                "results": [scalar_python, batch_python, batch_active],
                "consistency": {
                    "max_abs_diff_scalar_vs_batch_python": round(
                        _max_abs_diff(scalar_reference, batch_python_reference),
                        12,
                    ),
                    "max_abs_diff_batch_python_vs_batch_active": round(
                        _max_abs_diff(batch_python_reference, batch_active_reference),
                        12,
                    ),
                },
            }
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)

    print(
        json.dumps(
            {
                "output": str(output_path),
                "backend_status": report["backend_status"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
