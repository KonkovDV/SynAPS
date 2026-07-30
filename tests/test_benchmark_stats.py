"""D5: shared quality-study statistics helper (best/mean/std/CI/BKS)."""

from __future__ import annotations

import math

from benchmark._stats import expand_seed_repeats, summarize_runs


def test_summarize_empty_is_typed_none() -> None:
    summary = summarize_runs([])
    assert summary["n"] == 0
    assert summary["best"] is None
    assert summary["mean"] is None
    assert summary["std"] is None


def test_summarize_single_run_has_zero_spread() -> None:
    summary = summarize_runs([100.0])
    assert summary["n"] == 1
    assert summary["best"] == 100.0
    assert summary["mean"] == 100.0
    assert summary["std"] == 0.0
    assert summary["ci95_half_width"] == 0.0


def test_summarize_best_is_min_for_minimization() -> None:
    summary = summarize_runs([170.0, 174.0, 182.0])
    assert summary["best"] == 170.0
    assert math.isclose(summary["mean"], 175.333333, rel_tol=0, abs_tol=1e-4)
    # Sample std of {170,174,182} = 6.11..., positive spread.
    assert summary["std"] > 6.0
    assert summary["cv"] > 0.0
    # CI must bracket the mean.
    assert summary["ci95_low"] < summary["mean"] < summary["ci95_high"]


def test_summarize_best_is_max_when_not_minimizing() -> None:
    summary = summarize_runs([0.6, 0.9, 0.7], minimize=False)
    assert summary["best"] == 0.9


def test_summarize_deviation_from_bks() -> None:
    # best=170, mean=175.333; BKS=160 -> best dev +6.25%, mean dev +9.58%.
    summary = summarize_runs([170.0, 174.0, 182.0], bks=160.0)
    assert math.isclose(summary["best_dev_from_bks_pct"], 6.25, abs_tol=1e-2)
    assert math.isclose(summary["mean_dev_from_bks_pct"], 9.5833, abs_tol=1e-2)


def test_summarize_ignores_nan_and_none() -> None:
    summary = summarize_runs([100.0, float("nan"), None, 102.0])  # type: ignore[list-item]
    assert summary["n"] == 2
    assert summary["best"] == 100.0


def test_expand_seed_repeats_identity_for_single() -> None:
    assert expand_seed_repeats([1, 2, 3], 1) == [1, 2, 3]
    assert expand_seed_repeats([1, 2, 3], 0) == [1, 2, 3]


def test_expand_seed_repeats_derives_distinct_seeds() -> None:
    expanded = expand_seed_repeats([1, 2], 3)
    assert expanded == [1000, 1001, 1002, 2000, 2001, 2002]
    assert len(set(expanded)) == len(expanded)
