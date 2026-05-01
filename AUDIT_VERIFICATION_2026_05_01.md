# SynAPS Audit Verification — 2026-05-01

## Purpose

This note records what the late-April / early-May SynAPS audit still reported correctly on current `master`, what was already fixed before this re-verification pass, and what changed in this pass.

The audit text should be treated as a set of hypotheses, not as ground truth. Current repository state wins.

## Already Closed Before This Pass

These headline findings from the audit were already closed on current `master` before any new edits in this pass:

- `Order.release_date` already exists in `synaps/model.py`.
- schedule normalization no longer mutates predecessor references during validation.
- resource guards already forward solver-native `time_limit_s` instead of using the old wrapper-side timeout path.
- RSS accounting in `synaps/guards.py` already uses explicit platform-aware handling.
- `synaps/solvers/lower_bounds.py` already logs a warning when precedence-cycle corruption weakens the relaxed lower bound.
- the stale dead-code claim in `synaps/solvers/alns_solver.py` was already false on current `master`.

## Fixed In This Pass

Seven live defects were confirmed and changed:

1. ML advisory overrides are now gated to predictors with a loaded model.
Heuristic-only `RuntimePredictor.heuristic()` remains available for experimentation, but it no longer overrides deterministic routing in `select_solver()`.

2. Public schedule verification is now exhaustive.
`verify_schedule_result()` now calls `FeasibilityChecker().check(..., exhaustive=True)`, so portfolio and benchmark verification surfaces no longer under-report simultaneous violations.

3. LBBD setup bounds are now sequence-safe in both decomposition variants.
`synaps/solvers/lbbd_solver.py` and `synaps/solvers/lbbd_hd_solver.py` now:
- use a safe per-transition setup floor in the master only when every possible state transition on a machine is strictly positive;
- encode the master relaxation as `(n - 1) * min_setup` rather than `n * min_setup`;
- generate `setup_cost` cuts from a sequence-independent lower bound derived from the assigned state mix, not from the realized setup total of one incumbent sequence.

4. Standard LBBD now also emits `critical_path` cuts.
`synaps/solvers/lbbd_solver.py` now ships the same critical-path cut family that already existed in `LBBD-HD`, and the Phase 2 LBBD regression surface now asserts that the cut kind is exposed in solver metadata.

5. The staged bounded `100k` `RHC-ALNS` harness no longer reopens the catastrophic zero-assignment seed-stall family.
`benchmark/study_rhc_500k.py` now keeps the validated `alns_presearch_max_window_ops=1000` and `alns_presearch_min_time_limit_s=240.0` guard on `100k+` staged runs instead of relaxing it upward with scale. On current `master`, that moves the bounded `100k` native-backed rerun from `0/100000` scheduled operations in `610.696s` to a guarded fallback outcome of `6933/100000` scheduled operations in `90.281s`.

6. The RHC ALNS pre-search predicate now respects the scaled budget profile when one exists.
`synaps/solvers/rhc_solver.py` no longer lets the legacy raw-window-size guard veto ALNS entry when auto-scaling produced a concrete budget profile that still fits the bounded per-window budget. The new regression in `tests/test_alns_rhc_scaling.py` locks that contract in place.

7. ALNS initial seed construction is now explicitly budgeted and no longer monopolizes bounded windows.
`synaps/solvers/greedy_dispatch.py` now honors `time_limit_s` and returns `TIMEOUT` with partial-schedule metadata; `synaps/solvers/alns_solver.py` now converts that path into explicit `initial_seed_greedy_timed_out` failures, caps phase-1 seed construction on bounded windows, and preserves time for same-window fallback. On current `master`, the accepted bounded rerun in `benchmark/studies/2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap` reaches `7236/100000` scheduled operations in `90.255s` versus same-run `RHC-GREEDY` `7230/100000` in `90.365s`, with `windows_observed = 2`, `fallback_repair_skipped = false`, and no `solver_metadata.error`.

8. `_find_critical_path` is no longer duplicated between standard and hierarchical LBBD.
`synaps/solvers/lbbd_solver.py` now imports the public `find_critical_path` wrapper from `synaps/solvers/lbbd_hd_solver.py` under the `_find_critical_path` alias and the private duplicate (≈86 lines) was removed. Both solvers therefore share one realised critical-path implementation, which removes the rebuilt-from-scratch divergence risk between the two LBBD variants and keeps `find_critical_path` available to `tests/test_lbbd_hd_solver.py` unchanged.

