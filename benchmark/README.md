# SynAPS Benchmark Harness

Language: **EN** | [RU](README_RU.md)

Reproducible solver evaluation for the SynAPS scheduling platform.

## Quick Start

```bash
# Single solver, single instance
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED

# Generate a reproducible large boundary instance for LBBD routing studies
python -m benchmark.generate_instances benchmark/instances/generated_large.json \
  --preset large --seed 7

# Aggregate router behavior across generated preset/seed families
python -m benchmark.study_routing_boundary --presets medium large --seeds 1 2 3

# Compare actual solver behavior on generated preset families
python -m benchmark.study_solver_scaling --presets medium large --seeds 1 2 3 \
  --solvers GREED CPSAT-30 LBBD-10 AUTO

# Run the dedicated 50K large-instance RHC study and write artifacts under benchmark/
python -m benchmark.study_rhc_50k --preset industrial-50k --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/2026-04-12-rhc-50k

# Run the staged 500K stress-study in safe planning mode (resource projection + gate)
python -m benchmark.study_rhc_500k --execution-mode plan --lane both --seeds 1 2 3

# Execute gated stress-study ladder (runs only scales that pass admission gate)
python -m benchmark.study_rhc_500k --execution-mode gated --lane both --seeds 1 \
  --scales 50000 100000 200000 300000 500000 \
  --write-dir benchmark/studies/2026-04-19-rhc-500k

# Routed portfolio mode (router chooses the concrete solver)
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers AUTO

# Compare two solvers
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json \
  --solvers GREED CPSAT-30 --compare

# Compare the default exact profile against an epsilon-constrained Pareto slice
python -m benchmark.run_benchmark benchmark/instances/pareto_setup_tradeoff_4op.json \
  --solvers CPSAT-10 CPSAT-EPS-SETUP-110 --compare

# Multiple runs for statistical confidence
python -m benchmark.run_benchmark benchmark/instances/medium_20x10.json \
  --solvers GREED CPSAT-10 --runs 5 --compare

# All instances in a directory
python -m benchmark.run_benchmark benchmark/instances/ --solvers GREED CPSAT-30
```

## Solver Configurations

| Name | Solver | Parameters |
|------|--------|------------|
| `GREED` | GreedyDispatch | K1=2.0, K2=0.5 |
| `GREED-K1-3` | GreedyDispatch | K1=3.0, K2=0.5 |
| `CPSAT-10` | CpSatSolver | time_limit=10s |
| `CPSAT-30` | CpSatSolver | time_limit=30s |
| `CPSAT-120` | CpSatSolver | time_limit=120s |
| `CPSAT-EPS-SETUP-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise setup under a `1.10x` makespan cap |
| `CPSAT-EPS-TARD-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise tardiness under a `1.10x` makespan cap |
| `CPSAT-EPS-MATERIAL-110` | ParetoSliceCpSatSolver | 2-stage CP-SAT, minimise material loss under a `1.10x` makespan cap |
| `LBBD-5` | LbbdSolver | HiGHS master + CP-SAT sub, 5 iterations, capacity + load-balance cuts |
| `LBBD-10` | LbbdSolver | HiGHS master + CP-SAT sub, 10 iterations |
| `AUTO` | Portfolio router | Chooses a concrete solver configuration per instance |

## Academic Portfolio Note

`CPSAT-EPS-SETUP-110`, `CPSAT-EPS-TARD-110`, and `CPSAT-EPS-MATERIAL-110` are the public academic epsilon-constraint profiles in the SynAPS portfolio.

They are intentionally not marketed as full Pareto-front explorers. Instead, each exposes one reproducible and benchmarkable Pareto slice:

1. stage 1 finds a strong exact incumbent with the default makespan-first CP-SAT model;
2. stage 2 constrains makespan to within `10%` of that incumbent and minimises the chosen secondary objective (setup, tardiness, or material loss);
3. inside the slice, the solver tie-breaks on makespan to avoid arbitrary slack.

`LBBD-5` and `LBBD-10` demonstrate Logic-Based Benders Decomposition with HiGHS MIP master and CP-SAT subproblems. The master emits two cut types per iteration:

- **Capacity cuts** (Hooker & Ottosson 2003): tighten the lower bound based on bottleneck machine processing.
- **Load-balance cuts**: enforce `C_max >= total_load / num_machines` as a relaxation-free bound.

