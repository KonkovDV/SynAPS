from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def test_study_rhc_50k_propagates_seed_to_alns_inner_kwargs(monkeypatch, tmp_path: Path) -> None:
    """RHC-ALNS study rail should forward per-seed determinism into inner ALNS."""
    import benchmark.study_rhc_50k as study_module

    captured_kwargs: list[dict] = []

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        captured_kwargs.append({
            "solver_name": solver_name,
            "solver_kwargs": solver_kwargs,
            "seed": seed,
        })
        return {
            "status": "error",
            "feasible": False,
            "solver": solver_name,
            "makespan_min": 0.0,
            "total_setup_min": 0.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": 0,
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

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
        seeds=[7],
        solver_names=["RHC-ALNS"],
        write_dir=tmp_path,
    )

    assert report["study_kind"] == "rhc-50k"
    assert captured_kwargs
    forwarded = captured_kwargs[0]["solver_kwargs"]["inner_kwargs"]
    assert forwarded["random_seed"] == 7
    assert forwarded["dynamic_sa_enabled"] is True
    assert captured_kwargs[0]["solver_kwargs"]["hybrid_inner_routing_enabled"] is True
    assert captured_kwargs[0]["solver_kwargs"]["hybrid_inner_solver"] == "cpsat"


def test_study_rhc_50k_both_lanes_apply_worker_profiles(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Both-lane mode should emit throughput and strict reproducibility profiles."""
    import benchmark.study_rhc_50k as study_module

    captured_kwargs: list[dict] = []

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        captured_kwargs.append(
            {
                "solver_name": solver_name,
                "solver_kwargs": solver_kwargs,
                "seed": seed,
            }
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
            "metadata": {
                "inner_fallback_ratio": 0.0,
                "inner_fallback_kpi_passed": True,
            },
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
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
        assert kwargs["solver_kwargs"]["hybrid_inner_kwargs"]["random_seed"] == 11

    lanes = sorted(
        comparison["lane"]
        for comparison in report["records"][0]["comparisons"]
    )
    assert lanes == ["strict", "throughput"]


def test_study_rhc_50k_both_lanes_emit_outcome_rates_and_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Both-lane reports should expose completion rates and evidence taxonomy."""
    import benchmark.study_rhc_50k as study_module

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        return {
            "status": "error",
            "feasible": False,
            "solver": solver_name,
            "makespan_min": 100.0,
            "total_setup_min": 20.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": n_ops // 2,
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

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
        seeds=[11],
        solver_names=["RHC-ALNS"],
        lane="both",
        quality_gate_enabled=False,
        write_dir=tmp_path,
    )

    throughput_summary = report["summary_by_solver_lane"]["RHC-ALNS|throughput"]
    strict_summary = report["summary_by_solver_lane"]["RHC-ALNS|strict"]
    assert throughput_summary["process_completed_rate"] == 1.0
    assert throughput_summary["solve_completed_rate"] == 0.0
    assert strict_summary["process_completed_rate"] == 1.0
    assert strict_summary["solve_completed_rate"] == 0.0

    evidence = report["evidence"]
    assert evidence["outcome_taxonomy"]["version"] == "rhc-50k-v1"
    assert evidence["outcome_taxonomy"]["process_outcomes"] == ["completed"]
    assert "solver_error" in evidence["outcome_taxonomy"]["solve_outcomes"]
    assert evidence["lane_outcome_summary"]["RHC-ALNS|throughput"]["solve_completed_rate"] == 0.0


def test_study_rhc_50k_reports_cvar_and_quality_gate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Summary should expose CVaR robustness and quality-gate verdicts."""
    import benchmark.study_rhc_50k as study_module

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        if solver_name == "rhc-greedy":
            makespan = 100.0 + seed * 5.0
            metadata = {}
        else:
            makespan = 103.0 + seed * 5.0
            metadata = {
                "inner_fallback_ratio": 0.04,
                "inner_fallback_kpi_passed": True,
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

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
        seeds=[1, 2, 3],
        solver_names=["RHC-GREEDY", "RHC-ALNS"],
        lane="throughput",
        cvar_alpha=0.9,
        write_dir=tmp_path,
    )

    alns_summary = report["summary_by_solver"]["RHC-ALNS"]
    assert alns_summary["cvar_alpha"] == 0.9
    assert "cvar_makespan_minutes" in alns_summary
    assert "cvar_inner_fallback_ratio" in alns_summary

    gate_result = report["quality_gate"]["results"]["RHC-ALNS"]
    assert gate_result["passed"] is True
    assert gate_result["checks"]["feasibility"] is True
    assert gate_result["checks"]["scheduled_ratio"] is True
    assert gate_result["checks"]["fallback_ratio"] is True
    assert gate_result["checks"]["objective_degradation"] is True


def test_study_rhc_50k_uses_tuned_alns_window_budget_profile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Industrial 50K ALNS study profile should expose the tuned inner budget knobs."""
    import benchmark.study_rhc_50k as study_module

    captured_kwargs: list[dict] = []

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        captured_kwargs.append(
            {
                "solver_name": solver_name,
                "solver_kwargs": solver_kwargs,
                "seed": seed,
            }
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
            "metadata": {"inner_fallback_ratio": 0.0, "inner_fallback_kpi_passed": True},
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
        seeds=[3],
        solver_names=["RHC-ALNS"],
        write_dir=tmp_path,
    )

    assert report["study_kind"] == "rhc-50k"
    assert captured_kwargs
    profile = captured_kwargs[0]["solver_kwargs"]
    assert profile["alns_inner_window_time_cap_s"] == 180
    assert profile["progressive_admission_relaxation_enabled"] is True
    assert profile["admission_relaxation_min_fill_ratio"] == 0.30
    assert profile["alns_budget_auto_scaling_enabled"] is True
    assert profile["alns_budget_estimated_repair_s_per_destroyed_op"] == 0.125
    assert profile["hybrid_due_pressure_threshold"] == 0.35
    assert profile["hybrid_candidate_pressure_threshold"] == 4.0
    assert profile["inner_kwargs"]["use_cpsat_repair"] is True
    assert profile["inner_kwargs"]["repair_time_limit_s"] == 5
    assert profile["inner_kwargs"]["repair_num_workers"] == 1
    assert profile["inner_kwargs"]["cpsat_max_destroy_ops"] == 32
    assert profile["inner_kwargs"]["sa_auto_calibration_enabled"] is True
    assert profile["backtracking_enabled"] is True
    assert profile["backtracking_tail_minutes"] == 60
    assert profile["backtracking_max_ops"] == 24


def test_study_rhc_50k_quality_gate_flags_partial_schedule(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """50K study quality gate must expose and fail low scheduled-ratio runs."""
    import benchmark.study_rhc_50k as study_module

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        return {
            "status": "error",
            "feasible": False,
            "solver": solver_name,
            "makespan_min": 200.0,
            "total_setup_min": 40.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": n_ops // 2,
            "violations": 0,
            "solve_ms": 25,
            "gen_ms": 1,
            "verify_ms": 1,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": {
                "inner_fallback_ratio": 0.0,
                "inner_fallback_kpi_passed": True,
            },
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
        seeds=[1],
        solver_names=["RHC-GREEDY"],
        lane="throughput",
        write_dir=tmp_path,
    )

    summary = report["summary_by_solver"]["RHC-GREEDY"]
    assert summary["mean_scheduled_ratio"] == 0.5
    assert summary["cvar_unscheduled_ratio"] == 0.5

    gate_result = report["quality_gate"]["results"]["RHC-GREEDY"]
    assert gate_result["passed"] is False
    assert gate_result["checks"]["feasibility"] is False
    assert gate_result["checks"]["scheduled_ratio"] is False


def test_study_rhc_50k_reports_process_and_solve_outcomes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Study report should keep process completion separate from solve outcome."""
    import benchmark.study_rhc_50k as study_module

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        return {
            "status": "error",
            "feasible": False,
            "solver": solver_name,
            "makespan_min": 123.0,
            "total_setup_min": 10.0,
            "total_tardiness_min": 0.0,
            "total_material_loss": 0.0,
            "assigned_ops": n_ops // 10,
            "violations": 0,
            "solve_ms": 10,
            "gen_ms": 1,
            "verify_ms": 1,
            "n_ops": n_ops,
            "n_machines": n_machines,
            "n_states": n_states,
            "sdst_memory_bytes": 0,
            "metadata": {},
        }

    monkeypatch.setattr(study_module, "run_scaling_case", fake_run_scaling_case)

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
        seeds=[1],
        solver_names=["RHC-GREEDY"],
        lane="throughput",
        quality_gate_enabled=False,
        write_dir=tmp_path,
    )

    comparison = report["records"][0]["comparisons"][0]
    assert comparison["process_outcome"] == "completed"
    assert comparison["solve_outcome"] == "solver_error"
    assert comparison["results"]["process_outcome"] == "completed"
    assert comparison["results"]["solve_outcome"] == "solver_error"

    summary = report["summary_by_solver"]["RHC-GREEDY"]
    assert summary["process_completed_count"] == 1
    assert summary["solve_completed_count"] == 0
    assert summary["solver_error_count"] == 1


def test_study_rhc_50k_reports_optimization_signals(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """50K study summary should expose native and warm-start optimization signals."""
    import benchmark.study_rhc_50k as study_module

    observed_scales: list[int] = []

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        observed_scales.append(n_ops)
        metadata = {
            "inner_fallback_ratio": 0.02,
            "inner_fallback_kpi_passed": True,
            "acceleration": {
                "rhc_candidate_metrics_backend": "native",
                "rhc_candidate_metrics_np_backend": "native",
            },
            "inner_window_summaries": [
                {
                    "window": 1,
                    "resolution_mode": "inner",
                    "warm_start_used": True,
                    "warm_start_completed_assignments": 3,
                },
                {
                    "window": 2,
                    "resolution_mode": "fallback_greedy",
                    "warm_start_used": False,
                    "warm_start_completed_assignments": 0,
                },
            ],
        }

        return {
            "status": "feasible",
            "feasible": True,
            "solver": solver_name,
            "makespan_min": 120.0,
            "total_setup_min": 30.0,
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

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
        seeds=[5],
        solver_names=["RHC-ALNS"],
        lane="throughput",
        write_dir=tmp_path,
    )

    assert observed_scales == [50_000]

    summary = report["summary_by_solver"]["RHC-ALNS"]
    assert summary["native_acceleration_rate"] == 1.0
    assert summary["mean_warm_start_window_rate"] == 0.5
    assert summary["mean_warm_start_completed_assignments"] == 1.5


def test_study_rhc_50k_two_phase_refinement_uses_external_warm_start(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Two-phase 50K study should feed greedy baseline assignments into refinement."""
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from uuid import uuid4

    import benchmark.study_rhc_50k as study_module
    from synaps.model import Assignment, ObjectiveValues, ScheduleResult, SolverStatus

    start_time = datetime(2026, 1, 1, 8, 0, 0)
    operation_id = uuid4()
    work_center_id = uuid4()
    baseline_assignment = Assignment(
        operation_id=operation_id,
        work_center_id=work_center_id,
        start_time=start_time,
        end_time=start_time + timedelta(minutes=30),
    )
    solve_calls: list[dict] = []

    class FakeSdst:
        def memory_bytes(self) -> int:
            return 321

    def fake_generate_large_instance(**kwargs):
        return {"seed": kwargs["seed"]}

    def fake_verify_schedule_result(problem, result):
        return SimpleNamespace(feasible=True, violation_count=0)

    def fake_solve(self, problem, **kwargs):
        solve_calls.append(kwargs)
        if len(solve_calls) == 1:
            assert kwargs["inner_solver"] == "greedy"
            return ScheduleResult(
                solver_name="rhc-greedy",
                status=SolverStatus.FEASIBLE,
                assignments=[baseline_assignment],
                objective=ObjectiveValues(
                    makespan_minutes=150.0,
                    total_setup_minutes=35.0,
                ),
                metadata={},
            )

        assert kwargs["inner_solver"] == "alns"
        warm_start_assignments = kwargs["warm_start_assignments"]
        assert len(warm_start_assignments) == 1
        assert warm_start_assignments[0].operation_id == baseline_assignment.operation_id
        return ScheduleResult(
            solver_name="rhc-alns",
            status=SolverStatus.FEASIBLE,
            assignments=[baseline_assignment],
            objective=ObjectiveValues(
                makespan_minutes=120.0,
                total_setup_minutes=25.0,
            ),
            metadata={
                "inner_fallback_ratio": 0.0,
                "inner_fallback_kpi_passed": True,
                "external_warm_start_supplied_assignments": 1,
                "external_warm_start_used_windows": 1,
                "inner_window_summaries": [
                    {
                        "window": 1,
                        "warm_start_used": True,
                        "warm_start_completed_assignments": 1,
                    }
                ],
            },
        )

    monkeypatch.setattr(study_module, "generate_large_instance", fake_generate_large_instance)
    monkeypatch.setattr(
        study_module.SdstMatrix,
        "from_problem",
        staticmethod(lambda problem: FakeSdst()),
    )
    monkeypatch.setattr(study_module.RhcSolver, "solve", fake_solve)
    monkeypatch.setattr(study_module, "verify_schedule_result", fake_verify_schedule_result)

    report = study_module.study_rhc_50k(
        preset_name="industrial-50k",
        seeds=[13],
        solver_names=["RHC-ALNS-REFINE"],
        lane="throughput",
        quality_gate_enabled=False,
        write_dir=tmp_path,
    )

    assert len(solve_calls) == 2

    comparison = report["records"][0]["comparisons"][0]
    assert comparison["solver_config"] == "RHC-ALNS-REFINE"
    assert comparison["results"]["solver_name"] == "rhc-alns-refine"
    assert comparison["benchmark_config"]["sdst_memory_bytes"] == 321
    assert comparison["solver_metadata"]["two_phase_refinement_enabled"] is True
    assert comparison["solver_metadata"]["two_phase_baseline_assigned_ops"] == 1
    assert comparison["solver_metadata"]["two_phase_makespan_improvement_min"] == 30.0

    summary = report["summary_by_solver"]["RHC-ALNS-REFINE"]
    assert summary["mean_warm_start_window_rate"] == 1.0
    assert summary["mean_warm_start_completed_assignments"] == 1.0
