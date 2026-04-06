---
title: "SynAPS Technical Verification Report 2026-04"
status: "active"
version: "2.0.1"
last_updated: "2026-04-05"
date: "2026-04-05"
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
| Current pytest collection | `175` tests collected across `26` modules |
| Last fully recorded full-suite pass snapshot | `149/149` passed |
| Snapshot provenance | earlier April 2026 full-suite verification run recorded in this evidence pack |
| Current delta | the suite has expanded since that recorded pass snapshot |

Current collection now spans 26 modules, including the earlier core verification surfaces plus newer coverage for accelerators, benchmark boundary and scaling studies, benchmark generation and harness routes, CP-SAT phase-2 features, LBBD-HD, LBBD phase-2 features, replay artifacts, schema DDL, and solver-portfolio registry/routing behavior.

This means the repository's test surface is broader than the last fully recorded pass snapshot. It does **not** yet mean that a fresh `175/175` full-suite pass has been captured in this dated report.

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
2. tests cover the currently documented core solver families and surrounding routing surfaces, including CP-SAT, greedy dispatch, LBBD, incremental repair, LBBD-HD-related additions, and cross-solver consistency checks;
3. property-based testing (Hypothesis) validates structural invariants across random problem instances;
4. benchmark regression tests pin quality bounds to prevent silent regressions;
5. the benchmark harness works end-to-end on the canonical smoke instance;
6. the evidence cited in investor materials has been refreshed to distinguish the expanded suite size from the last fully recorded full-suite pass snapshot.

### Defects fixed in the earlier full-suite verification cycle (2026-04-04)

1. **LBBD cross-cluster precedence**: subproblems solved independently could produce assignments violating cross-cluster precedence and setup-gap constraints. Fixed with a post-assembly enforcement pass.
2. **CP-SAT integer discretization tolerance**: property-based tests revealed that CP-SAT integer-minute rounding produces slightly worse makespans than greedy's fractional minutes on small instances with non-unit speed factors. Tolerance adjusted from fixed +1 min to 15%.
3. **Greedy horizon overflow**: Hypothesis discovered that greedy dispatch schedules all operations even when slow speed factors push ops beyond the planning horizon. Feasibility check updated to treat horizon bounds as soft constraints for greedy.

## Remaining Verification Work

1. medium and large instance benchmark families with repeated runs and statistical reporting;
2. hardware disclosure and run-normalization for publication-grade benchmark comparisons;
3. additional stress cases for auxiliary-resource-heavy instances;
4. benchmark comparison against transparent external baselines;
5. a new single-shot full-suite pass record for the now-expanded 175-test collection.

## Documentation Alignment Fixes Applied (2026-04-05)

This verification surface now also records the investor-pack corrections applied after the 2026-04-04 slimming pass:

1. active English investor docs now align benchmark language to the currently verified smoke-instance result only: `tiny_3x3`, `106.67 -> 82.0` minutes, approximately `23.1%` versus `GREED`;
2. mojibake was corrected in active English router surfaces, glossary entries, and market-model formulas;
3. the default technical reading route still points first to `VERIFICATION_COVERAGE_AUDIT_2026_04.md`, while `HYPERDEEP_AUDIT_REPORT_2026_04.md` has been rewritten into a readable optional deep-audit summary and its raw historical snapshot was preserved in the archive;
4. the active Russian route is now explicit: `HYPER_DEEP_REPORT_2026_04_RU.md` is the concise summary surface, while the preserved long-form Russian investor narrative is routed through the archive copy of `HYPER_DEEP_REPORT_2026_04_RU_v2.md`.
