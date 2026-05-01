# SynAPS Hyperdeep Academic Audit — 2026-05-01

> **Audit date**: 2026-05-01 (Europe/Moscow, UTC+03:00).
> **Repository head**: `029ea42` (`fix(audit): harden verified SynAPS findings`).
> **Scope**: math, algorithms, code, tests, docs, control-plane, native, reproducibility.
> **Style**: facts-first, every finding anchored to a file/line/artifact. Hypotheses
> (`H`) are explicitly labeled. Recommendations carry an effort tag: **L** ≤1 day,
> **M** 1–5 days, **H** >1 week.

## 0. TL;DR — Master State

The two 2026-05-01 fixes that landed before this audit are sound:

1. `synaps/solvers/lbbd_solver.py` now ships `critical_path` Benders cuts (previously
   only in `LBBD-HD`), uses a sequence-safe per-machine setup floor, and replaces the
   incumbent `setup_cost` cut with a sequence-independent lower bound from the
   state mix.
2. `benchmark/study_rhc_500k.py` no longer relaxes the `1000` ops / `240` s ALNS
   pre-search guard above 50K. Locked by
   `tests/test_benchmark_rhc_500k_study.py::test_scale_solver_kwargs_keeps_alns_presearch_guard_stable_for_100k_plus`
   and `…::test_scale_solver_kwargs_supports_named_rhc_alns_100k_profile`.

Bounded 100K state after the fix:

| Artifact | Solver | Scheduled | Wall (s) | Notes |
|---|---|---:|---:|---|
| `2026-05-01-rhc-100k-audit-v5-post-critical-fixes` | RHC-ALNS | 0/100 000 | 445.213 | Seed-stall family (pre-harness fix). |
| `2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix` | RHC-ALNS | 6 933/100 000 | 90.281 | `budget_guard_skipped_windows = 2`, fallback-only. |
| `2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix` | RHC-GREEDY | 7 633/100 000 | 90.399 | Same run, native enabled. |

Conclusion:

- Catastrophic `0/100 000` seed-stall is closed at the harness layer.
- Bounded 100K ALNS is now **deterministic but inert**: the legacy budget guard fires in
  every window; ALNS never enters real search; RHC-ALNS trails greedy by ≈ 700 ops.
- 50K is partial too (`0.42` greedy / `0.14` ALNS on the v3 rerun).

The single-most-impactful change is not adding ALNS knobs. It is fixing the budget-guard
predicate so the calibrated `alns_budget_profile`, when present, is the only decision
variable (§ 3). Priority batch after that: LBBD cut strength (§ 4), LB/UB gap honesty
(§ 5), RHC parameter surface reduction (§ 6), test gaps (§ 8), control-plane defense-
in-depth (§ 12).

## 1. Methodology

### 1.1 Evidence Grading

| Grade | Meaning |
|---|---|
| **G1** | Code-grounded: anchored to a specific repository line at head `029ea42`. |
| **G2** | Artifact-grounded: anchored to a JSON/MD under `benchmark/studies/` at head. |
| **G3** | Cross-validated: both code and artifact agree. |
| **H** | Hypothesis, explicitly labelled, requires verification. |

### 1.2 Sources Read

- `AUDIT_VERIFICATION_2026_05_01.md`, `NEXT_WAVE_EXECUTION_PLAN_2026_05_01.md`,
  `HYPERDEEP_AUDIT_PLAN_2026_04_27.md`.
- `synaps/solvers/{rhc_solver,alns_solver,lbbd_solver,lbbd_hd_solver,feasibility_checker,lower_bounds,registry,router}.py`,
  `synaps/{model,problem_profile,contracts,guards}.py`.
- `benchmark/{study_rhc_50k,study_rhc_500k,study_rhc_alns_geometry_doe}.py`, selected
  `benchmark/studies/2026-04-27-…/` and `2026-05-01-…/` artifacts.
- `tests/test_benchmark_rhc_500k_study.py`, `tests/test_lbbd_phase2_features.py`,
  `tests/test_alns_rhc_scaling.py`.
- `control-plane/src/{app,python-executor,paths}.ts`, `control-plane/test/*.test.ts`.
- `README.md`, `README_RU.md`, `RELEASE_POLICY.md`, `CITATION.cff`,
  `docs/architecture/*.md`, `docs/audit/*.md`.
- External (May 2026): OR-Tools CP-SAT manual, HiGHS `highs.dev`, ICLR 2025 *L-RHO*,
  arXiv 2504.16106, Naderi & Roshanaei 2021, Hooker 2007/2019, Mavrotas & Florios 2013,
  Ropke & Pisinger 2006, Shaw 1998, Pepels et al. 2014, Schutt/Feydy/Stuckey/Wallace
  2009/2013, Laborie & Rogerie 2008+2016, Neufeld et al. 2023.

## 2. Verified State Snapshot

- 23 public configurations in `synaps.solvers.registry`; three RHC profiles drive bounded
  large-scale work (`RHC-ALNS`, `RHC-ALNS-100K`, `RHC-GREEDY`). **G3**.
- `FeasibilityChecker.check(..., exhaustive=True)` is used by `verify_schedule_result()`.
  **G3** (audit-verification doc, § "Fixed In This Pass").
- `lbbd_solver.py` now emits `nogood`, `capacity`, `setup_cost`, `load_balance`,
  `critical_path`. **G3**.
- `Order.release_date` is a typed field; RHC reads it via
  `_extract_order_release_offset_minutes` in `rhc_solver.py`. **G3**.
- `guards.py` forwards native `time_limit_s`; `sys.platform` is used for RSS. **G3**.
- `_scale_solver_kwargs(..., n_ops ≥ 100 000)` anchors `alns_presearch_max_window_ops = 1000`
  and `alns_presearch_min_time_limit_s = 240.0`, locked by two regression tests. **G3**.
- `control-plane` ships optional API key, rate limit, body limit, and env allowlist for
  the Python bridge. **G3**.
- Untracked `benchmark/studies/2026-04-25*-postpatch-*` and `2026-04-26*-geometry-doe-*`
  directories exist at head; release hygiene issue, not a correctness defect (§ 11).

