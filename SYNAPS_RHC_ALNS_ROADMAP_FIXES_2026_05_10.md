---
title: "SynAPS RHC-ALNS Roadmap Fixes"
status: "proposal"
date: "2026-05-10"
tags: [synaps, rhc, alns, roadmap, audit, implementation-plan]
---

# SynAPS RHC-ALNS Roadmap Fixes

## Scope

This document is an implementation handoff for an AI programmer. It corrects the proposed RHC-ALNS improvement plan after code-level inspection of the current SynAPS repository.

It is **not** an architecture SSOT. Treat it as an execution proposal/evidence note. Before implementation, verify current code because several items are already partially implemented.

## Key Repository Areas

| Area | Primary files |
|---|---|
| ALNS solver | `synaps/solvers/alns_solver.py` |
| RHC solver | `synaps/solvers/rhc/_solver.py` |
| RHC policy/budget/metadata | `synaps/solvers/rhc/_policy.py`, `_budget.py`, `_metadata.py` |
| SDST matrix | `synaps/solvers/sdst_matrix.py` |
| Native acceleration | `synaps/accelerators.py`, `native/synaps_native/src/lib.rs` |
| Lower bounds | `synaps/solvers/lower_bounds.py` |
| Feasibility checker | `synaps/solvers/feasibility_checker.py` |
| 50K benchmark rail | `benchmark/study_rhc_50k.py` |
| Relevant tests | `tests/test_alns_rhc_scaling.py`, `tests/test_benchmark_rhc_50k_study.py`, `tests/test_lower_bounds.py`, native parity tests |

## Current-State Corrections

The original task list should not be implemented blindly. Several tasks are already present in code.

| Original task | Current status | Correct action |
|---|---:|---|
| Task 1 Critical-path destroy | Mostly implemented | Add/adjust tests and invariants; do not rewrite from scratch |
| Task 2 Due-pressure destroy | Mostly implemented | Add tests; verify closure-aware behavior |
| Task 9 Warm-start from prior window | Partially implemented | Formalize conflict filtering and metadata |
| Task 11 Native CSR SDST | Not implemented | Redesign contract before coding; CSR is not automatically O(1) |
| Task 12 Operator weight persistence | Not implemented | Implement after warm-start metadata is stable |
| Task 3 Cross-window learning | Not implemented | Implement after weight persistence; feature-flag bias logic |
| Task 5 Adaptive SA temperature | Inline logic exists | Extract function; fix monotonicity requirement |
| Task 6 Lower-bound gap reporting | LB exists, gap metadata missing | Add ALNS metadata and tests |
| Task 7 Convergence diagnostics | Aggregates exist, no formal trace | Add bounded/flagged iteration diagnostics |
| Task 10 Benchmark quality gate | Partially implemented | Add inter-seed CV and high-variance flag |
| Task 4 Native destroy scoring | Not implemented | Depends on stable CSR/API and Python reference |
| Task 8 Parallel repair | Not implemented | Defer; high risk |
| Task 13 E2E | Benchmark rail exists | Add small E2E plus 50K evidence after features land |

## Corrected Execution Order

### Stage A — Stabilize Existing ALNS Foundation

#### A1. Critical-path destroy tests

**Files**:

- `synaps/solvers/alns_solver.py`
- `tests/test_alns_destroy_operators.py` or existing ALNS test module

**Do**:

- Confirm `_destroy_critical_path` builds a combined DAG from precedence and machine-sequence edges.
- Add deterministic unit tests for known small schedules.
- Add a property test with a valid invariant.

**Important correction**:

Do **not** require critical-path length to equal makespan for all feasible schedules. Current implementation sums operation durations over the combined DAG and does not necessarily account for idle gaps, release gaps, or setup gaps outside operation duration.

Use one of these invariants instead:

- critical-path duration is `<= makespan` for all feasible complete schedules;
- critical-path duration equals makespan only for compact no-idle schedules where all timing gaps are explained by precedence or machine sequence edges.

**Acceptance criteria**:

- Unit test identifies expected bottleneck chain on a known compact DAG.
- Property test does not fail on feasible schedules with idle time.

#### A2. Due-pressure destroy tests

**Files**:

- `synaps/solvers/alns_solver.py`
- `tests/test_alns_destroy_operators.py`

**Do**:

