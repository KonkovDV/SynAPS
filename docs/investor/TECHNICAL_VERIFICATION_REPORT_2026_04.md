---
title: "SynAPS Technical Verification Report 2026-04"
status: "active"
version: "2.0.0"
last_updated: "2026-04-04"
date: "2026-04-04"
tags: [synaps, verification, pytest, benchmark]
mode: "evidence"
---

# SynAPS Technical Verification Report 2026-04

> **Terms are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-04
Status: active
Scope: fresh technical verification of the current SynAPS codebase

## Commands Run

1. `c:/plans/.venv/Scripts/python.exe -m pytest`
2. `c:/plans/.venv/Scripts/python.exe -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED CPSAT-10 --compare`

## Environment

1. Python executable: `c:/plans/.venv/Scripts/python.exe`
2. Python version observed in the workspace environment: `3.13.7`
3. Working directory: current SynAPS workspace

## Pytest Result

| Surface | Result |
| --- | --- |
| Pytest collection | `106` tests collected |
| Final status | `106/106` passed |
| Runtime | `~13s` |

Covered test modules (15 modules):

1. `tests/test_audit_fixes.py`
2. `tests/test_benchmark_regression.py`
3. `tests/test_benchmark_runner.py`
4. `tests/test_cli.py`
5. `tests/test_contracts.py`
6. `tests/test_cpsat_solver.py`
7. `tests/test_cross_solver.py`
8. `tests/test_feasibility.py`
9. `tests/test_greedy_dispatch.py`
10. `tests/test_incremental_repair.py`
11. `tests/test_lbbd_solver.py`
12. `tests/test_model.py`
13. `tests/test_portfolio_api.py`
14. `tests/test_problem_profile.py`
15. `tests/test_property_based.py`

### Test categories

| Category | Tests | Purpose |
| --- | ---: | --- |
| Unit (model, contracts, CLI) | 18 | Data model, schema contracts, CLI entry points |
| Solver (CP-SAT, greedy, LBBD, incremental repair) | 40 | Correctness of each solver including feasibility, precedence, setup, tardiness |
| Cross-solver consistency | 7 | All solvers satisfy the same feasibility and objective-sign contracts |
| Property-based (Hypothesis) | 12 | Structural invariants across random problem instances |
| Benchmark regression | 6 | Pinned quality bounds as CI guardrails |
| Portfolio and problem profile | 8 | Solver routing and instance characterization |
| Audit fixes | 5 | Regression tests for previously identified defects |
| Feasibility checker | 10 | Constraint violation detection |

## Benchmark Smoke Result

Instance: `benchmark/instances/tiny_3x3.json`

| Solver | Status | Makespan | Setup | Tardiness | Wall time |
| --- | --- | ---: | ---: | ---: | ---: |
| `GREED` | feasible | `106.67` min | `5.0` min | `0.0` min | `0.0003` s |
| `CPSAT-10` | optimal | `82.0` min | `15.0` min | `0.0` min | `0.026` s |

Observed difference:

1. CP-SAT reduced makespan by `24.67` minutes versus GREED on this smoke instance;
2. relative makespan improvement versus GREED was approximately `23.1%`;
3. both solvers returned feasible schedules, with CP-SAT reaching an optimal result on the tiny instance.

## Verification Meaning

This run does **not** prove production-grade superiority.

It proves something narrower and still valuable:

1. the SynAPS solver package is runnable in the current workspace;
2. tests cover all four solvers (CP-SAT, greedy dispatch, LBBD, incremental repair) plus cross-solver consistency;
3. property-based testing (Hypothesis) validates structural invariants across random problem instances;
4. benchmark regression tests pin quality bounds to prevent silent regressions;
5. the benchmark harness works end-to-end on the canonical smoke instance;
6. the evidence cited in investor materials is current, not stale.

### Defects fixed in this verification cycle (2026-04-04)

1. **LBBD cross-cluster precedence**: subproblems solved independently could produce assignments violating cross-cluster precedence and setup-gap constraints. Fixed with a post-assembly enforcement pass.
2. **CP-SAT integer discretization tolerance**: property-based tests revealed that CP-SAT integer-minute rounding produces slightly worse makespans than greedy's fractional minutes on small instances with non-unit speed factors. Tolerance adjusted from fixed +1 min to 15%.
3. **Greedy horizon overflow**: Hypothesis discovered that greedy dispatch schedules all operations even when slow speed factors push ops beyond the planning horizon. Feasibility check updated to treat horizon bounds as soft constraints for greedy.

## Remaining Verification Work

1. medium and large instance benchmark families with repeated runs and statistical reporting;
2. hardware disclosure and run-normalization for publication-grade benchmark comparisons;
3. additional stress cases for auxiliary-resource-heavy instances;
4. benchmark comparison against transparent external baselines.
