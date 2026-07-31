"""Best-known solutions for the public FJSP instances bundled with SynAPS.

Phase 0.1 of the final brief: the safety net that catches S1/S4/S5-class
defects automatically. All 25 defects found by the external audits were
invisible to the self-generated corpus; ``CPSAT-30`` claiming ``OPTIMAL``
worse than a known optimum on ``mk01`` would have exposed S4 and S5 on the
first run, and an LBBD ``lower_bound`` above BKS exposes an S1-class invalid
bound.

Sources
-------
* Brandimarte (1993) ``mk01``..``mk10`` BKS values: Reijnen et al., "Job Shop
  Scheduling Benchmark" (arXiv:2308.12794), Table "Brandimarte 1-10"; ``mk06``
  refined to 57 per later literature (e.g. Lunardi et al. 2020,
  Escamilla-Serna et al. 2022, both reporting 57).

Mapping caveat (KEEP IN MIND for every consumer)
------------------------------------------------
``benchmark/fjs_loader.py`` maps heterogeneous machine alternatives to
``base_duration_min = min`` over the listed alternatives (the SynAPS core
models duration per operation, not per (operation, machine) pair). The loaded
instance is therefore a RELAXATION of the true instance:

    relaxed_optimum <= true_optimum <= BKS

so the honest, machine-checkable invariants are ONE-SIDED:

* a claimed ``OPTIMAL`` makespan must be <= BKS (violation = S4/S5-class
  overstatement);
* any reported lower bound must be <= BKS (violation = S1-class invalid
  bound).

Equality against BKS becomes assertable only once per-pair durations are
modeled exactly; until then never present bundled-instance makespans as
comparable to published per-pair-exact results.
"""

from __future__ import annotations

#: instance stem -> best-known makespan (see module docstring for sources).
BRANDIMARTE_BKS: dict[str, int] = {
    "mk01": 40,
    "mk02": 26,
    "mk03": 204,
    "mk04": 60,
    "mk05": 172,
    "mk06": 57,
    "mk07": 139,
    "mk08": 523,
    "mk09": 307,
    "mk10": 197,
}

#: Instances whose BKS is a proven optimum in the literature (subset; the
#: distinction matters only once equality checks become possible).
BRANDIMARTE_PROVEN_OPTIMAL: frozenset[str] = frozenset(
    {"mk01", "mk02", "mk03", "mk04", "mk05", "mk07", "mk08", "mk09"}
)

#: Published structural sizes (jobs, machines, operations) for parse sanity.
BRANDIMARTE_SHAPE: dict[str, tuple[int, int, int]] = {
    "mk01": (10, 6, 55),
    "mk02": (10, 6, 58),
    "mk03": (15, 8, 150),
    "mk04": (15, 8, 90),
    "mk05": (15, 4, 106),
    "mk06": (10, 10, 150),
    "mk07": (20, 5, 100),
    "mk08": (20, 10, 225),
    "mk09": (20, 10, 240),
    "mk10": (20, 15, 240),
}


def mre_percent(makespan: float, lower_bound: float) -> float:
    """Mean relative error against a lower bound: ``(Cmax - LB) / LB * 100``."""
    if lower_bound <= 0:
        raise ValueError("lower_bound must be positive for MRE")
    return (makespan - lower_bound) / lower_bound * 100.0


def bks_deviation_percent(makespan: float, bks: float) -> float:
    """Deviation from the best-known solution: ``(Cmax - BKS) / BKS * 100``."""
    if bks <= 0:
        raise ValueError("bks must be positive")
    return (makespan - bks) / bks * 100.0


__all__ = [
    "BRANDIMARTE_BKS",
    "BRANDIMARTE_PROVEN_OPTIMAL",
    "BRANDIMARTE_SHAPE",
    "bks_deviation_percent",
    "mre_percent",
]
