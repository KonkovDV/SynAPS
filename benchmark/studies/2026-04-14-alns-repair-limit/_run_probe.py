import json
import time
from pathlib import Path

from synaps.benchmarks.run_scaling_benchmark import run_benchmark

OUTPUT = Path("benchmark/studies/2026-04-14-alns-repair-limit/alns_repair_limit_probe.json")
OUTPUT.parent.mkdir(parents=True, exist_ok=True)

cases = []
for repair_limit in (1, 2, 5):
    print(f"RUN repair_time_limit_s={repair_limit}", flush=True)
    started = time.monotonic()
    result = run_benchmark(
        n_ops=2000,
        n_machines=60,
        n_states=20,
        solver_name="alns",
        solver_kwargs={
            "max_iterations": 60,
            "time_limit_s": 20,
            "repair_time_limit_s": repair_limit,
            "min_destroy": 20,
            "max_destroy": 150,
        },
        seed=1,
    )
    metadata = result.get("metadata", {})
    cases.append(
        {
            "repair_time_limit_s": repair_limit,
            "wall_probe_s": round(time.monotonic() - started, 3),
            "assigned_ops": result["assigned_ops"],
            "solve_ms": result["solve_ms"],
            "status": result["status"],
            "feasible": result["feasible"],
            "cpsat_repair_attempts": metadata.get("cpsat_repair_attempts"),
            "cpsat_repairs": metadata.get("cpsat_repairs"),
            "cpsat_repair_ms_total": metadata.get("cpsat_repair_ms_total"),
            "cpsat_repair_ms_mean": metadata.get("cpsat_repair_ms_mean"),
            "greedy_repair_attempts": metadata.get("greedy_repair_attempts"),
            "greedy_repairs": metadata.get("greedy_repairs"),
            "greedy_repair_ms_total": metadata.get("greedy_repair_ms_total"),
            "greedy_repair_ms_mean": metadata.get("greedy_repair_ms_mean"),
            "initial_solution_ms": metadata.get("initial_solution_ms"),
            "iterations_completed": metadata.get("iterations_completed"),
            "improvements": metadata.get("improvements"),
        }
    )
    OUTPUT.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"DONE repair_time_limit_s={repair_limit}", flush=True)

print("ALNS_REPAIR_LIMIT_PROBE_DONE", flush=True)
