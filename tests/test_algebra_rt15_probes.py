"""Wave 15 algebra probes: status = notary, not coverage.

A15-P0-1: RHC FEASIBLE ⇒ proven hard violations empty.
A15-P0-4: stabilize residual at pass cap is visible (converged=0).
A15-P0-5: empty disruption must not legalize a forged base plan.
"""

from __future__ import annotations

import pytest

from synaps.portfolio import repair_schedule
from synaps.solvers.feasibility_checker import FeasibilityChecker, proven_hard_violations
from synaps.solvers.rhc import RhcSolver
from tests.conftest import make_simple_problem


def test_rhc_feasible_implies_notary_clean() -> None:
    problem = make_simple_problem(n_orders=2, ops_per_order=2)
    result = RhcSolver().solve(problem)
    hard = proven_hard_violations(FeasibilityChecker().check(problem, result.assignments))
    if result.status.value == "feasible":
        assert hard == []
        assert result.metadata.get("temporal_stabilization_converged") is True
        assert result.metadata.get("notary_hard_violation_count") == 0
    else:
        assert result.status.value == "error"


def test_repair_rejects_empty_disruption() -> None:
    problem = make_simple_problem(n_orders=1, ops_per_order=1)
    with pytest.raises(ValueError, match="disrupted_op_ids must be non-empty"):
        repair_schedule(
            problem,
            base_assignments=[],
            disrupted_op_ids=[],
        )
