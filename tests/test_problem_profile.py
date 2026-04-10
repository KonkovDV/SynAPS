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


def test_build_problem_profile_treats_material_only_transitions_as_sequence_dependent() -> None:
    problem = make_simple_problem()
    payload = problem.model_dump()
    for entry in payload["setup_matrix"]:
        entry["setup_minutes"] = 0
        entry["energy_kwh"] = 0.0
        entry["material_loss"] = 0.0
    payload["setup_matrix"][0]["material_loss"] = 2.5

    modified_problem = problem.__class__.model_validate(payload)
    profile = build_problem_profile(modified_problem)

    assert profile.setup_nonzero_entry_count == 1
    assert profile.has_nonzero_setups is True


def test_build_problem_profile_computes_precedence_depth() -> None:
    # make_simple_problem(n_orders=2, ops_per_order=2) creates chains of length 2
    problem = make_simple_problem(n_orders=1, ops_per_order=4)

    profile = build_problem_profile(problem)

    # 4 ops in a single chain → depth = 4
    assert profile.precedence_depth == 4


def test_build_problem_profile_computes_resource_contention() -> None:
    problem = make_simple_problem(n_orders=3, ops_per_order=2)

    profile = build_problem_profile(problem)

    # 6 ops, each eligible for 2 WCs → each WC sees 6 ops → contention = 6.0
    assert profile.resource_contention == 6.0


def test_build_problem_profile_precedence_depth_single_op_per_order() -> None:
    # No predecessors → each op is a root → depth = 1
    problem = make_simple_problem(n_orders=3, ops_per_order=1)

    profile = build_problem_profile(problem)

    assert profile.precedence_depth == 1
