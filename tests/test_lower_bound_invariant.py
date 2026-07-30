"""N5 (audit v3): the reported LBBD lower bound must not be clamped to the
incumbent.

Commit a1f06f7 reported ``lower_bound = min(cut-free master relaxation,
best_ub)``. Clamping to the incumbent makes ``lb <= ub`` true *by construction*,
so the S1-class guard can no longer fail even if the relaxation becomes invalid
(> a feasible solution). The clamp muffled the very invariant it was meant to
protect. The fix reports the raw relaxation and flags the violation explicitly.
"""

from __future__ import annotations

from synaps.solvers._lbbd_cuts import reported_lower_bound


def test_raw_relaxation_reported_not_clamped() -> None:
    """An inflated relaxation is reported verbatim and flagged, not silenced."""
    reported, violated = reported_lower_bound(raw_relaxation=95.0, best_ub=90.0)
    assert reported == 95.0, "clamp to best_ub would hide an invalid relaxation"
    assert violated is True


def test_valid_relaxation_not_flagged() -> None:
    """A relaxation below the incumbent is reported and not flagged."""
    reported, violated = reported_lower_bound(raw_relaxation=67.0, best_ub=84.0)
    assert reported == 67.0
    assert violated is False


def test_no_incumbent_is_not_a_violation() -> None:
    """Without a finite incumbent there is nothing to violate."""
    reported, violated = reported_lower_bound(raw_relaxation=67.0, best_ub=float("inf"))
    assert reported == 67.0
    assert violated is False
