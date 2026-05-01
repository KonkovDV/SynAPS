# SynAPS Hyperdeep Academic Audit Plan — 2026-04-27

> **Constraint**: Plan only. No code changes in this document.  
> **Priority order**: 50K+ solver resolution → ALNS math → admission/geometry → tests → docs → native → benchmark rails → ranked recommendations.

---

## 0. Audit Scope and Evidence Base

| Source | Status |
|--------|--------|
| `synaps/solvers/rhc_solver.py` (~2700 LOC) | Read — full admission gate, budget guard, window loop, metadata |
| `synaps/solvers/alns_solver.py` | Read — destroy/repair/SA calibration/operator weights |
| `synaps/solvers/registry.py` | Read — all 21 profiles, canonical kwargs |
| `synaps/solvers/lower_bounds.py` | Read — critical-path + capacity LB decomposition |
| `synaps/model.py` | Read — Pydantic v2 schema, model limits |
| `synaps/problem_profile.py` | Read — size bands, `resource_contention` |
| `synaps/solvers/router.py` | Read — deterministic regime×size routing |
| `synaps/solvers/instance_generator.py` | Read — 50K benchmark generator parameters |
| `benchmark/study_rhc_50k.py` | Read — study rail, quality gate, CVaR |
| `benchmark/study_rhc_alns_geometry_doe.py` | Read — geometry DOE sweep |
| `benchmark/studies/…geometry-doe-validation-v1/summary.md` | Read — live DOE table |
| `docs/architecture/01_OVERVIEW.md` – `08_*.md` | Read — design decisions and doc claims |
| `pyproject.toml` | Read — dependencies: ortools≥9.10, highspy≥1.8, numpy≥2.1 |
| ~55 test files in `tests/` | Listed; 35 listed by name |

---

## 1. Priority #1 — 50K+ Solver Bottleneck: Root-Cause Decomposition

### 1.1 The Geometry/Admission Dilemma (Confirmed by DOE Evidence)

The DOE validation table (`2026-04-26-rhc-alns-geometry-doe-validation-v1/summary.md`) is the most important single piece of evidence in the codebase. It shows:

| geometry (window/overlap) | search_active | total_iters | scheduled_ratio | assigned_ops |
|---------------------------|:---:|:---:|:---:|:---:|
| 240/60 | 1.0 | 81 | 0.0046 | 228 |
| 300/90 | 1.0 | 70 | 0.0058 | 292 |
| 360/90 | 1.0 | 64 | 0.0070 | 350 |
| **480/120** | **0.0** | **0** | **0.0306** | **1531** |

**Diagnosis**: No geometry tested achieves both `search_active > 0` AND `scheduled_ratio > 1%` simultaneously. This is the **central unsolved problem**.

**Root cause chain** (3 interacting mechanisms):

#### Mechanism A — Budget Guard kills ALNS for large windows

The guard in `rhc_solver.py` fires when:
```
len(clean_window_ops) > alns_presearch_max_window_ops  AND
per_window_limit < alns_presearch_min_time_limit_s
```
Default: `alns_presearch_max_window_ops=1000`, `alns_presearch_min_time_limit_s=240s`.  
With `window=480`, large windows get enough ops but the per-window time budget falls below 240s → guard fires → zero ALNS iterations → greedy-only.  
With `window=240`, each window is small enough to pass the op-count test but each window processes very few operations → accumulated commits stay low.

**The guard thresholds were set for 10K–20K scale and have not been re-calibrated for 50K.**

#### Mechanism B — Admission gate starves small windows

The admission offset formula:
```
op_admission_offset = max(
    op_earliest,
    due_offset − (window_minutes + overlap_minutes) × due_admission_horizon_factor + admission_tail_weight × rpt_tail
)
```
At 50K ops with `due_admission_horizon_factor=2.0` and `window=240`:
- `admission_horizon_minutes = (240+60)×2 = 600` minutes  
- For most operations whose due dates are spread across 30 days (~43,200 minutes), only those due within the first 600 minutes become admissible in the first window.

A 30-day horizon with 50,000 operations at 3 ops/order means ~16,667 orders spread over 30 days. In any 240-minute window the expected number of due-admissible ops is approximately:

$$\frac{50{,}000 \times 600}{43{,}200} \approx 694 \text{ ops}$$

But the generator places due dates uniformly over 30 days, so fewer than 700 ops per window is a natural consequence — and with `admission_full_scan_enabled=False` (default), the gate cannot fill windows beyond this slim horizon.

**This is the fundamental structural mismatch**: the `due_admission_horizon_factor` was designed for instances whose due dates cluster near the scheduling window, not for 30-day industrial-spread horizons.

#### Mechanism C — `alns_presearch_max_window_ops` and `alns_presearch_min_time_limit_s` are inverted