This gives a current-proof surface for both multi-objective and decomposition research without overstating capabilities.

## Output Format

### Single Solver

```json
{
  "instance": "tiny_3x3.json",
  "solver_config": "GREED",
  "selected_solver_config": "GREED",
  "results": {
    "status": "feasible",
    "feasible": true,
    "proved_optimal": false,
    "solver_name": "greedy_dispatch",
    "makespan_minutes": 95.0,
    "total_setup_minutes": 18.0,
    "total_material_loss": 0.0,
    "assignments": 6
  },
  "statistics": {
    "runs": 1,
    "wall_time_s_mean": 0.0012,
    "wall_time_s_min": 0.0012,
    "wall_time_s_max": 0.0012,
    "peak_rss_mb": 85.0
  }
}
```

### Comparison Mode

```json
{
  "instance": "tiny_3x3.json",
  "comparisons": [
    {"solver_config": "GREED", "results": {...}, "statistics": {...}},
    {"solver_config": "CPSAT-30", "results": {...}, "statistics": {...}}
  ]
}
```

## Programmatic API

```python
from pathlib import Path
from benchmark.run_benchmark import load_problem, run_benchmark

problem = load_problem(Path("benchmark/instances/tiny_3x3.json"))
report = run_benchmark(Path("benchmark/instances/tiny_3x3.json"), solver_names=["GREED"], runs=3)
```

## Adding Solvers

Register new configurations in `synaps/solvers/registry.py`:

```python
_SOLVER_REGISTRY["MY-SOLVER"] = SolverRegistration(
  factory=build_my_solver,
  solve_kwargs={"param": value},
  description="short human-readable description",
)
```

The special `AUTO` mode is benchmark-only and routes through `synaps.solve_schedule()`.

## Parametric Instance Generation

`benchmark.generate_instances` activates the planned synthetic-generator surface from the benchmark protocol.

### Presets

| Preset | Intended band | Typical use |
|--------|---------------|-------------|
| `tiny` | small | CI smoke and schema sanity |
| `small` | small | regression and heuristic comparisons |
| `medium` | medium | exact-profile and epsilon-slice comparisons |
| `large` | large | LBBD routing boundary and decomposition studies |
| `industrial` | large | offline stress generation for research runs |

### CLI examples

```bash
# Start from a preset
python -m benchmark.generate_instances benchmark/instances/generated_medium.json \
  --preset medium --seed 11

# Override preset parameters for a custom stress instance
python -m benchmark.generate_instances benchmark/instances/generated_boundary.json \
  --preset large --seed 17 --jobs 48 --machines 14 --operations-min 4 --operations-max 6
```

The generator writes a current-schema `ScheduleProblem` JSON file and prints a summary containing the deterministic seed and the derived `problem_profile`. This makes the generated instance directly usable with `python -m synaps solve ...` and `python -m benchmark.run_benchmark ...` without any conversion step.

## Routing Boundary Study

`benchmark.study_routing_boundary` turns the generated preset families into a reproducible academic report.

It does three things:

1. generates each requested preset across the supplied deterministic seeds;
2. derives `problem_profile` for every generated instance;
3. records the deterministic router decision so Phase 1 LBBD-boundary assumptions are backed by concrete evidence.

Example:

```bash
python -m benchmark.study_routing_boundary \
  --presets medium large \
  --seeds 1 2 3 4 \
  --write-dir benchmark/instances/studies
```

The emitted JSON includes per-instance records plus `summary_by_preset`, including routed solver counts, size-band counts, operation-count statistics, and a `routing_stable` flag that makes boundary drift obvious when presets stop mapping to the expected portfolio member.

## Solver Scaling Study

`benchmark.study_solver_scaling` takes the same preset families and turns them into executable solver-comparison evidence.

For each generated preset/seed combination it:

1. materializes a current-schema instance;
2. runs the requested solver configurations through the public benchmark harness;
3. aggregates mean runtime, mean makespan, and feasibility rate by selected solver.

Example:

```bash
python -m benchmark.study_solver_scaling \
  --presets medium large \
  --seeds 1 2 3 \
  --solvers GREED CPSAT-30 LBBD-10 AUTO \
  --write-dir benchmark/instances/scaling-studies
```

The report keeps per-instance comparison records and emits `summary_by_preset`, which makes it straightforward to answer questions like “does `AUTO` collapse into `LBBD-10` on large generated instances?” and “what is the runtime trade-off between GREED and exact/decomposition profiles on the same preset family?”.

