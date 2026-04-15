"""Control study: RHC-ALNS greedy-only profile with early-stop=30 recheck."""

from __future__ import annotations

import json
import time
from pathlib import Path

from synaps.benchmarks.run_scaling_benchmark import run_benchmark


def main() -> None:
    artifact_dir = Path("benchmark/studies/2026-04-15-rhc-alns-early-stop-30-recheck")
    artifact_dir.mkdir(parents=True, exist_ok=True)

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
            "max_no_improve_iters": 30,
            "use_cpsat_repair": False,
        },
    }

    print("Running RHC-ALNS early-stop=30 recheck...", flush=True)
    t0 = time.monotonic()
    result = run_benchmark(
        n_ops=50_000,
        n_machines=100,
        n_states=20,
        solver_name="rhc-alns",
        solver_kwargs=solve_kwargs,
        seed=1,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    artifact = {
        "study_kind": "rhc-50k-early-stop-recheck",
        "preset_name": "industrial-50k",
        "elapsed_ms": elapsed_ms,
        "result": result,
    }
    artifact_path = artifact_dir / "rhc_50k_study.json"
    artifact_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps(artifact, indent=2), flush=True)


if __name__ == "__main__":
    main()