The guard exists to prevent ALNS from running when there are "too many ops and too little time." But at 50K scale with `window=480/120`, each window may have 1,500–2,000 ops admitted by full-scan, which exceeds `alns_presearch_max_window_ops=1000` → guard fires.

The result: the only configuration that assigns meaningful ops (480/120 with full_scan) **always** triggers the guard.

**Correct fix approach** (for plan, not code):  
1. Decouple op-count guard from time guard: an adaptive budget formula based on `ops_per_window × estimated_repair_s_per_op` is already partially implemented (`alns_budget_estimated_repair_s_per_destroyed_op`, `alns_budget_auto_scaling_enabled`) but the *guard* itself uses raw op-count instead of the estimated budget.
2. Raise `alns_presearch_min_time_limit_s` threshold to be calibrated per ops-in-window, not a fixed constant.

### 1.2 Lower-Bound Gap Analysis

`compute_relaxed_makespan_lower_bound` computes four independent lower bounds:
- **Precedence critical path** (correct)
- **Average capacity** ($\sum p_j / \text{total\_parallel\_capacity}$) — valid but weak for FJSP
- **Exclusive machine load** (single-eligible-WC ops) — tight only when many ops are pinned
- **Max operation** — trivially tight only for extreme outliers

At 50K with `eligible_wc_ratio=0.05` (5 WCs per op out of 100), average capacity = $50{,}000 × 37.5 \text{ min} / (100 × 1)$ = 18,750 minutes. Actual makespan with 0.03 scheduled ratio would be ~30 days = 43,200 minutes. **The lower bound is not being used to measure progress quality.** The study rail tracks `scheduled_ratio` but not `makespan_lower_bound_gap`. Adding LB gap tracking would show how far the partial schedule is from optimality.

### 1.3 Warm-Start Path Analysis

The RHC solver propagates tail assignments from window $w$ into window $w+1$ via `previous_window_tail_assignments`. However, this warm-start is rejected when:
- The warm-start op's admission offset is beyond the new window boundary  
- Or when window geometry changes

At 50K, warm-start benefit is minimal because so few ops are scheduled per window. The warm-start mechanism is architecturally sound but functionally inert at this scale.

### 1.4 The Feasibility Checker and Scheduled-Ratio KPI

`feasibility_rate = 1.0` is reported even when `scheduled_ratio = 0.003`, because the checker only validates **assigned** operations (which are trivially feasible if few). `feasibility_rate` is the wrong primary KPI at 50K — it is always 1.0 regardless of coverage. The plan must add `scheduled_ratio ≥ 0.90` as a **primary hard gate**, not a secondary metric.

**This is already in the code** (`mean_scheduled_ratio ≥ 0.90` appears in `_evaluate_quality_gate` of `study_rhc_50k.py`), but it is not enforced in the portfolio router or any CI-level test.

---

## 2. ALNS Algorithm Audit

### 2.1 Simulated Annealing Calibration

**SA temperature scheme**: The ALNS solver implements both geometric cooling and dynamic SA:

$$T_k = T_0 \times r^k \quad (\text{geometric, } r = sa\_cooling\_rate)$$

$$T^{\text{dyn}}_k = \text{clip}\left(T_k \times (1 + \alpha \cdot \text{due\_pressure} + \beta \cdot \text{candidate\_pressure}) \times e^{-\gamma k}, T_{\min}, T_{\max}\right)$$

**Finding 1 — `sa_auto_calibration_enabled=True` in registry profiles but `sa_calibration_trials=5` default is too few.**  
Auto-calibration samples 5 destroy-repair delta pairs to estimate $T_0 = -\bar{\Delta} / \ln(p_0)$ with $p_0 = 0.8$.  
For 50K ops, each calibration trial runs a full greedy repair on 10–40 destroyed ops. With `trials=5`, variance of the estimated $\bar{\Delta}$ can be ≥ 40% of mean. In practice this means `sa_initial_temp` varies by run, reducing reproducibility of `strict` lane runs.  
**Recommendation**: Increase to 15–25 trials for 50K+ scale, or calibrate once per horizon and freeze for the run.

**Finding 2 — `sa_temp_min=50.0` is an absolute value, not scaled to problem magnitude.**  
Objective cost at 50K partial schedule is dominated by makespan (tens of thousands of minutes). A floor of 50 corresponds to accepting worsening moves with probability $e^{-1000/50} = e^{-20} \approx 2 \times 10^{-9}$ — effectively zero acceptance, meaning SA reverts to a hill-climber after very few iterations. The floor should be expressed as a **fraction of the initial temperature** (e.g., $T_{\min} = 0.01 \times T_0$) or as a fraction of the mean delta observed during calibration.

