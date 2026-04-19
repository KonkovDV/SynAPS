from __future__ import annotations

from pathlib import Path


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
