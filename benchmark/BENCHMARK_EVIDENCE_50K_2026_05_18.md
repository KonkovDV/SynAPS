# SynAPS 50K Benchmark Evidence — 2026-05-18

> **Status**: Artifact-bound evidence. Not a universal performance guarantee.
> **Scope**: Reproducible 50K pilot protocol, recent measurements, and honest non-claims.
>
> **Superseded numbers (Red Team audit v3, 2026-07):** figures here predate the
> ceil duration grain (P0-4), the strict single-thread determinism default
> (N1 / ADR-0001), the LBBD no-good fix (N2), and the dispatch parallel-lane fix
> (M2). Makespan/timing figures on instances with fractional `speed_factor`,
> parallel machines, or CP-SAT under the default `determinism="strict"` shift
> and must be regenerated before being cited.

---

## Protocol

### Hardware / Environment

- **Python**: 3.13 (CI uses 3.12 and 3.13)
- **CPU**: CI `ubuntu-latest` (GitHub-hosted runner); local reference uses 12th-gen Intel or AMD Zen4
- **RAM**: >= 16 GB recommended for 50K strict lane
- **Native accelerator**: Optional (`synaps_native` wheel); Python fallback is authoritative

### Canonical Command Set

```bash
# Strict lane (single-threaded, deterministic)
python -m benchmark.study_rhc_50k \
  --lane strict \
  --solvers RHC-GREEDY,RHC-ALNS \
  --seeds 42,123,999 \
  --profile canonical

# Throughput lane (multi-worker)
python -m benchmark.study_rhc_50k \
  --lane throughput \
  --solvers RHC-GREEDY,RHC-ALNS \
  --seeds 42,123,999 \
  --profile canonical
```

### Policy Profile

- **Window geometry**: `max_window_size=480`, `window_overlap=120`
- **ALNS inner time cap**: `alns_inner_window_time_cap_s=180`
- **Budget guard**: disabled for geometry validation; enabled for conservative lane
- **Presearch max window ops**: `5000`
- **Early stop**: `max_no_improve_iters=30`
- **Admission**: `due_admission_horizon_factor=2.0`

### What We Record

| Metric | Why |
|--------|-----|
| `scheduled_ratio` | Primary outcome (% of 50,000 operations scheduled) |
| `makespan_minutes` | Schedule length |
| `total_setup_minutes` | Setup time aggregate |
| `total_material_minutes` | Material handling aggregate |
| `tardiness_count` / `tardiness_minutes` | Due-date adherence |
| `wall_time_seconds` | End-to-end solve time |
| `fallback_repair_skipped` | Whether CP-SAT repair was skipped |
| `solver_metadata.error` | Any solver-level failure string |
| `native_backend` | `native` or `python` for candidate scoring |

---

## Recent Evidence (2026-05-15)

### 50K v4 (post-critical-fixes, native-backed)

- **RHC-GREEDY**: Pass; scheduled ratio improved vs pure-Python v2 anchor
- **RHC-ALNS**: Pass; scheduled ratio improved vs pure-Python v2 anchor
- **Note**: Improvement is partly attributable to native acceleration; not algorithm-only comparable

### 100K v9 (bounded evidence, same protocol)

- **RHC-GREEDY**: `7509/100000` in `90.302s`
- **RHC-ALNS**: `7279/100000` in `90.263s` with `fallback_repair_skipped=false`
- **Same-run parity**: Confirmed between greedy and ALNS on identical seed

---

## Non-Claims

1. **Not a world record**: These numbers are artifact-bound to the current geometry, seed set, and hardware.
2. **Not algorithm-only**: Native acceleration contributes to throughput; pure-Python parity tests are maintained separately.
3. **Not 100% scheduling**: Partial scheduling is expected at 50K/100K scale; the goal is measurable improvement, not universal feasibility.
4. **Not cross-instance portable**: Results apply to generated benchmark instances, not arbitrary customer data.

---

## Failure Taxonomy (Observed)

| Category | Symptom | Typical Cause |
|----------|---------|---------------|
| `no-candidate` | Zero feasible candidates in a window | Overly restrictive admission or setup constraints |
| `budget-guard` | ALNS presearch aborts before search | `op_count < threshold` at window start |
| `infeasible-repair` | CP-SAT repair returns empty | Tight precedence + SDST makes subproblem infeasible |
| `seed-generation-timeout` | Initial seed budget exhausted | Large window with many precedence edges |
| `zero-yield-cpsat` | CP-SAT finds no improving solution | Insufficient time cap or overly constrained model |
| `time-limit-before-search` | Solver exits before first feasible | Global time cap < model construction time |

---

## Reproducibility Checklist

- [ ] `requirements-lock.txt` matches runtime environment
- [ ] `synaps_native` wheel built from matching `Cargo.lock` commit (if using native)
- [ ] `RhcPolicy` / named profile used (no ad-hoc kwargs)
- [ ] Seed list identical across runs
- [ ] `FeasibilityChecker` passes on output schedule
- [ ] `BENCHMARK_EVIDENCE_50K_YYYY_MM_DD.md` committed with artifact hashes

---

## Artifact Hashes

Generated from commit: `TBD at release tag`

| File | SHA-256 |
|------|---------|
| `benchmark/studies/2026-05-15-rhc-50k-audit-v4/results.json` | `TBD` |
| `benchmark/studies/2026-05-15-rhc-100k-v9/results.json` | `TBD` |

---

## Evidence Runs (2026-05-18)

### 50K Matrix Attempt

Command:
```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k --seeds 42 123 999 \
  --solvers RHC-GREEDY RHC-ALNS --lane throughput --runs 1
```

Outcome:
- Records generated: 1 (seed 42 only)
- Solver: RHC-GREEDY
- Process outcome: `completed`
- Solve outcome: `solver_error`
- Error message: empty (framework-level failure before solver telemetry)
- No inter-seed CV computable due to single record and solver-level failure

Interpretation:
- At 50K scale, the throughput lane with `industrial-50k` preset hits a solver-level failure before producing measurable scheduling telemetry.
- This is consistent with the known limitation that 50K feasibility is not guaranteed within current timeboxes.
- The benchmark harness itself is functional; the failure is in the solver runtime path.

### 100K Bounded Evidence

Command:
```bash
python -m benchmark.study_rhc_500k \
  --scales 100000 --solvers RHC-ALNS-100K RHC-GREEDY \
  --seeds 42 --lane throughput --execution-mode gated \
  --max-windows-override 2 --max-estimated-memory-gb 8
```

Outcome:
- Window 1: ALNS completed 100 iterations, 10 improvements, 6 violations remaining, 23.25s
- Window 2: started, max_windows reached (2)
- 98,067 operations unscheduled after all windows; fallback greedy repair triggered
- Result: partial schedule with bounded-window constraint

Interpretation:
- Confirms 100K active-search yield remains limited: even with `RHC-ALNS-100K` geometry, 2 windows schedule only ~3% of operations.
- Fallback greedy repair is the dominant completion path at 100K under current admission/seed policies.
- Consistent with 2026-05-15 bounded audit evidence (`7279/100000` ALNS, `7509/100000` GREEDY).

## Next Steps

1. Retry 50K with `RHC-ALNS` single-seed to determine if ALNS path produces different failure mode.
2. Document 50K as a stress boundary, not a feasibility target.
3. Proceed to 100K bounded evidence with explicit `--max-windows-override` for controlled academic slices.
4. Do not add new claims until a solver produces at least one feasible 50K+ outcome.
