# Syn-APS — Universal Advanced Planning & Scheduling Solver
"""
MO-FJSP-SDST-ML-ARC solver portfolio:
  - GreedyDispatch (ATCS-based, < 200 ms)
  - CpSatSolver (OR-Tools CP-SAT, time-boxed)
  - LbbdSolver (HiGHS master + CP-SAT sub, iterative Benders cuts)
  - IncrementalRepair (neighbourhood repair on disruptions)
  - FeasibilityChecker (constraint validation without solving)
"""

__version__ = "0.1.0"
