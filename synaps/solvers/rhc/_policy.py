"""Typed RHC policy presets and overrides.

Academic basis:
    - Rawlings & Mayne (2009): receding-horizon parametric families.
    - Pernas-Álvarez et al. (2025, IJPR): geometry-driven decomposition
      where window width, overlap, and inner-solver budget are coupled.

The ``RhcPolicySpec`` bundles every tunable that influences RHC geometry,
admission, budget, guards, and inner-solver routing.  Presets mirror the
four validated configurations in ``synaps.solvers.registry``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RhcPolicy(Enum):
    """Named RHC geometry + solver family."""

    COVERAGE_FIRST = "coverage-first"  # wide windows, ALNS inner
    BALANCED = "balanced"  # default 8h/2h ALNS
    SEARCH_ENTRY = "search-entry"  # 100K tight-geometry profile
    BOUNDED_100K = "bounded-100k"  # aggressive 5h/90m ALNS
    FAST_50K = "fast-50k"  # 50K wall-time optimized
    GREEDY_COVER = "greedy-cover"  # coverage-complete constructive path
    SEARCH_COVER = "search-cover"  # search-active geometry + coverage guard


@dataclass(frozen=True, slots=True)
class AdmissionSpec:
    """Window admission hyper-parameters."""

    window_minutes: int = 480
    overlap_minutes: int = 120
    max_ops_per_window: int = 5000
    candidate_pool_factor: float = 2.0
    due_admission_horizon_factor: float = 6.0
    admission_tail_weight: float = 0.5
    progressive_admission_relaxation_enabled: bool = True
    precedence_ready_candidate_filter_enabled: bool = False
    admission_relaxation_min_fill_ratio: float = 0.30
    admission_full_scan_enabled: bool = True


@dataclass(frozen=True, slots=True)
class BudgetSpec:
    """ALNS inner-solver budget scaling."""

    alns_inner_window_time_cap_s: float = 180.0
    alns_inner_window_time_cap_scale_threshold_ops: int = 4000
    alns_inner_window_time_cap_scaled_s: float = 180.0
    alns_budget_auto_scaling_enabled: bool = True
    alns_budget_estimated_repair_s_per_destroyed_op: float = 0.125
    alns_dynamic_repair_budget_enabled: bool = True
    alns_dynamic_repair_s_per_destroyed_op: float = 0.1
    alns_dynamic_repair_time_limit_min_s: float = 1.0
    alns_dynamic_repair_time_limit_max_s: float = 5.0
    alns_presearch_max_window_ops: int = 5000
    search_budget_reservation_s: float = 10.0
    # Hold wall-time for residual coverage greedy after windows stop.
    coverage_time_reserve_fraction: float = 0.0
    coverage_time_reserve_min_s: float = 0.0
    coverage_time_reserve_max_s: float = 300.0


@dataclass(frozen=True, slots=True)
class GuardSpec:
    """Pre-search and fallback guard-rails."""

    fallback_repair_enabled: bool = True
    # When True, residual greedy may overrun time_limit by soft_budget.
    fallback_repair_on_timeout: bool = True
    fallback_repair_soft_budget_s: float = 30.0
    backtracking_enabled: bool = True
    backtracking_tail_minutes: float = 60.0
    backtracking_max_ops: int = 24
    inner_fallback_kpi_threshold: float = 0.10
    inner_solver_min_budget_s: float = 0.0
    # Multiply declared planning horizon for slot clipping (coverage ceiling).
    coverage_horizon_extension_factor: float = 1.0
    # W1 coverage pace guard: deterministic outer/inner objective alignment.
    coverage_pace_guard_enabled: bool = False
    coverage_pace_threshold: float = 1.0
    coverage_pace_min_windows: int = 2
    # W-A commit-time precedence gate: defer commit candidates that would
    # bake a cross-window precedence violation into the frozen schedule.
    commit_precedence_gate_enabled: bool = False


@dataclass(frozen=True, slots=True)
class InnerSpec:
    """Inner solver selection and its per-window kwargs."""

    selected_inner_solver_name: str = "alns"
    inner_window_time_fraction: float = 0.8
    inner_kwargs: dict[str, Any] | None = None
    hybrid_inner_routing_enabled: bool = False
    hybrid_inner_solver: str = "cpsat"
    hybrid_due_pressure_threshold: float = 0.35
    hybrid_candidate_pressure_threshold: float = 4.0
    hybrid_max_ops: int = 1500
    hybrid_inner_kwargs: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RhcPolicySpec:
    """Complete parametric snapshot for one RHC run."""

    admission: AdmissionSpec
    budget: BudgetSpec
    guards: GuardSpec
    inner: InnerSpec

    @staticmethod
    def from_preset(policy: RhcPolicy) -> RhcPolicySpec:
        """Return the canonical preset for *policy*."""
        from synaps.solvers.rhc._policy import PRESETS

        return PRESETS.get(policy, PRESETS[RhcPolicy.BALANCED])


# ---------------------------------------------------------------------------
# Presets — validated configurations from synaps.solvers.registry
# ---------------------------------------------------------------------------

_PRESET_ALNS_INNER_KWARGS: dict[str, Any] = {
    "max_iterations": 100,
    "destroy_fraction": 0.03,
    "min_destroy": 10,
    "max_destroy": 40,
    "max_no_improve_iters": 30,
    "use_cpsat_repair": False,
    "repair_time_limit_s": 5,
    "repair_num_workers": 1,
    "cpsat_max_destroy_ops": 32,
    "sa_auto_calibration_enabled": True,
    "sa_calibration_trials": 20,
    "dynamic_sa_enabled": True,
    "sa_due_alpha": 0.35,
    "sa_candidate_beta": 0.15,
    "sa_pressure_cooling_gamma": 0.0015,
    "sa_temp_min": 50.0,
    "sa_temp_max": 500.0,
}

_PRESET_HYBRID_INNER_KWARGS: dict[str, Any] = {
    "num_workers": 4,
}

PRESETS: dict[RhcPolicy, RhcPolicySpec] = {
    RhcPolicy.COVERAGE_FIRST: RhcPolicySpec(
        admission=AdmissionSpec(
            window_minutes=600,
            overlap_minutes=180,
            max_ops_per_window=8000,
            candidate_pool_factor=2.5,
        ),
        budget=BudgetSpec(),
        guards=GuardSpec(),
        inner=InnerSpec(
            inner_kwargs=_PRESET_ALNS_INNER_KWARGS,
            hybrid_inner_kwargs=_PRESET_HYBRID_INNER_KWARGS,
        ),
    ),
    RhcPolicy.BALANCED: RhcPolicySpec(
        admission=AdmissionSpec(
            window_minutes=480,
            overlap_minutes=120,
        ),
        budget=BudgetSpec(),
        guards=GuardSpec(),
        inner=InnerSpec(
            inner_kwargs=_PRESET_ALNS_INNER_KWARGS,
            hybrid_inner_kwargs=_PRESET_HYBRID_INNER_KWARGS,
        ),
    ),
    RhcPolicy.SEARCH_ENTRY: RhcPolicySpec(
        admission=AdmissionSpec(
            window_minutes=300,
            overlap_minutes=90,
        ),
        budget=BudgetSpec(),
        guards=GuardSpec(),
        inner=InnerSpec(
            inner_kwargs=_PRESET_ALNS_INNER_KWARGS,
            hybrid_inner_kwargs=_PRESET_HYBRID_INNER_KWARGS,
        ),
    ),
    RhcPolicy.BOUNDED_100K: RhcPolicySpec(
        admission=AdmissionSpec(
            window_minutes=300,
            overlap_minutes=90,
        ),
        budget=BudgetSpec(),
        guards=GuardSpec(),
        inner=InnerSpec(
            inner_kwargs=_PRESET_ALNS_INNER_KWARGS,
            hybrid_inner_kwargs=_PRESET_HYBRID_INNER_KWARGS,
        ),
    ),
    # FAST_50K: Optimized for 50K-scale instances where wall-time matters more
    # than per-window optimality. Smaller windows (240 min) reduce per-window
    # operation count from ~1000 to ~500, yielding 2-4x faster ALNS per window.
    # Aggressive warm-start skip (gap < 3%) and adaptive iteration scaling
    # further reduce unnecessary computation on well-seeded windows.
    # v2 (2026-05-13): Raised time cap from 60s to 180s after native initial
    # seed reduced Phase 1 from 10s to 1ms — ALNS now has real iteration budget.
    RhcPolicy.FAST_50K: RhcPolicySpec(
        admission=AdmissionSpec(
            window_minutes=240,
            overlap_minutes=60,
            max_ops_per_window=600,
            candidate_pool_factor=2.0,
            due_admission_horizon_factor=6.0,
            admission_tail_weight=0.5,
            progressive_admission_relaxation_enabled=True,
            precedence_ready_candidate_filter_enabled=False,
            admission_relaxation_min_fill_ratio=0.30,
            admission_full_scan_enabled=True,
        ),
        budget=BudgetSpec(
            alns_inner_window_time_cap_s=180.0,
            alns_inner_window_time_cap_scale_threshold_ops=2000,
            alns_inner_window_time_cap_scaled_s=180.0,
            alns_budget_auto_scaling_enabled=True,
            alns_budget_estimated_repair_s_per_destroyed_op=0.125,
            alns_dynamic_repair_budget_enabled=True,
            alns_dynamic_repair_s_per_destroyed_op=0.1,
            alns_dynamic_repair_time_limit_min_s=1.0,
            alns_dynamic_repair_time_limit_max_s=3.0,
            alns_presearch_max_window_ops=2000,
        ),
        guards=GuardSpec(
            fallback_repair_enabled=True,
            backtracking_enabled=True,
            backtracking_tail_minutes=30.0,
            backtracking_max_ops=12,
            inner_fallback_kpi_threshold=0.10,
            inner_solver_min_budget_s=0.0,
        ),
        inner=InnerSpec(
            inner_kwargs={
                "max_iterations": 50,
                "destroy_fraction": 0.05,
                "min_destroy": 5,
                "max_destroy": 25,
                "max_no_improve_iters": 15,
                "use_cpsat_repair": False,
                "repair_time_limit_s": 3,
                "repair_num_workers": 1,
                "cpsat_max_destroy_ops": 20,
                "sa_auto_calibration_enabled": True,
                "sa_calibration_trials": 10,
                "dynamic_sa_enabled": True,
                "sa_due_alpha": 0.35,
                "sa_candidate_beta": 0.15,
                "sa_pressure_cooling_gamma": 0.002,
                "sa_temp_min": 50.0,
                "sa_temp_max": 500.0,
                "adaptive_iteration_scaling": True,
                "warm_start_skip_threshold_gap": 0.03,
            },
            hybrid_inner_routing_enabled=False,
            hybrid_inner_solver="cpsat",
            hybrid_due_pressure_threshold=0.35,
            hybrid_candidate_pressure_threshold=4.0,
            hybrid_max_ops=800,
            hybrid_inner_kwargs={"num_workers": 4},
        ),
    ),
    # GREEDY_COVER: constructive coverage-first path for 50K+ completeness.
    # At ≥10k ops the solver list-schedules in one global greedy pass (rolling
    # windows are for search inners). Residual fill remains the safety net
    # below that threshold; horizon overflow is still ERROR, not FEASIBLE.
    RhcPolicy.GREEDY_COVER: RhcPolicySpec(
        admission=AdmissionSpec(
            window_minutes=480,
            overlap_minutes=120,
            max_ops_per_window=10000,
            candidate_pool_factor=2.0,
            due_admission_horizon_factor=6.0,
            admission_tail_weight=0.5,
            progressive_admission_relaxation_enabled=True,
            precedence_ready_candidate_filter_enabled=False,
            admission_relaxation_min_fill_ratio=0.30,
            admission_full_scan_enabled=True,
        ),
        budget=BudgetSpec(
            coverage_time_reserve_fraction=0.20,
            coverage_time_reserve_min_s=60.0,
            coverage_time_reserve_max_s=300.0,
        ),
        guards=GuardSpec(
            fallback_repair_enabled=True,
            fallback_repair_on_timeout=True,
            fallback_repair_soft_budget_s=120.0,
            backtracking_enabled=False,
            coverage_horizon_extension_factor=1.0,
        ),
        inner=InnerSpec(
            selected_inner_solver_name="greedy",
            inner_window_time_fraction=0.95,
            inner_kwargs={},
            hybrid_inner_routing_enabled=False,
        ),
    ),
    # SEARCH_COVER: search-active ALNS geometry with a coverage safety net.
    # Geometry 360/90 is the search-active point from the 2026-04-26 bounded
    # DOE (fallback=0.0, search-active=1.0); the coverage-pace guard and the
    # GREEDY_COVER reserve mechanics keep the outer scheduled_ratio KPI from
    # regressing while ALNS runs the destroy-repair loop inside windows.
    RhcPolicy.SEARCH_COVER: RhcPolicySpec(
        admission=AdmissionSpec(
            window_minutes=360,
            overlap_minutes=90,
            max_ops_per_window=2000,
            candidate_pool_factor=2.0,
            due_admission_horizon_factor=2.0,
            admission_tail_weight=0.5,
            progressive_admission_relaxation_enabled=True,
            precedence_ready_candidate_filter_enabled=False,
            admission_relaxation_min_fill_ratio=0.30,
            admission_full_scan_enabled=True,
        ),
        budget=BudgetSpec(
            alns_inner_window_time_cap_s=120.0,
            alns_inner_window_time_cap_scale_threshold_ops=2000,
            alns_inner_window_time_cap_scaled_s=120.0,
            alns_budget_auto_scaling_enabled=True,
            alns_budget_estimated_repair_s_per_destroyed_op=0.125,
            alns_dynamic_repair_budget_enabled=True,
            alns_dynamic_repair_s_per_destroyed_op=0.1,
            alns_dynamic_repair_time_limit_min_s=1.0,
            alns_dynamic_repair_time_limit_max_s=3.0,
            alns_presearch_max_window_ops=2000,
            coverage_time_reserve_fraction=0.15,
            coverage_time_reserve_min_s=60.0,
            coverage_time_reserve_max_s=240.0,
        ),
        guards=GuardSpec(
            fallback_repair_enabled=True,
            fallback_repair_on_timeout=True,
            fallback_repair_soft_budget_s=60.0,
            backtracking_enabled=False,
            coverage_horizon_extension_factor=1.0,
            coverage_pace_guard_enabled=True,
            coverage_pace_threshold=1.0,
            coverage_pace_min_windows=2,
            commit_precedence_gate_enabled=True,
        ),
        inner=InnerSpec(
            inner_kwargs={
                **_PRESET_ALNS_INNER_KWARGS,
                "max_iterations": 80,
                "max_no_improve_iters": 20,
            },
            hybrid_inner_routing_enabled=False,
            hybrid_inner_kwargs=_PRESET_HYBRID_INNER_KWARGS,
        ),
    ),
}


def build_solve_kwargs_from_spec(
    spec: RhcPolicySpec,
    *,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten a ``RhcPolicySpec`` into the legacy kwargs dict.

    Override keys (dotted or flat) win over the preset, e.g.
    ``{"admission.window_minutes": 600}`` or ``{"window_minutes": 600}``.
    """
    base: dict[str, Any] = {
        # admission
        "window_minutes": spec.admission.window_minutes,
        "overlap_minutes": spec.admission.overlap_minutes,
        "max_ops_per_window": spec.admission.max_ops_per_window,
        "candidate_pool_factor": spec.admission.candidate_pool_factor,
        "due_admission_horizon_factor": spec.admission.due_admission_horizon_factor,
        "admission_tail_weight": spec.admission.admission_tail_weight,
        "progressive_admission_relaxation_enabled": (
            spec.admission.progressive_admission_relaxation_enabled
        ),
        "precedence_ready_candidate_filter_enabled": (
            spec.admission.precedence_ready_candidate_filter_enabled
        ),
        "admission_relaxation_min_fill_ratio": (spec.admission.admission_relaxation_min_fill_ratio),
        "admission_full_scan_enabled": spec.admission.admission_full_scan_enabled,
        # budget
        "alns_inner_window_time_cap_s": spec.budget.alns_inner_window_time_cap_s,
        "alns_inner_window_time_cap_scale_threshold_ops": (
            spec.budget.alns_inner_window_time_cap_scale_threshold_ops
        ),
        "alns_inner_window_time_cap_scaled_s": (spec.budget.alns_inner_window_time_cap_scaled_s),
        "alns_budget_auto_scaling_enabled": spec.budget.alns_budget_auto_scaling_enabled,
        "alns_budget_estimated_repair_s_per_destroyed_op": (
            spec.budget.alns_budget_estimated_repair_s_per_destroyed_op
        ),
        "alns_dynamic_repair_budget_enabled": spec.budget.alns_dynamic_repair_budget_enabled,
        "alns_dynamic_repair_s_per_destroyed_op": (
            spec.budget.alns_dynamic_repair_s_per_destroyed_op
        ),
        "alns_dynamic_repair_time_limit_min_s": spec.budget.alns_dynamic_repair_time_limit_min_s,
        "alns_dynamic_repair_time_limit_max_s": spec.budget.alns_dynamic_repair_time_limit_max_s,
        "alns_presearch_max_window_ops": spec.budget.alns_presearch_max_window_ops,
        "search_budget_reservation_s": spec.budget.search_budget_reservation_s,
        "coverage_time_reserve_fraction": spec.budget.coverage_time_reserve_fraction,
        "coverage_time_reserve_min_s": spec.budget.coverage_time_reserve_min_s,
        "coverage_time_reserve_max_s": spec.budget.coverage_time_reserve_max_s,
        "window_bound_inner_horizon": True,
        # guards
        "fallback_repair_enabled": spec.guards.fallback_repair_enabled,
        "fallback_repair_on_timeout": spec.guards.fallback_repair_on_timeout,
        "fallback_repair_soft_budget_s": spec.guards.fallback_repair_soft_budget_s,
        "backtracking_enabled": spec.guards.backtracking_enabled,
        "backtracking_tail_minutes": spec.guards.backtracking_tail_minutes,
        "backtracking_max_ops": spec.guards.backtracking_max_ops,
        "inner_fallback_kpi_threshold": spec.guards.inner_fallback_kpi_threshold,
        "inner_solver_min_budget_s": spec.guards.inner_solver_min_budget_s,
        "coverage_horizon_extension_factor": spec.guards.coverage_horizon_extension_factor,
        "coverage_pace_guard_enabled": spec.guards.coverage_pace_guard_enabled,
        "coverage_pace_threshold": spec.guards.coverage_pace_threshold,
        "coverage_pace_min_windows": spec.guards.coverage_pace_min_windows,
        "commit_precedence_gate_enabled": spec.guards.commit_precedence_gate_enabled,
        # inner
        "inner_solver": spec.inner.selected_inner_solver_name,
        "inner_window_time_fraction": spec.inner.inner_window_time_fraction,
        "inner_kwargs": dict(spec.inner.inner_kwargs or {}),
        "hybrid_inner_routing_enabled": spec.inner.hybrid_inner_routing_enabled,
        "hybrid_inner_solver": spec.inner.hybrid_inner_solver,
        "hybrid_due_pressure_threshold": spec.inner.hybrid_due_pressure_threshold,
        "hybrid_candidate_pressure_threshold": spec.inner.hybrid_candidate_pressure_threshold,
        "hybrid_max_ops": spec.inner.hybrid_max_ops,
        "hybrid_inner_kwargs": dict(spec.inner.hybrid_inner_kwargs or {}),
    }

    if overrides:
        for key, value in overrides.items():
            if key in base:
                base[key] = value
                continue
            # dotted-path override, e.g. "admission.window_minutes"
            parts = key.split(".")
            if len(parts) == 2 and parts[1] in base:
                base[parts[1]] = value

    return base


def resolve_policy(
    policy: RhcPolicy | None = None,
    overrides: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[RhcPolicySpec, dict[str, Any]]:
    """Resolve a policy + overrides into a concrete spec and kwargs dict.

    Backward-compatibility: if ``policy`` is None and ``kwargs`` is not empty,
    emit a ``DeprecationWarning`` and return the kwargs as-is (spec = BALANCED).
    """
    import warnings

    if policy is None:
        policy = RhcPolicy.BALANCED
        if kwargs:
            warnings.warn(
                "Passing raw kwargs to RhcSolver is deprecated; use RhcPolicy + overrides instead.",
                DeprecationWarning,
                stacklevel=3,
            )
            return PRESETS[policy], {**build_solve_kwargs_from_spec(PRESETS[policy]), **kwargs}

    spec = PRESETS.get(policy, PRESETS[RhcPolicy.BALANCED])
    flat = build_solve_kwargs_from_spec(spec, overrides=overrides)
    return spec, flat


__all__ = [
    "PRESETS",
    "AdmissionSpec",
    "BudgetSpec",
    "GuardSpec",
    "InnerSpec",
    "RhcPolicy",
    "RhcPolicySpec",
    "build_solve_kwargs_from_spec",
    "resolve_policy",
]
