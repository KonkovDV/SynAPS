# Red Team audit — Waves 1–7 (2026-08-11)

Independent hostile re-verification of SynAPS algebra + Wave 5–7 residuals at
HEAD after Wave 7 (`5575558`) plus honesty fixes from this audit.

## Verdict

**pass-with-residuals**

No CRITICAL correctness reopeners of Waves 1–7 algebra / T-30 / T-35 boundary /
MAB livelock / OPT==BKS. Two HIGH honesty/governance gaps found; one fixed in
this audit commit (native repair metadata), one documented and registry-downgraded
(KI-F7 portfolio oracle).

**Focused evidence:** `35 passed, 1 xfailed` (guards / lane / weighted_sum /
energy / MAB / wave6–7 / architecture / known-issues registry) plus Wave 5–7
claim probes from live code.

---

## Wave scorecard

| Wave | Theme | Verdict | Notes |
|---|---|---|---|
| 1–4 | Algebra (grain, lanes, LB, boundary, F10–F12) | **PASS** | Cores hold; KI-S3 sentinel intact |
| 5 | T-30 / T-35 / T-34 / KI close | **PASS** | C1 energy attach still fixed |
| 6 | Native skip, energy search, MAB pairs, SDST pack | **PASS** | `charge_pair_reject` still present |
| 7 | Destroy energy, meta, repair extract, GPL gate | **PASS** after H1 fix | Observe-only repair skip reason |

---

## Findings

### HIGH (fixed this audit)

| ID | Finding | Disposition |
|---|---|---|
| **RT17-H1** | `native_greedy_repair_fallback_reason` was pretensioned problem-wide whenever any op had overrides, while `_try_native_greedy_repair` skips only when **disrupted** ops carry overrides — metadata could claim skip while native still ran | **Fixed**: observe-only skip list + `native_greedy_repair_override_skips`; seed reason unchanged (problem-wide is correct for seed) |

### HIGH (accepted residual → Wave 8)

| ID | Finding | Disposition |
|---|---|---|
| **RT17-H2** | KI-F7 labeled `closed`, but `verify_schedule_result` / portfolio `verified_feasible` still uses `feasible=not violations` and does not call `hard_violations`. Beyond exact envelope, greedy-trap schedules can emit `SETUP_GAP` + `LANE_INFERENCE_UNPROVEN` and false-fail the customer oracle. `hard_violations` intentionally keeps trigger kinds (Wave 5 test asserts this) — demoting them is a product decision | **Registry downgraded** to `closed (envelope)`; portfolio third-state deferred |

### MEDIUM

| ID | Finding | Disposition |
|---|---|---|
| **RT17-M1** | `compute_min_out_assignment_setup_lb` is tested but unused in solvers | Accepted / latent |
| **RT17-M2** | `_attach_canonical_objective` field-wise copy is a silent-drop footgun for future objective fields | Accepted; monitor |
| **RT17-M3** | RHC `_evaluate_final` omits energy internally (published path OK via BaseSolver) | Accepted |
| **RT17-M4** | `_RATCHET_SLACK=10` masks mild growth on several long functions | Accepted; tighten later |
| **RT17-M5** | Some energy/MAB tests are weak (`energy >= 0`) | Accepted; strengthen in Wave 8 |
| **RT17-M6** | No `machine_duration_overrides` row in M0 conformance matrix | Accepted (Wave 5 optional) |

### LOW

| ID | Finding |
|---|---|
| **RT17-L1** | Seed vs repair override skip policy asymmetry (document; not a bug) |
| **RT17-L2** | CHANGELOG still carries older conflicting grain narratives |
| **RT17-L3** | `_solve_core` still 1681 ≫ 80 |

---

## Claim re-checks (live)

| Claim | Result | Evidence |
|---|---|---|
| Physical floor vs ceil grain | PASS | `timegrain.py`, `test_checker_physical_floor` |
| Exact lane + advisory | PASS (envelope) | `test_exact_lane_inference`, KI-F7 residual H2 |
| F4 boundary + energy field | PASS | `_attach_canonical_objective`, `test_solver_boundary_publishes_setup_energy` |
| KI-S3 BHK xfail | ACCEPTED | `test_guard_s3_bhk_bound_subset_monotone` xfail strict |
| T-30 `duration_minutes_for` | PASS | model + solvers + native skip |
| T-35 energy publish | PASS | evaluate + boundary |
| T-34 / MAB pairs + reject charge | PASS | `_alns_mab`, `charge_pair_reject` |
| KI-F16a OPT==BKS | PASS | `test_public_instances_bks` |
| KI-F16c SDST + GPL gate | PASS | 3 fixtures; dmorill GPL-3.0 do-not-vendor |
| Destroy-worst energy | PASS | `test_destroy_worst_prefers_high_energy_when_weighted` |
| Native meta honesty | PASS after H1 | observe-only repair skips |
| `_solve_core` ratchet | PASS | 1681; extracts ≤80 |

---

## Residual backlog (Wave 8 candidates)

1. Portfolio / `verify_schedule_result` F7 third-state (or demote greedy trigger kinds when unproven) — close RT17-H2.
2. Strengthen ALNS energy search preference test (not just `energy >= 0`).
3. Optional M0 conformance row for `machine_duration_overrides`.
4. Further `_solve_core` decomposition; ratchet slack review.
5. Harden `_attach_canonical_objective` against missing future fields.
6. Keep KI-S3 accepted; do not revive discountable TSP cuts.
7. Never vendor dmorill (GPL-3.0).

---

## Prior per-wave Red Team delta

| Prior doc | This audit |
|---|---|
| Wave 7.2 metadata PASS | Downgraded → **H1 fixed** |
| KI-F7 `closed` | Downgraded → **closed (envelope)** + H2 residual |
| Wave 5 C1 / Wave 6 MAB / energy | Reconfirmed PASS |
| Waves 1–4 algebra | Reconfirmed PASS |
