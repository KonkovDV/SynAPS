"""Control study: RHC-ALNS tuned profile with greedy-only inner repair."""

from __future__ import annotations

import json
import time
from pathlib import Path

from synaps.benchmarks.instance_generator import generate_large_instance
from synaps.benchmarks.run_scaling_benchmark import run_benchmark


def main() -> None:
    artifact_dir = Path("benchmark/studies/2026-04-14-rhc-alns-greedy-only")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    print("Generating 50K instance...", flush=True)
    generation_t0 = time.monotonic()
    problem = generate_large_instance(
        n_operations=50_000,
        n_machines=100,
        n_states=20,
        setup_density=0.5,
        seed=1,
    )
    generation_ms = int((time.monotonic() - generation_t0) * 1000)
    print(f"Generated {len(problem.operations)} ops in {generation_ms}ms", flush=True)

    solve_kwargs = {
        "window_minutes": 480,
        "overlap_minutes": 120,
        "inner_solver": "alns",
        "time_limit_s": 300,
        "max_ops_per_window": 5_000,
        "inner_kwargs": {
            "max_iterations": 100,
            "destroy_fraction": 0.03,
            "min_destroy": 10,
            "max_destroy": 40,
            "repair_time_limit_s": 10,
            "use_cpsat_repair": False,
        },
    }

    print("Running RHC-ALNS greedy-only control...", flush=True)
    result = run_benchmark(
        n_ops=50_000,
        n_machines=100,
        n_states=20,
        solver_name="rhc-alns",
        solver_kwargs=solve_kwargs,
        seed=1,
    )

    artifact = {
        "study_kind": "rhc-50k-greedy-only-control",
        "preset_name": "industrial-50k",
        "generation_time_ms": generation_ms,
        "result": result,
    }
    artifact_path = artifact_dir / "rhc_50k_study.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps(artifact, indent=2), flush=True)


if __name__ == "__main__":
    main()