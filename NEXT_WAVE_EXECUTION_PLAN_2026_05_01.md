# SynAPS Next-Wave Execution Plan — 2026-05-01 (updated 2026-05-15)

## Purpose

This document turns the remaining SynAPS backlog into an executable sequence backed by:

- current repository evidence;
- fresh benchmark reality on pushed `master`;
- external scheduling and optimization practice that remains relevant as of May 2026.

It is intentionally narrower than the older hyperdeep audit plan: this is the next implementation wave, not a full retrospective.

## Current Ground Truth

Repository-backed baseline before the next algorithm wave:

- 50K pure-Python comparison anchor remains `benchmark/studies/2026-04-27-rhc-50k-audit-v2-current-head`.
- Fresh post-critical-fixes 50K evidence is now closed under `benchmark/studies/2026-05-01-rhc-50k-audit-v3-post-critical-fixes`: `RHC-GREEDY` reached `mean_scheduled_ratio = 0.4184`, `RHC-ALNS` reached `0.1374`, and both ran with `native_acceleration_rate = 1.0`.
- 100K bounded pure-Python comparison anchor remains `benchmark/studies/2026-04-27-rhc-100k-audit-v4-current-head`.
- Fresh bounded 100K evidence is now closed under `benchmark/studies/2026-05-01-rhc-100k-audit-v5-post-critical-fixes`: `RHC-GREEDY` improved to `9287/100000` scheduled operations in `90.282s`, while `RHC-ALNS` regressed to `0/100000` in `445.213s` with `solver_metadata.error = "no assignments produced"`.
- Fresh bounded 100K follow-up evidence is now closed under `benchmark/studies/2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix`: `RHC-GREEDY` reached `7633/100000` scheduled operations in `90.399s`, while `RHC-ALNS` recovered to `6933/100000` in `90.281s` by skipping oversized ALNS pre-search windows (`budget_guard_skipped_windows = 2`) and falling back greedily. This closes the catastrophic zero-assignment seed-stall family on the staged harness, but it does not restore active ALNS search or greedy parity.
- Fresh bounded 100K predicate-follow-up evidence is now closed under `benchmark/studies/2026-05-01-rhc-100k-audit-v8-post-predicate-fix`: the `R1` predicate patch does re-enter ALNS search on the bounded rail, but the same run shows the next controlling bottleneck. `RHC-ALNS` starts ALNS on a `1501`-operation first window, spends about `808.843s` in initial solution generation, completes `0` iterations, and regresses to `0/100000` scheduled operations while `RHC-GREEDY` reaches `7013/100000` in `90.376s`.
- Fresh bounded 100K closure evidence is now closed under `benchmark/studies/2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap`: `RHC-ALNS` reaches `7236/100000` scheduled operations in `90.255s`, same-run `RHC-GREEDY` reaches `7230/100000` in `90.365s`, two bounded windows are observed, fallback repair is no longer skipped, and `solver_metadata.error` is absent. This closes the bounded-stability acceptance gate even though active ALNS search is still absent.
- Fresh 100K parity evidence is now closed under `benchmark/studies/2026-05-15-rhc-100k-v9`: `RHC-ALNS` reaches `7279/100000` scheduled operations in `90.263s`, same-run `RHC-GREEDY` reaches `7509/100000` in `90.302s`. **Same-run parity confirmed.**
- The TypeScript `control-plane` security/auth hardening shipped separately on 2026-05-01 as commit `7dc540f` (`fix(control-plane): harden auth and python bridge env`).
- Deep audit re-verification on current `master` is captured in `AUDIT_VERIFICATION_2026_05_01.md` and `REGRESSION_CLOSURE_2026_05_14.md`; all 350+ tests pass, type checking, lint, and format are green.

Current unresolved technical bottlenecks:

1. RHC/ALNS active-search yield above the bounded-stability gate. The accepted `v11` slice restores same-run bounded parity, but `search_active_window_rate` is still `0.0` and `inner_fallback_ratio` is still `1.0`, so the remaining 100K/200K work is yield optimization rather than catastrophic-stall containment.
2. LBBD master strength. (Wave 3b closed RHC parameter surface; LBBD cut quality remains the active algorithmic lever for raising the lower bound.)

## External Evidence Anchors

The next wave should stay aligned with these external references:

1. Google OR-Tools CP-SAT docs (`cp_tasks`, `cp_solver`, updated 2024-08-28): time limits and explicit stop conditions are first-class controls, so SynAPS should keep solver-native limits instead of wrapper-side thread kills.
2. ICLR 2025, `Learning-Guided Rolling Horizon Optimization for Long-Horizon Flexible Job-Shop Scheduling` (`L-RHO`): reduce re-optimization scope by fixing variables that do not need to move between horizons.
3. arXiv 2504.16106 (Apr 2025), `Updating Lower and Upper Bounds for the Job-Shop Scheduling Problem Test Instances`: benchmark progress is judged by stronger upper and lower bounds together, not by heuristic output alone.
4. Mavrotas and Florios 2013, `AUGMECON2`: exact Pareto generation remains the defensible baseline for multi-objective integer scheduling slices.
5. Naderi and Roshanaei 2021, `Critical-Path-Search Logic-Based Benders Decomposition Approaches for Flexible Job Shop Scheduling`: stronger LBBD progress comes from critical-path-aware cuts.
6. The 2023 preemptive FJSP LBBD line: exact decomposition quality improves when the subproblem feeds master cuts reflecting actual sequencing structure.
7. HiGHS current project posture (`highs.dev`, May 2026): HiGHS remains a credible large-scale open LP/MIP master layer.

