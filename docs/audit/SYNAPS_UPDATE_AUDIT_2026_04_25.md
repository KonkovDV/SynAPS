# SynAPS Update Audit (2026-04-25)

> Date: 2026-04-25
> Scope: post-audit hardening for RHC starvation handling and ALNS inner-window budget behavior, plus public documentation sync.
> Status: implemented in this session.

## 1. Audit Focus

This update executes the two highest-priority solver recommendations identified in the April audit loop:

1. strengthen candidate admission recovery under severe early-window starvation;
2. strengthen ALNS inner-window budget adaptation for large-window throughput.

## 2. Implemented Changes

### 2.1 RHC Admission Escalation

File: `synaps/solvers/rhc_solver.py`

Added a stronger fallback when admission filtering and standard progressive relaxation still leave the window underfilled:

- new controls:
  - `admission_full_scan_enabled` (default `True`)
  - `admission_full_scan_min_fill_ratio` (default `0.3`)
- behavior:
  - if `len(window_candidate_ids)` remains below the configured target, RHC escalates to all uncommitted operations for the current window;
  - the escalated set is still constrained by existing candidate-pool clamping/ranking.

Telemetry added:

- `admission_full_scan_enabled`
- `admission_full_scan_min_fill_ratio`
- `admission_full_scan_windows`
- `admission_full_scan_recovered_ops`

### 2.2 ALNS Dynamic Repair Budget Scaling

File: `synaps/solvers/rhc_solver.py`

Extended per-window ALNS autoscaling to include repair-time budget adaptation based on the effective destroy envelope.

- new controls:
  - `alns_dynamic_repair_budget_enabled` (default `True`)
  - `alns_dynamic_repair_s_per_destroyed_op` (default `0.1`)
  - `alns_dynamic_repair_time_limit_min_s` (default `1.0`)
  - `alns_dynamic_repair_time_limit_max_s` (default `5.0`)
- behavior:
  - per-window `repair_time_limit_s` is now auto-derived from `effective_max_destroy` and clamped by the configured min/max guardrails.

Telemetry added:

- per-window summary: `alns_effective_repair_time_limit_s`
- run-level metadata:
  - `alns_dynamic_repair_budget_enabled`
  - `alns_dynamic_repair_s_per_destroyed_op`
  - `alns_dynamic_repair_time_limit_min_s`
  - `alns_dynamic_repair_time_limit_max_s`
  - `alns_budget_mean_effective_repair_time_limit_s`

## 3. Test Coverage Update

File: `tests/test_alns_rhc_scaling.py`

Added/updated targeted tests:

1. `test_rhc_admission_full_scan_recovers_when_frontier_is_still_underfilled`
2. `test_rhc_dynamic_repair_budget_tracks_effective_destroy_size`
3. `test_rhc_auto_scales_alns_budget_before_inner_window_call` (extended assertions for effective repair budget telemetry)

## 4. Documentation Sync

Updated:

- `README.md`
- `README_RU.md`
- `benchmark/README.md`
- `benchmark/README_RU.md`
- `docs/README.md`
- `docs/README_RU.md`

Sync intent:

1. expose post-audit hardening controls and telemetry without overstating benchmark outcomes;
2. keep the current public 50K snapshot unchanged until a new post-audit run artifact is generated.

## 5. Verification Notes

Validation completed in this session:

- static diagnostics: no errors in
  - `synaps/solvers/rhc_solver.py`
  - `tests/test_alns_rhc_scaling.py`

Runtime test limitation encountered:

- local `pytest` execution is blocked in the current environment by binary/runtime issues (`pydantic_core` DLL architecture mismatch and external metadata decoding fault).

Recommendation:

1. rerun the targeted pytest slice in a clean SynAPS-supported Python environment;
2. regenerate `benchmark.study_rhc_50k` artifact to publish post-audit metrics.
