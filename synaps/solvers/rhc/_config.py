"""Typed, validated run configuration for :class:`~synaps.solvers.rhc.RhcSolver`.

``RhcSolver.solve`` historically read ~80 loosely typed ``kwargs`` inline at the
top of a 2 600-line method. This module is the single place that turns the
resolved keyword mapping (preset -> overrides -> legacy kwargs, see
:mod:`synaps.solvers.rhc._policy`) into immutable, grouped dataclasses.

Contract: every default, clamp and type coercion here is **byte-for-byte the
historical one** -- the refactor is behaviour-preserving and the solver's
published metadata echoes these values. Change a default here, not at a call
site, and record it in the CHANGELOG.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

_RESOURCE_GUARD_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _optional_int(raw: Any) -> int | None:
    return int(raw) if raw is not None else None


def _optional_float(raw: Any) -> float | None:
    return float(raw) if raw is not None else None


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


@dataclass(frozen=True, slots=True)
class RhcGeometryConfig:
    """Window geometry: width, overlap, caps and adaptive expansion."""

    window_minutes: int
    overlap_minutes: int
    max_ops_per_window: int
    window_load_factor: float
    max_windows: int | None
    window_bound_inner_horizon: bool
    window_horizon_slack_minutes: float
    coverage_horizon_extension_factor: float
    adaptive_window_enabled: bool
    adaptive_window_min_fill_ratio: float
    adaptive_window_max_multiplier: float

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> RhcGeometryConfig:
        window_minutes = int(kwargs.get("window_minutes", 480))
        overlap_minutes = int(kwargs.get("overlap_minutes", 120))
        default_slack = max(float(overlap_minutes), float(window_minutes) * 0.25)
        return cls(
            window_minutes=window_minutes,
            overlap_minutes=overlap_minutes,
            max_ops_per_window=int(kwargs.get("max_ops_per_window", 5000)),
            window_load_factor=float(kwargs.get("window_load_factor", 1.25)),
            max_windows=_optional_int(kwargs.get("max_windows")),
            window_bound_inner_horizon=bool(kwargs.get("window_bound_inner_horizon", True)),
            window_horizon_slack_minutes=max(
                0.0, float(kwargs.get("window_horizon_slack_minutes", default_slack))
            ),
            coverage_horizon_extension_factor=max(
                1.0, float(kwargs.get("coverage_horizon_extension_factor", 1.0))
            ),
            adaptive_window_enabled=bool(kwargs.get("adaptive_window_enabled", True)),
            adaptive_window_min_fill_ratio=_clamp(
                float(kwargs.get("adaptive_window_min_fill_ratio", 0.5)), 0.0, 1.0
            ),
            adaptive_window_max_multiplier=max(
                1.0, float(kwargs.get("adaptive_window_max_multiplier", 2.0))
            ),
        )


@dataclass(frozen=True, slots=True)
class RhcTimeBudget:
    """Wall-clock contract: window budget, coverage reserve and soft overrun.

    ``window_time_limit_s`` stops the rolling windows early enough to keep
    ``coverage_reserve_s`` for residual fill; ``coverage_deadline_s`` is the
    hard stop for that fill (``time_limit_s`` plus the optional soft budget).
    Under ``SYNAPS_ENABLE_RESOURCE_GUARDS`` the soft overrun is disabled so the
    advertised timeout cannot be amplified (DoS guard).
    """

    time_limit_s: float
    determinism: str
    fallback_repair_enabled: bool
    fallback_repair_on_timeout: bool
    fallback_repair_soft_budget_s: float
    coverage_time_reserve_fraction: float
    coverage_time_reserve_min_s: float
    coverage_time_reserve_max_s: float
    coverage_reserve_s: float
    window_time_limit_s: float
    coverage_deadline_s: float

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> RhcTimeBudget:
        time_limit_s = float(kwargs.get("time_limit_s", 600))
        on_timeout = bool(kwargs.get("fallback_repair_on_timeout", True))
        soft_budget_s = max(0.0, float(kwargs.get("fallback_repair_soft_budget_s", 30.0)))
        reserve_fraction = _clamp(
            float(kwargs.get("coverage_time_reserve_fraction", 0.0)), 0.0, 0.9
        )
        reserve_min_s = max(0.0, float(kwargs.get("coverage_time_reserve_min_s", 0.0)))
        reserve_max_s = max(reserve_min_s, float(kwargs.get("coverage_time_reserve_max_s", 300.0)))
        if reserve_fraction > 0.0:
            raw_reserve = time_limit_s * reserve_fraction
            if reserve_min_s > 0.0:
                raw_reserve = max(raw_reserve, reserve_min_s)
            raw_reserve = min(raw_reserve, reserve_max_s)
            # Never starve the window loop: keep at least half the wall budget.
            coverage_reserve_s = min(raw_reserve, time_limit_s * 0.5)
        else:
            coverage_reserve_s = 0.0
        coverage_deadline_s = time_limit_s + (soft_budget_s if on_timeout else 0.0)
        guards = os.environ.get("SYNAPS_ENABLE_RESOURCE_GUARDS", "").strip().lower()
        if guards in _RESOURCE_GUARD_TRUTHY:
            coverage_deadline_s = time_limit_s
            soft_budget_s = 0.0
        return cls(
            time_limit_s=time_limit_s,
            determinism=str(kwargs.get("determinism", "strict")),
            fallback_repair_enabled=bool(kwargs.get("fallback_repair_enabled", True)),
            fallback_repair_on_timeout=on_timeout,
            fallback_repair_soft_budget_s=soft_budget_s,
            coverage_time_reserve_fraction=reserve_fraction,
            coverage_time_reserve_min_s=reserve_min_s,
            coverage_time_reserve_max_s=reserve_max_s,
            coverage_reserve_s=coverage_reserve_s,
            window_time_limit_s=max(0.0, time_limit_s - coverage_reserve_s),
            coverage_deadline_s=coverage_deadline_s,
        )


@dataclass(frozen=True, slots=True)
class RhcAdmissionConfig:
    """Candidate admission, pool sizing and due-pressure ranking knobs."""

    candidate_admission_enabled: bool
    candidate_pool_factor: float
    max_candidate_pool: int | None
    due_admission_horizon_factor: float
    admission_tail_weight: float
    progressive_admission_relaxation_enabled: bool
    precedence_ready_candidate_filter_enabled: bool
    admission_relaxation_min_fill_ratio: float
    admission_full_scan_enabled: bool
    admission_full_scan_min_fill_ratio: float
    due_pressure_k1: float
    machine_coverage_boost: float
    due_pressure_overdue_boost: float

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> RhcAdmissionConfig:
        return cls(
            candidate_admission_enabled=bool(kwargs.get("candidate_admission_enabled", True)),
            candidate_pool_factor=max(1.0, float(kwargs.get("candidate_pool_factor", 3.0))),
            max_candidate_pool=_optional_int(kwargs.get("max_candidate_pool")),
            due_admission_horizon_factor=max(
                0.0, float(kwargs.get("due_admission_horizon_factor", 1.0))
            ),
            admission_tail_weight=max(0.0, float(kwargs.get("admission_tail_weight", 0.5))),
            progressive_admission_relaxation_enabled=bool(
                kwargs.get("progressive_admission_relaxation_enabled", True)
            ),
            precedence_ready_candidate_filter_enabled=bool(
                kwargs.get("precedence_ready_candidate_filter_enabled", False)
            ),
            admission_relaxation_min_fill_ratio=_clamp(
                float(kwargs.get("admission_relaxation_min_fill_ratio", 0.3)), 0.0, 1.0
            ),
            admission_full_scan_enabled=bool(kwargs.get("admission_full_scan_enabled", True)),
            admission_full_scan_min_fill_ratio=_clamp(
                float(kwargs.get("admission_full_scan_min_fill_ratio", 0.3)), 0.0, 1.0
            ),
            due_pressure_k1=float(kwargs.get("due_pressure_k1", 1.0)),
            machine_coverage_boost=float(kwargs.get("machine_coverage_boost", 1.15)),
            due_pressure_overdue_boost=float(kwargs.get("due_pressure_overdue_boost", 1.25)),
        )


@dataclass(frozen=True, slots=True)
class RhcAlnsBudgetConfig:
    """Per-window ALNS budget scaling, pre-search guard and EMA calibration."""

    inner_window_time_cap_s: float | None
    alns_inner_window_time_cap_s: float | None
    alns_inner_window_time_cap_scale_threshold_ops: int
    alns_inner_window_time_cap_scaled_s: float
    alns_budget_auto_scaling_raw: Any
    alns_budget_estimated_repair_s_per_destroyed_op_raw: Any
    alns_dynamic_repair_budget_enabled: bool
    alns_dynamic_repair_s_per_destroyed_op: float
    alns_dynamic_repair_time_limit_min_s: float
    alns_dynamic_repair_time_limit_max_s: float
    alns_repair_cost_alpha: float
    alns_presearch_budget_guard_enabled: bool
    alns_presearch_max_window_ops: int
    alns_presearch_min_time_limit_s: float

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> RhcAlnsBudgetConfig:
        repair_min_s = max(0.1, float(kwargs.get("alns_dynamic_repair_time_limit_min_s", 1.0)))
        return cls(
            inner_window_time_cap_s=_optional_float(kwargs.get("inner_window_time_cap_s")),
            alns_inner_window_time_cap_s=_optional_float(
                kwargs.get("alns_inner_window_time_cap_s")
            ),
            alns_inner_window_time_cap_scale_threshold_ops=int(
                kwargs.get("alns_inner_window_time_cap_scale_threshold_ops", 4000)
            ),
            alns_inner_window_time_cap_scaled_s=float(
                kwargs.get("alns_inner_window_time_cap_scaled_s", 180.0)
            ),
            alns_budget_auto_scaling_raw=kwargs.get("alns_budget_auto_scaling_enabled"),
            alns_budget_estimated_repair_s_per_destroyed_op_raw=kwargs.get(
                "alns_budget_estimated_repair_s_per_destroyed_op"
            ),
            alns_dynamic_repair_budget_enabled=bool(
                kwargs.get("alns_dynamic_repair_budget_enabled", True)
            ),
            alns_dynamic_repair_s_per_destroyed_op=max(
                0.01, float(kwargs.get("alns_dynamic_repair_s_per_destroyed_op", 0.1))
            ),
            alns_dynamic_repair_time_limit_min_s=repair_min_s,
            alns_dynamic_repair_time_limit_max_s=max(
                repair_min_s, float(kwargs.get("alns_dynamic_repair_time_limit_max_s", 5.0))
            ),
            alns_repair_cost_alpha=float(kwargs.get("alns_repair_cost_ema_alpha", 0.3)),
            alns_presearch_budget_guard_enabled=bool(
                kwargs.get("alns_presearch_budget_guard_enabled", True)
            ),
            alns_presearch_max_window_ops=int(kwargs.get("alns_presearch_max_window_ops", 1000)),
            alns_presearch_min_time_limit_s=float(
                kwargs.get("alns_presearch_min_time_limit_s", 240.0)
            ),
        )


@dataclass(frozen=True, slots=True)
class RhcInnerConfig:
    """Inner-solver routing, hybrid escalation and ALNS hand-off parameters."""

    inner_solver_name: str
    inner_kwargs: dict[str, Any]
    inner_solver_min_budget_s: float
    inner_window_time_fraction: float
    inner_fallback_kpi_threshold: float
    dynamic_no_improve_enabled: bool
    no_improve_due_alpha: float
    no_improve_candidate_beta: float
    no_improve_min_iters: int | None
    no_improve_max_iters: int | None
    random_seed_base: int
    hybrid_inner_routing_enabled: bool
    hybrid_inner_solver_name: str
    hybrid_due_pressure_threshold: float
    hybrid_candidate_pressure_threshold: float
    hybrid_max_ops: int
    hybrid_inner_kwargs: dict[str, Any]
    variable_fixing_enabled: bool
    variable_fixing_min_frequency: int
    variable_fixing_max_ratio: float
    cross_window_learning_enabled: bool

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> RhcInnerConfig:
        inner_kwargs: dict[str, Any] = dict(kwargs.get("inner_kwargs", {}))
        # RHC owns the per-window budget; never double-pass time_limit_s.
        inner_kwargs.pop("time_limit_s", None)
        seed_raw = kwargs.get("random_seed")
        return cls(
            inner_solver_name=str(kwargs.get("inner_solver", "alns")),
            inner_kwargs=inner_kwargs,
            inner_solver_min_budget_s=float(kwargs.get("inner_solver_min_budget_s", 0.0)),
            inner_window_time_fraction=_clamp(
                float(kwargs.get("inner_window_time_fraction", 0.8)), 0.1, 1.0
            ),
            inner_fallback_kpi_threshold=float(kwargs.get("inner_fallback_kpi_threshold", 0.1)),
            dynamic_no_improve_enabled=bool(kwargs.get("dynamic_no_improve_enabled", True)),
            no_improve_due_alpha=float(kwargs.get("no_improve_due_alpha", 0.6)),
            no_improve_candidate_beta=float(kwargs.get("no_improve_candidate_beta", 0.4)),
            no_improve_min_iters=_optional_int(kwargs.get("no_improve_min_iters")),
            no_improve_max_iters=_optional_int(kwargs.get("no_improve_max_iters")),
            random_seed_base=int(seed_raw) if seed_raw is not None else 0,
            hybrid_inner_routing_enabled=bool(kwargs.get("hybrid_inner_routing_enabled", False)),
            hybrid_inner_solver_name=str(kwargs.get("hybrid_inner_solver", "cpsat")),
            hybrid_due_pressure_threshold=float(kwargs.get("hybrid_due_pressure_threshold", 0.35)),
            hybrid_candidate_pressure_threshold=float(
                kwargs.get("hybrid_candidate_pressure_threshold", 1.75)
            ),
            hybrid_max_ops=int(kwargs.get("hybrid_max_ops", 1500)),
            hybrid_inner_kwargs=dict(kwargs.get("hybrid_inner_kwargs", {})),
            variable_fixing_enabled=bool(kwargs.get("variable_fixing_enabled", True)),
            variable_fixing_min_frequency=max(
                2, int(kwargs.get("variable_fixing_min_frequency", 2))
            ),
            variable_fixing_max_ratio=_clamp(
                float(kwargs.get("variable_fixing_max_ratio", 0.3)), 0.0, 0.5
            ),
            cross_window_learning_enabled=bool(kwargs.get("cross_window_learning_enabled", False)),
        )


@dataclass(frozen=True, slots=True)
class RhcCoverConfig:
    """Coverage safety nets: global cover, pace guard, commit gate, backtracking."""

    global_greedy_cover_min_ops: int
    cover_ready_rule: str
    cover_atcs_floor_window: float
    cover_atcs_exhaust_window: float
    coverage_pace_guard_enabled: bool
    coverage_pace_threshold: float
    coverage_pace_min_windows: int
    commit_precedence_gate_enabled: bool
    backtracking_enabled: bool
    backtracking_tail_minutes: float
    backtracking_max_ops: int

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any], *, overlap_minutes: int) -> RhcCoverConfig:
        return cls(
            global_greedy_cover_min_ops=max(
                0, int(kwargs.get("global_greedy_cover_min_ops", 10_000))
            ),
            cover_ready_rule=str(kwargs.get("cover_ready_rule", "fifo")),
            cover_atcs_floor_window=max(0.0, float(kwargs.get("cover_atcs_floor_window", 0.0))),
            cover_atcs_exhaust_window=max(0.0, float(kwargs.get("cover_atcs_exhaust_window", 0.0))),
            coverage_pace_guard_enabled=bool(kwargs.get("coverage_pace_guard_enabled", False)),
            coverage_pace_threshold=max(0.0, float(kwargs.get("coverage_pace_threshold", 1.0))),
            coverage_pace_min_windows=max(1, int(kwargs.get("coverage_pace_min_windows", 2))),
            commit_precedence_gate_enabled=bool(
                kwargs.get("commit_precedence_gate_enabled", False)
            ),
            backtracking_enabled=bool(kwargs.get("backtracking_enabled", False)),
            backtracking_tail_minutes=max(
                0.0, float(kwargs.get("backtracking_tail_minutes", overlap_minutes))
            ),
            backtracking_max_ops=max(0, int(kwargs.get("backtracking_max_ops", 0))),
        )


@dataclass(frozen=True, slots=True)
class RhcRunConfig:
    """The complete, immutable configuration of one ``RhcSolver.solve`` call."""

    geometry: RhcGeometryConfig
    budget: RhcTimeBudget
    admission: RhcAdmissionConfig
    alns_budget: RhcAlnsBudgetConfig
    inner: RhcInnerConfig
    cover: RhcCoverConfig
    external_warm_start_assignments: tuple[Any, ...]

    @classmethod
    def from_kwargs(cls, kwargs: dict[str, Any]) -> RhcRunConfig:
        geometry = RhcGeometryConfig.from_kwargs(kwargs)
        return cls(
            geometry=geometry,
            budget=RhcTimeBudget.from_kwargs(kwargs),
            admission=RhcAdmissionConfig.from_kwargs(kwargs),
            alns_budget=RhcAlnsBudgetConfig.from_kwargs(kwargs),
            inner=RhcInnerConfig.from_kwargs(kwargs),
            cover=RhcCoverConfig.from_kwargs(kwargs, overlap_minutes=geometry.overlap_minutes),
            external_warm_start_assignments=tuple(kwargs.get("warm_start_assignments", []) or []),
        )


__all__ = [
    "RhcAdmissionConfig",
    "RhcAlnsBudgetConfig",
    "RhcCoverConfig",
    "RhcGeometryConfig",
    "RhcInnerConfig",
    "RhcRunConfig",
    "RhcTimeBudget",
]
