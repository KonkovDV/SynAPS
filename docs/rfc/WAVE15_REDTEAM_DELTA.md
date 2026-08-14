# Wave 15 Red Team Delta — 2026-08-13

> Algebra status theorem, not a new solver. Claim level: **experiment**.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **A15-P0-1** | P0 | RHC claimed `FEASIBLE` when `scheduled_count == total_ops`, without a final `FeasibilityChecker` | `finalize_rhc_claim_status`: proven hard violations ⇒ `ERROR`; metadata `notary_hard_violation_*` |
| **A15-P0-2** | P0 | ALNS cleared pred + offset path dead without `horizon_start` | Pass `horizon_start` + offsets at every `_violates_frozen_precedence` site; merge frozen context ops into `ops_by_id` |
| **A15-P0-3** | P0 | ALNS `_has_machine_overlap` vs frozen ignored SDST | Optional setup-aware gap; wired on accept / repair lanes |
| **A15-P0-4** | P0 | Stabilize hit `max_passes` with residual shifts and RHC still said `FEASIBLE` | `stabilize_temporal_consistency` returns `converged`; RHC requires `converged==1` |
| **A15-P0-5** | P0 | `repair_schedule(..., disrupted_op_ids=[])` would legalize a forged base | `_repair_merged_kwargs` refuses empty disruption (after the RT-20 identity-kwargs guard) |
| **A15-P1-1** | P1 | `exact_required` lost to INTERACTIVE / latency≤1 | Exact branch runs first |
| **A15-P1-2** | P1 | CPSAT-30 name vs clamp | `effective_time_limit_s` next to `solver_time_limit_s`; config name unchanged |
| **A15-P1-3** | P1 | ALNS-300 shadowed ALNS-500 at 5k@400s | Check the 300s/ALNS-500 tier first |
| **A15-P1-4** | P1 | Replay top-level `feasible` followed solver status | `feasible == verification.feasible` (False when not performed) |
| **A15-P1-5** | P1 | Replay missing seed / kwargs fingerprint | `random_seed` + `config_fingerprint` on runtime/benchmark artifacts |
| **A15-P1-6** | P1 | Final RHC stabilize moved earlier windows | `immutable_op_ids` = ops committed before the last window |
| **A15-P1-7** | P1 | Commit precedence gate off outside SEARCH_COVER | Covered by P0-1 final notary |
| **A15-P1-8** | P1 | Offset path dead without horizon | Same close as P0-2 |
| **A15-P1-9** | P1 | Soft resource wall vs search box | `search_time_limit_is_solver_box`; resource `timeout_s` is a separate wall |
| **A15-P1-10** | P1 | SynAPS Operation is a chain | GridPlan fan-in already fail-closed in the notary; no ingest reject (would break legal multi-pred jobs) |
| **A15-P2** | P2 | Wall-clock ALNS/RHC; native greedy `eligible=[]` vs all; accel OR-mask; advisory swallow | Native CSR expands empty eligible to all WCs; empty CSR fail-closed (no machine-0 + 1e6). `native_available` / `native_module` share the full-kernel OR (includes greedy_repair). ALNS/RHC publish `wall_clock_path_dependent` + `determinism_violated` when wall stops a strict run. Unknown ML solver name is stamped on the routing reason. |
| **W16b-1** | P0 | `proven_hard_violations` demoted setup gaps on unproven lanes → false-FEASIBLE | Demotion removed; `LANE_INFERENCE_UNPROVEN` now surfaces as a hard violation making the claim UNKNOWN. |
| **W16b-3** | P1 | RHC `_evaluate_final` was lane-blind and undercounted tardiness for unscheduled orders | Delegates to `synaps.objective.evaluate` (lane-aware setup, horizon-anchored tardiness). |
| **W16-C6** | P0 | Native `greedy_repair` silently rejected after window 1 (`UNKNOWN_OPERATION` on frozen extras) and was aux-blind | Skip aux/parallel; filter UNKNOWN on extra-ops; record `validation_failed`. |
| **W16-C2/3** | P0 | Stabilize created aux/horizon violations | Ceiling guard + aux relocate; chain-depth pass budget. |
| **W16-C4** | P0 | Reanchor aux-blind vs committed reservations | Fail closed when merged schedule is aux-dirty. |
| **W16-C5** | P1 | ALNS accept ignored aux | `_overlap` includes aux sweep; native seed skipped when aux/parallel. |
| **W16-C7** | P1 | IncrementalRepair ERROR on `max_parallel>1` | Lane virtualization + unroll. |
| **W16-C8/10** | P1 | Horizon extension claimed FEASIBLE; notary vs oracle skew | Placement may extend; claim uses original horizon + `exhaustive=True`. |
| **W16-C11** | P0 | ALNS `_reanchor_against_frozen` `while True` on stacked frozen extra-ops (float dust / first-hit blocker) hung full pytest ~37% | Bounded loop; jump by `max` overlapping end; abort if earliest-start does not increase |
| **W16-C13** | P1 | `test_accelerators` fake-`synaps_native` left kernels None for later files | Restore real extension + reload accelerators after each poison test |
| **W16-C14** | P0 | GREEDY_COVER list-schedule ignored `Operation.latest_finish`; G11 outage windows could park past the declared finish while gap-fill already refused | Cap `_delay_start_for_aux` at `min(horizon, latest_finish)` |
| **W16-C15** | P1 | Router auto-selected `RHC-ALNS` / `RHC-ALNS-100K` at 60k/100k@>600s — search-entry profiles, not the 50k-FEASIBLE cover path | Auto-route those budgets to `RHC-GREEDY-COVER`; named ALNS profiles stay in the registry |
| **W16-C16** | P1 | Residual gap-fill after 100k list-schedule hung: 100k `MachineIndex.add` insorts + every gap scanned every aux occupancy | `MachineIndex.extend` bulk-load; `_candidate_starts` bisects `ends_sorted` |
| **W16-C17** | P1 | Non-delay append left idle holes; leftover chains waited for quadratic residual | On tail failure, insertion SGS (`select_earliest_horizon_slot`) in the same ready-queue pass |

Probes: `tests/test_algebra_rt15_probes.py`. Prior RT-20 probes remain green.

**Theorem (RHC, this commit):**  
`status == FEASIBLE ⇒ proven_hard_violations(check(problem, assignments)) = ∅`  
and temporal stabilization converged. Coverage alone is not feasibility.

Portfolio `solve_schedule(..., verify_feasibility=True)` already raised `PortfolioValidationError` on a dirty notary; this closes the **direct** `RhcSolver().solve` path that GridPlan does not always wrap.

ALNS already demotes to `ERROR` when its own final `FeasibilityChecker` is nonempty.

Do not claim bitwise-identical ALNS/RHC under a wall-clock timeout: remaining repair budget still depends on `time.monotonic()`. The P2 close makes that visible (`wall_clock_path_dependent`) instead of leaving it as an implicit seed contract.

## GridPlan pairing

GridPlan pairs this SynAPS tree: G11 per-op outage windows (`Operation.earliest_start` / `latest_finish`, Order = union), notary for `shift_calendar` / `availability` / `safety_constraints` / `service_area`, travel default 30 removed (empty matrix = 0; partial matrix fail-closed).

Not N-1. Not SAIDI. Heuristics never `OPTIMAL`.