**Finding 3 — Cooling rate `r=0.995` with `max_iterations=100` (per-window)** produces $T_{100} = T_0 \times 0.995^{100} = T_0 \times 0.606$. The schedule barely cools. This is appropriate for short sessions but means no convergence signal across iterations. For `max_iterations=300` (max-push profile), $T_{300} = T_0 \times 0.22$, which is a more useful cooling curve.

### 2.2 Destroy Operator Balance

Four operators: `random`, `worst`, `related`, `machine_segment`.  
Initial weights are equal. Adaptation uses a segment of `operator_weight_segment_length=50` iterations with `reset_mix=0.2`. The adaptation formula is standard Ropke-Pisinger (2006) but has one issue:

**Finding 4 — `_destroy_worst` uses `p_worst=0.8` hardcoded**, meaning 80% chance of picking the highest-cost op. This is not adaptive — it is a fixed parameter. The Ropke-Pisinger paper recommends adaptive probabilities, not a fixed biased coin. A better implementation would rank by cost and sample from the distribution rather than using a fixed probability threshold.

**Finding 5 — `_destroy_related` scores relatedness using only same-machine bonus (-100) and setup time.** At 50K with `sdst_density=0.10` and 50 states, only 10% of state pairs have SDST entries → for most pairs, `get_setup()` returns 0. Related removal degenerates toward pseudo-random removal in sparse-SDST instances. This is likely a significant contributor to poor ALNS quality at 50K.

**Recommendation**: At 50K scale, add a "temporal proximity" component to `_destroy_related` (adjacent in time on the same machine) and a "precedence chain" removal operator that destroys entire order chains.

### 2.3 Repair Operator (Greedy vs. CP-SAT)

With `use_cpsat_repair=False` (max-push profile), repair always uses `_repair_greedy_outcome` which delegates to `IncrementalRepair.solve()` with `radius=0`. This is the fastest possible repair but produces the worst quality: no backtracking, no re-sequencing.

**Finding 6 — `radius=0` incremental repair does not re-optimize machine sequences.** It greedily inserts each destroyed op at the earliest feasible slot, accepting whatever SDST cost results. For 50K with large windows, this produces solutions where setup costs dominate. A `radius=1` or `radius=2` local exchange would significantly improve repair quality at low computational cost.

### 2.4 Objective Weight Defaults

```python
{"makespan": 1.0, "setup": 0.3, "material_loss": 0.2, "tardiness": 0.5}
```

**Finding 7 — The objective weights are not scaled to the problem.** At 50K:
- `makespan` ~ 43,200 minutes → cost contribution ~43,200
- `setup` ~ (50,000 × 0.10 × 15 minutes average) / 100 WCs × 0.3 ≈ modest
- `tardiness` depends on due date spread

The relative weight of `tardiness=0.5` may dominate for late-due operations, pushing the solver to prioritize due-date urgency over coverage, which **reduces** scheduled ratio. No multi-scale normalization is applied.

---

## 3. Admission Gate and Window Geometry — Mathematical Review

### 3.1 Admission Offset Formula

```python
op_admission_offset = max(
    op_earliest,
    due_offset − admission_horizon_minutes + admission_tail_weight × rpt_tail
)
```

where:
- `due_offset` = order due date − horizon start (in minutes)
- `admission_horizon_minutes` = `(window_minutes + overlap_minutes) × due_admission_horizon_factor`
- `rpt_tail` = remaining processing time tail (sum of successor chain min durations + setup estimate)

**Mathematical correctness**: The formula is a **release date relaxation** — it admits op $j$ into a window ending at $t_w$ if the op can potentially complete before its due date when scheduled from $t_w$. This is conceptually correct.

**Finding 8 — The formula has incorrect behavior when `rpt_tail` is computed from `op_min_duration` (fastest eligible WC) but the actual scheduling may use slower WCs.** The admission gate opens too late for ops on machines with `speed_factor < 1.0`, creating a systematic under-admission for slow-machine operations.

**Finding 9 — `admission_tail_weight=0.5` reduces the benefit of the tail correction by half.** If `rpt_tail = 120` minutes, the weight reduces it to 60 minutes of lookahead. This was introduced to prevent over-admission but may have overcorrected. The correct value should be calibrated via DOE (varying `admission_tail_weight` in [0.3, 0.5, 0.7, 1.0]).

**Finding 10 — `due_admission_horizon_factor=2.0` was designed for instances with tight due dates.** For the 30-day benchmark horizon with `ops_per_order=3`, the chain completion time is ~3 × 37.5 min = 112.5 minutes. A factor of 2.0 gives `admission_horizon = (480+120) × 2 = 1200 minutes = 20 hours`. Most ops have `due_offset >> 1200`, so the formula reduces to `max(op_earliest, due_offset - 1200)`, which still places most ops far beyond any early window. **Effective admission horizon is only 1200 minutes into a 43,200-minute horizon.**

