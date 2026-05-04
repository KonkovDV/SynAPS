"""Budget arithmetic for the RHC solver's per-window inner search.

This module hosts the pure budget kernels that determine

    1. the wall-clock time cap allocated to one window's inner solve
       (`resolve_inner_window_time_cap`); and
    2. the ALNS-specific destroy/iteration scaling that fits an inner
       search into a given per-window time limit
       (`scale_alns_inner_budget`).

Decomposed from `synaps/solvers/rhc/_solver.py` as part of the R7 subpackage
split (see AGENTS.md Wave 4 / R7 roadmap).

Academic basis:
    - The destroy-size <-> repair-time-limit linearization mirrors the
      "operation cost" model used in adaptive large-neighborhood search
      literature (Pisinger & Ropke 2010): the expected wall time of one
      ALNS iteration is the destroy size times an empirically estimated
      per-operation repair cost. Solving for the operation count and
      iteration count under a wall-clock budget gives the closed-form
      caps implemented here.
    - The window-time fraction / cap policy is from receding-horizon MPC
      literature (Rawlings & Mayne 2009): the inner solver of a single
      window receives a bounded share of the global solve budget so the
      outer loop retains progress guarantees.

All helpers in this module are pure: they read scalar inputs and return
either a float or a dict and never mutate solver state. The RHC solver
retains ownership of all live counters and decision state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Time-cap policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InnerWindowTimeCapPolicy:
    """Configuration governing the per-window inner-solve wall-clock cap.

    All four fields come straight from the RHC solver kwargs:

    * ``inner_window_time_cap_s`` — global cap shared by all inner solvers.
    * ``alns_inner_window_time_cap_s`` — ALNS-specific override that wins
      over the global cap when set.
    * ``alns_inner_window_time_cap_scaled_s`` — large-window ALNS cap
      activated when the window operation count crosses
      ``alns_inner_window_time_cap_scale_threshold_ops``.
    * ``alns_inner_window_time_cap_scale_threshold_ops`` — operation-count
      threshold that triggers the scaled cap.
    """

    inner_window_time_cap_s: float | None
    alns_inner_window_time_cap_s: float | None
    alns_inner_window_time_cap_scaled_s: float
    alns_inner_window_time_cap_scale_threshold_ops: int


_DEFAULT_INNER_WINDOW_TIME_CAP_S = 60.0


def resolve_inner_window_time_cap(
    *,
    selected_solver_name: str,
    window_op_count: int,
    policy: InnerWindowTimeCapPolicy,
) -> float:
    """Resolve the wall-clock cap for one window's inner solve.

    Decision tree (mirrors the original closure exactly):

    * For ALNS:
        1. ``alns_inner_window_time_cap_s`` if set;
        2. else the global ``inner_window_time_cap_s`` if set;
        3. else, when ``window_op_count`` reaches the scale threshold,
           the scaled ALNS cap;
        4. else the default 60 s.
    * For any other inner solver:
        1. ``inner_window_time_cap_s`` if set;
        2. else the default 60 s.

    Pure function: reads only its scalar inputs.
    """
    if selected_solver_name == "alns":
        if policy.alns_inner_window_time_cap_s is not None:
            return policy.alns_inner_window_time_cap_s
        if policy.inner_window_time_cap_s is not None:
            return policy.inner_window_time_cap_s
        if window_op_count >= policy.alns_inner_window_time_cap_scale_threshold_ops:
            return policy.alns_inner_window_time_cap_scaled_s
        return _DEFAULT_INNER_WINDOW_TIME_CAP_S

    if policy.inner_window_time_cap_s is not None:
        return policy.inner_window_time_cap_s
    return _DEFAULT_INNER_WINDOW_TIME_CAP_S


# ---------------------------------------------------------------------------
# ALNS budget scaling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlnsBudgetPolicy:
    """Static ALNS-budget policy constants drawn from the RHC kwargs.

    * ``estimated_repair_s_per_destroyed_op_raw`` — empirical estimate of
      one repair-step wall time per destroyed operation. ``None`` means
      fall back to ``repair_time_limit_s / max_destroy`` (i.e. the
      requested per-iteration budget divided by the requested destroy
      size).
    * ``dynamic_repair_time_limit_min_s`` / ``_max_s`` — clamp range for
      the per-iteration repair-time limit derived from the effective
      destroy size.
    * ``dynamic_repair_s_per_destroyed_op`` — slope of the
      effective-repair-time vs. effective-destroy-size linearization.
    """

    estimated_repair_s_per_destroyed_op_raw: float | None
    dynamic_repair_time_limit_min_s: float
    dynamic_repair_time_limit_max_s: float
    dynamic_repair_s_per_destroyed_op: float


def scale_alns_inner_budget(
    *,
    effective_kwargs: dict[str, Any],
    per_window_limit: float,
    window_op_count: int,
    policy: AlnsBudgetPolicy,
) -> dict[str, Any]:
    """Compute effective ALNS iteration / destroy / repair caps for the
    current window given a wall-clock budget.

    Returns a dict with the seven keys consumed downstream by the RHC
    telemetry layer (and by the ALNS solver itself for the iteration
    cap):

    * ``requested_max_iterations``, ``requested_max_destroy`` — sanitized
      caller-supplied caps;
    * ``effective_max_iterations``, ``effective_max_destroy`` — caps
      after fitting them to ``per_window_limit``;
    * ``effective_repair_time_limit_s`` — the clamped per-iteration
      repair-time limit corresponding to the effective destroy size;
    * ``estimated_repair_s_per_destroyed_op`` — the per-destroyed-op
      cost actually used for the linearization (either policy-supplied
      or derived from the requested per-iteration budget);
    * ``scaled`` — boolean indicating whether either of the effective
      caps differs from the requested cap.

    Pure function: reads scalar inputs and the ``effective_kwargs`` dict
    by key (no mutation of the dict).
    """
    requested_max_iterations = max(
        1,
        int(effective_kwargs.get("max_iterations", 500)),
    )
    min_destroy = max(1, int(effective_kwargs.get("min_destroy", 20)))
    requested_max_destroy = max(
        min_destroy,
        int(effective_kwargs.get("max_destroy", 300)),
    )
    repair_time_limit_s = max(
        1.0,
        float(effective_kwargs.get("repair_time_limit_s", 10.0)),
    )

    estimated_repair_s_per_destroyed_op = (
        max(0.01, float(policy.estimated_repair_s_per_destroyed_op_raw))
        if policy.estimated_repair_s_per_destroyed_op_raw is not None
        else repair_time_limit_s / max(1, requested_max_destroy)
    )

    destroy_cap_from_budget = min(
        requested_max_destroy,
        max(
            min_destroy,
            int(
                per_window_limit
                / max(1, requested_max_iterations)
                / estimated_repair_s_per_destroyed_op
            ),
        ),
    )

    destroy_fraction = max(
        0.0,
        float(effective_kwargs.get("destroy_fraction", 0.05)),
    )
    requested_destroy_size = max(
        min_destroy,
        int(math.ceil(window_op_count * destroy_fraction)),
    )

    effective_max_destroy = max(
        min_destroy,
        min(requested_max_destroy, destroy_cap_from_budget),
    )
    estimated_destroy_size = min(requested_destroy_size, effective_max_destroy)
    estimated_iteration_seconds = max(
        0.1,
        estimated_destroy_size * estimated_repair_s_per_destroyed_op,
    )
    effective_max_iterations = min(
        requested_max_iterations,
        max(1, int(per_window_limit / estimated_iteration_seconds)),
    )
    effective_repair_time_limit_s = max(
        0.1,
        min(
            policy.dynamic_repair_time_limit_max_s,
            max(
                policy.dynamic_repair_time_limit_min_s,
                effective_max_destroy * policy.dynamic_repair_s_per_destroyed_op,
            ),
        ),
    )

    return {
        "requested_max_iterations": requested_max_iterations,
        "requested_max_destroy": requested_max_destroy,
        "effective_max_iterations": effective_max_iterations,
        "effective_max_destroy": effective_max_destroy,
        "effective_repair_time_limit_s": effective_repair_time_limit_s,
        "estimated_repair_s_per_destroyed_op": estimated_repair_s_per_destroyed_op,
        "scaled": (
            effective_max_iterations != requested_max_iterations
            or effective_max_destroy != requested_max_destroy
        ),
    }
