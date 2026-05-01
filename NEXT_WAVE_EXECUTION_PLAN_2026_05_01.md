# SynAPS Next-Wave Execution Plan — 2026-05-01

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
- The TypeScript `control-plane` security/auth hardening shipped separately on 2026-05-01 as commit `7dc540f` (`fix(control-plane): harden auth and python bridge env`).
- Deep audit re-verification on current `master` is now captured in `AUDIT_VERIFICATION_2026_05_01.md`; it separates stale findings from live defects and records the fixes that actually shipped in this pass.

Current unresolved technical bottlenecks are still split into two families:

1. RHC/ALNS active-search yield above the bounded-stability gate. The accepted `v11` slice restores same-run bounded parity, but `search_active_window_rate` is still `0.0` and `inner_fallback_ratio` is still `1.0`, so the remaining 100K/200K work is yield optimization rather than catastrophic-stall containment.
2. LBBD master strength and excessive RHC parameter surface area.

## External Evidence Anchors

The next wave should stay aligned with these external references:

1. Google OR-Tools CP-SAT docs (`cp_tasks`, `cp_solver`, updated 2024-08-28): time limits and explicit stop conditions are first-class controls, so SynAPS should keep solver-native limits instead of wrapper-side thread kills.
2. ICLR 2025, `Learning-Guided Rolling Horizon Optimization for Long-Horizon Flexible Job-Shop Scheduling` (`L-RHO`): the key large-scale lesson is to reduce re-optimization scope by fixing variables that do not need to move between horizons. For SynAPS, this supports a tighter admission/fix/free policy instead of adding more raw ALNS iterations.
3. arXiv 2504.16106 (Apr 2025), `Updating Lower and Upper Bounds for the Job-Shop Scheduling Problem Test Instances`: benchmark progress is judged by stronger upper and lower bounds together, not by heuristic output alone. SynAPS should therefore track tighter lower-bound evidence in the 50K/100K rails rather than only scheduled ratio and makespan.
4. Mavrotas and Florios 2013, `AUGMECON2`: exact Pareto generation remains the defensible baseline for multi-objective integer scheduling slices. SynAPS should keep epsilon-constraint exact slices as the reference surface for calibration and documentation, not treat weighted ALNS scalarization as a Pareto substitute.
5. Naderi and Roshanaei 2021, `Critical-Path-Search Logic-Based Benders Decomposition Approaches for Flexible Job Shop Scheduling`: stronger LBBD progress comes from critical-path-aware cuts, not only coarse capacity/load cuts.
6. The 2023 preemptive FJSP LBBD line (`Logic-based Benders decomposition for the preemptive flexible job shop`): exact decomposition quality improves when the subproblem feeds master cuts that reflect actual sequencing structure instead of generic master relaxation pressure.
7. HiGHS current project posture (`highs.dev`, May 2026): HiGHS remains a credible large-scale open LP/MIP master layer, so the missing piece in SynAPS is cut quality and master formulation strength, not replacing the master solver.

## What This Means For SynAPS

The practical May 2026 reading is:

- do not spend the next wave on broader metaheuristic knob growth;
- do not hide weak coverage behind partial feasibility metrics;
- do strengthen lower bounds and decomposition cuts;
- do shrink horizon work by fixing safe decisions and simplifying runtime profiles;
- do keep benchmark claims tied to reproducible bounded rails.

## Execution Order

### Wave 1 — Close The Evidence Loop

Status: completed on 2026-05-01.

Goal: refresh the two canonical large-instance evidence slices on pushed `master`.

Completed outputs:

1. Closed the fresh 50K audit in `benchmark/studies/2026-05-01-rhc-50k-audit-v3-post-critical-fixes`.
2. Closed the bounded 100K rerun in `benchmark/studies/2026-05-01-rhc-100k-audit-v5-post-critical-fixes`.
3. Compared both outputs against:
   - `2026-04-27-rhc-50k-audit-v2-current-head`
   - `2026-04-27-rhc-100k-audit-v4-current-head`
4. Recorded the controlling deltas in scheduled ratio, fallback ratio, search-entry behavior, wall time, and execution backend.

Result:

- both study directories now contain reproducible JSON artifacts;
- 50K improved on scheduled coverage for both solvers, but the rerun is environment-shifted because native acceleration was active;
- 100K `RHC-GREEDY` improved under the native-backed rerun, while bounded 100K `RHC-ALNS` regressed to a one-window zero-assignment stall and reopened the old seed-construction failure family.

Follow-up update after the original wave closure:

- `benchmark/studies/2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix` now shows that restoring the staged `1000/240` ALNS presearch guard removes the catastrophic `0/100000` failure mode on the bounded `100k` native-backed rail;
- `benchmark/studies/2026-05-01-rhc-100k-audit-v8-post-predicate-fix` now shows that the `R1` predicate patch re-enters ALNS search on the bounded `100k` rail, but the run still fails because initial solution generation consumes the full window budget before search begins;
- `benchmark/studies/2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap` now shows that explicit phase-1 seed caps close that deeper initial-seed stall family and restore same-run bounded parity without reopening `solver_metadata.error` or `fallback_repair_skipped = true`;
- the remaining 100K issue is therefore no longer bounded-stability. The controlling open bottleneck is fallback-heavy behavior with `search_active_window_rate = 0.0`, not catastrophic pre-search stall.