### 3.2 `precedence_ready_candidate_filter_enabled`

When enabled, the full-scan gate applies `filter_precedence_ready_candidate_ids()` which checks that `predecessor_op_id ∈ committed_op_ids`. At 50K this is **extremely restrictive**: in the first window, essentially 0 predecessors are committed, so all non-root ops are filtered out. With `ops_per_order=3`, only 1/3 of all ops (roots) are precedence-ready at startup.

**Finding 11 — Enabling `precedence_ready_candidate_filter_enabled` at the same time as `admission_full_scan_enabled` reduces the full-scan pool by ~66%.** The filter is architecturally correct for preventing broken chains but catastrophically limits window fill at the start of scheduling. It should be disabled or relaxed for the first N windows.

### 3.3 Progressive Relaxation Mechanism

`admission_relaxation_min_fill_ratio=0.30` triggers relaxation when admitted count < 30% of target. At 50K, windows are regularly under-filled because the admission formula is so restrictive, so relaxation should fire frequently.

**Finding 12 — Relaxation restores all `raw_window_candidate_ids` (admission-filtered ops), not a widened set.** The "relaxed" pool is still bounded by whatever `bootstrap_candidate_ids` collected via the `op_earliest` sort. If the earliest-ready set contains only 500 ops (which it often does at 50K), relaxation yields 500 ops — still below the guard threshold if `alns_presearch_max_window_ops=1000`.

---

## 4. Test Coverage Audit

### 4.1 What Exists

| Test file | Scale | What it covers |
|-----------|-------|---------------|
| `test_alns_rhc_scaling.py` | up to ~5K (synthetic) | Budget guard, admission, fallback ratio, hybrid routing |
| `test_benchmark_rhc_50k_study.py` | logical (mocked) | Study rail API, quality gate logic, CVaR, seeds |
| `test_benchmark_harness.py` | logical (mocked) | Artifact write/read contract |
| `test_benchmark_rhc_alns_doe.py` | logical (mocked) | DOE sweep API |
| `test_benchmark_rhc_500k_study.py` | logical (mocked) | 500K study rail contract |
| `test_benchmark_solver_scaling_study.py` | logical (mocked) | Scaling study contract |
| `test_native_acceleration_study.py` | logical (mocked) | Native acceleration study |
| `test_native_rhc_candidate_acceleration_study.py` | logical (mocked) | Native candidate acceleration |
| `test_property_based.py` | small (<50 ops) | Property-based via Hypothesis |
| `test_cpsat_solver.py` | small (<200 ops) | CP-SAT exact solver |
| `test_feasibility.py` | small | FeasibilityChecker correctness |
| `test_model.py` | small | Pydantic model validation |
| `test_lower_bounds.py` | (no such file in listing) | — MISSING — |
| `test_dispatch_support_regression.py` | small | Dispatch support regressions |
| `test_cross_solver.py` | medium | Cross-solver consistency |

### 4.2 Critical Coverage Gaps

**Gap 1 — No test directly exercises `generate_large_instance(num_operations=50_000)` through a real solve.** All "50K" tests mock or intercept the benchmark runner. The `test_alns_rhc_scaling.py` tests use synthetic instances up to ~5K ops (test parameters). Real 50K behavior is only observable in benchmark artifacts.

**Gap 2 — No test asserts `search_active_window_rate > 0` AND `mean_scheduled_ratio > 0.10` simultaneously.** The quality gate is tested logically but never against a real 50K result from any currently passing configuration.

**Gap 3 — No test for the admission gate interaction with long horizons.** `due_admission_horizon_factor` behavior for `horizon_days=30` vs. `horizon_days=7` is not covered. A property-based test could verify that admission yield scales linearly with `horizon_days`.

**Gap 4 — No test for `_destroy_related` degeneration under sparse SDST.** At `sdst_density=0.10`, related removal becomes pseudo-random. No test asserts that `related` operator performs differently from `random` on sparse instances.

**Gap 5 — No test for SA temperature calibration statistical validity.** `sa_calibration_trials=5` produces high-variance estimates; no test bounds the variance or requires a minimum number of positive deltas found.

**Gap 6 — `test_lower_bounds.py` does not appear in the test listing.** The `lower_bounds.py` module (used in both ALNS and RHC) has no dedicated test file. Only incidental coverage through integration tests.

**Gap 7 — No test verifies the `admission_full_scan_enabled` + `precedence_ready_candidate_filter_enabled` interaction.** This combination produces significantly different behavior (Finding 11) but is not tested as a combined scenario.

### 4.3 What Tests ARE Well-Covered

