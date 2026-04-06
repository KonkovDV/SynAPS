"""Academic Pareto-slice solver for SynAPS.

This wrapper turns the existing exact CP-SAT solver into a first-class
epsilon-constraint portfolio member:

1. stage 1 solves the default makespan-first model to obtain a high-quality
   incumbent;
2. stage 2 re-solves the same instance while keeping makespan within a bounded
   relaxation and minimising a chosen secondary objective directly.

The result is a near-optimal Pareto slice that is benchmarkable and available
through the public solver registry.
"""

from __future__ import annotations

import math
from typing import Any

from synaps.model import ScheduleProblem, ScheduleResult, SolverStatus
from synaps.solvers import BaseSolver
from synaps.solvers.cpsat_solver import CpSatSolver


class ParetoSliceCpSatSolver(BaseSolver):
    """Two-stage exact solver that exposes a bounded Pareto slice."""

    @property
    def name(self) -> str:
        return "cpsat_pareto_slice"

    def solve(self, problem: ScheduleProblem, **kwargs: Any) -> ScheduleResult:
        total_time_limit_s = int(kwargs.get("time_limit_s", 30))
        stage1_time_limit_s = int(
            kwargs.get(
                "stage1_time_limit_s",
                max(1, min(total_time_limit_s - 1, total_time_limit_s // 2 or 1)),
            )
        )
        stage2_time_limit_s = max(1, total_time_limit_s - stage1_time_limit_s)
        random_seed = int(kwargs.get("random_seed", 42))
        num_workers = int(kwargs.get("num_workers", 8))
        material_loss_scale = int(kwargs.get("material_loss_scale", 1000))
        primary_objective = str(kwargs.get("primary_objective", "setup"))
        max_makespan_ratio = float(kwargs.get("max_makespan_ratio", 1.05))

        baseline_solver = CpSatSolver()
        baseline = baseline_solver.solve(
            problem,
            time_limit_s=stage1_time_limit_s,
            random_seed=random_seed,
            num_workers=num_workers,
            material_loss_scale=material_loss_scale,
        )

        if baseline.status not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            baseline.metadata = {
                **baseline.metadata,
                "pareto_slice": {
                    "stage": "baseline_only",
                    "primary_objective": primary_objective,
                    "max_makespan_ratio": max_makespan_ratio,
                    "fallback_reason": "baseline solve did not produce a feasible incumbent",
                },
            }
            return baseline

        max_makespan_minutes = int(
            math.ceil(baseline.objective.makespan_minutes * max_makespan_ratio)
        )
        epsilon_constraints = {"max_makespan_minutes": max_makespan_minutes}

        slice_result = baseline_solver.solve(
            problem,
            time_limit_s=stage2_time_limit_s,
            random_seed=random_seed,
            num_workers=num_workers,
            material_loss_scale=material_loss_scale,
            objective_mode="epsilon_primary",
            primary_objective=primary_objective,
            epsilon_constraints=epsilon_constraints,
        )

        slice_result.solver_name = self.name
        slice_result.metadata = {
            **slice_result.metadata,
            "pareto_slice": {
                "stage": "epsilon_primary",
                "baseline_solver": baseline.solver_name,
                "baseline_makespan_minutes": baseline.objective.makespan_minutes,
                "baseline_setup_minutes": baseline.objective.total_setup_minutes,
                "baseline_tardiness_minutes": baseline.objective.total_tardiness_minutes,
                "primary_objective": primary_objective,
                "max_makespan_ratio": max_makespan_ratio,
                "max_makespan_minutes": max_makespan_minutes,
                "stage1_time_limit_s": stage1_time_limit_s,
                "stage2_time_limit_s": stage2_time_limit_s,
            },
        }
        return slice_result


__all__ = ["ParetoSliceCpSatSolver"]
