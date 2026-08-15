# Nervous-month Red Team — 2026-08-14

Hostile pass on `synaps/domains/cable/nervous_month.py`, campaign gate fix,
CLI `cable-nervous-month`, and the measured 20 316-op month in
`CABLE_NERVOUS_MONTH_ACCEL_2026_08.md`. Claim level: **experiment**.

## Verdict

**ship with residuals.** The 16-machine month is a real `FEASIBLE` cover
(exhaustive notary empty, stabilize `converged=1`, no horizon clip). The
8-machine mix is also COVER-feasible (2026-08-15) with family flex +
6-colour wheel + continuation exhaust. Do not advertise a live factory
month, INFIMUM parity, or “repair is 10× faster”.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **N-P0-1** | P0 | Harsh month never actually solved | 1 600 parents → 20 316 ops, 96 WC, `RHC-GREEDY-COVER`, `feasible`, notary 0, stabilize converged, 9.362 s + 0.314 s notary |
| **N-P0-2** | P0 | Campaign `earliest_start` snapped to the **due** slot | Gate is now min release in `(state, due-slot)`, snapped down. Regression: `test_campaign_gate_is_release_not_due` |
| **N-P0-3** | P0 | Waves ran on an `error` cover | Waves skip unless cover is `feasible` and notary is empty |
| **N-P1-1** | P1 | C-R6 “no 5k–40k cable FEASIBLE pack” | This pack is 20 316 cable ops. Still not 500k, still not INFIMUM |
| **N-R1** | P1 | 8 machines/stage cannot cover this mix | **closed 2026-08-15**: family + wheel + exhaust stay → 20 316/20 316, 49.1 min/op, tardiness 87 134 |

## Live residuals (do not paper over)

| ID | Sev | Finding | Why it stays |
|----|-----|---------|--------------|
| **N-R2** | P1 | COVER still pays heavy SMED at 16/stage | 2.52e6 setup minutes under windowed ATCS. 8-stage exhaust stay cut this to 9.98e5 (49.1 min/op). |
| **N-R3** | P1 | Repair vs full is **not** “new rush order vs reschedule” | Waves re-dispatch existing high-priority ops. `full_resolve_s` re-covers the **same** instance. Speedup 1.77× (5.24 s vs 9.25 s). Neighbourhood 20–28 |
| **N-R4** | P1 | Wave 1 Hamming \(R=0\) | Freeze + greedy put the 20 ops back on the same `(wc, start)`. That is a no-move, not a proof of stability policy quality |
| **N-R5** | P1 | `peak_wip_drums=265` vs pool 96 | Processing Cumulative frees the drum at op end. C5a still gated. Same as C-R2 |
| **N-R6** | P2 | Seed=1 only | No distribution over seeds. Do not quote a confidence interval |
| **N-R7** | P2 | IncrementalRepair re-notaries all 20k ops | Honest, but it dominates repair wall time. Delta notary is A4, not shipped |
| **N-R8** | P2 | `temporal_stabilization_converged` is false on the GREED CI path | Metadata key is RHC-only. Tiny `--orders 6` uses `GREED` |
| **N-R9** | P2 | Colour-dedicated lines are not the 8-machine closer | Encoded as opt-in `--colour-lines`. At 8/stage they drop coverage to 0.854; the closer is wheel + exhaust stay, not cells |

## Attack attempts that did not land

- Mixing 499 770 ops / 145 s into this RFC: numbers are 20 316 / 9.362 s, different generator.
- Mixing INFIMUM 39k/40 min: stated as marketing, not a target.
- Claiming 8-machine FEASIBLE without exhaust stay: FIFO/ATCS-only still `error`; the closer is family + wheel + continuation exhaust.
- Dead public functions: `run_nervous_month` / `generate_nervous_month` / `nervous_sku_catalog` are exported and called from CLI.
- Architecture ratchet: new helpers ≤80; `run_nervous_month` 75; `cli.py::main` still within 130+10.
- AVX-512 / rayon / DRL: not introduced.
- `allow_freeze_break` default false on waves; rush cannot steal freeze-window starts.

## Forbidden claims (repeat)

Do not add: INFIMUM 39k/40 min, +78M RUB, Zhu −9.8% makespan, Prysmian drum −25%,
SynAPS 499770/145s as cable evidence, N-1, SAIDI, SOTA, “we replaced INFIMUM”,
“repair is an order of magnitude faster”, “8-machine FIFO is FEASIBLE”,
“Hamming 0 means the freeze is proven”.

## Next honest step

Multiseed 1..5 on 1600@8 with the exhaust-stay default, plus independent
exhaustive notary on that cover. Do not open C5a to make the month faster.
Plant/vendor OSINT ledger:
`docs/rfc/CABLE_MOSKABELMET_OSINT_REDTEAM_2026_08_15.md`.