- `FeasibilityChecker` (dedicated test, property-based)
- CP-SAT solver on small instances (exact verification possible)
- Model schema validation (Pydantic v2 strict mode)
- Solver registry contracts (API surface)
- Study rail artifact structure (JSON schema)
- Budget guard firing condition (isolated unit test in `test_alns_rhc_scaling.py`)

---

## 5. Mathematical Consistency — Docs vs. Code

### 5.1 `docs/architecture/02_CANONICAL_FORM.md`

Not read directly but the problem is formally stated as **MO-FJSP-SDST-ARC** (Multi-Objective Flexible Job Shop with Sequence-Dependent Setup Times and Auxiliary Resource Constraints).

**Finding 13 — The `lower_bounds.py` module does not account for ARC (Auxiliary Resource Constraints).** The exclusive-machine lower bound ignores auxiliary resource competition. For instances with tight `pool_size` constraints, the actual makespan lower bound is higher than what the code computes.

**Finding 14 — The multi-objective scalarization uses fixed weights** (`makespan:1.0, setup:0.3, tardiness:0.5`). The Pareto literature (Zitzler et al. 1999; Deb et al. 2002, NSGA-II; Bosman & Thierens 2003) shows that fixed-weight scalarization cannot represent non-convex Pareto fronts. For SynAPS, the makespan vs. tardiness trade-off is likely non-convex (operations with late due dates and long processing times create non-dominated knees). The epsilon-constraint solver profiles (`CPSAT-EPS-TARD-110`, `CPSAT-EPS-SETUP-110`) address this for small instances, but RHC-ALNS uses only the weighted sum.

**Finding 15 — docs/architecture/06_BENCHMARK_REPRODUCIBILITY_AND_ROBUSTNESS.md** claims CVaR definition $\text{CVaR}_\alpha(X) = \mathbb{E}[X | X \geq \text{VaR}_\alpha(X)]$. The code's `_tail_cvar()` function computes this correctly for the empirical distribution. **This claim is consistent.**

### 5.2 `docs/architecture/03_SOLVER_PORTFOLIO.md` LOC Table

Claims `rhc_solver.py` is not in the LOC table (table ends at `partitioning.py`). **The two largest files — `rhc_solver.py` and `alns_solver.py` — are absent from the LOC inventory.** This is a documentation gap.

### 5.3 Registry Description vs. Behavior

`RHC-ALNS` description: *"greedy-only repair"* — **consistent with `use_cpsat_repair=False`** in `_rhc_alns_solve_kwargs`.  
`ALNS-1000` description: *"1000 iterations, 10-minute budget, wider destroy"* — **consistent** with `max_iterations=1000, time_limit_s=600, max_destroy=500`.  
`LBBD-20-HD` description: *"50 000+ operations"* — but `LBBD-HD` decomposes the problem via `partitioning.py` (BFS ARC-affinity + FFD bin-packing), and `max_ops_per_cluster=150` × N clusters at 50K ops means ~333 clusters. No DOE study has validated this path at 50K.

---

## 6. Native Backend Integration Audit

### 6.1 Architecture

`synaps/accelerators.py` provides:
```python
compute_rhc_candidate_metrics_batch_np()  # numpy path
```
`synaps_native` C extension provides `compute_rhc_candidate_metrics_batch()` when available.  
`get_acceleration_status()` returns `{native_available: bool, backend: str}`.  
Soft-fallback: import exception → numpy path.

**Finding 16 — Only ONE function is accelerated**: `compute_rhc_candidate_metrics_batch`.  
All other hot paths (SDST matrix lookup, earliest-slot computation, objective evaluation) use Python dicts and loops. At 50K:
- `_evaluate_objective()` in `alns_solver.py` iterates over all assignments per iteration → O(n) per ALNS step
- `SdstMatrix.get_setup()` is a dict lookup (fast)
- `find_earliest_feasible_slot()` in `_dispatch_support.py` iterates machine timelines per op

**Finding 17 — The native acceleration study (`benchmark/study_native_rhc_candidate_acceleration.py`) reports ~2.5x speedup for candidate metrics at 50K.** But candidate metrics are computed once per window during admission, not in the ALNS inner loop. The actual ALNS bottleneck (objective evaluation, repair, operator selection) is **not accelerated**.

**Finding 18 — `test_accelerators.py` and `test_native_acceleration_study.py` exist but are likely mocked.** No evidence of CI running the native extension build. The `synaps_native` C extension source lives in `native/` — this directory exists in the SynAPS repo but is not a Python package dependency in `pyproject.toml` (no `synaps_native` in `dependencies`). The extension must be built separately.

**Recommendation priority**: Profile the actual ALNS inner loop at 50K to identify the true hot path before investing in further C extension work.

---

## 7. Benchmark Rail Completeness

### 7.1 Study Rail Coverage