## Dedicated 50K RHC Study

`benchmark.study_rhc_50k` is the reproducible large-instance study for the current `RHC-GREEDY` and `RHC-ALNS` path.

It does four things in one command:

1. materializes a deterministic `industrial-50k` benchmark instance per requested seed;
2. runs the public benchmark harness with `RHC-GREEDY` and `RHC-ALNS`;
3. preserves per-instance records, solver metadata, and verification timing;
4. writes a JSON artifact under the chosen `benchmark/` directory so README and audit claims can point to a stable evidence surface.

`industrial-50k` temporal generation note (2026-04-26):

- orders now carry explicit `release_offset_min` in `domain_attributes`;
- release offsets are sampled with an early-skewed long-tail law over `0..0.55*horizon`;
- this preserves first-window admission signal for short geometry-smoke DOE while keeping late-release diversity for larger staged runs.

Short-smoke evidence checkpoint:

- artifact [studies/2026-04-26-rhc-alns-geometry-doe-postfix-smoke-v4/rhc_alns_geometry_doe.json](studies/2026-04-26-rhc-alns-geometry-doe-postfix-smoke-v4/rhc_alns_geometry_doe.json)
  recovered non-zero admission pressure (`peak_raw_window_candidate_count=2670` vs smoke-v2 zero-frontier collapse);
- coverage is still below historical baseline in this constrained 10s/1-window slice, so treat this as admission-recovery hardening rather than full throughput closure.

ALNS tuning checkpoint (geometry DOE v6, 2026-04-26):

- canonical DOE profile now fixes `due_admission_horizon_factor=2.0` to keep admission pressure non-zero before ALNS budget guards;
- artifact [studies/2026-04-26-rhc-alns-geometry-doe-v6-alns-tuning/rhc_alns_geometry_doe.json](studies/2026-04-26-rhc-alns-geometry-doe-v6-alns-tuning/rhc_alns_geometry_doe.json) is the current tuning evidence surface;
- in the strict 10s/1-window slice, `480/120` is the only geometry with non-zero scheduled coverage (`scheduled_ratio=0.0147`) and non-zero frontier (`peak_raw_window_candidate_count=6637`), while `240/60`, `300/90`, and `360/90` collapse to `no assignments produced` under this budget.

Example:

```bash
python -m benchmark.study_rhc_50k \
  --preset industrial-50k \
  --seeds 1 \
  --solvers RHC-GREEDY RHC-ALNS \
  --write-dir benchmark/studies/2026-04-13-rhc-50k-machine-index
```

The study writes materialized instances under `instances/` and a top-level `rhc_50k_study.json` artifact with aggregated wall-clock, verification time, makespan, setup totals, and RHC-specific metadata such as preprocessing time and candidate-pool pressure.
The study summary now also emits `summary_by_solver.*.inner_window_summary`, which lifts per-window audit signals like `search_active_window_rate`, `mean_initial_solution_ms`, `mean_commit_yield`, and `warm_start_rejected_reason_counts` out of raw `inner_window_summaries`.

April 2026 hardening note:

- ALNS initial seeds are now full-feasibility validated before local search and before being reused as a final recovery baseline.
- On the RHC-ALNS lane, a window that exhausts its budget before the first LNS iteration is now recorded as `inner_time_limit_exhausted_before_search` and routed through the existing fallback-greedy path.
- When auditing a fresh `rhc_50k_study.json`, inspect both solver-level KPIs and `inner_window_summaries` for `initial_solution_ms`, `time_limit_exhausted_before_search`, and `final_violation_recovery_*`.
- For partial RHC outputs (`status=error` with `ops_scheduled < ops_total`), use `lower_bound_upper_bound_comparable` before reading `gap`: current code sets `gap` to `null` for committed-subset schedules because their raw `lower_bound` and `upper_bound` are not mathematically comparable.

### Current artifacts

The baseline artifact is [studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json](studies/2026-04-13-rhc-50k-machine-index/rhc_50k_study.json).

The latest pre-fix live stress-matrix artifact is [studies/test-50k-academic-matrix-v1/rhc_50k_study.json](studies/test-50k-academic-matrix-v1/rhc_50k_study.json).

