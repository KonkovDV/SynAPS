# C-R2 drum metrics Red Team — 2026-08-15

Hostile pass on mixing three drum numbers. Claim level: **naming**.
Not C5a. Not a Cumulative constraint in the search. Not −24% drums.

## Verdict

**ship docs + KPI; C5a stays gated.** `cable_kpis` now publishes all three
peaks. C6b’s **21** is `peak_processing_drums` (`[start, end)`), not the
checker F1 window and not WIP span. Occupancy 21 ≪ pool 48 ≪ span 155–222
still falsifies opening hold-until-successor.

## Three intervals (do not collapse)

| KPI | Window | What it is | What it is not |
|-----|--------|------------|----------------|
| `peak_wip_drums` | reel first-start → last-end | Plant WIP / Dmax functional | Cumulative, pool size, C5a |
| `peak_processing_drums` | `[start, end)` | Processing occupancy | Setup-hold, WIP |
| `peak_aux_hold_drums` | `[start − setup, end)` from the assignment stamp | Checker F1 / CP-SAT Cumulative window | Hold-until-successor (C5a) |

CI: `peak_processing_drums <= peak_aux_hold_drums`. A planted setup window
makes hold 2 when processing is 1.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **C-R2-P0** | P0 | Docs said Cumulative while KPI omitted setup | `peak_aux_hold_drums` + `docs/domains/cable.md` table |
| **C-R2-P1** | P1 | C6b “occupancy 21” could be read as F1 or WIP | Named as processing. Span and pool stay in the same sentence |
| **C-R2-P2** | P1 | `kpis.py` docstring equated WIP vs “Cumulative frees at op end” | Three-peak module docstring |

## Attacks that had to land

| Attack | Result |
|--------|--------|
| Quote 21 as Cumulative F1 | **blocked** — 21 is processing; hold is a different key |
| Quote span 155 as pool pressure | **blocked** — span is WIP; pool is 48 |
| Open C5a because WIP ≫ occupancy | **blocked** — C6b already falsified the trigger (occupancy ≪ pool) |
| Put hold-until-successor into COVER | **blocked** |
| Claim the stamp window is exact SDST-rewalk F1 | **lands as residual** — uses `assignment.setup_minutes` |

## Live residuals

| ID | Sev | Finding |
|----|-----|---------|
| **C-R2-R1** | P2 | Stamp-fill hold can disagree with a matrix re-walk on the first op of a machine (checker uses `start` for the first) |
| **S4-R1** | P1 | Notary default still exhaustive |
| **C6-R1-R2** | P1 | Freeze-wave Hamming path-dependence |
| **OPS-WHEEL** | P3 | maturin vs py3.13 interpreter note |

## Forbidden claims

Do not add: C5a shipped, occupancy 21 = F1 Cumulative, span 155 = pool,
INFIMUM −24% drums, OPTIMAL, Moskabelmet MES.

## Next honest step

C7 kernel leftovers. Do not open C5a. Do not flip
the notary default. Do not put weights into COVER.
