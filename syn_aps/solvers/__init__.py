"""Solver interface — abstract base class for all scheduling solvers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from syn_aps.model import ScheduleProblem, ScheduleResult


class BaseSolver(ABC):
    """Common interface for the entire solver portfolio."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique solver identifier."""

    @abstractmethod
    def solve(self, problem: ScheduleProblem, **kwargs: object) -> ScheduleResult:
        """Produce a schedule for the given problem.

        Args:
            problem: Fully specified scheduling problem.
            **kwargs: Solver-specific parameters (time_limit_s, random_seed, etc.).

        Returns:
            ScheduleResult with assignments and objective values.
        """
