from __future__ import annotations

from pathlib import Path


def test_study_rhc_500k_plan_mode_skips_execution(monkeypatch, tmp_path: Path) -> None:
    import benchmark.study_rhc_500k as study_module

    def fail_if_called(**kwargs):
        raise AssertionError("run_scaling_case must not be called in plan mode")

    monkeypatch.setattr(study_module, "run_scaling_case", fail_if_called)

    report = study_module.study_rhc_500k(
        execution_mode="plan",
        scales=[50_000],
        seeds=[1],
        solver_names=["RHC-GREEDY"],
        lane="throughput",
        write_dir=tmp_path,
    )

    assert report["study_kind"] == "rhc-500k"
    assert report["execution_mode"] == "plan"
    assert report["scale_records"][0]["execution"] == "skipped"
    assert Path(report["artifact_path"]).exists()


def test_study_rhc_500k_gated_mode_respects_resource_gate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    call_count = 0

    def fake_run_scaling_case(**kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "status": "feasible",
            "feasible": True,
            "solver": kwargs["solver_name"],
            "makespan_min": 100.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": kwargs["n_ops"],
            "violations": 0,
            "solve_ms": 1,
            "gen_ms": 1,
            "verify_ms": 0,
            "n_ops": kwargs["n_ops"],
            "n_machines": kwargs["n_machines"],
            "n_states": kwargs["n_states"],
            "sdst_memory_bytes": 0,
            "metadata": {},
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[500_000],
        seeds=[1],
        solver_names=["RHC-GREEDY"],
        lane="throughput",
        max_eligible_links=1_000,
        write_dir=tmp_path,
    )

    assert call_count == 0
    record = report["scale_records"][0]
    assert record["resource_gate"]["allowed"] is False
    assert record["execution"] == "skipped"
    assert record["skip_reason"] == "resource_gate"


def test_study_rhc_500k_reports_summary_and_quality_gate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        if solver_name == "rhc-greedy":
            makespan = 100.0 + seed
            metadata = {
                "acceleration": {
                    "rhc_candidate_metrics_backend": "python",
                },
            }
        else:
            makespan = 103.0 + seed
            metadata = {
                "inner_fallback_ratio": 0.05,
                "acceleration": {
                    "rhc_candidate_metrics_backend": "native",
                },
            }

        return {
            "status": "feasible",
            "feasible": True,
            "solver": solver_name,
            "makespan_min": makespan,
            "total_setup_min": 20.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": n_ops,
            "violations": 0,
            "solve_ms": 10,
            "gen_ms": 1,
            "verify_ms": 1,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": metadata,
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[50_000],
        seeds=[1, 2],
        solver_names=["RHC-GREEDY", "RHC-ALNS"],
        lane="throughput",
        write_dir=tmp_path,
    )

    greedy_key = "RHC-GREEDY|throughput|50000"
    alns_key = "RHC-ALNS|throughput|50000"

    assert greedy_key in report["summary_by_config"]
    assert alns_key in report["summary_by_config"]
    assert report["summary_by_config"][alns_key]["feasibility_rate"] == 1.0
    assert "cvar_makespan_minutes" in report["summary_by_config"][alns_key]
    assert "mean_inner_fallback_ratio" in report["summary_by_config"][alns_key]
    greedy_run = next(
        run
        for run in report["scale_records"][0]["runs"]
        if run["solver_label"] == "RHC-GREEDY"
    )
    alns_run = next(
        run
        for run in report["scale_records"][0]["runs"]
        if run["solver_label"] == "RHC-ALNS"
    )
    assert greedy_run["results"]["acceleration"] == {
        "rhc_candidate_metrics_backend": "python",
    }
    assert alns_run["results"]["acceleration"] == {
        "rhc_candidate_metrics_backend": "native",
    }

    gate_result = report["quality_gate"]["results"][alns_key]
    assert gate_result["checks"]["feasibility"] is True
    assert gate_result["checks"]["scheduled_ratio"] is True
    assert gate_result["checks"]["fallback_ratio"] is True
    assert gate_result["checks"]["objective_degradation"] is True
    assert gate_result["passed"] is True


def test_study_rhc_500k_preserves_solver_metadata_for_audit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        return {
            "status": "error",
            "feasible": False,
            "solver": solver_name,
            "makespan_min": 123.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 5.0,
            "total_material_loss": 0.0,
            "assigned_ops": 321,
            "violations": 0,
            "solve_ms": 1000,
            "gen_ms": 1,
            "verify_ms": 1,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": {
                "ops_scheduled": 321,
                "ops_total": n_ops,
                "inner_resolution_counts": {
                    "inner": 2,
                    "fallback_greedy": 1,
                },
                "inner_fallback_reason_counts": {
                    "inner_time_limit_exhausted_before_search": 1,
                },
                "inner_window_summaries": [
                    {
                        "window": 1,
                        "resolution_mode": "inner",
                        "iterations_completed": 12,
                        "improvements": 7,
                        "initial_solution_ms": 345,
                        "time_limit_exhausted_before_search": False,
                    }
                ],
            },
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[100_000],
        seeds=[1],
        solver_names=["RHC-ALNS"],
        lane="throughput",
        write_dir=tmp_path,
    )

    run = report["scale_records"][0]["runs"][0]
    assert run["solver_metadata"]["ops_scheduled"] == 321
    assert run["solver_metadata"]["inner_resolution_counts"] == {
        "inner": 2,
        "fallback_greedy": 1,
    }
    assert run["solver_metadata"]["inner_fallback_reason_counts"] == {
        "inner_time_limit_exhausted_before_search": 1,
    }
    assert run["solver_metadata"]["inner_window_summaries"][0]["iterations_completed"] == 12
    assert run["solver_metadata"]["inner_window_summaries"][0]["initial_solution_ms"] == 345


