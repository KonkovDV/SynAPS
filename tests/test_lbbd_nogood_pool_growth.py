"""N2: the LBBD cut pool must grow as the master explores assignments.

Root cause (audit v3): ``cut_pool_fingerprint`` keyed no-goods on
``(kind, bottleneck_ops, rhs)`` only. Every no-good carries an empty
``bottleneck_ops`` and ``rhs == 0.0``, so all no-goods collapse to the single
fingerprint ``("nogood", frozenset(), 0.0)``. The second no-good (for a
different assignment) is dropped as a duplicate, so the master keeps excluding
only the first assignment and returns the second one forever: on ``tiny_3x3``
this produced ``pool_size=1, skipped_duplicate=19`` over 20 iterations. A no-good
MUST be distinguished by the assignment it forbids.
"""

from __future__ import annotations

import json
from pathlib import Path

from synaps.model import ScheduleProblem
from synaps.solvers._lbbd_cuts import cut_pool_fingerprint
from synaps.solvers.lbbd_solver import LbbdSolver, _BendersCut

_INSTANCES = Path(__file__).resolve().parent.parent / "benchmark" / "instances"


def _load(name: str) -> ScheduleProblem:
    return ScheduleProblem.model_validate(json.loads((_INSTANCES / f"{name}.json").read_text()))


def test_nogood_fingerprint_distinguishes_assignments() -> None:
    """Two no-goods over different assignments must not collapse to one entry."""
    from uuid import uuid4

    op_a, op_b, wc_1, wc_2 = uuid4(), uuid4(), uuid4(), uuid4()
    cut_1 = _BendersCut(
        assignment_map={op_a: wc_1, op_b: wc_2}, kind="nogood", rhs=0.0, bottleneck_ops=set()
    )
    cut_2 = _BendersCut(
        assignment_map={op_a: wc_2, op_b: wc_1}, kind="nogood", rhs=0.0, bottleneck_ops=set()
    )
    assert cut_pool_fingerprint(cut_1) != cut_pool_fingerprint(cut_2)
    # An identical assignment still deduplicates.
    cut_1_again = _BendersCut(
        assignment_map={op_a: wc_1, op_b: wc_2}, kind="nogood", rhs=0.0, bottleneck_ops=set()
    )
    assert cut_pool_fingerprint(cut_1) == cut_pool_fingerprint(cut_1_again)


def test_lbbd_cut_pool_grows_on_tiny_instance() -> None:
    """The master must learn: pool grows and duplicates stay a minority."""
    problem = _load("tiny_3x3")
    result = LbbdSolver().solve(problem, time_limit_s=20, max_iterations=20, random_seed=42)
    pool = result.metadata.get("cut_pool", {}) or {}
    size = int(pool.get("size", 0))
    duplicates = int(pool.get("skipped_duplicate", 0))
    iterations = int(result.metadata.get("iterations", 0))
    assert size > 1, f"cut pool did not grow: size={size} (master is spinning on one assignment)"
    assert duplicates < max(iterations // 2, 1), (
        f"too many duplicate no-goods: {duplicates}/{iterations}"
    )


def test_lbbd_reports_benders_activity_honestly() -> None:
    """N2b: benders_active reflects whether the master actually learned."""
    problem = _load("tiny_3x3")
    result = LbbdSolver().solve(problem, time_limit_s=20, max_iterations=20, random_seed=42)
    pool_size = int((result.metadata.get("cut_pool", {}) or {}).get("size", 0))
    assert "benders_active" in result.metadata
    assert result.metadata["benders_active"] is (pool_size > 0)
    # When cuts were generated the degeneracy warning must be silent.
    if pool_size > 0:
        assert result.metadata["quality_warning"] is None
    else:
        assert result.metadata["quality_warning"] == "lbbd_no_cuts_degenerate"