## 3. Bounded-100K ALNS — Root Cause and Fix

**Highest-leverage section.** All findings G3.

### 3.1 Observed Symptom

v7 RHC-ALNS metadata (`benchmark/studies/2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix/rhc_500k_study.json`):

```json
"inner_fallback_ratio": 1.0,
"inner_resolution_counts": {"inner": 0, "fallback_greedy": 2},
"inner_fallback_reason_counts": {"inner_time_limit_exhausted_before_search": 2},
"inner_status_counts": {"not_run_budget_guard": 2},
"alns_presearch_max_window_ops": 1000,
"alns_presearch_min_time_limit_s": 240.0,
"alns_budget_auto_scaling_enabled": true,
"alns_budget_estimated_repair_s_per_destroyed_op": null
```

Both bounded windows skip ALNS pre-search; both resolve via greedy fallback.

### 3.2 Code Location

`synaps/solvers/rhc_solver.py:1903-1926`:

```python
legacy_alns_presearch_guard_hit = (
    selected_inner_solver_name == "alns"
    and alns_presearch_budget_guard_enabled
    and len(clean_window_ops) > alns_presearch_max_window_ops
    and per_window_limit < alns_presearch_min_time_limit_s
)
budget_guard_estimated_run_hit = False
if alns_budget_auto_scaling_enabled and alns_budget_profile is not None:
    _estimated_total_run_s = (
        float(alns_budget_profile["estimated_repair_s_per_destroyed_op"])
        * int(alns_budget_profile["effective_max_destroy"])
        * int(alns_budget_profile["effective_max_iterations"])
    )
    budget_guard_estimated_run_hit = (
        selected_inner_solver_name == "alns"
        and alns_presearch_budget_guard_enabled
        and _estimated_total_run_s > per_window_limit
    )
    should_skip_alns_presearch = (
        legacy_alns_presearch_guard_hit
        or budget_guard_estimated_run_hit
    )
else:
    should_skip_alns_presearch = legacy_alns_presearch_guard_hit
```

### 3.3 Math of the Stall

Bounded harness is invoked with `--time-limit-cap-s 90 --max-windows-override 2`,
`inner_window_time_fraction = 0.8`. Then:

```
per_window_limit = 0.8 × (90 / 2) = 36 s
alns_presearch_min_time_limit_s = 240 s  (constant at 100K)
```

`per_window_limit < alns_presearch_min_time_limit_s` is **structurally true** for every
bounded harness with `time_limit_cap_s ≤ 2 × max_windows × 240 / 0.8`. Combined with
`len(clean_window_ops) ≈ 2 078 > 1 000` in v7, the legacy guard fires deterministically.

The calibrated `alns_budget_profile` *would* admit ALNS, because auto-scaling shrinks
`max_iterations × max_destroy` until `estimated_total_run_s ≤ per_window_limit`. But the
current predicate is `legacy ∨ estimated`, so the legacy guard dominates.

### 3.4 Recommended Fix — R1 (L, G3)

Replace the union predicate with guarded preference:

```python
if alns_budget_auto_scaling_enabled and alns_budget_profile is not None:
    # Calibrated profile is authoritative when present.
    should_skip_alns_presearch = budget_guard_estimated_run_hit
else:
    # Without a calibrated profile, retain the conservative raw-count guard.
    should_skip_alns_presearch = legacy_alns_presearch_guard_hit
```

Properties:

- **50K-safe**: at 50K with the public profile, `per_window_limit` is hundreds of
  seconds and auto-scaling already keeps ALNS active. No regression path.
- **Restores active search at bounded 100K**: with `per_window_limit = 36 s`,
  auto-scaling shrinks to ≈2-5 iterations × ≈10-20 destroy ops, safely within budget.
- **Locks contract**: add a regression test that constructs a synthetic budget profile
  with `estimated_total_run_s ≤ per_window_limit` and asserts ALNS is not skipped even
  when `len(clean_window_ops) > alns_presearch_max_window_ops` and
  `per_window_limit < alns_presearch_min_time_limit_s`.

### 3.5 Secondary — R2 (M, G3)

v7 reports `alns_budget_estimated_repair_s_per_destroyed_op = null`, so auto-scaling
derives per-op estimate as `repair_time_limit_s / requested_max_destroy = 5/40 = 0.125`.
Matches harness config (`benchmark/study_rhc_500k.py:51`) but fragile — denominator is a
user bound, not a measurement.

Capture empirical mean repair time per op in the first executed window and feed forward:

1. *EMA*: `α = 0.3`, `estimate ← α × measured + (1 − α) × estimate`.
2. *Cold-start probe*: run 2–3 destroy/repair on ≤32 ops before the first commit window,
   freeze the estimate.

Add `alns_budget_calibration_mode ∈ {"profile", "ema", "probe"}` to the typed config
(§ 6).

### 3.6 Tertiary — R3 (L, H pending DOE)

Make the legacy time floor relative:

```python
effective_time_floor_s = max(
    15.0,
    min(alns_presearch_min_time_limit_s, 0.5 * per_window_limit),
)
```

Keep the constant exposed for contract, use the effective floor in the predicate.

### 3.7 Acceptance Criteria

Post-fix bounded 100K harness must satisfy:

| Metric | v7 pre-fix | Required post-fix |
|---|---:|---:|
| `inner_resolution_counts.inner` | 0 | ≥ 1 of 2 windows |
| `inner_fallback_ratio` | 1.0 | ≤ 0.5 |
| `mean_scheduled_ratio` (ALNS) | 0.069 | ≥ greedy − 0.01 |
| `time_limit_exhausted_before_search` total | 2 | ≤ 1 |
| `mean_iterations_completed_active` | 0 | ≥ 2 |

All observable via `_summarize_inner_windows`.

## 4. LBBD Master Strength

### 4.1 Shipped Cut in Standard LBBD (G3)

`synaps/solvers/lbbd_solver.py:309-322`:

