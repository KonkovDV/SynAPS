"""Tests for SynAPS instance profiling."""

from __future__ import annotations

from synaps.problem_profile import build_problem_profile
from tests.conftest import make_simple_problem


def test_build_problem_profile_on_simple_problem() -> None:
    problem = make_simple_problem()

    profile = build_problem_profile(problem)

    assert profile.state_count == 2
    assert profile.order_count == 2
    assert profile.operation_count == 4
    assert profile.work_center_count == 2
    assert profile.precedence_edge_count == 2
    assert profile.setup_entry_count == 4
    assert profile.setup_nonzero_entry_count == 4
    assert profile.has_nonzero_setups is True
    assert profile.has_aux_constraints is False
    assert profile.size_band == "small"


def test_build_problem_profile_uses_all_work_centers_when_eligibility_is_empty() -> None:
    problem = make_simple_problem()
    payload = problem.model_dump()
    payload["operations"][0]["eligible_wc_ids"] = []
    modified_problem = problem.__class__.model_validate(payload)

    profile = build_problem_profile(modified_problem)

    assert profile.avg_eligible_work_centers >= 1.0