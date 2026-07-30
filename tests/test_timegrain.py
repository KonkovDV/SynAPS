"""P0-4: a single canonical operation-duration formula across all solvers.

Measured before the fix (Red Team audit, tag P0-4): the same operation was 3.0
minutes for CP-SAT (max(1, round(base/speed))) and 3.333 for GREEDY (raw
base/speed), so solvers optimized numerically different problems. All duration
derivations now go through ``synaps.timegrain.duration_minutes``; this test
pins the canonical formula and guards against a new ad-hoc ``base/speed``
rounding creeping back into a solver.
"""

from __future__ import annotations

import re
from pathlib import Path

from synaps.timegrain import duration_minutes

SOLVERS_DIR = Path(__file__).resolve().parent.parent / "synaps" / "solvers"


def test_duration_minutes_canonical_values() -> None:
    assert duration_minutes(10, 3.0) == 3  # 10/3 = 3.33 -> round -> 3
    assert duration_minutes(10, 1.0) == 10
    assert duration_minutes(10, 2.0) == 5
    assert duration_minutes(1, 100.0) == 1  # floored at 1
    assert duration_minutes(10, 0.0) == 10  # non-positive speed treated as 1.0


def test_no_adhoc_duration_formula_in_solvers() -> None:
    """P0-4: no solver may re-derive duration as round(base/speed) inline.

    The canonical grain lives only in synaps/timegrain.py; every other module
    must call ``duration_minutes``. This catches a regression where a solver
    reintroduces its own rounding and desynchronizes from the rest.
    """
    pattern = re.compile(r"round\(\s*[\w.]*base_duration_min\s*/")
    offenders: list[str] = []
    for path in SOLVERS_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "ad-hoc duration formula found (use timegrain.duration_minutes):\n"
        + "\n".join(offenders)
    )