- Test tardy-order targeting.
- Test smallest-positive-slack fallback when no orders are tardy.
- Test that successor closure is applied in the ALNS main loop, not necessarily inside the raw operator.

**Important correction**:

If a property test checks that destroyed operations belong to top-tardy orders, apply that assertion to the **raw operator result**. After `_expand_successor_closure`, extra successors may be included for feasibility even if their parent order is not top-tardy.

**Acceptance criteria**:

- Tardy branch selects temporally latest operations from highest weighted-tardiness orders.
- Slack fallback selects smallest positive slack orders.
- Closure-aware test verifies successors are included after main-loop closure expansion.

### Stage B — Low-Risk Observability Improvements

#### B1. Add ALNS lower-bound gap metadata

**Files**:

- `synaps/solvers/alns_solver.py`
- `synaps/solvers/lower_bounds.py`
- tests near ALNS metadata tests

**Do**:

`compute_relaxed_makespan_lower_bound(problem)` already exists and includes machine-load, critical-path, exclusive-machine, max-operation, and auxiliary-resource components.

Add ALNS metadata fields:

```python
"alns_lower_bound": round(lower_bound.value, 4),
"alns_gap_ratio": round(
    (best_cost_or_makespan - lower_bound.value) / max(lower_bound.value, 1e-6),
    6,
),
"lower_bound_components": lower_bound.as_metadata(),
```

Use objective makespan when possible. If ALNS cost is weighted objective, do not mix weighted cost with makespan lower bound. Prefer:

```python
makespan = best_objective.makespan_minutes
```

**Acceptance criteria**:

- ALNS `ScheduleResult.metadata` contains `alns_lower_bound`, `alns_gap_ratio`, and `lower_bound_components`.
- `alns_gap_ratio >= 0` for complete feasible schedules.
- Existing lower-bound tests still pass.

#### B2. Extract SA temperature function

**Files**:

- `synaps/solvers/alns_solver.py`
- ALNS tests

**Do**:

Extract inline dynamic SA logic to a pure function, for example:

```python
def _compute_effective_temperature(
    *,
    base_temp: float,
    due_pressure: float,
    candidate_pressure: float,
    due_alpha: float,
    candidate_beta: float,
    min_temp: float,
    max_temp: float,
) -> float:
    ...
```

**Important correction**:

The original requirement said temperature should decrease monotonically with increasing `due_pressure`. Current code increases exploration under pressure:

```python
factor = 1.0 + sa_due_alpha * due_pressure + sa_candidate_beta * candidate_pressure
```

This is reasonable. Therefore update the property test to:

- temperature is always in `[sa_temp_min, sa_temp_max]`;
- temperature is **non-decreasing** with increasing due pressure when candidate pressure is held constant.

Do not silently invert the search behavior unless explicitly approved.

**Acceptance criteria**:

- Pure function has direct unit/property tests.
- Existing ALNS behavior remains equivalent for default parameters.

#### B3. Add bounded ALNS convergence diagnostics

**Files**:

- `synaps/solvers/alns_solver.py`
- ALNS metadata tests

**Do**:

Add a lightweight dataclass or dict record for iterations, but avoid unbounded metadata growth.

Recommended fields:

```python
iteration
operator_name
destroy_size
repair_status
candidate_cost
best_cost
temperature
accepted
improved
```

Recommended kwargs:

```python
record_iteration_metrics: bool = False
max_iteration_records: int = 500
```

Always keep aggregate fields in metadata:

- `iterations_completed`
- `accepted_iterations`
- `improved_iterations`
- `operator_attempt_counts`
- `alns_final_operator_weights`
- `stagnation_detected`
- `stagnation_iteration`

**Acceptance criteria**:

- Metadata fields are present even when iteration trace is disabled.
- Trace length never exceeds `max_iteration_records`.
- Stagnation metadata is set when `max_no_improve_iters` triggers.

### Stage C — RHC ↔ ALNS Bridge

#### C1. Formalize warm-start filtering

**Files**:

- `synaps/solvers/rhc/_solver.py`
- preferably a helper module such as `synaps/solvers/rhc/_warm_start.py` or existing `_window.py`
- RHC tests

**Current state**:

RHC already collects:

- external `warm_start_assignments`
- `previous_window_tail_assignments`
- rewound assignments

and passes `warm_start_assignments` to the selected inner solver.

**Do**:

