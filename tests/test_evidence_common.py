"""evidence_common stats (KI-N9) and cpu_flags (KI-N10)."""

from __future__ import annotations

from benchmark.evidence_common import cpu_flags, summarize_seed, t_crit_95


def test_summarize_seed_n3_matches_historical_constant() -> None:
    stats = summarize_seed([10.0, 20.0, 30.0])
    assert stats["n"] == 3
    assert stats["ci95_t_halfwidth"] is not None
    expected = t_crit_95(3)
    assert expected is not None
    assert abs(expected - 4.302652729911275) < 1e-12


def test_summarize_seed_n10_emits_t_interval() -> None:
    values = [48269, 84156, 87134, 112047, 124644, 131980, 145731, 151960, 164355, 186947]
    stats = summarize_seed(values)
    assert stats["n"] == 10
    assert stats["ci95_t_halfwidth"] is not None
    assert stats["ci95_t_low"] < stats["mean"] < stats["ci95_t_high"]
    # Cable hand row used t=2.262, df=9.
    assert abs(t_crit_95(10) - 2.2621571627409915) < 1e-9


def test_t_crit_95_uses_df_n_minus_1() -> None:
    assert t_crit_95(1) is None
    n3 = t_crit_95(3)
    n10 = t_crit_95(10)
    n11 = t_crit_95(11)
    assert n3 is not None and abs(n3 - 4.302652729911275) < 1e-12
    assert n10 is not None and abs(n10 - 2.2621571627409915) < 1e-12
    assert n11 is not None and abs(n11 - n10) > 1e-6


def test_summarize_seed_n1_has_no_interval() -> None:
    stats = summarize_seed([42.0])
    assert stats["n"] == 1
    assert stats["ci95_t_halfwidth"] is None
    assert stats["ci95_t_low"] == 42.0


def test_cpu_flags_none_or_string() -> None:
    flags = cpu_flags()
    assert flags is None or isinstance(flags, str)