## What This Means For SynAPS

- Do not spend the next wave on broader metaheuristic knob growth.
- Do not hide weak coverage behind partial feasibility metrics.
- Do strengthen lower bounds and decomposition cuts.
- Do shrink horizon work by fixing safe decisions and simplifying runtime profiles.
- Do keep benchmark claims tied to reproducible bounded rails.

## Execution Order

### Wave 1 — Close The Evidence Loop

Status: completed on 2026-05-01.

Goal: refresh the two canonical large-instance evidence slices on pushed `master`.

Completed outputs:
1. Closed the fresh 50K audit in `benchmark/studies/2026-05-01-rhc-50k-audit-v3-post-critical-fixes`.
2. Closed the bounded 100K rerun in `benchmark/studies/2026-05-01-rhc-100k-audit-v5-post-critical-fixes`.
3. Compared both outputs against the 2026-04-27 anchors.
4. Recorded the controlling deltas in scheduled ratio, fallback ratio, search-entry behavior, wall time, and execution backend.

Key findings: both study directories now contain reproducible JSON artifacts; 50K improved on scheduled coverage for both solvers under native acceleration; 100K `RHC-GREEDY` improved while bounded 100K `RHC-ALNS` regressed to a one-window zero-assignment stall, reopening the old seed-construction failure family. (See full analysis in the 2026-05-01 audit report.)

### Wave 2 — Control-Plane Security/Auth Changeset

Status: completed on 2026-05-01 via commit `7dc540f`.

Goal: keep the shipped `control-plane` hardening isolated from solver-algorithm work.

### Wave 3 — Tighten LBBD Master Strength + Initial-Seed Budget Contract

Status: **completed 2026-05-15.**

**Wave 3a — Initial-seed budget fix (completed 2026-05-15):**
- `GreedyDispatch.solve()` now honors `time_limit_s` → returns `TIMEOUT` + `partial_schedule=True`
- `AlnsSolver` passes remaining budget to every greedy call, surfaces `initial_seed_greedy_timed_out`
- 100K v9 evidence: `RHC-ALNS` `7279/100000` in `90.263s`, same-run parity with `RHC-GREEDY` `7509/100000` in `90.302s`
- Artifact: `benchmark/studies/2026-05-15-rhc-100k-v9/`
- Tests: `tests/test_greedy_dispatch_time_limit.py` (2 tests)

**Wave 3b — LBBD cut strengthening (completed 2026-05-15):**
- `machine_tsp` cut (Bellman-Held-Karp) integrated in both LBBD and LBBD-HD
- `critical_path` cut with ≥ 5 % makespan threshold (R9) in both solvers
- Cut-pool deduplication via `cut_pool_fingerprint()`
- `ub_evolution` and `cut_kind_lb_contribution` tracking in solver metadata
- HiGHS warm-start via `setSolution()` using previous master assignment

### Wave 4 — Reduce The RHC Parameter Surface

Status: **completed 2026-05-15.**

- Named policy presets: `coverage-first`, `balanced`, `search-entry`, `bounded-100k`, `fast-50k`
- Structured spec dataclasses: `AdmissionSpec`, `BudgetSpec`, `GuardSpec`, `InnerSpec`
- `build_solve_kwargs_from_spec()` with dotted-path override support
- `resolve_policy()` with deprecation path for raw kwargs
- Cross-window variable fixing (L-RHO pattern) via `detect_cross_window_stable_ops()`
- Fixed-op IDs passed to ALNS inner solver with per-op stability frequency tracking
- 136 regression tests pass across LBBD, RHC, and greedy dispatch suites

### Wave 5 — Refresh Multi-Objective Positioning

Status: **completed 2026-05-15 (documentation pass).**

- README updated: separated Wave 3b, 4, and 5 as distinct delivered items
- Next-Wave Execution Plan reflects final status for all waves
- 100K+ snapshot updated with May 2026 bounded parity evidence (`7279/100000` ALNS, `7509/100000` GREEDY)
- Quick-evidence artifact: `benchmark/studies/2026-05-15-quick-evidence/quick_20ops.json` confirms all 4 policy presets return feasible solutions

## Stop Conditions

Pause only if one of these becomes true:

1. large-instance reruns fail because of an environment defect rather than SynAPS behavior;
2. LBBD master strengthening requires a public-contract change not implied by the current solver portfolio;
3. variable-fixing policy for RHC changes benchmark semantics enough that existing public claims must be explicitly versioned.

Otherwise the default is to continue through the next algorithm wave (strengthening LBBD cuts and improving active-search yield) without reopening planning.

## Output Expectations (Next Algorithm Wave)

1. Fresh 50K multi-seed benchmark evidence with improved active-search yield
2. LBBD master cut-strength comparison (with/without TSP cut, with/without CP share threshold)
3. Improved 100K coverage via active-search yield optimization