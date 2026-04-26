# RHC 500K Scaling Protocol (2026)

## Goal

Define a reproducible, risk-bounded protocol to evaluate SynAPS RHC pathways at industrial stress scales up to 500k+ operations.

Primary target:
- execute staged studies without uncontrolled OOM/runtime collapse
- preserve scientific comparability across lanes and seeds
- report robust metrics (including tail risk)

## Scope

This protocol is implemented by:
- benchmark/study_rhc_500k.py

It extends the 50k methodology from benchmark/study_rhc_50k.py.

## Execution Lanes

1. throughput
- operational lane
- allows multi-worker hybrid CP-SAT where configured

2. strict
- replay lane
- single-worker deterministic profile for comparable runs

3. both
- runs throughput and strict per seed and per scale

## Scale Ladder

Default staged ladder:

- 50,000
- 100,000
- 200,000
- 300,000
- 500,000

The study can run in three execution modes:

1. plan
- no solver execution
- only topology/resource projection + gate decisions

2. gated
- execute only scales that pass resource gate

3. full
- execute all requested scales, ignoring gate decisions

## Resource Projection Model

For a scale point with:
- N operations
- M machines
- S states
- flexibility f (fraction of eligible machines per operation)
- setup density rho

the harness projects:

- eligible ops per operation:

  e = max(1, round(M * f))

- eligible links:

  L = N * e

- expected setup entries:

  E_setup = M * S * (S - 1) * rho

- dense SDST memory (3 tensors: int32 + float32 + float32):

  B_sdst = M * S * S * 12

- total projected model bytes (coarse conservative estimate):

  B_proj = B_sdst + B_setup_entries + B_eligible_links + B_operation_objects + B_order_objects

- projected working set:

  B_working = B_proj * k

where k is the working_set_multiplier.

## Resource Gate

Default hard limits in study_rhc_500k.py:

- max_estimated_memory_gb = 64
- max_setup_entries = 25,000,000
- max_eligible_links = 60,000,000

Current public model limits also matter:

- max_operations = 200,000
- max_orders = 200,000
- max_work_centers = 10,000
- max_setup_entries = 2,000,000

If any limit is exceeded, the scale point is skipped in gated mode.

Important interpretation:

- 300k and 500k may be blocked by model/schema limits even when memory projection is still modest.
- Therefore, "500k+ protocol" means a staged scientific scaling surface, not a claim that 500k execution is currently admitted by the public model.

## Robust Metrics

Per solver|lane|scale summary:

- feasibility_rate
- mean/median/IQR makespan
- mean/median/IQR wall time
- mean scheduled ratio
- tail unscheduled risk via CVaR
- throughput in assigned operations per second
- inner fallback ratio (when available)

Tail risk metric:

CVaR_alpha(X) = E[X | X >= VaR_alpha(X)]

Default alpha = 0.95.

## Quality Gate

Per solver|lane|scale checks:

1. summary_ok
2. feasibility == 1.0
3. mean_scheduled_ratio >= min_scheduled_ratio
4. mean_inner_fallback_ratio <= max_inner_fallback_ratio (if available)
5. objective degradation <= max_makespan_degradation_ratio versus baseline solver in the same lane and scale

Default baseline solver:
- RHC-GREEDY

## 2026-04-26 Harness Corrections

The 100k+ audit exposed a harness-level mismatch: ALNS window/time scaling was increasing with scale, but the pre-search guard remained effectively fixed at its 50k thresholds.

The harness now applies scale-aware updates for `RHC-ALNS`:

- `alns_presearch_max_window_ops` increases with scale and stays bounded by `max_ops_per_window`
- `alns_presearch_min_time_limit_s` decreases with scale with a conservative floor
- optional `max_windows_override` provides bounded academic runs without changing core solver policy

This correction is a study-surface fix, not a proof that large-window ALNS is solved at 100k+.

## Academic Positioning

This protocol follows robust evaluation principles used in large-scale scheduling studies:

- staged escalation instead of one-shot megascale execution
- deterministic replay lane separated from throughput lane
- explicit resource admission controls before heavy solve phases
- tail-aware metrics (CVaR, IQR) instead of mean-only reporting

## Recommended Commands

Plan only (safe):

python -m benchmark.study_rhc_500k --execution-mode plan --lane both --seeds 1 2 3

Gated execution (default):

python -m benchmark.study_rhc_500k --execution-mode gated --lane both --seeds 1 2 3

Bounded 100k ALNS audit run:

python -m benchmark.study_rhc_500k --execution-mode gated --scales 100000 --solvers RHC-ALNS --lane throughput --seeds 1 --time-limit-cap-s 90 --max-windows-override 2

Single high scale stress test:

python -m benchmark.study_rhc_500k --execution-mode gated --scales 500000 --lane throughput --seeds 1

## Interpretation Rule

If 500k fails gate or solve quality constraints, do not claim production readiness.
Use recorded projections and per-scale summaries to tune:

- topology policy (ops_per_machine_target, state growth)
- window/time scaling exponents
- hybrid routing thresholds
- fallback pressure limits

The protocol is intentionally evidence-first and does not treat a single successful run as proof of stable scale readiness.