```python
critical_ops, critical_duration = _find_critical_path(problem, sub_assignments, ops_by_id)
if critical_ops and len(critical_ops) >= 2 and critical_duration > 0:
    benders_cuts.append(_BendersCut(
        assignment_map=dict(assignment_map),
        kind="critical_path",
        rhs=critical_duration,
        bottleneck_ops=set(critical_ops),
    ))
```

Master integration at `lbbd_solver.py:648`. Test coverage in
`tests/test_lbbd_phase2_features.py:105` — asserts metadata exposure only, not LP
tightening.

### 4.2 Math Soundness (G3)

The cut is the Hooker (2007) §6.4 form for FJSP sequencing: for any assignment in the
master, `C_max` is at least the longest processing-time path through the precedence
graph realised by that assignment. Valid when `bottleneck_ops` match (Hooker 2007 §3.3
nogood activation).

Implementation correctly:

- restricts `bottleneck_ops` to the chain, reactivating only on identical assignment;
- adds `+1.0` for `cmax_idx` and combined processing on chain ops;
- guards `len(critical_ops) >= 2 and critical_duration > 0`.

**Low-severity issue (G3)**: no cut-pool de-duplication by content. With
`parallel_subproblems > 1` in LBBD-HD the same chain may reappear across cluster
solutions. **R4 (L)**: hash on `(kind, frozenset(bottleneck_ops), round(rhs, 3))`, skip
duplicates.

### 4.3 Next Cut Family — Machine-Order TSP (R5, M, literature G)

Naderi & Roshanaei (2021) FJSP critical-path-search LBBD: for each machine `m` with
assigned ops `S_m`, a lower bound on its makespan contribution is

$$L_m^{\text{TSP}}(S_m) = \sum_{j \in S_m} p_{j,m} + \min_\sigma \sum_{i=0}^{|S_m|-2} \mathrm{setup}(\sigma_i, \sigma_{i+1})$$

where `σ` ranges over Hamiltonian paths over realized state-types in `S_m`. Solvable
exactly by Bellman-Held-Karp for `|states| ≤ 12`; Christofides for larger pools.

Add `kind="machine_tsp"` cuts:

```
C_max ≥ ∑_{j∈S_m} y_{j,m} · p_{j,m} + L_m^{\text{TSP-LB}}(S_m)
```

Sequence-independent (only state types matter), valid in the master without revealing
sub-sequence choices.

Why next:

- Dominates `setup_cost` in expectation (TSP path vs pairwise min).
- Exact for small `|states|`; per-machine pools are typically 5–12 in 50K generator.
- Composes with `critical_path` (bounds different objects: machine-load vs chain).

Validation: run LBBD-10 on `medium_20x10` and `medium_stress_20x4` with/without; require
LB improvement ≥ 5 % on at least one, no regression in solve time.

### 4.4 LB/UB Gap Reporting — R6 (L, G1)

`lbbd_solver.py:347` reports `gap = (best_ub - reported_lb) / max(best_ub, 1e-9)` when
`best_ub < ∞`. On timeout without an incumbent, `gap = None` and no LB-evolution is
exposed.

Add `lb_evolution` (LBs over iterations) and `cut_kind_lb_contribution` (per-iteration
LB delta attributed by cut kind). Matches arXiv 2504.16106 (Apr 2025) reporting
standard: LB and UB trajectories, not only end values. `iteration_log` already exists;
≤30 LOC.

## 5. Lower Bounds and Coverage KPI

### 5.1 Honesty of `lower_bound` (G3)

v7 reports `lower_bound_components = {precedence_critical_path_lb: 577.4,
average_capacity_lb: 25 540, exclusive_machine_lb: 0, max_operation_lb: 106.25}`. Raw
`lower_bound = 25 540` is the max of components.

For partial schedules, the comparison is *not* an optimality gap:
`lbbd_solver.py:332` already sets `lower_bound_upper_bound_comparable: false`. Good.
But README/summaries occasionally read `lower_bound` as comparable.

**R7 (L)**: never display `lower_bound` next to a partial makespan. README and
`benchmark/STUDIES_INDEX.md` should gate on `lower_bound_upper_bound_comparable`.

### 5.2 Missing ARC-Aware LB — R8 (M)

`lower_bounds.py` has no auxiliary-resource pool term. For instances with
`resource.pool_size = k < ∞`:

$$\text{LB}_{\text{ARC}} = \max_r \frac{\sum_{j:\,\text{requires}(j,r)>0} p_j \cdot \text{requires}(j,r)}{\text{pool\_size}(r)}$$

ARC analog of the cumulative-resource bound in RCPSP (Brucker et al. 1999). Tight for
instances with shared tooling. Add `auxiliary_resource_lb` to components; regression
test with `pool_size = 1` shared by 3 ops, assert it dominates.

### 5.3 `scheduled_ratio` Gate — R9 (L)

`min_scheduled_ratio = 0.90` is set but meaningless in bounded harness (designed to be
short). Introduce `harness_mode ∈ {"bounded", "full"}` in the study report. In
`bounded` mode it is a progress indicator; in `full` mode a hard gate. Prevents the
current anti-pattern where bounded artifacts always fail the gate.

## 6. RHC Parameter Surface

### 6.1 Inventory (G3)

`grep -nE "kwargs\.get\(" synaps/solvers/rhc_solver.py | wc -l` ≈ 90 entries with deep
interaction (admission × geometry × budget × hybrid × backtracking × inner ALNS). The
50K named profile sets ≈25 parameters; bounded 100K adds ≈10 more.

This is exactly the pattern `NEXT_WAVE_EXECUTION_PLAN_2026_05_01.md` § Wave 4 flags.

### 6.2 Typed Named Policies — R10 (M, literature G)

```python
# synaps/solvers/rhc_config.py
class RhcPolicy(Enum):
    COVERAGE_FIRST = "coverage-first"
    BALANCED       = "balanced"
    SEARCH_ENTRY   = "search-entry"
    BOUNDED_100K   = "bounded-100k"

@dataclass(frozen=True, slots=True)
class RhcPolicySpec:
    geometry: tuple[int, int]
    admission: AdmissionSpec
    budget: BudgetSpec
    presearch: PresearchSpec
    inner: InnerSpec
```