The retired guarded-profile artifact is [studies/2026-04-26-rhc-alns-postfix-canonical-v4/rhc_50k_study.json](studies/2026-04-26-rhc-alns-postfix-canonical-v4/rhc_50k_study.json).

The current-head audit before the profile refresh is [studies/2026-04-27-rhc-50k-audit-v1/rhc_50k_study.json](studies/2026-04-27-rhc-50k-audit-v1/rhc_50k_study.json).

The refreshed current-head public/default audit is [studies/2026-04-27-rhc-50k-audit-v2-current-head/rhc_50k_study.json](studies/2026-04-27-rhc-50k-audit-v2-current-head/rhc_50k_study.json).

Read them together rather than collapsing them into one story:

- the pre-fix stress matrix preserves the old ALNS failure shape, where coverage was weak but some windows did enter search;
- the guarded-profile artifact preserves the second regime, where oversized ALNS windows are skipped before costly seed generation can burn the whole per-window budget;
- the current-head-before-refresh audit preserves the mixed regime, where early windows do enter ALNS, but windows 2-3 burn budget on zero-yield CP-SAT repair and later windows fall back or time out under hybrid CP-SAT routing;
- the refreshed current-head audit shows the public profile after that cleanup: hybrid CP-SAT routing and CP-SAT repair are gone from the public path, windows 1-2 still enter search, and later windows now fail earlier with `inner_time_limit_exhausted_before_search` during seed construction;
- all current-head public runs still report `status=error` and `feasible=false`, so none should be read as a solved industrial benchmark.
- in that partial regime, compare coverage and fallback metrics first; do not interpret bound-gap quality unless `lower_bound_upper_bound_comparable=true`.

The current split is now more precise:

- pre-fix `RHC-ALNS|throughput` reported `mean_scheduled_ratio = 0.0946`, `mean_makespan_minutes = 4985.85`, and `mean_inner_fallback_ratio = 0.1`;
- guarded-profile `RHC-ALNS|throughput` reports `mean_scheduled_ratio = 0.3028`, `mean_makespan_minutes = 9675.18`, and `mean_inner_fallback_ratio = 1.0`;
- current-head-before-refresh `RHC-ALNS|throughput` reports `mean_scheduled_ratio = 0.1243`, `mean_makespan_minutes = 4134.84`, and `mean_inner_fallback_ratio = 0.625`;
- current-head-after-refresh `RHC-ALNS|throughput` reports `mean_scheduled_ratio = 0.0845`, `mean_makespan_minutes = 3059.82`, and `mean_inner_fallback_ratio = 0.6667`;
- current-head-after-refresh `RHC-GREEDY|throughput` remains the stronger pure-coverage baseline at `mean_scheduled_ratio = 0.3563` with zero inner fallback.

So the public 50K path remains real and reproducible, but the latest evidence is now four-way: ALNS can enter search; the retired public profile was wasting too much budget in CP-SAT side paths; and the refreshed public default removes those side paths yet still loses late windows to seed-construction exhaustion. That is why the public `RHC-ALNS` default stays greedy-only and hybrid-off, while the DOE harnesses keep those knobs exposed for controlled experiments.

Post-audit (2026-04-26) solver hardening now includes:

- full-frontier escalation for underfilled admission windows (`admission_full_scan_*` metadata);
- dynamic ALNS repair-budget scaling tied to effective destroy envelope (`alns_effective_repair_time_limit_s`);
- explicit pre-search short-circuiting for oversized ALNS windows (`budget_guard_skipped_initial_search`).

RHC-ALNS profile update (April 2026):

- `due_admission_horizon_factor=2.0` (was 1.0): tuned via geometry DOE v6 to maintain non-zero admission pressure in short ALNS windows;
- `alns_presearch_max_window_ops=5000`: synchronized with effective window cap to align presearch guard with candidate-pool semantics;
- `admission_full_scan_enabled=False`: capped full-scan semantics (adds candidates up to `candidate_pool_limit` only, not all uncommitted ops) now prevents runaway candidate sets in underfilled windows;
- `hybrid_inner_routing_enabled=False`: the public benchmark default no longer routes due-pressure windows directly into CP-SAT after the 2026-04-27 audits showed timeout-heavy hybrid behavior on the retired profile;
- `inner_kwargs.use_cpsat_repair=False`: the public benchmark default now uses greedy-only ALNS repair because the 2026-04-27 50K audit showed zero accepted CP-SAT repairs on the retired profile;
- new telemetry fields added to metadata:
  - `precedence_ready_blocked_by_precedence_count`: count of ops rejected due to unresolved predecessor constraints;
  - `precedence_ready_ratio`: ratio of precedence-ready ops among those evaluated (0–1);
  - `admission_full_scan_triggered_windows`: count of windows where full-scan path was activated;
  - `admission_full_scan_added_ops`: count of ops added during full-scan path;
  - `admission_full_scan_final_pool_peak`: peak candidate-pool size after full-scan phase.

