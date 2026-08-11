# Known Issues Registry

> SynAPS defect / sentinel registry (audit v4, T-41 / F15; Wave 5 updates).
> Every intentional `pytest.mark.xfail` in `tests/test_redteam_guards.py`
> MUST have a row here. CI enforces the link via
> `tests/test_known_issues_registry.py`.

| ID | Severity | Status | Summary | Sentinel / tests | Tracking |
|---|---|---|---|---|---|
| KI-S3 | MEDIUM | accepted (sentinel) | `compute_machine_tsp_lower_bound` is not monotone under set shrinkage: `L(S) - L(S\\{j})` can be > 0, so a cut that discounts only `p_j` over-claims. Cuts removed; BHK kept for fixed-set LB + docs (T-23). Prefer `compute_min_out_assignment_setup_lb` recomputed on the fixed assigned set (also not absolutely subset-monotone; never discount). **Wave 10: permanent accepted until a sound monotone LB is invented — do not revive cuts.** | `tests/test_redteam_guards.py::test_guard_s3_bhk_bound_subset_monotone` (xfail strict) | F6 / GUARD-S3 / T-23 / Wave 10 |
| KI-F7 | LOW | closed | Exact lane inference holds in-envelope; greedy fallback emits `LANE_INFERENCE_UNPROVEN`. Customer oracle uses `proven_hard_violations` with **WC-scoped** demotion of lane/setup FP kinds only — **not** physical `MACHINE_CAPACITY_VIOLATION` (Wave 8 / Wave 11 / Wave 12 H12-1). | `tests/test_exact_lane_inference.py`, `tests/test_wave11_hyper_rt.py`, `tests/test_wave12_hyper_rt.py` | F7 / Wave 5–12 |
| KI-F16 | LOW | closed (partial pack) | Brandimarte OPT==BKS (F16a); SDST public slice (F16c); M0 `machine_duration_overrides` (Wave 9). Full Shen/dmorill pack: **permanent forbid — dmorill is GPL-3.0** (Wave 10). Native ABI for true `p_{o,m}`: **permanent deferral**; skip-to-Python remains the contract. | `tests/test_public_instances_bks.py`, `tests/test_sdst_fjs_loader.py`, `tests/test_model_field_conformance.py`, `docs/rfc/WAVE10_DEFERRED_DECISIONS.md` | F16 / T-30 / Wave 5–10 |

## How to add an entry

1. Prefer a **repro test that fails** (`xfail` only for intentional sentinels).
2. Add a row with a stable `KI-*` id, severity, status, and the exact pytest node id.
3. Reference the finding id from `docs/audit/REDTEAM_AUDIT_V4_ALGEBRA_PLAN_2026_08_11.md` when applicable.
4. When the defect is fixed: flip status to `closed`, remove the `xfail`, and keep the row for history.
