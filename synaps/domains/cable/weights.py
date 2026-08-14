"""Named scalarization for cable_pvc. Does not change DEFAULT_WEIGHTS."""

from __future__ import annotations

# Coverage stays level-0 in objective_sort_key. These weights only affect
# scalarize / CP-SAT / ALNS search. Makespan is demoted: plant pain is scrap,
# tardiness, and (via KPIs, not this vector) drum WIP.
CABLE_PVC_WEIGHTS: dict[str, float] = {
    "makespan": 0.05,
    "setup": 0.25,
    "material": 1.0,
    "tardiness": 1.0,
    "energy": 0.1,
}

# CP-SAT terms are integers. 0.05 would truncate to 0 if passed raw.
CABLE_PVC_CPSAT_WEIGHTS: dict[str, int] = {
    key: max(0, round(value * 100)) for key, value in CABLE_PVC_WEIGHTS.items()
}