### Wave 2 — Control-Plane Security/Auth Changeset

Status: completed on 2026-05-01 via commit `7dc540f`.

Goal: keep the shipped `control-plane` hardening isolated from solver-algorithm work.

Included scope:

- optional API-key gate via `x-api-key` or `Authorization: Bearer`;
- optional fixed-window rate limit;
- configurable body limit;
- constant-time API-key comparison;
- Python bridge environment allowlist that no longer forwards `SYNAPS_CONTROL_PLANE_*` secrets to the Python subprocess;
- English and Russian control-plane documentation updates.

Required validation:

- `cd control-plane ; npm test`
- `cd control-plane ; npm run build`

Commit rule:

- keep this as its own commit/push unit, separate from solver-algorithm work.

### Wave 3 — Tighten LBBD Master Strength

Status: in progress.

The 2026-05-01 audit-reverification pass already shipped one safety slice in both `LBBD` and `LBBD-HD`: the master now uses a safe setup-transition floor, and `setup_cost` cuts now use sequence-independent lower bounds instead of incumbent-sequence setup totals. The current head also ports the `critical_path` cut family from `LBBD-HD` into standard `LBBD`, so the next step is to measure and extend cut strength beyond that baseline.

Goal: make the LBBD line stronger before expanding ALNS complexity again.

Priority work:

1. Quantify the impact of the shipped standard `critical_path` cut family on medium and large instances, not just on metadata exposure.
2. Extend LBBD beyond the shipped safe setup floor, setup lower-bound repair, and current `critical_path` family with stronger master-side sequencing bounds such as TSP-style machine-order cuts.
3. Extend the master-reporting surface so every LBBD run exposes which cuts tightened the lower bound and by how much.
4. Revalidate `LBBD-10`, `LBBD-20-HD`, and any new master profile against at least one medium exact instance and one large generated instance.

Why this comes before broader ALNS tuning:

- the literature-backed path to stronger exact/decomposition performance is better cuts and bounds;
- SynAPS currently has a master-quality problem more than a master-solver problem.

Success criteria:

- lower bound improves on at least one benchmark family relative to current master-only cuts;
- no regression in small/medium exact validation;
- `LBBD-20-HD` marketing claims remain disabled unless supported by real artifacts.

### Wave 4 — Reduce The RHC Parameter Surface

Goal: replace broad parametric freedom with a smaller named-policy space.

Target simplification:

1. Collapse geometry, admission, and budget controls into named policy bundles.
2. Preserve only the parameters that change regime-level behavior.
3. Move from many raw knobs to a small set of profiles such as:
   - `coverage-first`
   - `balanced`
   - `search-entry`
   - `bounded-100k`
4. Introduce a variable-fixing policy inspired by `L-RHO`: once operations stay stable across windows, prefer fixing them instead of re-opening them every horizon.
5. Fold the bounded-100K search-entry contract into that named-policy layer, so the solver can distinguish between:
   - profile-aware ALNS entry;
   - safe greedy fallback;
   - and future budget-aware initial-seed strategies.

Concrete implementation direction:

- keep admission full-scan, precedence relaxation, and budget guard decisions policy-driven;
- measure how many assignments remain unchanged across consecutive windows;
- only reopen unstable or conflict-exposed regions.

Success criteria:

- fewer public runtime knobs in the 50K/100K study surfaces;
- better explanation quality in metadata;
- same or better scheduled ratio with less profile drift.

### Wave 5 — Refresh Multi-Objective Positioning

Goal: keep the exact Pareto story academically defensible while avoiding overclaiming ALNS weighted sums.

Actions:

1. Keep `AUGMECON2`/epsilon-constraint exact slices as the reference Pareto surface.
2. Do not describe weighted ALNS output as Pareto exploration.
3. Add documentation that clearly separates:
   - exact Pareto slices;
   - heuristic scalarized trade-offs;
   - large-instance coverage heuristics.

Success criteria:

- docs and benchmark descriptions no longer blur exact and heuristic multi-objective surfaces.

## Exact Commands For The Closure Slice

### Finish the fresh 50K rerun

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/2026-05-01-rhc-50k-audit-v3-post-critical-fixes
```

### Run the bounded 100K rerun

```bash
python -m benchmark.study_rhc_500k \
  --execution-mode gated \
  --scales 100000 \
  --solvers RHC-GREEDY RHC-ALNS \
  --lane throughput \
  --seeds 1 \
  --time-limit-cap-s 90 \
  --max-windows-override 2 \
   --write-dir benchmark/studies/2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap
```

### Validate the control-plane changeset

```bash
cd control-plane
npm test
npm run build
```

## Output Expectations

The next-wave closure should produce:

1. one separate `control-plane` security/auth commit;
2. one benchmark-evidence update after the fresh 50K and bounded 100K reruns finish;
3. one follow-on algorithm wave focused first on LBBD cuts and second on RHC surface reduction.

## Stop Conditions

Pause only if one of these becomes true:

1. the large-instance reruns fail because of an environment defect rather than SynAPS behavior;
2. LBBD master strengthening requires a public-contract change that is not implied by the current solver portfolio;
3. the variable-fixing policy for RHC would change benchmark semantics enough that existing public claims must be explicitly versioned.

Otherwise the default is to continue through the waves without reopening planning.