"""Typed, validated run configuration for :class:`~synaps.solvers.alns_solver.AlnsSolver`.

``AlnsSolver._solve_core`` historically read ~60 loosely typed ``kwargs``
inline. This module turns the keyword mapping into immutable, grouped
dataclasses. Every default, clamp and coercion is **byte-for-byte the
historical one** (the 2026-10 decomposition is behaviour-preserving; the
solver echoes these values in its metadata).

Values that need the problem instance (e.g. ``frozen_context_operations``
defaulting to ``problem.operations``) or module-level helpers that tests patch
(objective-weight normalisation) are resolved by the run engine, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


@dataclass(frozen=True, slots=True)
class AlnsBudgetConfig:
    """Iteration ceiling, wall-clock deadline and destroy/repair sizing."""

    max_iterations: int
    time_limit_s: float
    determinism: str
    destroy_fraction: float
    min_destroy: int
    max_destroy: int
    repair_time_limit_s: int
    repair_num_workers: int
    use_cpsat_repair: bool
    cpsat_max_destroy_ops: int
    adaptive_destroy_enabled: bool
    adaptive_destroy_grow_rate: float
    adaptive_destroy_shrink_rate: float
    ema_repair_alpha: float
    adaptive_iteration_scaling: bool
    warm_start_skip_threshold_gap: float

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> AlnsBudgetConfig:
        max_destroy = int(kwargs.get("max_destroy", 300))
        return cls(
            max_iterations=int(kwargs.get("max_iterations", 500)),
            time_limit_s=float(kwargs.get("time_limit_s", 300)),
            determinism=str(kwargs.get("determinism", "strict")),
            destroy_fraction=float(kwargs.get("destroy_fraction", 0.05)),
            min_destroy=int(kwargs.get("min_destroy", 20)),
            max_destroy=max_destroy,
            repair_time_limit_s=int(kwargs.get("repair_time_limit_s", 10)),
            repair_num_workers=max(
                1, int(kwargs.get("repair_num_workers", kwargs.get("num_workers", 1)))
            ),
            use_cpsat_repair=bool(kwargs.get("use_cpsat_repair", True)),
            cpsat_max_destroy_ops=int(kwargs.get("cpsat_max_destroy_ops", min(20, max_destroy))),
            adaptive_destroy_enabled=bool(kwargs.get("adaptive_destroy_enabled", False)),
            adaptive_destroy_grow_rate=float(kwargs.get("adaptive_destroy_grow_rate", 1.15)),
            adaptive_destroy_shrink_rate=float(kwargs.get("adaptive_destroy_shrink_rate", 0.85)),
            ema_repair_alpha=float(kwargs.get("ema_repair_alpha", 0.3)),
            adaptive_iteration_scaling=bool(kwargs.get("adaptive_iteration_scaling", False)),
            warm_start_skip_threshold_gap=float(kwargs.get("warm_start_skip_threshold_gap", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class AlnsAnnealingConfig:
    """Simulated-annealing temperature, cooling and pressure coupling."""

    sa_auto_calibration_enabled: bool
    sa_calibration_trials: int
    sa_initial_acceptance_probability: float
    sa_initial_temp: float
    sa_cooling_rate: float
    dynamic_sa_enabled: bool
    sa_due_alpha: float
    sa_candidate_beta: float
    sa_pressure_cooling_gamma: float
    sa_temp_min: float
    sa_temp_max: float
    due_pressure: float
    candidate_pressure: float

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> AlnsAnnealingConfig:
        return cls(
            sa_auto_calibration_enabled=bool(kwargs.get("sa_auto_calibration_enabled", False)),
            # R6: >= 10-50 worsening samples for a reliable estimate (Pepels 2014).
            sa_calibration_trials=max(0, int(kwargs.get("sa_calibration_trials", 15))),
            sa_initial_acceptance_probability=float(
                kwargs.get("sa_initial_acceptance_probability", 0.8)
            ),
            sa_initial_temp=float(kwargs.get("sa_initial_temp", 100.0)),
            sa_cooling_rate=float(kwargs.get("sa_cooling_rate", 0.995)),
            dynamic_sa_enabled=bool(kwargs.get("dynamic_sa_enabled", True)),
            sa_due_alpha=float(kwargs.get("sa_due_alpha", 0.35)),
            sa_candidate_beta=float(kwargs.get("sa_candidate_beta", 0.15)),
            sa_pressure_cooling_gamma=float(kwargs.get("sa_pressure_cooling_gamma", 0.0015)),
            sa_temp_min=float(kwargs.get("sa_temp_min", 50.0)),
            sa_temp_max=float(kwargs.get("sa_temp_max", 500.0)),
            due_pressure=max(0.0, float(kwargs.get("due_pressure", 0.0))),
            candidate_pressure=max(0.0, float(kwargs.get("candidate_pressure", 0.0))),
        )


@dataclass(frozen=True, slots=True)
class AlnsAdaptationConfig:
    """Operator adaptation (roulette segments / UCB1 pairs) and stagnation."""

    operator_weight_segment_length: int
    operator_weight_reset_mix: float
    mab_pair_selection: bool
    initial_operator_weights_raw: Any
    cross_window_operator_bias_enabled: bool
    cross_window_hints: Any
    max_no_improve_base_iters: int
    dynamic_no_improve_enabled: bool
    no_improve_due_alpha: float
    no_improve_candidate_beta: float
    no_improve_min_iters: int
    no_improve_max_iters: int
    record_iteration_metrics: bool
    max_iteration_records: int

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> AlnsAdaptationConfig:
        base = int(kwargs.get("max_no_improve_iters", 0))
        return cls(
            operator_weight_segment_length=max(
                1, int(kwargs.get("operator_weight_segment_length", 50))
            ),
            operator_weight_reset_mix=_clamp(
                float(kwargs.get("operator_weight_reset_mix", 0.2)), 0.0, 0.95
            ),
            mab_pair_selection=bool(kwargs.get("mab_pair_selection", False)),
            initial_operator_weights_raw=kwargs.get("initial_operator_weights"),
            cross_window_operator_bias_enabled=bool(
                kwargs.get("cross_window_operator_bias_enabled", False)
            ),
            cross_window_hints=kwargs.get("cross_window_hints"),
            max_no_improve_base_iters=base,
            dynamic_no_improve_enabled=bool(kwargs.get("dynamic_no_improve_enabled", False)),
            no_improve_due_alpha=float(kwargs.get("no_improve_due_alpha", 0.6)),
            no_improve_candidate_beta=float(kwargs.get("no_improve_candidate_beta", 0.4)),
            no_improve_min_iters=int(
                kwargs.get("no_improve_min_iters", max(1, base // 2) if base > 0 else 0)
            ),
            no_improve_max_iters=int(
                kwargs.get("no_improve_max_iters", base * 4 if base > 0 else 0)
            ),
            record_iteration_metrics=bool(kwargs.get("record_iteration_metrics", False)),
            max_iteration_records=max(1, int(kwargs.get("max_iteration_records", 500))),
        )


@dataclass(frozen=True, slots=True)
class AlnsSeedConfig:
    """Phase-1 initial-solution policy, warm start and frozen (RHC) context."""

    seed: int
    initial_beam_op_limit: int
    frozen_initial_repair_max_ops: int
    frozen_initial_repair_min_remaining_time_s: float
    native_initial_seed_enabled: bool
    search_budget_reservation_s: float
    phase1_wall_fraction: float
    objective_weights_raw: dict[str, Any] | None
    warm_start_assignments_raw: Any
    frozen_assignments: tuple[Any, ...]
    frozen_predecessor_end_offsets: dict[Any, float]
    frozen_context_operations_raw: Any
    fixed_op_ids: frozenset[Any]

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> AlnsSeedConfig:
        fixed_raw = kwargs.get("fixed_op_ids")
        return cls(
            seed=int(kwargs.get("random_seed", 42)),
            initial_beam_op_limit=int(kwargs.get("initial_beam_op_limit", 60)),
            frozen_initial_repair_max_ops=int(kwargs.get("frozen_initial_repair_max_ops", 2000)),
            frozen_initial_repair_min_remaining_time_s=float(
                kwargs.get("frozen_initial_repair_min_remaining_time_s", 30.0)
            ),
            native_initial_seed_enabled=bool(kwargs.get("native_initial_seed_enabled", True)),
            search_budget_reservation_s=float(kwargs.get("search_budget_reservation_s", 10.0)),
            phase1_wall_fraction=_clamp(float(kwargs.get("phase1_wall_fraction", 0.5)), 0.1, 0.9),
            objective_weights_raw=(
                dict(kwargs["objective_weights"]) if kwargs.get("objective_weights") else None
            ),
            warm_start_assignments_raw=kwargs.get("warm_start_assignments"),
            frozen_assignments=tuple(kwargs.get("frozen_assignments") or ()),
            frozen_predecessor_end_offsets={
                op_id: float(offset)
                for op_id, offset in dict(kwargs.get("frozen_predecessor_end_offsets", {})).items()
            },
            frozen_context_operations_raw=kwargs.get("frozen_context_operations"),
            fixed_op_ids=frozenset(fixed_raw) if fixed_raw else frozenset(),
        )


@dataclass(frozen=True, slots=True)
class AlnsRunConfig:
    """The complete, immutable configuration of one ALNS solve."""

    budget: AlnsBudgetConfig
    annealing: AlnsAnnealingConfig
    adaptation: AlnsAdaptationConfig
    seeding: AlnsSeedConfig

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> AlnsRunConfig:
        return cls(
            budget=AlnsBudgetConfig.from_kwargs(kwargs),
            annealing=AlnsAnnealingConfig.from_kwargs(kwargs),
            adaptation=AlnsAdaptationConfig.from_kwargs(kwargs),
            seeding=AlnsSeedConfig.from_kwargs(kwargs),
        )


__all__ = [
    "AlnsAdaptationConfig",
    "AlnsAnnealingConfig",
    "AlnsBudgetConfig",
    "AlnsRunConfig",
    "AlnsSeedConfig",
]
