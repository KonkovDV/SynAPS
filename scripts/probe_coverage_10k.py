"""Quick coverage probe for RHC-GREEDY-COVER on industrial-10k."""

from __future__ import annotations

import time

from benchmark.generate_instances import generate_problem, preset_spec
from synaps.solvers.rhc import RhcPolicy, RhcSolver
from synaps.solvers.rhc._policy import RhcPolicySpec, build_solve_kwargs_from_spec


def main() -> None:
    spec = preset_spec("industrial-10k", seed=1)
    problem = generate_problem(spec)
    total = len(problem.operations)
    horizon_min = (
        problem.planning_horizon_end - problem.planning_horizon_start
    ).total_seconds() / 60.0
    print(f"ops={total} machines={len(problem.work_centers)} horizon_min={horizon_min:.1f}")

    kwargs = build_solve_kwargs_from_spec(RhcPolicySpec.from_preset(RhcPolicy.GREEDY_COVER))
    kwargs["time_limit_s"] = 90
    kwargs["max_windows"] = 120

    t0 = time.monotonic()
    result = RhcSolver(policy=RhcPolicy.GREEDY_COVER).solve(problem, **kwargs)
    elapsed = time.monotonic() - t0
    scheduled = int(result.metadata.get("ops_scheduled", len(result.assignments)))
    print(f"status={result.status.value}")
    print(f"scheduled_ratio={scheduled / total:.4f}")
    print(f"ops_unscheduled={result.metadata.get('ops_unscheduled')}")
    print(f"fallback_attempted={result.metadata.get('fallback_repair_attempted')}")
    print(f"fallback_skipped={result.metadata.get('fallback_repair_skipped')}")
    print(f"windows_solved={result.metadata.get('windows_solved')}")
    print(f"horizon_clipped={result.metadata.get('horizon_clipped_assignments')}")
    print(f"coverage_reserve_s={result.metadata.get('coverage_reserve_s')}")
    print(f"window_time_limit_s={result.metadata.get('window_time_limit_s')}")
    print(f"elapsed_s={elapsed:.2f}")


if __name__ == "__main__":
    main()
