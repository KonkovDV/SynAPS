# Known Issues Registry

> SynAPS defect / sentinel registry (audit v4, T-41 / F15).
> Every intentional `pytest.mark.xfail` in `tests/test_redteam_guards.py`
> MUST have a row here. CI enforces the link via
> `tests/test_known_issues_registry.py`.

| ID | Severity | Status | Summary | Sentinel / tests | Tracking |
|---|---|---|---|---|---|
| KI-S3 | MEDIUM | open (sentinel) | `compute_machine_tsp_lower_bound` is not monotone under set shrinkage: `L(S) - L(S\\{j})` can be > 0, so a cut that discounts only `p_j` over-claims. Cuts removed; BHK kept for fixed-set LB + docs (T-23). Use `compute_min_out_assignment_setup_lb` when a cheap non-metric LB is needed. | `tests/test_redteam_guards.py::test_guard_s3_bhk_bound_subset_monotone` (xfail strict) | F6 / GUARD-S3 / T-23 |
| KI-F7 | LOW | open | Exact lane inference falls back to greedy (UNPROVEN) when `n>512`, `max_parallel>8`, or state budget exhausted — no dedicated violation kind flags heuristic fallback. | `tests/test_exact_lane_inference.py` | F7 residual |
| KI-F16 | LOW | open | Public BKS invariant is one-sided (claimed OPTIMAL / LB above literature BKS fails; equality on proven OPT subset not yet required). PyJobShop cross-validation is optional-skip when the dep is absent. SDST public pack not yet vendored. | `tests/test_public_instances_bks.py`, `tests/test_pyjobshop_cross_validation.py` | F16 / T-31 |

## How to add an entry

1. Prefer a **repro test that fails** (`xfail` only for intentional sentinels).
2. Add a row with a stable `KI-*` id, severity, status, and the exact pytest node id.
3. Reference the finding id from `docs/audit/REDTEAM_AUDIT_V4_ALGEBRA_PLAN_2026_08_11.md` when applicable.
4. When the defect is fixed: flip status to `closed`, remove the `xfail`, and keep the row for history.