- Extract a pure helper for filtering warm starts against current window and frozen boundary.
- Reject assignments whose operation is not in the next active window.
- Reject assignments for frozen committed operations.
- Reject direct conflicts with frozen boundary assignments where detectable cheaply.
- Return both accepted assignments and rejection counts/reasons.

Suggested return shape:

```python
@dataclass(frozen=True)
class WarmStartSelection:
    assignments: list[Assignment]
    supplied_count: int
    accepted_count: int
    rejected_count: int
    rejected_reason_counts: dict[str, int]
```

**Acceptance criteria**:

- RHC per-window metadata includes:
  - `warm_start_used`
  - `warm_start_supplied_assignments`
  - `warm_start_completed_assignments`
  - `warm_start_rejected_reason_counts`
- Edge case: all warm-start assignments conflict -> solver falls back to fresh initial generation and records reason.

#### C2. ALNS operator weight persistence

**Files**:

- `synaps/solvers/alns_solver.py`
- `synaps/solvers/rhc/_solver.py`
- tests

**Do**:

In ALNS, accept:

```python
initial_operator_weights: dict[str, float] | list[float] | None
```

Prefer dict by operator name because `DESTROY_OPERATORS` order may change.

Add metadata:

```python
"alns_operator_names": [...],
"alns_initial_operator_weights": {...},
"alns_final_operator_weights": {...},
```

In RHC, after each ALNS window:

- extract `alns_final_operator_weights`;
- store it in local solve-scoped state;
- pass it to the next window as `initial_operator_weights`.

**Fallback**:

- If list length mismatches operator count, log warning and use uniform weights.
- If dict has missing/extra keys, keep recognized positive weights, fill missing uniformly, then normalize.

**Acceptance criteria**:

- Operator weights always normalize to sum `1.0` within tolerance.
- Mismatched list length falls back to uniform.
- RHC passes previous window weights to the next ALNS window.

#### C3. Cross-window quality summaries

**Files**:

- `synaps/solvers/rhc/_solver.py`
- possible helper module under `synaps/solvers/rhc/`
- ALNS solver only after telemetry is stable

**Do**:

Implement telemetry first; do not immediately bias search.

Define:

```python
@dataclass(frozen=True)
class WindowQualitySummary:
    per_machine_utilization: dict[Any, float]
    setup_cost_by_machine: dict[Any, float]
    tardiness_contribution: float
    operation_count: int
```

Add:

```python
quality_summary_buffer = deque(maxlen=5)
```

After each window solve:

- compute and append summary;
- pass `cross_window_hints` to ALNS only when feature flag is enabled.

Recommended flags:

```python
cross_window_learning_enabled: bool = False
cross_window_operator_bias_enabled: bool = False
```

**Acceptance criteria**:

- Buffer length never exceeds 5.
- Hints are propagated when enabled.
- No search behavior changes when disabled.

#### C4. Bounded cross-window operator bias

**Files**:

- `synaps/solvers/alns_solver.py`
- tests

**Do**:

If `cross_window_hints` indicate high setup cost concentration, apply small bounded boost to setup-disrupting operators such as `machine_segment` and possibly `worst`.

Rules:

- bias must be feature-flagged;
- max boost should be bounded, e.g. 10–15%;
- normalize after bias;
- emit metadata showing applied bias.

**Acceptance criteria**:

- Weights remain normalized.
- Bias is absent when feature flag is off.
- Bias cannot zero out any operator.

### Stage D — Benchmark Quality Gate

#### D1. Add inter-seed CV and high-variance flag

**Files**:

- `benchmark/study_rhc_50k.py`
- `tests/test_benchmark_rhc_50k_study.py`

**Do**:

In `_summarize_solver_records`, compute coefficient of variation across seed-level makespan values:

```python
inter_seed_cv_makespan = stdev(makespans) / mean(makespans)
```

Handle edge cases:

- fewer than 2 values -> `0.0`
- mean <= 0 -> `0.0`

Add:

```python
"inter_seed_cv_makespan": round(cv, 6),
"high_variance": cv > 0.15,
```

**Acceptance criteria**:

- `high_variance` is true at CV > 0.15.
- `high_variance` is false at CV <= 0.15.
- Single-seed runs report CV `0.0`.

#### D2. Preserve and test CVaR definition

**Files**:

- `benchmark/study_rhc_50k.py`
- tests

