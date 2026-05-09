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

    COVERAGE_FIRST = "coverage-first"      # wide windows, ALNS inner
    BALANCED = "balanced"                  # default 8h/2h ALNS
    SEARCH_ENTRY = "search-entry"          # 100K tight-geometry profile
    BOUNDED_100K = "bounded-100k"            # aggressive 5h/90m ALNS


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


@dataclass(frozen=True, slots=True)
class GuardSpec:
    """Pre-search and fallback guard-rails."""

    fallback_repair_enabled: bool = True
    backtracking_enabled: bool = True
    backtracking_tail_minutes: float = 60.0
    backtracking_max_ops: int = 24
    inner_fallback_kpi_threshold: float = 0.10
    inner_solver_min_budget_s: float = 0.0


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
        "admission_relaxation_min_fill_ratio": (
            spec.admission.admission_relaxation_min_fill_ratio
        ),
        "admission_full_scan_enabled": spec.admission.admission_full_scan_enabled,
        # budget
        "alns_inner_window_time_cap_s": spec.budget.alns_inner_window_time_cap_s,
        "alns_inner_window_time_cap_scale_threshold_ops": (
            spec.budget.alns_inner_window_time_cap_scale_threshold_ops
        ),
        "alns_inner_window_time_cap_scaled_s": (
            spec.budget.alns_inner_window_time_cap_scaled_s
        ),
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
        # guards
        "fallback_repair_enabled": spec.guards.fallback_repair_enabled,
        "backtracking_enabled": spec.guards.backtracking_enabled,
        "backtracking_tail_minutes": spec.guards.backtracking_tail_minutes,
        "backtracking_max_ops": spec.guards.backtracking_max_ops,
        "inner_fallback_kpi_threshold": spec.guards.inner_fallback_kpi_threshold,
        "inner_solver_min_budget_s": spec.guards.inner_solver_min_budget_s,
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
                "Passing raw kwargs to RhcSolver is deprecated; "
                "use RhcPolicy + overrides instead.",
                DeprecationWarning,
                stacklevel=3,
            )
            return PRESETS[policy], {**build_solve_kwargs_from_spec(PRESETS[policy]), **kwargs}

    spec = PRESETS.get(policy, PRESETS[RhcPolicy.BALANCED])
    flat = build_solve_kwargs_from_spec(spec, overrides=overrides)
    return spec, flat


__all__ = [
    "RhcPolicy",
    "RhcPolicySpec",
    "AdmissionSpec",
    "BudgetSpec",
    "GuardSpec",
    "InnerSpec",
    "PRESETS",
    "build_solve_kwargs_from_spec",
    "resolve_policy",
]