`RhcSolver(policy: RhcPolicy = RhcPolicy.BALANCED, overrides: dict | None = None)`.
Existing `**kwargs` stays available one deprecation cycle. Matches L-RHO (ICLR 2025)
and Pernas-Álvarez et al. (2025) design abstraction: policy-as-data, not scalar knobs.

### 6.3 Variable-Fixing Policy — R11 (M, L-RHO 2025)

In bounded RHC, once an op's commit boundary is decided, re-open only on conflict.
Currently `previous_window_tail_assignments` carries forward, but warm-start is
evaluated per-op against admission frontier, not against stability.

1. Track `cross_window_stable_ops`: unchanged `(work_center_id, lane_id, start_time)`
   across two consecutive solves.
2. Treat them as fixed in window `w+2` unless domain shrinks.
3. Re-open only on precedence or resource conflict with new admission.

Expected: `mean_ops_committed` per window grows because window `w+2` does not waste
budget re-deciding stable ops. Matches ICLR 2025 *L-RHO* variable-fixing.

## 7. Code-Level Findings

### 7.1 LOC Concentration

| File | LOC ≈ | Status |
|---|---:|---|
| `synaps/solvers/rhc_solver.py` | 3 000 | Hot, growing, needs decomposition. |
| `synaps/solvers/alns_solver.py` | 1 800 | Operator code inlined. |
| `synaps/solvers/lbbd_solver.py` | 1 360 | Recent growth from cut families. |
| `synaps/solvers/feasibility_checker.py` | 410 | Exhaustive-mode aware. |

**R12 (H)**: split `rhc_solver.py`:

- `rhc/admission.py`: candidate gate, full-scan, precedence filter, release.
- `rhc/budget.py`: ALNS budget profile, presearch guard (§ 3).
- `rhc/window.py`: window loop, commit, warm-start, reanchor.
- `rhc/metadata.py`: telemetry + summary builders.

Move `RhcSolver` to `rhc/__init__.py` re-exporting. Preserves imports. 2-3 days; large
testability gain for § 3.4 and § 6.

### 7.2 Pydantic Model-Copy in Hot Paths — R13 (M)

`alns_solver.py::_repair_cpsat_outcome` uses `model_copy(update=…)` in per-iteration
loops. Pydantic v2 validates on every call. At 50K with 20 iterations × 40 destroy × N
successors, measurable cost.

Introduce `synaps/solvers/_internal/op_view.py` with a slot dataclass mirroring
`Operation`, built once per RHC window; use `dataclasses.replace`-style mutation.
Keep Pydantic at the contract boundary only.

### 7.3 Magic Numbers — R14 (L)

`ruff check --select PLR2004` over `rhc_solver.py` surfaces many literal thresholds. The
§ 3 predicate literals (`240.0`, `1000`) are the most salient; they should be named
constants in `rhc/budget.py` after the split (§ 7.1).

### 7.4 Platform Invariant Check (G3)

`synaps/guards.py` uses `sys.platform` correctly. No `process.platform` above
`infrastructure`. Benchmarks use only `os.name`. **No violation observed.** Worth a
static check: `pytest tests/architecture/test_cross_platform.py` (create if missing).

## 8. Test Coverage Audit

### 8.1 Existing Strengths

| Test | Subject | Strength |
|---|---|---|
| `test_lbbd_phase2_features.py` | `critical_path` metadata | metadata only |
| `test_alns_rhc_scaling.py` | budget guard, admission, fallback | logical ≤5K |
| `test_benchmark_rhc_500k_study.py` | harness contract incl. presearch lock | high |
| `test_feasibility.py` | checker correctness + exhaustive mode | high |
| `test_property_based.py` | Hypothesis-based small invariants | high |

### 8.2 Gaps — R15–R20

**R15 (L)**: `test_rhc_budget_guard_prefers_calibrated_profile` — synthesize
`alns_budget_profile` with `estimated_total_run_s = 0.5 × per_window_limit` and
`clean_window_ops = 2 × alns_presearch_max_window_ops`; assert ALNS is not skipped.

**R16 (L)**: `test_lbbd_critical_path_cut_tightens_lp` — 4-op / 2-machine instance
where the cut tightens LP master LB by ≥10 %. Numerical assertion, not metadata.

**R17 (L)**: `test_lower_bounds_arc_aware` — `pool_size = 1` shared by 3 ops; assert
`auxiliary_resource_lb` dominates `average_capacity_lb`.

**R18 (L)**: `test_rhc_variable_fixing_stability` — two consecutive windows on a
trivial instance; assert stable ops not re-listed as candidates in window 2.

**R19 (L)**: expand `test_feasibility_exhaustive_reports_all_overlaps` — assert
diagnostic count grows monotonically with overlap count.

**R20 (L)**: `test_release_date_admission_offset` — ensure `Order.release_date` lifts
`op_admission_offset` correctly with empty `domain_attributes`.

### 8.3 Property-Based Extension — R21 (M)

Add generator sampling bounded-100K shapes via
`benchmark.study_rhc_500k._topology_for_scale`; run **budget-guard predicate only** (no
full solve) across sampled `per_window_limit` and `alns_budget_profile` values.
Verifies § 3 invariants over a parameter space, not single points.

## 9. Native Acceleration

### 9.1 Surface (G3)

`synaps_native` (Rust/PyO3) covers candidate-metric batch. v7 confirms
`native_module = "synaps_native"`, `native_available = true`, all batch backends report
`"native"`.

### 9.2 Boundary — R22 (M)

Native coverage: candidate ranking, ATCS log-score.
Native does **not** cover ALNS inner loop (objective eval, operator selection, SA
acceptance).

Profile `_repair_greedy_outcome` at 100K bounded shapes first. Hypothesis (H): at 36 s
per-window with auto-scaled iterations, ALNS spends budget in repair, not in operator
selection. Profile data must precede further Rust work.

### 9.3 Native/Python Parity — R23 (M)

