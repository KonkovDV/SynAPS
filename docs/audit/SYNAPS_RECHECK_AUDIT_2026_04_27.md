# SynAPS Recheck Audit (2026-04-27)

> Date: 2026-04-27
> Scope: current-head recheck after the public `RHC-ALNS` profile cleanup and the staged `100k+` geometry retune.
> Status: evidence-backed audit memo for the current repository state.

## 1. Audit Questions

This recheck focused on four narrow questions:

1. did the latest `100k+` harness change only move the failure mode, or did it actually let ALNS enter search;
2. what is the real current boundary between solver/runtime limits and model/schema limits;
3. which external ALNS / CP-SAT practices are already implemented in SynAPS, and which remain open research work;
4. what is the next justified engineering target after the two published April 27 commits.

## 2. Current Local Evidence

### 2.1 Public/default profile state

The public `RHC-ALNS` profile has already been cleaned away from the retired CP-SAT-heavy side paths.

Current public/default evidence anchors:

- 50K audit before the public profile refresh: [../../benchmark/studies/2026-04-27-rhc-50k-audit-v1/rhc_50k_study.json](../../benchmark/studies/2026-04-27-rhc-50k-audit-v1/rhc_50k_study.json)
- 50K audit after the public profile refresh: [../../benchmark/studies/2026-04-27-rhc-50k-audit-v2-current-head/rhc_50k_study.json](../../benchmark/studies/2026-04-27-rhc-50k-audit-v2-current-head/rhc_50k_study.json)
- 100K retired-profile failure artifact: [../../benchmark/studies/2026-04-27-rhc-100k-audit-v1/rhc_500k_study.json](../../benchmark/studies/2026-04-27-rhc-100k-audit-v1/rhc_500k_study.json)
- 100K staged geometry-refresh artifact: [../../benchmark/studies/2026-04-27-rhc-100k-audit-v3-geometry-refresh/rhc_500k_study.json](../../benchmark/studies/2026-04-27-rhc-100k-audit-v3-geometry-refresh/rhc_500k_study.json)
- 100K current-head same-run artifact: [../../benchmark/studies/2026-04-27-rhc-100k-audit-v4-current-head/rhc_500k_study.json](../../benchmark/studies/2026-04-27-rhc-100k-audit-v4-current-head/rhc_500k_study.json)

The authoritative 50K public/default evidence for this audit is now the April 27 `v2` artifact above, not `v1`. It shows that the public profile cleanup removed hybrid CP-SAT routing and CP-SAT micro-repair from the benchmark default, but coverage did not improve: `RHC-GREEDY` finishes at `17815/49871` scheduled (`mean_scheduled_ratio = 0.3563`), while `RHC-ALNS` finishes at `4223/49871` (`mean_scheduled_ratio = 0.0845`, `mean_inner_fallback_ratio = 0.6667`). Early ALNS windows still enter search, but later windows now fail earlier with `inner_time_limit_exhausted_before_search` during seed construction.

### 2.2 100K staged-harness results

The staged `100k` geometry-refresh artifacts are the decisive local result for this audit:

- first-window geometry narrowed from the retired `480/120` staged setting to `300/90` for `100k+`;
- `v3` first showed that ALNS now reaches the search loop instead of stalling entirely in initial solution generation, with `55` iterations, `43` improvements, `0` inner fallback, `4678 / 100000` scheduled operations, and about `90.118s` wall time;
- fresh current-head `v4` keeps that search-entry result in a same-run comparison: `RHC-GREEDY` schedules `7852 / 100000` operations in `90.213s`, while `RHC-ALNS` schedules `3420 / 100000` in `90.113s` after entering search in both bounded windows (`56` and `30` iterations, `45` and `18` improvements, `0` CP-SAT repairs, `0` inner fallback).

This falsifies the older blanket reading that `100K ALNS never reaches search`.

It does **not** establish production readiness:

- `feasible = false`
- `mean_scheduled_ratio = 0.0342` on the fresh current-head same-run slice
- `RHC-ALNS` still trails the same-run `RHC-GREEDY` baseline on scheduled coverage
- quality gate still fails.

### 2.3 Current scale-boundary surface

A fresh current-head plan-mode scale ladder confirms the present hard boundary:

- current-head plan artifact: [../../benchmark/studies/2026-04-27-rhc-500k-plan-v1-current-head/rhc_500k_study.json](../../benchmark/studies/2026-04-27-rhc-500k-plan-v1-current-head/rhc_500k_study.json)

Observed boundary:

- `50000`, `100000`, `200000` pass the resource/model gate;
- `300000` and `500000` are blocked by `operations_exceed_model_limit`;
- projected memory remains well below the configured workstation threshold, so the active public boundary is model/schema capacity, not RAM pressure.

## 3. External Fact-Check

This audit rechecked the current SynAPS behavior against openly accessible primary or maintainer-level sources:

- Google OR-Tools CP-SAT: explicit solver time limits and status semantics (`OPTIMAL`, `FEASIBLE`, `INFEASIBLE`, `MODEL_INVALID`, `UNKNOWN`)
- Google OR-Tools job shop modeling guide: interval variables + precedence + `NoOverlap` as the exact scheduling core
- `alns` maintainer documentation: initial solution dependence, destroy/repair loop, acceptance criteria, and adaptive operator selection