Bounded 100K evidence for the retired profile is [studies/2026-04-27-rhc-100k-audit-v1/rhc_500k_study.json](studies/2026-04-27-rhc-100k-audit-v1/rhc_500k_study.json). It shows `RHC-GREEDY` scheduling `8144/100000` operations in `90.226s`, while `RHC-ALNS` schedules `0/100000` operations and exhausts `400518 ms` in initial solution generation before the first ALNS iteration. Treat that artifact as failure evidence for the retired profile, not as a claim that the refreshed default is already validated at 100K.

Bounded 100K evidence for the staged geometry-refresh harness is [studies/2026-04-27-rhc-100k-audit-v3-geometry-refresh/rhc_500k_study.json](studies/2026-04-27-rhc-100k-audit-v3-geometry-refresh/rhc_500k_study.json). In that slice, the staged `100k+` harness narrows `RHC-ALNS` first-window geometry to `300/90`, reducing the first inner slice to `760` ops. The run reaches `ALNS starting`, completes `55` iterations with `43` improvements, records `0` inner fallback, and finishes at `4678/100000` scheduled operations in `90.118s`. Read that artifact as proof that 100K ALNS can now enter search under the staged harness, not as proof that the 100K path is closed: the run still ends partial and `feasible=false`.

Fresh bounded 100K current-head evidence on that same staged harness is [studies/2026-04-27-rhc-100k-audit-v4-current-head/rhc_500k_study.json](studies/2026-04-27-rhc-100k-audit-v4-current-head/rhc_500k_study.json). It reports `RHC-GREEDY` scheduling `7852/100000` operations in `90.213s`, while `RHC-ALNS` schedules `3420/100000` in `90.113s`. ALNS still reaches search in both bounded windows, completing `56` and `30` iterations with `45` and `18` improvements, using `0` CP-SAT repairs, and reporting `0` inner fallback. Read that artifact as the honest current comparison: search-entry is preserved, but scheduled coverage still trails the same-run greedy baseline and remains partial (`mean_scheduled_ratio = 0.0342`, `feasible = false`).

## Staged 500K Study

`benchmark.study_rhc_500k` is the stress-study harness for 500K+ operation scenarios.

It extends the 50K workflow with:

1. staged scale ladder (default `50k -> 100k -> 200k -> 300k -> 500k`);
2. explicit resource projection (setup entries, eligibility links, dense SDST footprint, working-set estimate);
3. admission gate before expensive solves (`execution-mode gated`);
4. robust summary metrics (mean/median/IQR/CVaR for makespan and wall-time, scheduled-ratio and tail unscheduled risk);
5. quality gate versus baseline solver on the same lane and scale.

### Execution modes

- `plan`: only topology/resource projection and gate decisions; no solver execution.
- `gated`: executes only scales that pass resource gate.
- `full`: executes all requested scales, ignoring gate decisions.

### Typical usage

```bash
# Fast scientific planning pass (no heavy solve)
python -m benchmark.study_rhc_500k --execution-mode plan --lane both --seeds 1 2 3

# Controlled stress run with gate-protected execution
python -m benchmark.study_rhc_500k --execution-mode gated --lane both --seeds 1 \
  --scales 50000 100000 200000 300000 500000 \
  --write-dir benchmark/studies/2026-04-19-rhc-500k
```

The script writes `rhc_500k_study.json` into the selected study directory.
Each executed run now also preserves raw `solver_metadata`, including `inner_window_summaries`, so staged 100K+ audit slices can be reconstructed from the artifact JSON instead of relying on terminal-only traces.
The staged summary layer also promotes those window-level signals into `summary_by_config.*.inner_window_summary`, so audit consumers can read search-entry, seed-cost, commit-yield, and warm-start rejection patterns without manually folding raw per-window arrays.

## Instances

See [`instances/README.md`](instances/README.md) for the instance format and included files.