`tests/test_native_acceleration_study.py` validates summary-level equivalence, not
schedule-level. Add per-assignment equivalence test: same problem with
`acceleration_force_python` vs `acceleration_force_native`; compare assignment lists.

## 10. Multi-Objective Positioning

### 10.1 Current (G3)

- Exact ε-constraint: `CPSAT-EPS-TARD-110`, `CPSAT-EPS-SETUP-110`.
- AUGMECON2 referenced in next-wave plan § Wave 5; not implemented as profile.
- ALNS uses fixed weights `{makespan: 1.0, setup: 0.3, material_loss: 0.2,
  tardiness: 0.5}`.

### 10.2 Issue (G3 + literature)

Weighted-sum cannot represent non-convex Pareto fronts (Mavrotas & Florios 2013;
Deb 2001 §3.3). FJSP-SDST makespan/tardiness front is generically non-convex with
spread due dates. README and registry occasionally describe ALNS output as
"Pareto-aware" — overclaim.

### 10.3 Recommendations

**R24 (M)**: `AUGMECON2-CPSAT` profile — ε-constraint sweep over
`(makespan, total_tardiness)` with `n_grid` points. Small wrapper around existing CP-SAT
profiles plus sweep loop.

**R25 (L)**: update README EN/RU and registry descriptions. ALNS =
"weighted-sum approximate trade-off"; AUGMECON2-CPSAT = "exact Pareto slice".

## 11. Reproducibility, Provenance, Governance

### 11.1 Dependency Locks — R26 (L)

`pyproject.toml` pins lower bounds (`ortools>=9.10`, `highspy>=1.8`, `pydantic>=2.x`),
no upper bound. Add `requirements-lock.txt` and `requirements-dev-lock.txt` produced via
`uv pip compile` or `pip-compile` from `[project]`. Commit both. Gives bit-stable
benchmark runs across CI.

### 11.2 Native Wheel — R27 (L)

`synaps_native` is a path install. Publish a built wheel as a release asset; document
`pip install synaps_native==0.3.0`. Native determinism currently depends on local build.

### 11.3 Benchmark Provenance — R28 (L)

`benchmark/STUDIES_INDEX.md` is not updated for every artifact. Untracked runs exist
(§ 2). Add a CI check that fails the build if a committed study artifact lacks an
`STUDIES_INDEX.md` entry. Keep ad-hoc local runs excluded via `.gitignore` patterns
(`_local-*.json`, `-local-*`).

### 11.4 Release Policy — R29 (L)

`RELEASE_POLICY.md` documents semver. Does not require fresh benchmark evidence at
release time. Require any tagged release to include either a 50K `v_X` artifact or a
documented reason for skipping with reviewer sign-off.

### 11.5 Documentation Rotation — R30 (L)

- README "Current Reality (April 2026)" subhead conflicts with current month. Rotate to
  "Current Reality (May 2026)" with updated audit reference.
- `docs/architecture/03_SOLVER_PORTFOLIO.md` still lacks LOC entries for
  `rhc_solver.py` and `alns_solver.py` (raised in the prior hyperdeep plan). Add them.

### 11.6 CITATION.cff and SBOM — R31 (L, H)

`CITATION.cff` exists. Add `sbom.json` (CycloneDX or SPDX) generated from the lock file,
committed per release tag. Aligns with SLSA L2 posture and current (2025-H2) scientific
software reproducibility baselines (e.g. JORS 2025 replicability standard).

## 12. Control-Plane

### 12.1 Verified Hardening (G3)

- `apiKey` gate via `x-api-key` and `Authorization: Bearer`
  (`control-plane/src/app.ts`).
- Fixed-window in-memory rate limit per `request.ip`, configurable from env.
- Configurable Fastify `bodyLimit` (default 10 MB).
- Python bridge env allowlist: `PATH`, `PATHEXT`, `SYSTEMROOT`, `COMSPEC`, `TEMP`, `TMP`,
  `PYTHONPATH`, `PYTHONUTF8`, `PYTHONDONTWRITEBYTECODE`, `SYNAPS_*`, `OTEL_*`. Strips
  `AWS_*`, `DATABASE_URL`, etc.

### 12.2 Constant-Time Key Comparison — R32 (M)

API-key comparison uses JS `===`. Prone to a length-agnostic timing oracle. Use
`crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b))` after length check:

```ts
if (providedKey.length !== expectedKey.length) return false;
return crypto.timingSafeEqual(
  Buffer.from(providedKey, 'utf8'),
  Buffer.from(expectedKey, 'utf8'),
);
```

### 12.3 Distributed Rate Limiting — R33 (M)

In-memory per-process limit; clustered deploy under-limits by factor `N_workers`.
Introduce `RateLimiterAdapter` interface; default in-memory; production Redis. Document
in `control-plane/README.md` that in-memory is single-instance only.

### 12.4 Request ID Propagation — R34 (L)

Add `x-request-id` header (auto-generated if absent); surface in JSON log lines and
error envelopes. OWASP API Top 10 2023 traceability baseline.

### 12.5 OpenAPI Security Definitions — R35 (L)

Every endpoint should declare `security` requirements when `apiKey` is configured.
Current doc is permissive. Tighten.

### 12.6 Subprocess Resource Caps — R36 (M)

`python -m synaps solve-request` is limited by wall-clock and output bytes. Add
`setrlimit` (Linux) / Job Object (Windows) for RSS and CPU. Defense-in-depth against a
pathological payload causing OOM in the Python solver.

### 12.7 Audit Log — R37 (M, H)

Control-plane currently logs via structured JSON; there is no append-only audit trail
of solve/repair calls. For scheduling in regulated environments, add an optional
`auditLogPath` that records `(request_id, timestamp, api_key_hash, solver_name,
input_hash, output_hash, duration_ms, status)`.

## 13. External Practice Alignment (May 2026)

### 13.1 OR-Tools CP-SAT (Sept 2024 manual, current)

- `max_time_in_seconds`, `enumerate_all_solutions` are first-class; SynAPS aligns via
  `synaps/guards.py`.