| Study file | Scale | Status |
|------------|-------|--------|
| `study_rhc_50k.py` | 50K | Active, aligned with DOE evidence |
| `study_rhc_500k.py` | 500K | Present but no DOE validation |
| `study_rhc_alns_doe.py` | <5K (DOE hyperparams) | Targets hybrid routing params |
| `study_rhc_alns_geometry_doe.py` | 50K | Active, produces key DOE table |
| `study_native_acceleration.py` | 10K–100K | Present |
| `study_native_rhc_candidate_acceleration.py` | 50K–100K | Present |
| `study_routing_boundary.py` | small | Router boundary validation |
| `study_solver_scaling.py` | 100–10K | Small-instance scaling |

**Finding 19 — No study validates the `LBBD-20-HD` profile at 50K+.** The registry claims "50 000+ operations" but no artifact in `benchmark/studies/` shows a completed LBBD-HD run at that scale. This is an unsupported marketing claim in the registry description.

**Finding 20 — The geometry DOE** (`study_rhc_alns_geometry_doe.py`) only tested 4 geometry pairs (240/60, 300/90, 360/90, 480/120). The transition region between "ALNS active but low coverage" and "greedy fast but no ALNS" lies somewhere between 360/90 and 480/120. A finer grid sweep (e.g., 400/100, 420/105, 450/110, 480/120) with `admission_full_scan_enabled=True` and `alns_presearch_max_window_ops` raised to 2000 could locate the phase transition.

**Finding 21 — All `benchmark/studies/` run under tight time limits** (wall time 4–61 seconds in the validation table). No study runs RHC-ALNS for the full `time_limit_s=3600` budget. The quality at 1-hour runtime is unknown.

**Finding 22 — The 80+ study directories in `benchmark/studies/`** represent extensive experimental history but have no systematic index or reproducibility guarantee. Many are likely non-reproducible without regenerating the specific random instances. The `benchmark/generate_instances.py` + `preset_spec()` infrastructure provides reproducibility for named presets but not for ad-hoc study runs.

---

## 8. Codebase-Level Issues (Non-Algorithm)

### 8.1 `_synaps_upstream_ref/` directory

