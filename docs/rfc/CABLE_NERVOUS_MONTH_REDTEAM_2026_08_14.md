# Nervous-month Red Team — 2026-08-14

Hostile pass on `synaps/domains/cable/nervous_month.py`, campaign gate fix,
CLI `cable-nervous-month`, and the measured 20 316-op month in
`CABLE_NERVOUS_MONTH_ACCEL_2026_08.md`. Claim level: **experiment**.

## Verdict

**ship with residuals.** The 16-machine month is a real `FEASIBLE` cover
(exhaustive notary empty, stabilize `converged=1`, no horizon clip). Do not
advertise a live factory month, INFIMUM parity, or “repair is 10× faster”.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **N-P0-1** | P0 | Harsh month never actually solved | 1 600 parents → 20 316 ops, 96 WC, `RHC-GREEDY-COVER`, `feasible`, notary 0, stabilize converged, 9.362 s + 0.314 s notary |
| **N-P0-2** | P0 | Campaign `earliest_start` snapped to the **due** slot | Gate is now min release in `(state, due-slot)`, snapped down. Regression: `test_campaign_gate_is_release_not_due` |
| **N-P0-3** | P0 | Waves ran on an `error` cover | Waves skip unless cover is `feasible` and notary is empty |
| **N-P1-1** | P1 | C-R6 “no 5k–40k cable FEASIBLE pack” | This pack is 20 316 cable ops. Still not 500k, still not INFIMUM |

## Live residuals (do not paper over)

| ID | Sev | Finding | Why it stays |
|----|-----|---------|--------------|
| **N-R1** | P1 | 8 machines/stage cannot cover this mix | 1 600@8 → coverage 0.50 `error`; 800@8 → 0.92 `error`. Default CLI is 16/stage because that is the measured COVER-feasible shop, not because the plant has 96 machines |
| **N-R2** | P1 | COVER pays SMED on almost every colour | 2.75e6 setup minutes at 16/stage. Native heap order is `(floor, seq, uuid_rank)`, not ATCS. Python `GREED` hung at 400 parents / 8 machines (>120 s, no result) |
| **N-R3** | P1 | Repair vs full is **not** “new rush order vs reschedule” | Waves re-dispatch existing high-priority ops. `full_resolve_s` re-covers the **same** instance. Speedup 1.77× (5.24 s vs 9.25 s). Neighbourhood 20–28 |
| **N-R4** | P1 | Wave 1 Hamming \(R=0\) | Freeze + greedy put the 20 ops back on the same `(wc, start)`. That is a no-move, not a proof of stability policy quality |
| **N-R5** | P1 | `peak_wip_drums=265` vs pool 96 | Processing Cumulative frees the drum at op end. C5a still gated. Same as C-R2 |
| **N-R6** | P2 | Seed=1 only | No distribution over seeds. Do not quote a confidence interval |
| **N-R7** | P2 | IncrementalRepair re-notaries all 20k ops | Honest, but it dominates repair wall time. Delta notary is A4, not shipped |
| **N-R8** | P2 | `temporal_stabilization_converged` is false on the GREED CI path | Metadata key is RHC-only. Tiny `--orders 6` uses `GREED` |
| **N-R9** | P2 | Family lines / colour calendar not encoded | Accel A2/A5. 36 SKUs still eligible on every machine of the stage |

## Attack attempts that did not land

- Mixing 499 770 ops / 145 s into this RFC: numbers are 20 316 / 9.362 s, different generator.
- Mixing INFIMUM 39k/40 min: stated as marketing, not a target.
- Claiming FEASIBLE on the 8-machine overload: CLI now skips waves; report status stays `error`.
- Dead public functions: `run_nervous_month` / `generate_nervous_month` / `nervous_sku_catalog` are exported and called from CLI.
- Architecture ratchet: new helpers ≤80; `run_nervous_month` 75; `cli.py::main` still within 130+10.
- AVX-512 / rayon / DRL: not introduced.
- `allow_freeze_break` default false on waves; rush cannot steal freeze-window starts.

## Forbidden claims (repeat)

Do not add: INFIMUM 39k/40 min, +78M RUB, Zhu −9.8% makespan, Prysmian drum −25%,
SynAPS 499770/145s as cable evidence, N-1, SAIDI, SOTA, “we replaced INFIMUM”,
“repair is an order of magnitude faster”, “8-machine shop is FEASIBLE”,
“Hamming 0 means the freeze is proven”.

## Next honest step

A1 (ATCS ready key in native COVER) on the **same** 1 600@8 instance. Success is
`feasible` at 8/stage with notary empty, or a written fail that setups still
overflow. Do not open C5a to make the month faster.
