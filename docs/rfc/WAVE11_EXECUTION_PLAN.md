# Wave 11 execution plan — Hyper Red Team fix pack

- **Inputs:** `HYPER_REDTEAM_AUDIT_2026_08_11.md`
- **Date:** 2026-08-11

## Priority order

| Step | ID | Exit criteria |
|---|---|---|
| 11.1 | C2 | IncrementalRepair never FEASIBLE with unrepaired ops |
| 11.2 | C1 | CP-SAT fallback receives frozen constraints |
| 11.3 | H1 | `proven_hard_violations` demotes only unproven WCs |
| 11.4 | H3 | ALNS cost uses `DEFAULT_WEIGHTS` + material alias |
| 11.5 | H2 | IncrementalRepair refuses `max_parallel>1` loudly |
| 11.6 | H4+H5 | Router catches ValueError; SolveOptions rejects OOB limits |
| 11.7 | M1 | LBBD applicator rejects `setup_cost`/`machine_tsp` |
| 11.8 | Verify + commit + push | Focused green + audit delta |

## Non-goals

Native ABI, GPL pack, RHC mega-decompose, TOU energy.
