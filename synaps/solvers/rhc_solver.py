"""RHC solver compatibility shim (deprecated).

Import from synaps.solvers.rhc directly:
    from synaps.solvers.rhc import RhcSolver, RhcWindowState
"""
from __future__ import annotations

import warnings

warnings.warn(
    "synaps.solvers.rhc_solver is deprecated; "
    "import from synaps.solvers.rhc directly",
    DeprecationWarning,
    stacklevel=2,
)

from synaps.solvers.rhc import RhcSolver, RhcWindowState

__all__ = ["RhcSolver", "RhcWindowState"]