### 3.1 CP-SAT discipline

The OR-Tools guidance is explicit that long exact searches should run behind concrete time limits, and that `UNKNOWN` means the solver stopped before either a feasible solution or an infeasibility proof was certified.

Engineering implication for SynAPS:

- CP-SAT subsolvers should remain bounded, local, and diagnostically explicit;
- CP-SAT micro-repair should not silently consume the dominant share of a large-window `RHC-ALNS` budget.

Current SynAPS alignment:

- large-window RHC ALNS now exposes explicit budget/fallback telemetry;
- the public/default profile no longer routes large-window behavior through CP-SAT-heavy side paths.

### 3.2 ALNS best-practice alignment

The current ALNS documentation emphasises the following structure:

1. start from an initial solution;
2. iterate destroy/repair;
3. evaluate candidates through an explicit acceptance criterion;
4. adapt operator selection using search outcomes.

Current SynAPS alignment is partial but real:

- initial-solution handling is explicit and validated (`warm_start`, frozen-compatible greedy repair, beam/greedy seed fallback);
- simulated-annealing style acceptance already exists, with auto-calibration hooks;
- destroy-operator scoring already uses a roulette-weight update pattern;
- run metadata records search-entry, iteration count, fallback ratio, and budget behavior.

Open gap versus modern ALNS practice:

- SynAPS still uses a relatively simple destroy-side roulette policy instead of segmented roulette or pair-level bandit selection such as `alpha-UCB`;
- acceptance is calibrated internally, but not yet expressed through an explicit public `autofit`-style target such as “accept solutions up to `x%` worse with probability `p` over `n` iterations”.

These are valid next-step research knobs, but the current evidence does **not** justify promoting them straight into the public default profile.

## 4. Mathematical Reading Of The Current Bottleneck

The decisive local control path remains:

- [../../synaps/solvers/alns_solver.py](../../synaps/solvers/alns_solver.py)
- [../../synaps/solvers/rhc_solver.py](../../synaps/solvers/rhc_solver.py)

Key consequence:

1. ALNS constructs an initial complete solution before the main destroy/repair loop.
2. Therefore, if the budget is exhausted during seed construction, later repair settings such as `use_cpsat_repair` are irrelevant to the observed failure.
3. The April 27 staged `100k` geometry-refresh result shows that once first-window geometry is narrowed enough, ALNS does enter search.

So the current root cause is no longer “CP-SAT repair is too heavy” in isolation.

The more precise current diagnosis is:

- first-window admission geometry,
- initial seed construction pressure,
- and partial-plan coverage under fixed per-window budget

are now the dominant variables on the `100k+` path.

## 5. Audit Verdict

### 5.1 Verified / corrected

1. The old blanket claim that `100K ALNS never reaches search` is false on current staged evidence.
2. The public/default `RHC-ALNS` profile should indeed stay away from hybrid CP-SAT routing and CP-SAT micro-repair for the large public benchmark path.
3. The refreshed public/default `50K` profile removed CP-SAT-heavy side-path waste, but the dominant failure mode moved to seed construction before search in later windows.
4. The present `300k` / `500k` boundary is a model/schema cap, not a memory cap.

### 5.2 Still open

1. There is still no evidence for a production-ready full-horizon `100k` solve.
2. The fresh current-head same-run `100k` comparison is still a partial, non-feasible bounded run, and `RHC-ALNS` still trails `RHC-GREEDY` on scheduled coverage.
3. The refreshed public/default `50K` path is still not coverage-competitive, even though it no longer wastes budget in CP-SAT side paths.
4. The next large-scale improvement is more likely to come from seed/admission/coverage work than from re-enabling heavier CP-SAT side paths.

## 6. Recommended Next Experiments

The next justified engineering batch is narrow:

1. instrument and compare per-window `initial_solution_ms`, admitted-op count, committed-op yield, and warm-start rejection reasons across `50k v2` and `100k v4`, instead of relying mainly on end-of-run scheduled ratio;
2. test smaller or more scale-aware admission geometry / candidate-pool settings on staged `100k+` runs to raise coverage without re-enabling hybrid CP-SAT side paths;
3. test richer ALNS operator-selection / acceptance schemes only as an experimental branch, not as an immediate public-default replacement.

## 7. Deliverable Summary

For this recheck, the academically defensible claim set is:

- SynAPS currently has evidence-backed `50k` and bounded staged `100k` research surfaces;
- the April 27 evidence now separates three distinct facts:
  - the retired public `50k` profile wasted budget in CP-SAT side paths;
  - the refreshed public `50k` default removes that waste but still collapses late windows in seed construction;
  - the staged `100k` harness can re-enter search under `300/90`, yet fresh same-run coverage still trails greedy;
- the remaining hard problem is now explicit: improve late-window `50k` search stability and `100k+` partial-plan coverage without hiding the cost behind fallback or exact-subsolver side paths.