def test_study_rhc_500k_summarizes_inner_window_audit_signals(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        return {
            "status": "error",
            "feasible": False,
            "solver": solver_name,
            "makespan_min": 123.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 5.0,
            "total_material_loss": 0.0,
            "assigned_ops": 321,
            "violations": 0,
            "solve_ms": 1000,
            "gen_ms": 1,
            "verify_ms": 1,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": {
                "inner_fallback_ratio": 0.5,
                "inner_window_summaries": [
                    {
                        "window": 1,
                        "resolution_mode": "inner",
                        "iterations_completed": 12,
                        "improvements": 7,
                        "ops_in_window": 120,
                        "ops_committed": 36,
                        "initial_solution_ms": 345,
                        "time_limit_exhausted_before_search": False,
                        "warm_start_used": True,
                    },
                    {
                        "window": 2,
                        "resolution_mode": "fallback_greedy",
                        "iterations_completed": 0,
                        "improvements": 0,
                        "ops_in_window": 180,
                        "ops_committed": 18,
                        "initial_solution_ms": 455,
                        "time_limit_exhausted_before_search": True,
                        "budget_guard_skipped_initial_search": True,
                        "warm_start_used": False,
                        "warm_start_rejected_reason": "warm_start_incomplete",
                    },
                ],
            },
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[100_000],
        seeds=[1],
        solver_names=["RHC-ALNS"],
        lane="throughput",
        write_dir=tmp_path,
    )

    inner = report["summary_by_config"]["RHC-ALNS|throughput|100000"]["inner_window_summary"]
    assert inner["windows_observed"] == 2
    assert inner["search_active_windows"] == 1
    assert inner["search_active_window_rate"] == 0.5
    assert inner["budget_guard_skipped_windows"] == 1
    assert inner["time_limit_exhausted_before_search_windows"] == 1
    assert inner["fallback_windows"] == 1
    assert inner["total_iterations_completed"] == 12
    assert inner["mean_initial_solution_ms"] == 400.0
    assert inner["max_initial_solution_ms"] == 455
    assert inner["mean_ops_in_window"] == 150.0
    assert inner["mean_ops_committed"] == 27.0
    assert inner["mean_commit_yield"] == 0.2
    assert inner["warm_start_used_windows"] == 1
    assert inner["warm_start_window_rate"] == 0.5
    assert inner["warm_start_rejected_reason_counts"] == {
        "warm_start_incomplete": 1,
    }


def test_study_rhc_500k_lane_both_profiles_workers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    captured_kwargs: list[dict] = []

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        captured_kwargs.append({
            "solver_name": solver_name,
            "solver_kwargs": solver_kwargs,
            "seed": seed,
        })
        return {
            "status": "feasible",
            "feasible": True,
            "solver": solver_name,
            "makespan_min": 100.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": n_ops,
            "violations": 0,
            "solve_ms": 1,
            "gen_ms": 1,
            "verify_ms": 0,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": {"inner_fallback_ratio": 0.0},
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[50_000],
        seeds=[11],
        solver_names=["RHC-ALNS"],
        lane="both",
        write_dir=tmp_path,
    )

    assert report["lane_mode"] == "both"
    assert len(captured_kwargs) == 2

    workers = sorted(
        {
            kwargs["solver_kwargs"]["hybrid_inner_kwargs"]["num_workers"]
            for kwargs in captured_kwargs
        }
    )
    assert workers == [1, 4]

    for kwargs in captured_kwargs:
        assert kwargs["solver_kwargs"]["random_seed"] == 11
        assert kwargs["solver_kwargs"]["inner_kwargs"]["random_seed"] == 11
        assert kwargs["solver_kwargs"]["inner_kwargs"]["use_cpsat_repair"] is False
        assert kwargs["solver_kwargs"]["hybrid_inner_routing_enabled"] is False
        assert kwargs["solver_kwargs"]["hybrid_inner_kwargs"]["random_seed"] == 11
        assert kwargs["solver_kwargs"]["backtracking_enabled"] is True
        assert kwargs["solver_kwargs"]["backtracking_tail_minutes"] == 60
        assert kwargs["solver_kwargs"]["backtracking_max_ops"] == 24
        assert kwargs["solver_kwargs"]["progressive_admission_relaxation_enabled"] is True
        assert kwargs["solver_kwargs"]["precedence_ready_candidate_filter_enabled"] is True
        assert kwargs["solver_kwargs"]["admission_relaxation_min_fill_ratio"] == 0.30
        assert kwargs["solver_kwargs"]["alns_budget_auto_scaling_enabled"] is True
        assert (
            kwargs["solver_kwargs"]["alns_budget_estimated_repair_s_per_destroyed_op"]
            == 0.125
        )
        assert kwargs["solver_kwargs"]["hybrid_due_pressure_threshold"] == 0.35
        assert kwargs["solver_kwargs"]["hybrid_candidate_pressure_threshold"] == 4.0