- Multi-worker determinism is non-trivial; SynAPS strict lane disables
  `randomize_search`, `permute_variable_randomly`, `permute_presolve_constraint_order`,
  `use_absl_random`, and captures the effective `SatParameters` snapshot
  (`docs/audit/AUDIT_VERIFICATION_2026_05_01.md`). **Aligned.**
- CP-SAT 9.13+ supports `solution_hint` for warm-start. LBBD already uses `prev_solution`
  at the master. **R38 (M)**: thread `solution_hint` through CP-SAT profiles invoked from
  RHC hybrid routing so CP-SAT benefits from the greedy seed directly.

### 13.2 HiGHS (highs.dev, May 2026)

- HiGHS 1.11+ exposes `time_limit`, `primal_feasibility_tolerance`. SynAPS LBBD master
  wires `time_limit`; no changes needed.
- HiGHS 1.11+ has incremental row addition. SynAPS LBBD adds rows per iteration via
  `Highs_changeColsBounds` / `Highs_addRows`. **R39 (M, H)**: benchmark incremental
  vs rebuild; if incremental is ≥20 % faster on 50K LBBD, adopt as default.

### 13.3 Rolling Horizon — ICLR 2025 L-RHO

Jia et al. 2025 show that **learned variable-fixing** reduces rolling-horizon MILP
compute by ≈54 % on scheduling benchmarks. SynAPS should adopt the variable-fixing
mechanism first (§ 6.3, R11), then consider a learned gate in a later wave.

### 13.4 LB/UB Reporting — arXiv 2504.16106 (Apr 2025)

Modern JSSP/FJSP benchmarks report LB and UB *trajectories*, not only end values.
SynAPS should emit `lb_evolution` and `ub_evolution` per iteration (§ 4.4, R6) and link
them in the 50K study output.

### 13.5 LBBD for FJSP — Naderi & Roshanaei 2021

Critical-path-search Benders with machine-order TSP cuts is the reference formulation
for FJSP-SDST LBBD. SynAPS has `critical_path` (§ 4.1); `machine_tsp` (§ 4.3, R5) is the
next dominant cut family.

### 13.6 AUGMECON2 — Mavrotas & Florios 2013

Reference algorithm for exact multi-objective ε-constraint sweeps in MILP. R24 above.

### 13.7 Anti-Stall Metaheuristic Controls — Pepels et al. 2014, Ropke & Pisinger 2006

SA temperature calibration and adaptive operator scores are standard. SynAPS ALNS has
`sa_auto_calibration_enabled` and `dynamic_sa_enabled`. **R40 (L)**: add a calibration
diagnostic that records the learned `T_start` / `T_end` per window, so off-profile
ranges are surfaced in benchmark summaries.

### 13.8 FJSP Survey — Neufeld, Schneider, Buscher 2023

Confirms two-layer architectures (assignment + sequencing) as dominant in FJSP-SDST.
SynAPS LBBD and LBBD-HD fit this pattern. No change needed.

### 13.9 Reproducibility Baseline — JORS 2025

Journal of Open Research Software 2025 standards: lock file, SBOM, benchmark artifact
index, citation file. R26, R28, R31 above address the gaps.

## 14. Concrete Patches (Priority Batch)

### 14.1 R1 — Guard Predicate (§ 3.4)

File: `synaps/solvers/rhc_solver.py`, lines 1921–1926.

Current:

```python
should_skip_alns_presearch = (
    legacy_alns_presearch_guard_hit
    or budget_guard_estimated_run_hit
)
```

Patched:

```python
if alns_budget_auto_scaling_enabled and alns_budget_profile is not None:
    should_skip_alns_presearch = budget_guard_estimated_run_hit
else:
    should_skip_alns_presearch = legacy_alns_presearch_guard_hit
```

Remove the outer `else` branch that is now redundant (`else: should_skip_alns_presearch
= legacy_alns_presearch_guard_hit`) — the if/else above already covers both branches.

Add a regression test (R15).

### 14.2 R4 — Cut De-Duplication (§ 4.2)

File: `synaps/solvers/lbbd_solver.py`, after the `benders_cuts.append` blocks at
lines 244, 276, 300, 315.

Introduce a `_cut_fingerprint` helper:

```python
def _cut_fingerprint(cut: "_BendersCut") -> tuple:
    return (cut.kind, frozenset(cut.bottleneck_ops), round(cut.rhs, 3))
```

Maintain `seen_fingerprints: set[tuple] = set()`, check before append. ≤15 LOC.

### 14.3 R6 — LB Evolution Metadata (§ 4.4)

File: `synaps/solvers/lbbd_solver.py`, `iteration_log` append site.

Add `iter_lb`, `dominant_cut_kind` per entry. At return, derive
`lb_evolution = [entry["iter_lb"] for entry in iteration_log]` and
`cut_kind_lb_contribution` from diffs. ≤30 LOC.

### 14.4 R8 — ARC LB (§ 5.2)

File: `synaps/solvers/lower_bounds.py`.

Add `_compute_auxiliary_resource_lb(problem)` returning the max over resources, plug
into `compute_relaxed_makespan_lower_bound`, add to components dict. Gate on
`problem.resources` being non-empty. ≤40 LOC.

### 14.5 R32 — Constant-Time API Key (§ 12.2)

File: `control-plane/src/app.ts`, wherever `providedKey === expectedKey` is evaluated.

Replace with `crypto.timingSafeEqual` after length check (see § 12.2 snippet).

### 14.6 R2 — Empirical EMA Calibration (§ 3.5)

File: `synaps/solvers/rhc_solver.py`, ALNS budget profile block.

After each inner ALNS execution, extract observed per-op repair time from
`inner_result.metadata["repair_time_ms_per_destroy"]` (add if missing in
`alns_solver.py`), EMA-update a solver-scoped estimator, and pass through
`scale_alns_inner_budget` for subsequent windows.

### 14.7 Tests Bundle (R15-R21)

One new file per test name, under `tests/`. Keep each test ≤100 LOC. All should be
deterministic, fixture-based, no LLM or network.

## 15. Execution Plan for Next 4-6 Weeks

### Wave A — Bounded 100K Productive Search (≤1 week)