**Do**:

Keep `_tail_cvar` as empirical tail mean beyond VaR unless changing definition intentionally.

Add property/unit tests:

- `CVaR >= VaR` for non-empty positive lists and alpha in `(0.5, 0.99)`.
- Empty list returns `0.0`.

**Acceptance criteria**:

- CVaR behavior is documented and tested.

### Stage E — Native SDST and Destroy Scoring

#### E1. Redesign CSR SDST contract before implementation

**Files**:

- `synaps/solvers/sdst_matrix.py`
- `synaps/accelerators.py`
- `native/synaps_native/src/lib.rs`
- native parity tests

**Important correction**:

Do not claim classic CSR provides O(1) lookup. CSR lookup is usually O(row nonzeros) or O(log row nonzeros) if rows are sorted. O(1) requires an additional hash/direct index and may violate memory constraints.

Recommended backend decision:

| Backend | Best for | Lookup |
|---|---|---|
| Dense NumPy | small/dense state spaces | O(1) |
| Sorted CSR | large sparse matrices | O(log row nnz) |
| CSR + hash index | hot random sparse lookup | amortized O(1), higher memory |

**Do**:

- Keep existing dense `SdstMatrix` as default for small cases.
- Add transparent sparse/native backend only when memory estimate favors it.
- Add backend metadata:
  - `sdst_backend`: `dense_numpy`, `csr_python`, `csr_native`
  - `sdst_memory_bytes`

**Acceptance criteria**:

- CSR lookup matches dense/dict lookup for all valid triples.
- Unknown triples return zero consistently.
- 100 machines × 20 states × 700K entries memory target is measured, not assumed.

#### E2. Native `get_setup_batch`

**Do**:

Expose a batch lookup API that accepts integer-index vectors, not UUIDs:

```text
wc_indices: int[]
from_state_indices: int[]
to_state_indices: int[]
```

Return:

```text
setup_values: int[]
```

**Acceptance criteria**:

- One FFI call handles many triples.
- Native and Python outputs match exactly.
- Python fallback is deterministic.

#### E3. Native worst-destroy scoring

**Files**:

- `synaps/accelerators.py`
- `native/synaps_native/src/lib.rs`
- `synaps/solvers/alns_solver.py`

**Do**:

Only after Python reference and SDST backend are stable.

Native function should accept structure-of-arrays integer data and return score vector. Python remains responsible for selecting operation IDs.

**Acceptance criteria**:

- Native and Python score vectors match within `1e-10` for deterministic numeric inputs.
- Fallback path works when native module is unavailable.
- Benchmark proves real speedup before enabling by default.

### Stage F — Parallel Repair

#### F1. Defer by default

Task 8 is high risk. Do not implement until Stages A–E are green.

Reasons:

- precedence constraints can cross partitions;
- machine sequence and setup constraints cross partitions;
- auxiliary resources can cross partitions;
- merge may break feasibility;
- Windows `ProcessPoolExecutor` has pickling/spawn overhead and reliability concerns.

#### F2. If implemented, use staged rollout

Order:

1. Pure partitioning function.
2. Serial per-partition simulation.
3. Merge validation with `FeasibilityChecker`.
4. Greedy fallback on any invalid sub-result.
5. ProcessPool dispatch behind feature flag.

Recommended flags:

```python
parallel_repair_enabled: bool = False
repair_num_workers: int = 1
```

**Acceptance criteria**:

- Partition balance tests pass.
- Merge correctness tests pass for non-conflicting and conflicting sub-results.
- Any infeasible/timeout sub-region triggers full greedy fallback.
- Final merged assignments pass `FeasibilityChecker`.

### Stage G — End-to-End Validation

#### G1. Small E2E integration test

**File**:

- `tests/test_e2e_rhc_alns_integration.py` or similar

**Do**:

Use a synthetic 500-operation instance with:

- critical-path and due-pressure operators enabled;
- warm-start enabled;
- operator weight persistence enabled;
- gap metadata enabled;
- convergence metadata enabled;
- native path enabled only if available, fallback accepted.

**Acceptance criteria**:

- result is feasible;
- zero `FeasibilityChecker` violations;
- metadata fields are populated:
  - `warm_start_used`
  - `warm_start_completed_assignments`
  - `alns_final_operator_weights`
  - `alns_gap_ratio`
  - `stagnation_detected`
  - `inter_seed_cv_makespan` in benchmark summary where applicable.

