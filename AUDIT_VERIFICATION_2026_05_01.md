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

Three live defects were confirmed and changed:

1. ML advisory overrides are now gated to predictors with a loaded model.
Heuristic-only `RuntimePredictor.heuristic()` remains available for experimentation, but it no longer overrides deterministic routing in `select_solver()`.

2. Public schedule verification is now exhaustive.
`verify_schedule_result()` now calls `FeasibilityChecker().check(..., exhaustive=True)`, so portfolio and benchmark verification surfaces no longer under-report simultaneous violations.

3. LBBD setup bounds are now sequence-safe in both decomposition variants.
`synaps/solvers/lbbd_solver.py` and `synaps/solvers/lbbd_hd_solver.py` now:
- use a safe per-transition setup floor in the master only when every possible state transition on a machine is strictly positive;
- encode the master relaxation as `(n - 1) * min_setup` rather than `n * min_setup`;
- generate `setup_cost` cuts from a sequence-independent lower bound derived from the assigned state mix, not from the realized setup total of one incumbent sequence.

## Still Open After Re-Verification

These items remain real follow-up work after the current pass:

- bounded `100k` `RHC-ALNS` still has an unstable seed/search-entry path on current `master`;
- stronger LBBD master cuts are still needed beyond the shipped safe setup floor and setup lower-bound repair;
- the large RHC parameter surface still needs reduction into a smaller named-policy space.

## Validation Evidence

The changes above were revalidated with focused tests on Windows using system `python`:

- `python -m pytest tests/test_ml_advisory.py -q`
- `python -m pytest tests/test_portfolio_api.py -k verify_schedule_result -q`
- `python -m pytest tests/test_lbbd_phase2_features.py tests/test_lbbd_solver.py tests/test_lbbd_hd_solver.py -q`

Note:
The repository `.venv` is still not usable for this validation path on the current Windows host because `pydantic_core` fails to import there. This is an environment defect, not part of the solver-code fixes above.