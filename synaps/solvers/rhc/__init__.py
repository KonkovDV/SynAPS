"""RHC (Rolling Horizon Control) solver package.

Public API — import from here, not from submodules:
    from synaps.solvers.rhc import RhcSolver, RhcWindowState
"""
from __future__ import annotations

from synaps.solvers.rhc._solver import RhcSolver
from synaps.solvers.rhc._state import RhcWindowState

__all__ = ["RhcSolver", "RhcWindowState"]
