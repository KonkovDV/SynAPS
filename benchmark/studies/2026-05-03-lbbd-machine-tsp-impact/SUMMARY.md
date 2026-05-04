# LBBD machine_tsp cut — empirical impact

**Date:** 2026-05-03  
**Audit ID:** R5  
**Solver config:** time_limit_s=20, max_iterations=10, random_seed=42, setup_relaxation=False  

Each instance was solved twice with the only varying input being
`enable_machine_tsp_cuts`. The baseline reuses the legacy
sequence-independent `setup_cost` floor; the experimental run prefers
the Bellman-Held-Karp `machine_tsp` bound when it applies.

## Headline metrics

| Instance | Config | LB | UB | Gap | Iter | Wall (s) | Cuts | Skipped dup |
|---|---|---:|---:|---:|---:|---:|---|---:|
| medium_stress_20x4 | baseline_without_tsp | 183.00 | 183.00 | 0.0000 | 2 | 3.496 | capacity=1, critical_path=1, load_balance=1, setup_cost=2 | 0 |
| medium_stress_20x4 | with_machine_tsp | 183.00 | 183.00 | 0.0000 | 2 | 3.453 | capacity=1, critical_path=1, load_balance=1, machine_tsp=2 | 0 |
| medium_4state_tsp_dominance_16x4 | baseline_without_tsp | 262.00 | 262.00 | 0.0000 | 2 | 4.236 | capacity=1, critical_path=1, load_balance=1, setup_cost=2 | 0 |
| medium_4state_tsp_dominance_16x4 | with_machine_tsp | 260.00 | 260.00 | 0.0000 | 2 | 4.244 | capacity=1, critical_path=1, load_balance=1, machine_tsp=2 | 0 |

## Per-iteration master LB trajectory

### medium_stress_20x4 — baseline_without_tsp

- **lb_evolution:** 138.33, 183.00
- **cut_kind_lb_contribution:** capacity=8.93, critical_path=8.93, load_balance=8.93, master_relaxation=138.33, setup_cost=17.87

### medium_stress_20x4 — with_machine_tsp

- **lb_evolution:** 138.33, 183.00
- **cut_kind_lb_contribution:** capacity=8.93, critical_path=8.93, load_balance=8.93, machine_tsp=17.87, master_relaxation=138.33

### medium_4state_tsp_dominance_16x4 — baseline_without_tsp

- **lb_evolution:** 164.55, 262.00
- **cut_kind_lb_contribution:** capacity=19.49, critical_path=19.49, load_balance=19.49, master_relaxation=164.55, setup_cost=38.98

### medium_4state_tsp_dominance_16x4 — with_machine_tsp

- **lb_evolution:** 164.55, 260.00
- **cut_kind_lb_contribution:** capacity=19.09, critical_path=19.09, load_balance=19.09, machine_tsp=38.18, master_relaxation=164.55

## Reading the table

- **LB / UB / Gap** are the final master lower bound, best feasible upper
  bound, and `(UB - LB) / max(UB, eps)` reported by the solver.
- **lb_evolution** is the master LB after each iteration's HiGHS solve.
- **cut_kind_lb_contribution** attributes each iteration's positive
  ΔLB to the cut kinds added in the previous iteration; mixed-kind
  iterations split the delta equally.
- **Skipped dup** counts cuts suppressed by the R3 fingerprint dedup.

Reproduce: `python benchmark/studies/2026-05-03-lbbd-machine-tsp-impact/run.py`.