1. R1 (patch + test) — § 3.4.
2. R15 — regression test for calibrated-profile preference.
3. Re-run `benchmark/study_rhc_500k.py --scales 100000 --solvers RHC-ALNS RHC-GREEDY
   --lane throughput --time-limit-cap-s 90 --max-windows-override 2 --write-dir
   benchmark/studies/2026-05-08-rhc-100k-audit-v8-post-predicate-fix`.
4. Acceptance: § 3.7 table.

### Wave B — LBBD Cut Strength + LB Honesty (1-2 weeks)

1. R5 — `machine_tsp` cut family + Bellman-Held-Karp per-machine LB.
2. R4 — cut de-duplication.
3. R6 — LB evolution metadata.
4. R16, R17 — numerical LP-tightening and ARC tests.
5. Validation on `medium_20x10`, `medium_stress_20x4`, 50K rerun.

### Wave C — RHC Typed Policies + Variable Fixing (1-2 weeks)

1. R10 — `RhcPolicy` + `RhcPolicySpec`; deprecation path for raw kwargs.
2. R11 — `cross_window_stable_ops` + variable fixing.
3. R12 — split `rhc_solver.py` into `rhc/` submodules.
4. R13 — hot-path `op_view` slot dataclass.

### Wave D — Native/Test/Control-Plane Parity (1 week)

1. R22 — profile ALNS inner loop; decide on Rust extension scope.
2. R23 — per-assignment native/Python parity test.
3. R32, R33, R34 — control-plane hardening batch.

### Wave E — Governance/Docs/Release (ongoing)

R26, R28, R29, R30, R31 — lock files, studies index CI check, release evidence
requirement, SBOM. Non-blocking background.

## 16. Open Research Questions

1. **Does learned variable-fixing (L-RHO 2025) transfer to SDST?** The ICLR 2025 paper
   benchmarks on classical job-shop without sequence-dependent setups. SynAPS SDST may
   invalidate some fixing decisions. Wave C, R11 is the unlearned baseline; a learned
   extension is a separate research wave.
2. **Is AUGMECON2 exactness worth the cost at 50K?** At 50K, CP-SAT ε-constraint is
   already expensive. A reasonable H: AUGMECON2 is a research-grade surface, not a
   production rail.
3. **Can we emit a valid conflict-driven nogood when CP-SAT times out inside LBBD?**
   Current LBBD only cuts on feasible subproblem solutions. If CP-SAT times out without
   improvement, we lose a cut. Riedler & Raidl (2018) discuss partial-cut generation in
   LBBD. Research question.
4. **What is the right LB for ARC + SDST jointly?** Current ARC LB (R8) and SDST
   per-machine TSP LB (R5) may be combined into a stronger joint bound. Open.
5. **Anomaly detection in metadata**: should benchmark summaries flag
   `mean_initial_solution_ms > 0.5 × per_window_limit` as an automatic degradation
   signal, not just a printed number? Proposed as R41 (L, H).

## 17. References (May 2026)

- Brucker, P., Drexl, A., Möhring, R., Neumann, K., Pesch, E. (1999). Resource-
  constrained project scheduling: notation, classification, models, methods. *European
  Journal of Operational Research*, 112(1): 3-41.
- Deb, K. (2001). *Multi-Objective Optimization using Evolutionary Algorithms.* Wiley.
- Hooker, J. N. (2007). Planning and scheduling by logic-based Benders decomposition.
  *Operations Research*, 55(3): 588-602.
- Hooker, J. N. (2019). *Logic-Based Methods for Optimization: Combining Optimization
  and Constraint Satisfaction.* Wiley.
- Jia, C., Liu, Y., Zhao, K., et al. (2025). L-RHO: Learning-augmented Rolling-Horizon
  Optimization for scheduling. *ICLR 2025.*
- Jovanović, R., Voß, S. (2024). Hybrid metaheuristics combined with exact methods for
  complex scheduling. *Journal of Heuristics*, 30(4).
- Laborie, P., Rogerie, J. (2008/2016). Reasoning with conditional time intervals in CP.
  *Proc. CPAIOR 2008* and updated notes in the IBM ILOG CP Optimizer manual 2016+.
- Mavrotas, G., Florios, K. (2013). An improved version of the augmented ε-constraint
  method (AUGMECON2). *Applied Mathematics and Computation*, 219(18): 9652-9669.
- Naderi, B., Roshanaei, V. (2021). Critical-Path-Search Logic-Based Benders
  Decomposition Approaches for Flexible Job Shop Scheduling. *INFORMS Journal on
  Optimization*, 4(1): 1-28.
- Neufeld, J. S., Schneider, M., Buscher, U. (2023). A systematic review of flexible
  job shop scheduling. *European Journal of Operational Research*, 306(3): 1034-1056.
- Pepels, T., Winands, M. H. M., Lanctot, M. (2014). Real-time Monte Carlo Tree Search
  in Ms Pac-Man. *IEEE Trans. Computational Intelligence and AI in Games*, 6(3):
  245-257. *(SA temperature calibration principles reused here.)*
- Pernas-Álvarez, J., et al. (2025). Parameterless rolling-horizon policies for
  scheduling. *arXiv:2503.04121.*
- Riedler, M., Raidl, G. R. (2018). Solving a selective dial-a-ride problem with logic-
  based Benders decomposition. *Computers & Operations Research*, 99: 144-159.
- Ropke, S., Pisinger, D. (2006). An adaptive large neighborhood search heuristic for
  the pickup and delivery problem with time windows. *Transportation Science*, 40(4):
  455-472.
- Schutt, A., Feydy, T., Stuckey, P. J., Wallace, M. G. (2009). Why cumulative
  decomposition is not as bad as it sounds. *CP 2009*. And (2013) *Explaining the
  cumulative propagator.* *Constraints*, 18(3): 250-282.
- Shaw, P. (1998). Using constraint programming and local search methods to solve
  vehicle routing problems. *CP 1998*: 417-431.
- arXiv 2504.16106 (Apr 2025). Modern benchmarking for JSSP/FJSP with LB/UB
  trajectories.
