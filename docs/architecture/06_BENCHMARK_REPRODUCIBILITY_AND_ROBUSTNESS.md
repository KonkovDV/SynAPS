# 06. Benchmark Reproducibility And Robustness

## Purpose

This document defines a reproducible benchmark protocol for large-scale SynAPS studies,
with explicit robustness and quality-gate criteria.

## Scope

Applies to:

- `benchmark/study_rhc_50k.py`
- `benchmark/study_rhc_alns_doe.py`
- RHC-ALNS evaluation lanes (`throughput`, `strict`)

## Reproducibility Lanes

Two execution lanes are maintained to separate throughput behavior from strict replay behavior.

1. `throughput`
- intended for operational benchmarking
- multi-worker CP-SAT in hybrid repair (`num_workers = 4`)

2. `strict`
- intended for deterministic replay and scientific comparison
- single-worker CP-SAT in hybrid repair (`num_workers = 1`)
- fixed random seeds for RHC, ALNS inner loop, and hybrid CP-SAT calls

When `lane = both`, both lanes are executed per seed and summarized independently.

## Robustness Metrics

For each solver summary we report central and tail statistics.

- Mean and median makespan
- IQR for makespan and wall time
- Empirical CVaR for makespan and inner fallback ratio

Definition used in SynAPS:

$$
\text{CVaR}_{\alpha}(X) = \mathbb{E}[X \mid X \geq \text{VaR}_{\alpha}(X)]
$$

with default `alpha = 0.95`.

## Quality Gate

Each solver summary receives a multi-criterion gate verdict:

1. Feasibility check
- `feasibility_rate == 1.0`

2. Fallback pressure check
- `mean_inner_fallback_ratio <= max_inner_fallback_ratio`

3. Objective degradation check
- against baseline solver (default `RHC-GREEDY`)
- `mean_makespan / baseline_mean_makespan <= max_makespan_degradation_ratio`

The gate passes only if all checks pass.

## DOE Sweep

`benchmark/study_rhc_alns_doe.py` performs bounded grid search over:

- `hybrid_due_pressure_threshold`
- `hybrid_candidate_pressure_threshold`
- `hybrid_max_ops`
- `sa_due_alpha`
- `sa_candidate_beta`

Configurations are ranked by:

1. gate pass status
2. feasibility rate
3. mean makespan
4. mean inner fallback ratio

## Recommended Workflow

1. Run lane study:

```bash
python -m benchmark.study_rhc_50k --preset industrial-50k --lane both --seeds 1 2 3
```

2. Run DOE sweep:

```bash
python -m benchmark.study_rhc_alns_doe --lane strict --seeds 1 2 3 --max-combinations 24
```

3. Promote candidate profile only if quality gate passes in strict lane.

## External References

1. OR-Tools CP-SAT solver docs and solver-limit guidance:
- https://developers.google.com/optimization/cp/cp_solver
- https://developers.google.com/optimization/cp/cp_tasks

2. OR-Tools SAT parameter surface:
- https://github.com/google/or-tools/blob/stable/ortools/sat/sat_parameters.proto

3. Robust tail-risk objective:
- Rockafellar, R.T., Uryasev, S. (2000), Optimization of Conditional Value-at-Risk.

4. Property-based verification strategy:
- https://hypothesis.readthedocs.io/en/latest/
