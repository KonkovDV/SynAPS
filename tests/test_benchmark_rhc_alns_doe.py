from __future__ import annotations

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
    assert gate_result["checks"]["fallback_ratio"] is True
    assert gate_result["checks"]["objective_degradation"] is True


def test_run_rhc_alns_doe_generates_ranked_report(monkeypatch, tmp_path: Path) -> None:
    import benchmark.study_rhc_alns_doe as doe_module

    def fake_run_scaling_case(*, n_ops, n_machines, n_states, solver_name, solver_kwargs, seed):
        due = float(solver_kwargs["hybrid_due_pressure_threshold"])
        cand = float(solver_kwargs["hybrid_candidate_pressure_threshold"])
        sa_due = float(solver_kwargs["inner_kwargs"]["sa_due_alpha"])

        # Synthetic surface: slightly better around canonical center.
        distance = abs(due - 0.35) + abs(cand - 1.75) + abs(sa_due - 0.35)
        makespan = 100.0 + distance * 20.0 + seed
        fallback_ratio = min(0.2, 0.03 + distance * 0.1)

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
            "metadata": {
                "inner_fallback_ratio": fallback_ratio,
            },
        }

    monkeypatch.setattr(doe_module, "run_scaling_case", fake_run_scaling_case)

    report = doe_module.run_rhc_alns_doe(
        seeds=[1, 2],
        lane="throughput",
        n_ops=1_000,
        n_machines=10,
        n_states=5,
        max_combinations=4,
        write_dir=tmp_path,
    )

    assert report["study_kind"] == "rhc-alns-doe"
    assert report["seed_count"] == 2
    assert len(report["config_summaries"]) == 4
    assert report["top_configs"]

    first = report["config_summaries"][0]
    assert "summary" in first
    assert "quality_gate" in first
    assert "cvar_makespan_minutes" in first["summary"]
    assert "mean_inner_fallback_ratio" in first["summary"]
    assert "passed" in first["quality_gate"]