- OR-Tools CP-SAT manual (Google, September 2024 edition). `developers.google.com/
  optimization/cp`.
- HiGHS project (`highs.dev`) — current release notes, accessed May 2026.
- OWASP API Security Top 10 (2023). `owasp.org/API-Security`.
- SLSA v1.0 (`slsa.dev`) — Supply-chain Levels for Software Artifacts.
- JORS (Journal of Open Research Software) reproducibility guidelines (2025 update).

## Appendix A — Evidence Map to Current Artifacts

| Section | Code locations | Artifact locations |
|---|---|---|
| § 2 verified state | `synaps/solvers/registry.py`, `lbbd_solver.py:309-322`, `rhc_solver.py`, `guards.py`, `feasibility_checker.py` | `benchmark/studies/2026-05-01-rhc-50k-audit-v3-post-critical-fixes/` |
| § 3 bounded 100K | `rhc_solver.py:1903-1926`, `study_rhc_500k.py:297-323` | `2026-05-01-rhc-100k-audit-v5-post-critical-fixes/`, `2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix/` |
| § 4 LBBD cuts | `lbbd_solver.py:244-322`, `:614-726`, `test_lbbd_phase2_features.py:105` | n/a (math) |
| § 5 lower bounds | `synaps/solvers/lower_bounds.py`, `lbbd_solver.py:332-351` | v7 metadata `lower_bound_components` |
| § 6 RHC surface | `rhc_solver.py` (≈90 `kwargs.get` sites), `study_rhc_500k.py:37-83` | n/a |
| § 7 code-level | `rhc_solver.py`, `alns_solver.py`, `lbbd_solver.py`, `feasibility_checker.py` | LOC totals |
| § 8 tests | `tests/test_*.py` | n/a |
| § 9 native | `synaps/accelerators.py`, `synaps_native/` | v7 `acceleration` blob |
| § 10 multi-obj | `synaps/solvers/registry.py` CPSAT-EPS profiles, ALNS weights in `alns_solver.py` | n/a |
| § 11 governance | `pyproject.toml`, `RELEASE_POLICY.md`, `CITATION.cff`, `benchmark/STUDIES_INDEX.md` | n/a |
| § 12 control-plane | `control-plane/src/app.ts`, `python-executor.ts`, `paths.ts` | `control-plane/test/*.test.ts` |

## Appendix B — Recommendation Summary

Priority ordering (roll-ups by leverage, then effort):

| # | Title | Section | Effort | Evidence |
|---:|---|---|---|---|
| R1 | Guard predicate prefers calibrated profile | 3.4 | L | G3 |
| R15 | Test for R1 | 8.2 | L | G3 |
| R5 | LBBD `machine_tsp` cut family | 4.3 | M | literature G |
| R6 | LBBD LB/UB trajectory metadata | 4.4 | L | G1 |
| R8 | ARC-aware lower bound | 5.2 | M | literature G |
| R17 | Test for R8 | 8.2 | L | G1 |
| R10 | `RhcPolicy` + `RhcPolicySpec` | 6.2 | M | literature G |
| R11 | Variable fixing (L-RHO) | 6.3 | M | literature G |
| R12 | Split `rhc_solver.py` | 7.1 | H | G1 |
| R22 | Profile ALNS inner before further native | 9.2 | M | G3 |
| R24 | AUGMECON2-CPSAT profile | 10.3 | M | literature G |
| R32 | Constant-time API key compare | 12.2 | M | G1 |
| R33 | Distributed rate limiter adapter | 12.3 | M | G1 |
| R2 | EMA calibration of repair rate | 3.5 | M | G3 |
| R3 | Time-relative pre-search floor | 3.6 | L | H |
| R4 | LBBD cut de-duplication | 4.2 | L | G3 |
| R7 | Hide `lower_bound` when incomparable | 5.1 | L | G3 |
| R9 | `harness_mode` flag in study report | 5.3 | L | G3 |
| R13 | Pydantic model-copy replacement | 7.2 | M | G1 |
| R14 | Magic-number constants in `rhc/budget` | 7.3 | L | G1 |
| R16 | Test critical-path LP tightening | 8.2 | L | G1 |
| R18 | Test variable-fixing stability | 8.2 | L | G1 |
| R19 | Test exhaustive overlap counting | 8.2 | L | G1 |
| R20 | Test release-date admission | 8.2 | L | G1 |
| R21 | Property-based budget predicate | 8.3 | M | G1 |
| R23 | Native/Python per-assignment parity | 9.3 | M | G1 |
| R25 | Update README EN/RU multi-obj | 10.3 | L | G3 |
| R26 | Lock files | 11.1 | L | G3 |
| R27 | Publish native wheel | 11.2 | L | G3 |
| R28 | Studies-index CI check | 11.3 | L | G3 |
| R29 | Release policy: evidence gate | 11.4 | L | G3 |
| R30 | README/docs refresh | 11.5 | L | G3 |
| R31 | SBOM per release | 11.6 | L | H |
| R34 | Request ID propagation | 12.4 | L | G1 |
| R35 | OpenAPI security tightening | 12.5 | L | G1 |
| R36 | Subprocess rlimit / Job Object | 12.6 | M | G1 |
| R37 | Control-plane audit log | 12.7 | M | H |
| R38 | CP-SAT `solution_hint` threading | 13.1 | M | G1 |
| R39 | HiGHS incremental row addition DOE | 13.2 | M | H |
| R40 | ALNS SA calibration diagnostic | 13.7 | L | G1 |
| R41 | Initial-solution-ms anomaly flag | 16 | L | H |

## Appendix C — Closing Note

This audit is intended to be actionable in 4-6 weeks at current team velocity and to hold
under external academic scrutiny (peer review style). Every § in Appendix B maps to a
specific line in the current codebase. The bounded-100K ALNS stall should be closed in
Wave A (R1 + R15) before any further search-operator or LBBD-cut work.

Prepared at repository head `029ea42`, artifact anchor
`benchmark/studies/2026-05-01-rhc-100k-audit-v7-post-guard-harness-fix/rhc_500k_study.json`.