def test_study_rhc_500k_applies_time_limit_cap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    captured_time_limits: list[int] = []

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        captured_time_limits.append(int(solver_kwargs["time_limit_s"]))
        return {
            "status": "feasible",
            "feasible": True,
            "solver": solver_name,
            "makespan_min": 100.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": n_ops,
            "violations": 0,
            "solve_ms": 1,
            "gen_ms": 1,
            "verify_ms": 0,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": {},
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[100_000],
        seeds=[1],
        solver_names=["RHC-GREEDY"],
        lane="throughput",
        time_limit_growth_power=0.5,
        time_limit_cap_s=120,
        write_dir=tmp_path,
    )

    assert captured_time_limits == [120]


def test_study_rhc_500k_applies_max_windows_override(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    captured_max_windows: list[int | None] = []

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        captured_max_windows.append(solver_kwargs.get("max_windows"))
        return {
            "status": "feasible",
            "feasible": True,
            "solver": solver_name,
            "makespan_min": 100.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": n_ops,
            "violations": 0,
            "solve_ms": 1,
            "gen_ms": 1,
            "verify_ms": 0,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": {},
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[50_000],
        seeds=[1],
        solver_names=["RHC-ALNS"],
        lane="throughput",
        max_windows_override=2,
        write_dir=tmp_path,
    )

    assert captured_max_windows == [2]


def test_scale_solver_kwargs_relaxes_alns_presearch_guard_for_100k_plus() -> None:
    import benchmark.study_rhc_500k as study_module

    base_kwargs = study_module._default_solver_specs()["RHC-ALNS"]["solver_kwargs"]
    scaled = study_module._scale_solver_kwargs(
        "RHC-ALNS",
        base_kwargs,
        n_ops=200_000,
        base_ops=50_000,
        time_limit_growth_power=0.5,
        max_window_growth_power=0.35,
        max_window_cap=25_000,
        time_limit_cap_s=120,
    )

    assert scaled["window_minutes"] == 300
    assert scaled["overlap_minutes"] == 90
    assert scaled["alns_presearch_budget_guard_enabled"] is True
    assert scaled["alns_presearch_max_window_ops"] > 1_000
    assert scaled["alns_presearch_max_window_ops"] <= scaled["max_ops_per_window"]
    assert scaled["alns_presearch_min_time_limit_s"] < 240.0
    assert scaled["alns_presearch_min_time_limit_s"] >= 30.0


def test_study_rhc_500k_uses_narrower_alns_geometry_for_100k_plus(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    captured_geometries: list[tuple[int, int]] = []

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        captured_geometries.append(
            (
                int(solver_kwargs["window_minutes"]),
                int(solver_kwargs["overlap_minutes"]),
            )
        )
        return {
            "status": "feasible",
            "feasible": True,
            "solver": solver_name,
            "makespan_min": 100.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": n_ops,
            "violations": 0,
            "solve_ms": 1,
            "gen_ms": 1,
            "verify_ms": 0,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": {"inner_fallback_ratio": 0.0},
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[100_000],
        seeds=[1],
        solver_names=["RHC-ALNS"],
        lane="throughput",
        write_dir=tmp_path,
    )

    assert captured_geometries == [(300, 90)]


def test_study_rhc_500k_blocks_execution_above_model_operation_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import benchmark.study_rhc_500k as study_module

    call_count = 0

    def fake_run_scaling_case(**kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "status": "feasible",
            "feasible": True,
            "solver": kwargs["solver_name"],
            "makespan_min": 100.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": kwargs["n_ops"],
            "violations": 0,
            "solve_ms": 1,
            "gen_ms": 1,
            "verify_ms": 0,
            "n_ops": kwargs["n_ops"],
            "n_machines": kwargs["n_machines"],
            "n_states": kwargs["n_states"],
            "sdst_memory_bytes": 0,
            "metadata": {},
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_500k(
        execution_mode="gated",
        scales=[500_000],
        seeds=[1],
        solver_names=["RHC-GREEDY"],
        lane="throughput",
        write_dir=tmp_path,
    )

    assert call_count == 0
    record = report["scale_records"][0]
    assert record["resource_gate"]["allowed"] is False
    assert "operations_exceed_model_limit" in record["resource_gate"]["reasons"]
    assert record["execution"] == "skipped"
    assert record["skip_reason"] == "resource_gate"
