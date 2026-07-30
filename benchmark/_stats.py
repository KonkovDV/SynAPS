"""Shared quality-study statistics (Red Team audit v2, tag D5).

Quality DOE studies were single-shot point estimates. With a measured ~7%
run-to-run spread (before the D1 determinism fix, and still present for the
native non-deterministic path), a point estimate is not informative. This
module provides the literature-standard aggregation every quality study should
report: best-of-N, mean-over-N, standard deviation, coefficient of variation,
a normal-approximation confidence interval, and deviation of the best and mean
from a Best-Known-Solution (BKS) when one is supplied.
"""

from __future__ import annotations

import math
import statistics
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

# z-scores for common two-sided confidence levels (normal approximation).
_Z_BY_CONFIDENCE = {0.90: 1.6448536269514722, 0.95: 1.959963984540054, 0.99: 2.5758293035489004}


def _z_for(confidence: float) -> float:
    """Return the two-sided z-score for a confidence level (nearest tabulated)."""
    return min(_Z_BY_CONFIDENCE.items(), key=lambda kv: abs(kv[0] - confidence))[1]


def summarize_runs(
    values: Sequence[float],
    *,
    bks: float | None = None,
    minimize: bool = True,
    confidence: float = 0.95,
) -> dict[str, Any]:
    """Summarize repeated quality measurements.

    ``values`` are per-run objective values (e.g. makespan) across seeds and/or
    repeats. ``minimize`` selects whether ``best`` is the min (default, e.g.
    makespan) or max. When ``bks`` is given, ``best_dev_from_bks_pct`` and
    ``mean_dev_from_bks_pct`` are the relative percentage gaps
    ``(value - bks) / bks * 100`` (always signed toward "worse than BKS" for a
    minimization objective).

    Returns an empty-but-typed summary (``n == 0``) when ``values`` is empty so
    callers never special-case the no-data path.
    """
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    n = len(clean)
    if n == 0:
        return {
            "n": 0,
            "best": None,
            "mean": None,
            "std": None,
            "cv": None,
            "ci95_half_width": None,
            "ci95_low": None,
            "ci95_high": None,
            "best_dev_from_bks_pct": None,
            "mean_dev_from_bks_pct": None,
        }

    best = min(clean) if minimize else max(clean)
    mean = statistics.mean(clean)
    # Sample standard deviation (ddof=1); 0 for a single run.
    std = statistics.stdev(clean) if n > 1 else 0.0
    cv = (std / mean) if mean else 0.0
    # Normal-approximation CI on the mean: z * std / sqrt(n).
    half_width = _z_for(confidence) * std / math.sqrt(n) if n > 1 else 0.0

    summary: dict[str, Any] = {
        "n": n,
        "best": round(best, 6),
        "mean": round(mean, 6),
        "std": round(std, 6),
        "cv": round(cv, 6),
        "ci95_half_width": round(half_width, 6),
        "ci95_low": round(mean - half_width, 6),
        "ci95_high": round(mean + half_width, 6),
        "best_dev_from_bks_pct": None,
        "mean_dev_from_bks_pct": None,
    }

    if bks is not None and math.isfinite(float(bks)) and float(bks) != 0.0:
        bks_f = float(bks)
        summary["best_dev_from_bks_pct"] = round((best - bks_f) / bks_f * 100.0, 4)
        summary["mean_dev_from_bks_pct"] = round((mean - bks_f) / bks_f * 100.0, 4)

    return summary


def expand_seed_repeats(seeds: Sequence[int], repeats: int) -> list[int]:
    """Expand ``seeds`` into ``repeats`` deterministic derived seeds each.

    A study that iterates the returned list runs every base seed ``repeats``
    times with distinct derived seeds, so the per-configuration sample captures
    both between-seed and (native) within-configuration variance while staying
    reproducible. ``repeats <= 1`` returns the seeds unchanged.
    """
    if repeats <= 1:
        return list(seeds)
    expanded: list[int] = []
    for seed in seeds:
        for r in range(repeats):
            # Deterministic, collision-free derived seed.
            expanded.append(int(seed) * 1000 + r)
    return expanded