9. The ALNS final-validation recovery test is no longer dependent on a fragile checker-call count.
`tests/test_alns_rhc_scaling.py::TestAlnsSolver::test_alns_recovers_when_final_validation_rejects_incumbent` now uses `_make_3state_problem(n_orders=12, ops_per_order=6)` so `n_ops > initial_beam_op_limit`. Phase 1 then takes the single-greedy initial-seed branch instead of the beam+greedy branch, which makes the second `FeasibilityChecker.check(...)` call the final incumbent check rather than the post-greedy validation, restoring the deterministic `#1 = post-Phase-1 / #2 = final / #3 = recovered-initial` checker-call sequence the test relies on.

## Still Open After Re-Verification

These items remain real follow-up work after the current pass:

- bounded `100k` `RHC-ALNS` now clears the bounded-stability gate on current `master`, but it still lacks a productive active-search regime: `v11` restores same-run parity via bounded seed caps and fallback repair, yet `search_active_window_rate` remains `0.0` and `inner_fallback_ratio` remains `1.0`;
- stronger LBBD master cuts are still needed beyond the shipped safe setup floor, setup lower-bound repair, and current `critical_path` family;
- the large RHC parameter surface still needs reduction into a smaller named-policy space.

## Validation Evidence

The changes above were revalidated with focused tests on Windows using system `python`:

- `python -m pytest tests/test_ml_advisory.py -q`
- `python -m pytest tests/test_portfolio_api.py -k verify_schedule_result -q`
- `python -m pytest tests/test_lbbd_phase2_features.py tests/test_lbbd_solver.py tests/test_lbbd_hd_solver.py -q`
- `python -m pytest tests/test_alns_rhc_scaling.py -q -k "prefers_scaled_budget_profile_over_legacy_size_cut"`
- `python -m pytest tests/test_greedy_dispatch.py -q -k "returns_timeout_with_partial_schedule_when_budget_exhausted"`
- `python -m pytest tests/test_alns_rhc_scaling.py -q -k "caps_initial_seed_budget_below_full_window_budget or initial_seed_timeout_when_budget_exhausted or falls_back_when_alns_initial_seed_times_out or falls_back_when_inner_alns_exhausts_budget_before_search or prefers_scaled_budget_profile_over_legacy_size_cut"`
- `python -m pytest tests/test_benchmark_rhc_500k_study.py tests/test_alns_rhc_scaling.py tests/test_lbbd_phase2_features.py tests/test_lbbd_solver.py -q -k "scale_solver_kwargs or study_rhc_500k or presearch_budget_guard or critical_path or lbbd or setup" --tb=short`
- `python -m benchmark.study_rhc_500k --execution-mode gated --scales 100000 --solvers RHC-GREEDY RHC-ALNS --lane throughput --seeds 1 --time-limit-cap-s 90 --max-windows-override 2 --write-dir benchmark/studies/2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix`
- `python -m benchmark.study_rhc_500k --execution-mode gated --scales 100000 --solvers RHC-GREEDY RHC-ALNS --lane throughput --seeds 1 --time-limit-cap-s 90 --max-windows-override 2 --write-dir benchmark/studies/2026-05-01-rhc-100k-audit-v8-post-predicate-fix`
- `python -m benchmark.study_rhc_500k --execution-mode gated --scales 100000 --solvers RHC-GREEDY RHC-ALNS --lane throughput --seeds 1 --time-limit-cap-s 90 --max-windows-override 2 --write-dir benchmark/studies/2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap`

Latest bounded-100K interpretation:

- `benchmark/studies/2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix` remains the proof that restoring the staged `1000/240` guard envelope closes the catastrophic staged-harness collapse and yields a safe `6933/100000` fallback outcome.
- `benchmark/studies/2026-05-01-rhc-100k-audit-v8-post-predicate-fix` proves that the new predicate really does re-enter ALNS search on the bounded rail: the first window now starts `ALNS` on `1501` operations instead of being pre-search-skipped.
- The same `v8` artifact also falsifies the idea that `R1` alone closes bounded `100k`: ALNS spends about `808843 ms` in initial solution generation, completes `0` iterations, and the overall `RHC-ALNS` run falls back to `0/100000` scheduled operations with `solver_metadata.error = "no assignments produced"`.
- `benchmark/studies/2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap` closes that deeper initial-seed stall family on current `master`: `RHC-ALNS` reaches `7236/100000` in `90.255s`, `RHC-GREEDY` reaches `7230/100000` in `90.365s`, two bounded windows are observed, fallback repair does run, and the run no longer reports `solver_metadata.error`.
- `v11` is still not proof of productive ALNS search at `100k`; it is the proof that the bounded acceptance gate is closed and that the remaining 100K work is now a yield-optimization problem rather than a catastrophic-stall problem.

Note:
The repository `.venv` is still not usable for the full Windows benchmark-validation path. Focused pytest runs succeed there, but OR-Tools imports fail on the bounded-100K benchmark path with `OSError: [WinError 193] %1 is not a valid Win32 application`. This is an environment defect, not part of the solver-code fixes above.