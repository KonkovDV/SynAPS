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

from synaps.model import ObjectiveValues, ScheduleProblem, ScheduleResult, SolverStatus
from synaps.solvers import BaseSolver
from synaps.solvers.cpsat_solver import CpSatSolver


class ParetoSliceCpSatSolver(BaseSolver):
    """Two-stage exact solver that exposes a bounded Pareto slice."""

    @staticmethod
    def _normalise_epsilon_grid(
        max_makespan_ratio: float,
        epsilon_grid: object | None,
    ) -> list[float]:
        """Return a sorted, unique epsilon grid with a safe fallback.

        Ratios below 1.0 are rejected because they would tighten makespan below
        the baseline incumbent and frequently make stage-2 infeasible.
        """

        if epsilon_grid is None:
            return [max(1.0, max_makespan_ratio)]

        if isinstance(epsilon_grid, list | tuple | set):
            raw_ratios = list(epsilon_grid)
        else:
            raw_ratios = [epsilon_grid]

        valid_ratios: list[float] = []
        for raw_ratio in raw_ratios:
            try:
                ratio = float(raw_ratio)
            except (TypeError, ValueError):
                continue
            if ratio < 1.0:
                continue
            valid_ratios.append(ratio)

        if not valid_ratios:
            return [max(1.0, max_makespan_ratio)]

        return sorted(set(valid_ratios))

    @staticmethod
    def _primary_value(objective: ObjectiveValues, primary_objective: str) -> float:
        values = {
            "makespan": objective.makespan_minutes,
            "setup": objective.total_setup_minutes,
            "material_loss": objective.total_material_loss,
            "tardiness": objective.total_tardiness_minutes,
        }
        try:
            return float(values[primary_objective])
        except KeyError as exc:
            supported = ", ".join(sorted(values))
            raise ValueError(
                "Unsupported primary_objective "
                f"'{primary_objective}'. Expected one of: {supported}"
            ) from exc

    def _is_candidate_better(
        self,
        candidate: ScheduleResult,
        incumbent: ScheduleResult | None,
        primary_objective: str,
    ) -> bool:
        if incumbent is None:
            return True

        candidate_rank = (
            self._primary_value(candidate.objective, primary_objective),
            float(candidate.objective.makespan_minutes),
            float(candidate.objective.weighted_sum),
        )
        incumbent_rank = (
            self._primary_value(incumbent.objective, primary_objective),
            float(incumbent.objective.makespan_minutes),
            float(incumbent.objective.weighted_sum),
        )
        return candidate_rank < incumbent_rank

    @staticmethod
    def _count_non_dominated_points(points: list[dict[str, float]]) -> int:
        non_dominated = 0
        for index, point in enumerate(points):
            dominated = False
            for other_index, other in enumerate(points):
                if other_index == index:
                    continue
                dominates = (
                    other["makespan_minutes"] <= point["makespan_minutes"]
                    and other["primary_value"] <= point["primary_value"]
                    and (
                        other["makespan_minutes"] < point["makespan_minutes"]
                        or other["primary_value"] < point["primary_value"]
                    )
                )
                if dominates:
                    dominated = True
                    break
            if not dominated:
                non_dominated += 1
        return non_dominated

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
        epsilon_grid = self._normalise_epsilon_grid(
            max_makespan_ratio=max_makespan_ratio,
            epsilon_grid=kwargs.get("epsilon_grid"),
        )

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

        per_slice_stage2_time_s = max(1, stage2_time_limit_s // len(epsilon_grid))
        stage2_remainder_s = stage2_time_limit_s - per_slice_stage2_time_s * len(epsilon_grid)

        epsilon_points: list[dict[str, object]] = []
        feasible_points_for_frontier: list[dict[str, float]] = []
        selected_result: ScheduleResult | None = None
        selected_ratio: float | None = None

        for index, epsilon_ratio in enumerate(epsilon_grid):
            allocated_time_s = per_slice_stage2_time_s + (1 if index < stage2_remainder_s else 0)
            max_makespan_minutes = int(
                math.ceil(baseline.objective.makespan_minutes * epsilon_ratio)
            )
            epsilon_constraints = {"max_makespan_minutes": max_makespan_minutes}

            slice_result = baseline_solver.solve(
                problem,
                time_limit_s=allocated_time_s,
                random_seed=random_seed,
                num_workers=num_workers,
                material_loss_scale=material_loss_scale,
                objective_mode="epsilon_primary",
                primary_objective=primary_objective,
                epsilon_constraints=epsilon_constraints,
            )

            point_payload: dict[str, object] = {
                "epsilon_ratio": epsilon_ratio,
                "max_makespan_minutes": max_makespan_minutes,
                "time_limit_s": allocated_time_s,
                "status": slice_result.status.value,
            }

            if slice_result.status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
                primary_value = self._primary_value(slice_result.objective, primary_objective)
                point_payload.update(
                    {
                        "makespan_minutes": slice_result.objective.makespan_minutes,
                        "setup_minutes": slice_result.objective.total_setup_minutes,
                        "tardiness_minutes": slice_result.objective.total_tardiness_minutes,
                        "material_loss": slice_result.objective.total_material_loss,
                        "primary_value": primary_value,
                    }
                )
                feasible_points_for_frontier.append(
                    {
                        "makespan_minutes": float(slice_result.objective.makespan_minutes),
                        "primary_value": float(primary_value),
                    }
                )
                if self._is_candidate_better(slice_result, selected_result, primary_objective):
                    selected_result = slice_result
                    selected_ratio = epsilon_ratio

            epsilon_points.append(point_payload)

        if selected_result is None:
            baseline.metadata = {
                **baseline.metadata,
                "pareto_slice": {
                    "stage": "baseline_only",
                    "primary_objective": primary_objective,
                    "max_makespan_ratio": max_makespan_ratio,
                    "epsilon_grid": epsilon_grid,
                    "fallback_reason": "epsilon grid produced no feasible point",
                    "epsilon_points": epsilon_points,
                },
            }
            return baseline

        selected_result.solver_name = self.name
        selected_result.metadata = {
            **selected_result.metadata,
            "pareto_slice": {
                "stage": "epsilon_grid" if len(epsilon_grid) > 1 else "epsilon_primary",
                "baseline_solver": baseline.solver_name,
                "baseline_makespan_minutes": baseline.objective.makespan_minutes,
                "baseline_setup_minutes": baseline.objective.total_setup_minutes,
                "baseline_tardiness_minutes": baseline.objective.total_tardiness_minutes,
                "baseline_material_loss": baseline.objective.total_material_loss,
                "primary_objective": primary_objective,
                "max_makespan_ratio": max_makespan_ratio,
                "epsilon_grid": epsilon_grid,
                "selected_ratio": selected_ratio,
                "stage1_time_limit_s": stage1_time_limit_s,
                "stage2_time_limit_s": stage2_time_limit_s,
                "non_dominated_point_count": self._count_non_dominated_points(
                    feasible_points_for_frontier
                ),
                "epsilon_points": epsilon_points,
            },
        }
        return selected_result


__all__ = ["ParetoSliceCpSatSolver"]