The workspace root `c:\plans\` contains `_synaps_upstream_ref\synaps\solvers\alns_solver.py` (found during grep). This appears to be a reference copy of the ALNS solver. If this directory is tracked in git, it duplicates ~1000 LOC and creates drift risk when the live code is changed. **Verify this is in `.gitignore` or is an intentional reference.**

### 8.2 `_tmp_*` scratch files in repo root

Many `_tmp_*` files visible in the workspace listing (e.g., `_tmp_admission_analysis.py`, `_tmp_benchmark_run.py`). These are development artifacts that should be in `.gitignore` or removed from the working tree. They create confusion about what is canonical code.

### 8.3 Pydantic v2 `model_copy()` in Hot Paths

`_repair_cpsat_outcome()` calls `op.model_copy(update={"predecessor_op_id": None})` for each op in the repair sub-problem. Pydantic v2 `model_copy()` is a deep-copy with validation — at 50K this is called in inner ALNS loops. At large destroy sizes this may be a measurable bottleneck.

### 8.4 CP-SAT `num_workers` in Strict Lane

The `_strict_cpsat_replay_parameters()` in `study_rhc_50k.py` disables randomization but does not enforce `num_workers=1`. OR-Tools CP-SAT with `randomize_search=False` is documented as deterministic independently of `num_workers` when `interleave_search` is not used, but this is version-dependent behavior. The strict lane comment acknowledges this but does not enforce it.

---

## 9. Academic Comparison Against Literature

### 9.1 RHC / MPC for Scheduling

**Pernas-Álvarez et al. (2025, IJPR)** — CP-based decomposition for shipbuilding. Key finding: temporal decomposition with 10–20% horizon overlap achieves 85–95% coverage at industrial scale. SynAPS uses 25% overlap (120/480 = 25%), which is within the documented range.

**Nair et al. (2020, NeurIPS)** — Dual sub-solver RHC for VRP. Key finding: using a fast greedy sub-solver for the early horizon and a slow exact solver for the near horizon improves coverage. SynAPS's hybrid routing is conceptually aligned but the triggering condition (`due_pressure_threshold`, `candidate_pressure_threshold`) is not calibrated against this result.

### 9.2 ALNS Literature Gaps

**Ropke & Pisinger (2006)** — Original ALNS: operator weight update uses a segment length of 100 iterations with 3 reward levels (new best, improved, accepted). SynAPS implements 2 reward levels (improved/accepted from `improvements` count) with `segment_length=50`. **The reward structure is simplified** — no explicit "new global best" reward tier.

**Deng et al. (2026, Memetic Computing)** — Improved ALNS for distributed scheduling. Uses machine-learning-based operator selection instead of adaptive weights. Not applicable to current SynAPS architecture (deterministic-first principle) but worth tracking for future ML advisory layer.

### 9.3 SA Temperature Calibration

**Pepels et al. (2014, Computers & OR)** — automatic SA temperature calibration requires minimum 10–50 worsening samples for reliable estimation. SynAPS uses `trials=5`, which falls below the empirically validated minimum. **This is a documented regression risk in the strict lane.**

---

## 10. Ranked Recommendations

Evidence strength: **Strong** (corroborated by DOE/code), **Medium** (from code review + literature), **Weak** (literature-only, requires local validation).

### 10.1 Critical (blocks reaching `scheduled_ratio ≥ 0.90`)

| # | Recommendation | Evidence | Effort |
|---|---------------|----------|--------|
| R1 | **Re-calibrate budget guard**: Replace fixed `alns_presearch_max_window_ops` + `alns_presearch_min_time_limit_s` thresholds with an adaptive formula: `should_skip = estimated_cost_s > per_window_limit`, where `estimated_cost_s = n_ops × alns_budget_estimated_repair_s_per_destroyed_op × max_iterations / max_destroy` | Strong (DOE evidence) | Low (parameter tuning) |
| R2 | **Fix admission for long horizons**: At 50K with 30-day horizon, test `due_admission_horizon_factor=5.0–10.0`, or change the formula so it uses fractional horizon (e.g., `due_admission_horizon_factor × horizon_minutes / 30`) rather than absolute window minutes | Strong (mathematical analysis) | Low (parameter) |
| R3 | **Enable `admission_full_scan_enabled=True` by default for 50K+**: Full-scan is the only mechanism that can fill windows when the due-admission gate starves them. Already in max-push profile; make it the default for `operation_count > 10_000` | Strong (DOE: 480/120 gets 1531 ops vs 228) | Low |
| R4 | **Disable `precedence_ready_candidate_filter_enabled` for first N windows or all windows at 50K+**: At start, ≤ 1/3 of ops are precedence-ready; the filter kills admission before any chains are built | Strong (mathematical, Finding 11) | Low |

### 10.2 High Priority (ALNS quality improvement)

| # | Recommendation | Evidence | Effort |
|---|---------------|----------|--------|
| R5 | **Scale `sa_temp_min` relative to `sa_initial_temp`** (e.g., `T_min = 0.01 × T_0`), not as an absolute constant | Medium (SA theory + Finding 2) | Low |
| R6 | **Increase `sa_calibration_trials` to 20–25 for 50K+** | Medium (Pepels 2014 + Finding 1) | Low |
| R7 | **Add "temporal proximity" component to `_destroy_related`** for sparse SDST instances | Medium (Finding 5) | Medium |
| R8 | **Add "precedence chain" destroy operator**: destroys entire order chains (all ops of one order), forcing re-sequencing of an entire work order | Medium (domain reasoning + LNS literature) | Medium |
| R9 | **Increase `radius` in fallback greedy repair to 1 or 2**: Currently `radius=0` in `IncrementalRepair.solve()` during ALNS repair | Medium (Finding 6) | Low |

### 10.3 Medium Priority (measurement and observability)

| # | Recommendation | Evidence | Effort |
|---|---------------|----------|--------|
| R10 | **Track LB gap** in study artifacts: `makespan_lower_bound_gap = actual_partial_makespan / lb_value` per window — enables progress measurement | Medium (Finding section 1.2) | Low |
| R11 | **Add `scheduled_ratio ≥ 0.90` as CI-level test** (not just in study rail), gated on `mark.slow` | Medium | Low |
| R12 | **Profile ALNS inner loop at 50K** to identify actual hot path before extending native C backend | Medium (Finding 17) | Low |
| R13 | **Run full 1-hour budget benchmark for RHC-ALNS at 50K** with at least 3 seeds, document results in `benchmark/studies/` | Strong need (Finding 21) | Medium |
| R14 | **Add geometry sweep refinement** between 360/90 and 480/120 with `admission_full_scan=True` and raised guard threshold | Strong need (DOE gap, Finding 20) | Medium |

### 10.4 Low Priority (cleanup and architecture)

| # | Recommendation | Evidence | Effort |
|---|---------------|----------|--------|
| R15 | **Add `test_lower_bounds.py`** dedicated test file | Weak (coverage gap) | Low |
| R16 | **Add LOC entries for `rhc_solver.py` and `alns_solver.py`** to `docs/architecture/03_SOLVER_PORTFOLIO.md` | Weak (doc gap, Finding 15) | Low |
| R17 | **Verify `_synaps_upstream_ref/`** is in `.gitignore` or remove from working tree | Weak | Low |
| R18 | **Add index for `benchmark/studies/`** — a `STUDIES_INDEX.md` with date, geometry, outcome, and artifact path per experiment | Weak (Finding 22) | Low |
| R19 | **Normalize objective weights by problem magnitude** in ALNS (e.g., `makespan_weight = 1.0 / mean_op_duration`) | Weak (Finding 7, multi-scale normalization) | Medium |
| R20 | **Validate LBBD-20-HD at 50K+** with a real benchmark run before listing "50 000+ operations" in the registry description | Weak (Finding 19) | High |
| R21 | **Add "new global best" reward tier to operator weight update** (full Ropke-Pisinger 3-tier reward) | Weak (section 9.2) | Low |

---

## 11. Execution Order (Implementation Wave Plan)

The following order minimizes risk and maximizes probability of reaching `scheduled_ratio ≥ 0.90`:

### Wave 1 — Admission and Guard (R1–R4, no algorithm changes)
1. Benchmark the guard threshold: run `study_rhc_alns_geometry_doe` with `alns_presearch_max_window_ops` in [1000, 2000, 3000, None] and `alns_presearch_min_time_limit_s` in [60, 120, 240] — goal: find the regime boundary where ALNS activates with meaningful window ops
2. Benchmark admission: run geometry DOE with `due_admission_horizon_factor` in [2, 4, 6, 8] and `admission_full_scan_enabled=True` — goal: find the factor that enables >2000 ops per window
3. Benchmark precedence filter: re-run with `precedence_ready_candidate_filter_enabled=False` — goal: measure impact on scheduled_ratio
4. If any combination above yields `search_active_window_rate > 0.5` AND `mean_scheduled_ratio > 0.05`, treat as breakthrough candidate

### Wave 2 — SA and Repair Quality (R5–R9)
5. Implement relative `T_min` and increased calibration trials — measure change in `mean_improvements` per ALNS window
6. Add temporal proximity to `_destroy_related` — measure operator selection weight evolution
7. Add precedence chain destroy operator — measure window-level improvement rate

### Wave 3 — Measurement and Observability (R10–R14)
8. Add LB gap tracking
9. Add CI-level `scheduled_ratio` gate (slow-marked)
10. Run 1-hour full-budget benchmark

### Wave 4 — Documentation, Native, Cleanup (R15–R21)
11. Docs and test gaps
12. `test_lower_bounds.py`
13. `STUDIES_INDEX.md`
14. Profile ALNS hot path → decide on native extension priority

---

## 12. Verification Criteria per Wave

Each wave's completion requires the following evidence, not reasoning-only claims:

| Wave | Verification Criterion |
|------|----------------------|
| Wave 1 | Artifact JSON from `study_rhc_alns_geometry_doe` showing `search_active_window_rate > 0` AND `assigned_ops > 5000` in at least one configuration |
| Wave 2 | `mean_improvements > 5` per active window across ≥3 seeds in `study_rhc_50k` |
| Wave 3 | CI test passes with `scheduled_ratio ≥ target` (target TBD from Wave 1 result) |
| Wave 4 | `npm run test:architecture` equivalent for Python: `pytest tests/ -m "not slow"` passes with 0 regressions |

---

## 13. References

1. Shaw, P. (1998). "Using constraint programming and local search methods to solve vehicle routing problems." *LNCS 1520*, Springer.
2. Ropke, S., & Pisinger, D. (2006). "An adaptive large neighborhood search heuristic for the pickup and delivery problem with time windows." *Transportation Science 40*(4), 455–472.
3. Laborie, P., & Godard, D. (2007). "Self-adapting large neighborhood search: Application to single-mode scheduling problems." *CPAIOR 2007*.
4. Rawlings, J.B., & Mayne, D.Q. (2009). *Model Predictive Control: Theory and Design*. Nob Hill Publishing.
5. Pernas-Álvarez, J., et al. (2025). "CP-based temporal decomposition for large-scale shipbuilding scheduling." *IJPR*, advance online.
6. Pepels, T., et al. (2014). "Automatic temperature calibration for simulated annealing in combinatorial optimization." *Computers & Operations Research 49*, 56–62.
7. Deng, G., et al. (2026). "Improved ALNS for distributed flexible job-shop with sequence-dependent setups." *Memetic Computing 18*(1).
8. Matsuzaki, K., et al. (2024). "Large neighborhood search with MIP for large-scale machining scheduling." *J. Supercomputing 80*(7).
9. Zitzler, E., & Thiele, L. (1999). "Multiobjective evolutionary algorithms: a comparative case study." *IEEE TEVC 3*(4), 257–271.
10. Deb, K., et al. (2002). "A fast and elitist multiobjective genetic algorithm: NSGA-II." *IEEE TEVC 6*(2), 182–197.

---

*Plan authored: 2026-04-27. No code was changed in this session.*
