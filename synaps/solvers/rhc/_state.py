"""Typed window state for RHC solver.

This module is the foundation for R6 (typed RhcPolicy) and R7 (subpackage split).
All RHC window transitions must go through RhcWindowState — never bare dicts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class RhcWindowState:
    """State of a single RHC window at any point during solve.

    Invariants:
    - budget_remaining_s >= 0 always
    - overlap_tail contains only committed assignments from the previous window
    - status transitions: pending → (alns_running | greedy_fallback) → done | failed
    """
    window_id: int
    status: Literal[
        "pending",
        "seed_building",
        "alns_running",
        "greedy_fallback",
        "inner_time_limit_exhausted",
        "budget_guard_skipped",
        "done",
        "failed",
    ]
    budget_total_s: float
    budget_remaining_s: float
    ops_admitted: int
    ops_scheduled: int
    overlap_tail_size: int
    alns_iterations_completed: int
    alns_improvements: int
    inner_time_limit_exhausted: bool
    budget_guard_skipped_initial_search: bool
    admission_full_scan_used: bool
    seed_timed_out: bool
    # Filled after window completes:
    wall_s: float = 0.0
    fallback_reason: str | None = None

    @property
    def scheduled_ratio(self) -> float:
        if self.ops_admitted == 0:
            return 0.0
        return self.ops_scheduled / self.ops_admitted

    @property
    def budget_utilization(self) -> float:
        if self.budget_total_s == 0:
            return 0.0
        return (self.budget_total_s - self.budget_remaining_s) / self.budget_total_s

    def as_metadata(self) -> dict[str, object]:
        """Serialize to metadata-compatible dict (mirrors existing metadata contract)."""
        return {
            "window_id": self.window_id,
            "status": self.status,
            "budget_total_s": round(self.budget_total_s, 3),
            "budget_remaining_s": round(self.budget_remaining_s, 3),
            "budget_utilization": round(self.budget_utilization, 4),
            "ops_admitted": self.ops_admitted,
            "ops_scheduled": self.ops_scheduled,
            "scheduled_ratio": round(self.scheduled_ratio, 4),
            "overlap_tail_size": self.overlap_tail_size,
            "alns_iterations_completed": self.alns_iterations_completed,
            "alns_improvements": self.alns_improvements,
            "inner_time_limit_exhausted": self.inner_time_limit_exhausted,
            "budget_guard_skipped_initial_search": self.budget_guard_skipped_initial_search,
            "admission_full_scan_used": self.admission_full_scan_used,
            "seed_timed_out": self.seed_timed_out,
            "wall_s": round(self.wall_s, 3),
            "fallback_reason": self.fallback_reason,
        }
