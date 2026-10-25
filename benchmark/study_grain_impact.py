"""Which published benchmark instances can the A-01 grain fix change? (T-02)

Audit 2026-10 (A-01) moved the reservation grain from ``ceil(b / v)`` to
``ceil(b / v - GRAIN_EPSILON_MIN)``. The two differ only when ``b / v`` is an
exact integer that IEEE-754 division rounds UP (e.g. ``57 / 1.14``). For each
generator/preset behind the published evidence this study counts the
(operation, eligible work center) pairs whose grain changes. A cell with zero
pairs cannot move under A-01 by construction; a non-zero cell may move on
re-capture (each affected pair reserves one minute less) and must be re-run as
a new session, never by rewriting hashed evidence.

Usage::

    python -m benchmark.study_grain_impact --out benchmark/results/grain-impact.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchmark.generate_instances import _PRESET_SPECS, generate_problem, preset_spec
from benchmark.study_cover_ladder import SCALES as COVER_LADDER_SCALES
from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.timegrain import GRAIN_EPSILON_MIN

if TYPE_CHECKING:
    from synaps.model import ScheduleProblem

SEEDS = (1, 42, 999)
MAX_LADDER_OPS = 100_000  # 200k/500k generation is minutes and GiB; same speed set
# Studies that call generate_large_instance(duration_range=(8, 24)).
SHORT_DURATION_STUDIES = ("deadzone-5k", "calendar-3000", "beam-alns-box")


def _legacy_grain(base: int, speed: float) -> int:
    return max(1, math.ceil(base / speed))


def _audited_grain(base: int, speed: float) -> int:
    return max(1, math.ceil(base / speed - GRAIN_EPSILON_MIN))


def changed_pairs(problem: ScheduleProblem) -> dict[str, int]:
    """Count operations / (operation, work center) pairs whose grain changes."""
    speed = {
        wc.id: (wc.speed_factor if wc.speed_factor > 0 else 1.0) for wc in problem.work_centers
    }
    all_ids = list(speed)
    ops_hit = pairs = 0
    for op in problem.operations:
        hit = False
        for wc_id in op.eligible_wc_ids or all_ids:
            if wc_id in op.machine_duration_overrides:
                continue  # integer override: no division, no grain
            base, factor = op.base_duration_min, speed[wc_id]
            if _legacy_grain(base, factor) != _audited_grain(base, factor):
                pairs += 1
                hit = True
        ops_hit += hit
    return {"operations": len(problem.operations), "ops_changed": ops_hit, "pairs_changed": pairs}


def run() -> dict[str, Any]:
    cells: list[dict[str, Any]] = []
    for scale in COVER_LADDER_SCALES:
        if scale["n_operations"] > MAX_LADDER_OPS:
            continue
        kwargs = {key: value for key, value in scale.items() if key != "scale_id"}
        for seed in SEEDS:
            counts = changed_pairs(generate_large_instance(**kwargs, seed=seed))
            cells.append(
                {"family": "cover-ladder", "cell": scale["scale_id"], "seed": seed, **counts}
            )
    for seed in SEEDS:
        counts = changed_pairs(
            generate_large_instance(
                n_operations=5000, n_machines=8, duration_range=(8, 24), seed=seed
            )
        )
        cells.append({"family": "duration-8-24", "cell": "5k@8", "seed": seed, **counts})
    for name in sorted(_PRESET_SPECS):
        for seed in SEEDS:
            counts = changed_pairs(generate_problem(preset_spec(name, seed=seed)))
            cells.append({"family": "preset", "cell": name, "seed": seed, **counts})
    return {
        "study": "A-01 grain impact on published benchmark generators (audit 2026-10, T-02)",
        "grain_epsilon_min": GRAIN_EPSILON_MIN,
        "short_duration_studies": list(SHORT_DURATION_STUDIES),
        "cells": cells,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = run()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    unaffected = sorted({c["cell"] for c in payload["cells"] if c["pairs_changed"] == 0})
    affected = sorted({c["cell"] for c in payload["cells"] if c["pairs_changed"] > 0})
    print("unaffected:", ", ".join(unaffected))
    print("may move on re-capture:", ", ".join(affected))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
