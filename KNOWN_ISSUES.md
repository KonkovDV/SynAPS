# Known Issues Registry

> SynAPS defect / sentinel registry (audit v4, T-41 / F15; Wave 5 updates).
> Every intentional `pytest.mark.xfail` in `tests/test_redteam_guards.py`
> MUST have a row here. CI enforces the link via
> `tests/test_known_issues_registry.py`.

| ID | Severity | Status | Summary | Sentinel / tests | Tracking |
|---|---|---|---|---|---|
| KI-S3 | MEDIUM | accepted (sentinel) | `compute_machine_tsp_lower_bound` is not monotone under set shrinkage: `L(S) - L(S\\{j})` can be > 0, so a cut that discounts only `p_j` over-claims. Cuts removed; BHK kept for fixed-set LB + docs (T-23). Prefer `compute_min_out_assignment_setup_lb` recomputed on the fixed assigned set (also not absolutely subset-monotone; never discount). | `tests/test_redteam_guards.py::test_guard_s3_bhk_bound_subset_monotone` (xfail strict) | F6 / GUARD-S3 / T-23 |
| KI-F7 | LOW | closed | Exact lane inference falls back to greedy when `n>512`, `max_parallel>8`, or state budget exhausted; greedy-driven hard faults now emit advisory `LANE_INFERENCE_UNPROVEN` (filter via `hard_violations`). | `tests/test_exact_lane_inference.py::test_greedy_fallback_emits_lane_inference_unproven` | F7 residual → Wave 5.1 |
| KI-F16 | LOW | closed (partial pack) | Brandimarte OPT==BKS (F16a); SDST public slice expanded to 3 hand fixtures (F16c). Full Shen/dmorill pack still deferred pending license. ALNS native skips when overrides present (Wave 6.1). | `tests/test_public_instances_bks.py`, `tests/test_sdst_fjs_loader.py`, `tests/test_wave6_residuals.py` | F16 / T-31 / Wave 5–6 |

## How to add an entry

1. Prefer a **repro test that fails** (`xfail` only for intentional sentinels).
2. Add a row with a stable `KI-*` id, severity, status, and the exact pytest node id.
3. Reference the finding id from `docs/audit/REDTEAM_AUDIT_V4_ALGEBRA_PLAN_2026_08_11.md` when applicable.
4. When the defect is fixed: flip status to `closed`, remove the `xfail`, and keep the row for history.
