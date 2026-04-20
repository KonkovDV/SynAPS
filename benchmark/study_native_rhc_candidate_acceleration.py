"""Microbenchmark: Python vs active backend for RHC candidate metric scoring.

This script compares two execution modes for the RHC candidate-metrics hot path:
1) batch_python: batch call with the native RHC backend disabled
2) batch_active: batch call using the active backend (native if installed)

The output is a JSON report suitable for CI artifact storage and large-scale
performance tracking at 50k+/100k+/500k+ candidate counts.
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


def _mean(values: list[float]) -> float:
    if not values:
        return 1.0
    return max(sum(values) / len(values), 1.0)


def _build_eligible_patterns(
    *,
    rng: Random,
    machine_count: int,
    pattern_count: int,
    min_width: int,
    max_width: int,
) -> list[list[int]]:
    patterns: list[list[int]] = []
    for _ in range(pattern_count):
        width = rng.randint(min_width, max_width)
        patterns.append(sorted(rng.sample(range(machine_count), k=width)))
    return patterns


def _generate_vectors(
    *,
    size: int,
    seed: int,
    machine_count: int = 128,
    pattern_count: int = 64,
) -> dict[str, Any]:
    rng = Random(seed)

    machine_available_offsets = [rng.uniform(0.0, 24_000.0) for _ in range(machine_count)]
    predecessor_end_offsets = [rng.uniform(0.0, 24_000.0) for _ in range(size)]
    due_offsets = [rng.uniform(60.0, 28_000.0) for _ in range(size)]
    rpt_tail_minutes = [rng.uniform(5.0, 480.0) for _ in range(size)]
    order_weights = [rng.uniform(1.0, 10.0) for _ in range(size)]
    p_tilde_minutes = [rng.uniform(1.0, 120.0) for _ in range(size)]

    patterns = _build_eligible_patterns(
        rng=rng,
        machine_count=machine_count,
        pattern_count=pattern_count,
        min_width=1,
        max_width=4,
    )
    eligible_machine_indices = [patterns[index % pattern_count] for index in range(size)]

    return {
        "machine_available_offsets": machine_available_offsets,
        "eligible_machine_indices": eligible_machine_indices,
        "predecessor_end_offsets": predecessor_end_offsets,
        "due_offsets": due_offsets,
        "rpt_tail_minutes": rpt_tail_minutes,
        "order_weights": order_weights,
        "p_tilde_minutes": p_tilde_minutes,
        "avg_total_p": _mean(p_tilde_minutes),
        "due_pressure_k1": 1.0,
        "due_pressure_overdue_boost": 1.25,
        "machine_count": machine_count,
        "pattern_count": pattern_count,
    }


@contextmanager
def _force_python_backend() -> Iterator[None]:
    original = accelerators._native_compute_rhc_candidate_metrics_batch
    try:
        accelerators._native_compute_rhc_candidate_metrics_batch = None
        yield
    finally:
        accelerators._native_compute_rhc_candidate_metrics_batch = original


def _run_batch(vectors: dict[str, Any]) -> tuple[list[float], list[float]]:
    return accelerators.compute_rhc_candidate_metrics_batch(
        machine_available_offsets=vectors["machine_available_offsets"],
        eligible_machine_indices=vectors["eligible_machine_indices"],
        predecessor_end_offsets=vectors["predecessor_end_offsets"],
        due_offsets=vectors["due_offsets"],
        rpt_tail_minutes=vectors["rpt_tail_minutes"],
        order_weights=vectors["order_weights"],
        p_tilde_minutes=vectors["p_tilde_minutes"],
        avg_total_p=vectors["avg_total_p"],
        due_pressure_k1=vectors["due_pressure_k1"],
        due_pressure_overdue_boost=vectors["due_pressure_overdue_boost"],
    )


def _benchmark_mode(
    *,
    label: str,
    repeats: int,
    vectors: dict[str, Any],
) -> dict[str, Any]:
    timings_ms: list[float] = []
    slack_checksum = 0.0
    pressure_checksum = 0.0

    for _ in range(repeats):
        start = time.perf_counter()
        slacks, pressures = _run_batch(vectors)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings_ms.append(elapsed_ms)
        slack_checksum = sum(slacks)
        pressure_checksum = sum(pressures)

    return {
        "mode": label,
        "runs": repeats,
        "min_ms": round(min(timings_ms), 6),
        "median_ms": round(statistics.median(timings_ms), 6),
        "mean_ms": round(statistics.mean(timings_ms), 6),
        "slack_checksum": round(slack_checksum, 6),
        "pressure_checksum": round(pressure_checksum, 6),
    }


def _safe_speedup(baseline_mean_ms: float, improved_mean_ms: float) -> float | None:
    if baseline_mean_ms <= 0.0 or improved_mean_ms <= 0.0:
        return None
    return round(baseline_mean_ms / improved_mean_ms, 6)


def _max_abs_diff(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        raise ValueError("cannot compare vectors of different lengths")
    if not left:
        return 0.0
    return max(abs(a - b) for a, b in zip(left, right, strict=True))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Python vs active RHC candidate metric acceleration paths"
    )
    parser.add_argument(
        "--sizes",
        type=str,
        default="50000,100000,500000",
        help="Comma-separated candidate vector sizes",
    )
    parser.add_argument("--repeats", type=int, default=3, help="Repetitions per mode")
    parser.add_argument("--seed", type=int, default=20260420, help="Base random seed")
    parser.add_argument(
        "--output",
        type=str,
        default="benchmark/results/native-rhc-candidate-acceleration.json",
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

        with _force_python_backend():
            batch_python = _benchmark_mode(
                label="batch_python",
                repeats=args.repeats,
                vectors=vectors,
            )
            python_reference = _run_batch(vectors)

        batch_active = _benchmark_mode(
            label="batch_active",
            repeats=args.repeats,
            vectors=vectors,
        )
        active_reference = _run_batch(vectors)

        report["sizes"].append(
            {
                "size": size,
                "machine_count": vectors["machine_count"],
                "pattern_count": vectors["pattern_count"],
                "results": [batch_python, batch_active],
                "consistency": {
                    "max_abs_diff_slack_python_vs_active": round(
                        _max_abs_diff(python_reference[0], active_reference[0]),
                        12,
                    ),
                    "max_abs_diff_pressure_python_vs_active": round(
                        _max_abs_diff(python_reference[1], active_reference[1]),
                        12,
                    ),
                },
                "speedups": {
                    "batch_active_over_batch_python": _safe_speedup(
                        batch_python["mean_ms"],
                        batch_active["mean_ms"],
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