from __future__ import annotations

import json
from pathlib import Path

from synaps.problem_profile import build_problem_profile
from synaps.solvers.router import route_solver_config

from benchmark.generate_instances import (
    GenerationSpec,
    generate_problem,
    preset_spec,
    write_problem_instance,
)


def test_generate_problem_is_reproducible_for_the_same_seed() -> None:
    spec = preset_spec("medium", seed=17)

    first = generate_problem(spec)
    second = generate_problem(spec)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_preset_spec_large_routes_to_lbbd_large_nominal_band() -> None:
    problem = generate_problem(preset_spec("large", seed=7))

    profile = build_problem_profile(problem)
    decision = route_solver_config(problem)

    assert profile.size_band == "large"
    assert profile.operation_count > 120
    assert profile.has_aux_constraints is True
    assert profile.has_nonzero_setups is True
    assert decision.solver_config == "LBBD-10"


def test_write_problem_instance_persists_json_and_summary(tmp_path: Path) -> None:
    spec = GenerationSpec(
        n_jobs=4,
        n_machines=3,
        operations_per_job=(2, 3),
        state_count=3,
        flexibility=0.5,
        sdst_density=0.6,
        sdst_range=(6, 14),
        proc_time_range=(10, 25),
        due_date_tightness=0.45,
        aux_resource_probability=0.35,
        aux_resource_types=2,
        seed=123,
    )
    instance_path = tmp_path / "generated" / "boundary.json"

    summary = write_problem_instance(instance_path, spec)
    payload = json.loads(instance_path.read_text(encoding="utf-8"))

    assert instance_path.exists()
    assert payload["planning_horizon_start"] < payload["planning_horizon_end"]
    assert len(payload["orders"]) == 4
    assert len(payload["work_centers"]) == 3
    assert summary["seed"] == 123
    assert summary["problem_profile"]["order_count"] == 4
    assert summary["problem_profile"]["work_center_count"] == 3
    assert summary["problem_profile"]["setup_entry_count"] > 0