#### G2. 50K benchmark evidence

**Files**:

- `benchmark/study_rhc_50k.py`
- benchmark results output path

**Do**:

Run at least 3 seeds after feature integration.

Check:

- all runs complete or have classified outcome;
- feasible runs have zero validation violations;
- fallback ratio below configured threshold;
- makespan degradation within quality-gate threshold;
- inter-seed CV reported;
- high-variance flag reported.

**Important correction**:

Do not require full native-vs-Python heuristic makespan equality within `0.1%` if native uses approximate ranking kernels. Use strict parity for deterministic kernels and looser tolerance for full heuristic outcomes.

Recommended tolerances:

| Check | Tolerance |
|---|---:|
| Native objective evaluation vs Python | exact or `1e-9` |
| Native batch setup lookup vs Python | exact |
| Native deterministic score vector vs Python | `1e-10` |
| Full native-vs-Python heuristic makespan | 1–5%, or evidence-based threshold |
| Feasibility | exact: zero violations |

## Implementation Guardrails

### Do not rewrite stable code unnecessarily

Task 1 and Task 2 are already implemented in `alns_solver.py`. Focus on tests, metadata, and correctness refinements.

### Keep feature flags for behavior-changing logic

Use feature flags for:

- cross-window learning bias;
- parallel repair;
- native sparse backend if not yet proven;
- full iteration trace.

### Prefer name-keyed operator weights

Do not persist operator weights only by list index. Use operator names to avoid silent mismatch if `DESTROY_OPERATORS` order changes.

### Keep Python fallback authoritative

Every native seam must have:

- deterministic Python fallback;
- parity test;
- backend metadata;
- no hard dependency on native module availability.

### Be careful with weighted objective vs makespan gap

Lower-bound gap must compare makespan to makespan lower bound. Do not compare weighted ALNS cost to makespan lower bound.

## Minimal Pull Request Checklist

Before opening/merging implementation PR:

- [ ] Task 1/2 tests added or updated without duplicate implementation.
- [ ] ALNS metadata includes lower-bound gap fields.
- [ ] SA temperature pure function tested with corrected monotonicity.
- [ ] Warm-start filtering helper has unit tests.
- [ ] Operator weight persistence implemented by operator name.
- [ ] Benchmark summary includes inter-seed CV and high-variance flag.
- [ ] Focused tests pass.
- [ ] Any native feature has Python fallback and parity tests.
- [ ] Parallel repair remains disabled unless fully validated.
- [ ] E2E small integration test passes.

## Suggested Focused Test Commands

Adjust names to actual test module names after implementation.

```powershell
python -m pytest tests/test_alns_destroy_operators.py -q
python -m pytest tests/test_lower_bounds.py -q
python -m pytest tests/test_benchmark_rhc_50k_study.py -q
python -m pytest tests/test_alns_rhc_scaling.py -q
```

For native changes:

```powershell
python -m pytest tests/test_accelerators.py tests/test_native_objective_parity.py tests/test_native_stabilize_parity.py -q
```

For final integration:

```powershell
python -m pytest tests/test_e2e_rhc_alns_integration.py -q
```

## Recommended Commit Slicing

Use multiple small commits instead of one giant commit:

1. `test(alns): cover critical-path and due-pressure destroy invariants`
2. `feat(alns): report lower-bound gap and convergence metadata`
3. `feat(rhc): formalize warm-start filtering metadata`
4. `feat(rhc-alns): persist operator weights across windows`
5. `feat(benchmark): add inter-seed variance quality signal`
6. `feat(native): add csr sdst backend with parity tests`
7. `feat(alns): add native destroy scoring seam`
8. `feat(rhc-alns): add e2e integration evidence`

## Final Recommendation

Implement the roadmap in this order:

1. Tests and metadata for already-existing ALNS operators.
2. Gap reporting and SA extraction.
3. Warm-start filtering and operator weight persistence.
4. Benchmark variance quality gate.
5. Cross-window telemetry, then optional bounded bias.
6. Native CSR and destroy scoring.
7. Parallel repair only after everything above is stable.
8. E2E 500-op and 50K benchmark evidence.

This order gives the highest confidence-to-risk ratio and avoids destabilizing feasibility-critical scheduling paths before observability and validation are strong enough.
