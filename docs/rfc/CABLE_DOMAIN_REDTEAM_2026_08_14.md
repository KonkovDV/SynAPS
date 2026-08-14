# Cable domain Red Team — 2026-08-14

Hostile pass on the encode-first Moskabelmet drop (`synaps/domains/cable/*`,
`planning_policy.py`, IncrementalRepair freeze, `RepairRequest` fields).
Claim level: **experiment**. Not live-factory. Not INFIMUM. Not C5.

## Verdict

**ship with residuals.** C0–C3 and freeze neighbourhood subtraction are real
and tested. C4 is a named scalar, not a search objective. C5 remains gated.
Do not advertise “SynAPS now plans Moskabelmet”.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **C-P0-1** | P0 | Cable physics only in docs | Adapter writes `p=ceil(L/v)`, reel pre-split, SKU SDST, drum aux, generator, GREEDY `FEASIBLE` + empty exhaustive notary (`tests/test_domain_cable.py`, `python -m synaps cable-demo`) |
| **C-P0-2** | P0 | 3-day freeze was RHC intra-solve only | `frozen_ids_for_repair` subtracts issued starts from IncrementalRepair neighbourhood; rush cannot steal; breakdown of that op still can |
| **C-P1-1** | P1 | `Order.quantity` unused | Adapter still writes `base_duration_min`; quantity stored as metres for PDM round-trip, kernel unchanged (honest) |
| **C-P1-2** | P1 | Hamming formula `\|△\|/\|old\|` on tuples exceeded 1 | Rewritten as share of baseline ops whose `(wc, start)` moved, in `[0,1]` |
| **C-P2-1** | P2 | Catalog had 8 domains | Domain 9 + `schema/examples/cable.json` |
| **C-R6** | P2 | No 5k–40k cable FEASIBLE pack | Closed 2026-08-14: nervous-month 20 316 ops. `CABLE_NERVOUS_MONTH_REDTEAM_2026_08_14.md` |

Evidence: `tests/test_domain_cable.py` + `tests/test_architecture.py` (ratchet) +
`tests/test_incremental_repair.py` + `tests/test_contracts.py` + CLI demo
3 parent orders → 5 reels / 20 ops, `feasible`, notary 0, `peak_wip_drums=2`.

## Live residuals (do not paper over)

| ID | Sev | Finding | Why it stays |
|----|-----|---------|--------------|
| **C-R1** | P1 | `CABLE_PVC_WEIGHTS` is not used by GREEDY/ATCS construction | Wiring it into list-schedule would change universal default behaviour. Pass `objective_weights` into CP-SAT/ALNS when you actually search. Test only proves scalarize ranking. |
| **C-R2** | P1 | `peak_wip_drums` is a schedule functional, not a Cumulative constraint | Processing aux frees the drum at op end. Plant WIP holds until the next stage. C5a. Demo: pool ≫ 2 while Dmax=2 on a tiny instance — gap will grow with chain slack. |
| **C-R3** | P1 | Freeze does not apply to `solve_schedule` | Issued-plan lock is a *repair* policy. A first GREEDY plan can still interleave colours. |
| **C-R4** | P2 | Campaign windows only snap `earliest_start` | Not INFIMUM lot combining. Cross-order predecessors still illegal. |
| **C-R5** | P2 | Setup minutes are parametric, not plant SMED | 240/360/400 min are order-of-magnitude vs MAPRE hundreds of minutes, not a dump. |
| **C-R7** | P2 | `allow_freeze_break` is a boolean, not an ACL | A client can always set it true. Policy, not cryptography. |
| **C-R8** | P2 | Blocking / no-wait / AMR / RFID drums | PyJobShop class, Processes 2025 AMR, Prysmian Alesea — out of kernel. |

## Attack attempts that did not land

- Neighbourhood freeze forgotten on the virtualized `max_parallel` path: freeze runs inside `_solve_core` after virtualization maps assignments; op ids stay the same.
- Empty `disrupted_op_ids` + freeze legalizing a forged base: still refused by `repair_schedule` (RT-20 / A15-P0-5).
- Architecture ratchet: `_solve_core` 260 ≤ 253+10; `main` 133 ≤ 130+10; new helpers ≤ 80.
- Public dead functions: cable surface is imported from `synaps/domains/cable/__init__.py` and called from CLI / IncrementalRepair.

## Forbidden claims (repeat)

Do not add: INFIMUM 39k/40 min, +78M RUB, 27 days, Zhu −9.8% makespan, Prysmian drum −25%, SynAPS 499770/145s, N-1, SAIDI, SOTA, “we replaced INFIMUM”.

## Next honest step

Measure `peak_wip_drums` vs processing-aux peak on a 5k cable instance. Open C5a only if C4 weights + freeze cannot move Dmax. Nervous-month 20 316-op pack is done (`D_max=265` vs pool 96).
