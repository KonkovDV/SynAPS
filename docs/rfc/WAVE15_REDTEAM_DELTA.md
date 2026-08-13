# Wave 15 Red Team Delta — 2026-08-13

> Algebra status theorem, not a new solver. Claim level: **experiment**.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **A15-P0-1** | P0 | RHC claimed `FEASIBLE` when `scheduled_count == total_ops`, without a final `FeasibilityChecker` | `finalize_rhc_claim_status`: proven hard violations ⇒ `ERROR`; metadata `notary_hard_violation_*` |
| **A15-P0-4** | P0 | Stabilize hit `max_passes` with residual shifts and RHC still said `FEASIBLE` | `stabilize_temporal_consistency` returns `converged`; RHC requires `converged==1` |
| **A15-P0-5** | P0 | `repair_schedule(..., disrupted_op_ids=[])` would legalize a forged base | `_repair_merged_kwargs` refuses empty disruption (after the RT-20 identity-kwargs guard) |

Probes: `tests/test_algebra_rt15_probes.py`. Prior RT-20 probes remain green.

**Theorem (RHC, this commit):**  
`status == FEASIBLE ⇒ proven_hard_violations(check(problem, assignments)) = ∅`  
and temporal stabilization converged. Coverage alone is not feasibility.

Portfolio `solve_schedule(..., verify_feasibility=True)` already raised `PortfolioValidationError` on a dirty notary; this closes the **direct** `RhcSolver().solve` path that GridPlan does not always wrap.

## Left honest (do not claim closed)

| ID | Why it stays open |
|----|-------------------|
| **A15-P0-2** | ALNS/RHC predecessor-clear vs frozen succ-before-pred. Needs restored-graph check or never clearing those edges. Separate composition patch. |
| **A15-P0-3** | ALNS `_has_machine_overlap` vs frozen is not setup-aware (`end_frozen == start_free` with setup>0). |
| **A15-P1-1…10** | Router `exact_required`, CPSAT-30 name vs clamp, ALNS tier shadowing, replay fields, stabilize of committed windows, fan-in DAG. |
| **P2** | Wall-clock ALNS/RHC nondeterminism; native greedy `eligible=[]` vs all; accel OR-mask. |

ALNS already demotes to `ERROR` when its own final `FeasibilityChecker` is nonempty (unlike RHC before this pass).

## GridPlan pairing

GridPlan 0.1.12 pins this SynAPS commit. Domain-layer RT-21 (G7–G15) lives in the GridPlan repo: notary `release_date` / `eligible_crew_ids` / `SHORT_DURATION`, FIFO freeze pin, `job.priority`, replan job-set identity. G11 last-window-wins remains residual.

Not N-1. Not SAIDI. Heuristics never `OPTIMAL`.
