# Nervous-month cable benchmark and acceleration plan (August 2026)

- **Date:** 2026-08-14
- **Repo:** SynAPS standalone. Not GridPlan. Not live Moskabelmet MES.
- **Claim boundary:** one synthetic 30-day high-mix instance, seed=1, measured
  on this machine. Not INFIMUM 39k/40 min. Not 499 770-op GREEDY_COVER. Not SOTA.

## What was actually computed

CLI: `python -m synaps cable-nervous-month --orders 1600 --seed 1 --waves 4
--disruptions 20 --machines-per-stage 16 --drum-pool 96`

| Quantity | Value |
|----------|-------|
| Parent sales orders | 1 600 (15% rush, scattered releases, 36 SKUs shuffled) |
| Reels after 900 m pre-split | 3 386 |
| Operations (6 stages) | 20 316 |
| Work centers | 96 (16 per stage × 6) |
| Drum processing pool | 96 |
| Setup matrix entries | 120 960 |
| Horizon | 720 h (2026-08-01 UTC) |
| Solver | `RHC-GREEDY-COVER` (native Kolisch parallel SGS, ≥10k) |
| Status | `feasible` |
| Exhaustive notary hard violations | 0 |
| `temporal_stabilization.converged` | 1 |
| Generate | 0.971 s |
| Cover | 9.362 s (RHC wall 6 351 ms, 20 316/20 316, clipped=0) |
| Independent notary | 0.314 s |
| Makespan | 39 660 / 43 200 min |
| Setup minutes | 2 746 120 |
| Material loss (m) | 230 305 |
| Tardiness minutes | 134 224 |
| Peak WIP drums (`D_max` functional) | 265 |
| Processing drum pool | 96 |

Weekly freeze (72 h + 7 d × wave) + 20 high-priority re-dispatches, radius 4,
`allow_freeze_break=False`, `SolveRegime.RUSH_ORDER`. IncrementalRepair already
runs exhaustive notary on the full assignment list. No CP-SAT fallback.

| Wave | Freeze end (UTC) | Neighbourhood | Repair s | Status | Hamming \(R\) | Notes |
|------|------------------|---------------|----------|--------|---------------|-------|
| 0 | 2026-08-04 | 24 | 5.240 | feasible | 0.000640 | full re-cover 9.253 s, speedup 1.77× |
| 1 | 2026-08-11 | 20 | 5.105 | feasible | 0.000 | same `(wc, start)` for the 20 ops |
| 2 | 2026-08-18 | 24 | 5.978 | feasible | 0.000345 | |
| 3 | 2026-08-25 | 28 | 5.796 | feasible | 0.000197 | |

Waves re-queue **existing** high-priority ops after the freeze; they do not
insert new parent orders. Full re-cover is another solve of the **same**
instance, not a mutated rush dump.

## Overload row (same mix, smaller shop)

Same generator, 8 machines/stage, drum pool 48, seed=1:

| Orders | Ops | Cover | Coverage | Wall | Notes |
|--------|-----|-------|----------|------|-------|
| 1 600 | 20 316 | `error` | 0.503 after campaign fix (0.407 when campaign pinned `earliest_start` to the due slot) | ~15 s | horizon packed at 43 200 min, 10 104 leftover |
| 800 | 10 188 | `error` | 0.916 | ~4 s | still overflows |

16/stage is the measured COVER-feasible shop for this mix, not a claim that
Moskabelmet has 96 machines. 24/stage also `feasible` (11.45 s) — more
eligible machines, slower SGS, not a quality win.

ATCS `GREED` at 400 parents / 8 machines was **killed after 120 s with no
output**. Do not use Python ATCS as the month engine.

## Why setups ate the 8-machine shop

Processing load is modest: ~3.4k reels × ~2 h of stage time ≪ 8 machines ×
720 h. Parametric SMED is 240–400 min per colour/section/compound change.
Native list-schedule pops ready ops by `(floor, seq, uuid_rank)` and then
picks the earliest-end machine **including** SDST. It does **not** pick the
next ready op to keep the colour. Result at 16/stage: **2.75e6 setup minutes**
vs 96 × 720 h = 6.91e4 machine-hours (~66% of the calendar is changeover).
`peak_wip_drums=265` vs processing pool 96 is the C5a occupancy gap, not a
cover failure.

Campaign fix (2026-08-14): the gate is the earliest **release** in a
`(state, due-slot)` group, snapped down to 8 h. The previous snap-to-due
forbade starting until the due bucket and is a regression test in
`test_campaign_gate_is_release_not_due`.

## Acceleration plan (rank by measured bottleneck, August 2026 practice)

Do these in order. Iron rule: ML may only advise. No AVX-512. No rayon on the
main cover loop. No DRL as the factory engine. No vendoring dmorill GPL-3.

| Rank | Move | Why now | Practice analogue | Kernel? |
|------|------|---------|-------------------|---------|
| **A1** | Setup-aware ready selection inside native COVER (ATCS / IATCS log-score among ready ops, then earliest-end machine) | Setups are the 8-machine infeasibility and 66% of the 16-machine calendar. Python `GREED` ATCS already exists and **does not scale** to this month | Pinedo ATCS; ADVARIS “setup by diameter / colour / insulation”; Asprova insulation changeover | Yes — native `list_schedule.rs` ready-heap key. Red Team before merge |
| **A2** | Family-dedicated `eligible_wc_ids` (PVC vs XLPE lines) | Encode-first; cuts cross-family 400 min compound setups without touching SGS | Real cable shops do not run every SKU on every extruder | No |
| **A3** | Incremental machine/aux calendar in IncrementalRepair | Neighbourhood 20–28 ops, repair 5.1–6.0 s vs cover 9.4 s (only 1.77×). Cost is scanning 20k frozen assignments, not CP-SAT | Timefold 2.5 pin + `ProblemChange` + incremental score ([docs](https://docs.timefold.ai/timefold-solver/latest/responding-to-change/real-time-planning)); Zhu et al. *Processes* 14(5):769 (2026) VNS repair 18 h→0.83 h after construction | Yes, repair path only |
| **A4** | Delta notary on the neighbourhood ∪ affected machines | IncrementalRepair already re-checks the **full** 20k list (honest FEASIBLE). Standalone notary is 0.31 s; do not drop exhaustive notary on the **cover** claim | Timefold incremental score, not “skip the checker” | Yes, with a Red Team that a frozen-op miss is still P0 |
| **A5** | Colour-calendar campaign (per-family slot phase) **or** keep freeze as the L-RHO analogue | L-RHO (arXiv:2502.15791, 2025) fixes stable machine assignments, up to 54% vs naïve RHO. Graph-RHO (arXiv:2604.10073, 2026) GNN + adaptive threshold, >30% on 2k-op benches. SynAPS already **policy-fixes** issued starts (`frozen_ids_for_repair`). A GNN is optional advice, not the engine | Moskabelmet 3-day freeze; ADVARIS look-ahead / what-if; Timefold pinning | Campaign = no. GNN = advisory sidecar only |
| **A6** | C5a hold-until-successor | Quality (`D_max` 265 vs pool 96), **not** first-line speed | Plant drums stay in WIP; Prysmian Alesea/Aucxis is visibility, not APS | Gated C5 |

Out of scope for speed: GPU GA, AVX-512, DRL factory policy, 500k synthetic
coverage numbers, INFIMUM marketing, GREED ATCS at ≥10k.

## How this sits vs August 2026 products

ADVARIS (2026 public copy) says a cable APS can put “several thousand orders”
into finite-capacity detail in “a few minutes”. This run is 1 600 parents /
20 316 ops in **9.4 s construction**, which is the same *time class* for a
list-schedule, not a bake-off and not setup-optimal sequencing. INFIMUM 39k/40 min
remains unpublished algebra. There is still no OSS cable APS.

## Reproduce

Tiny (CI): `python -m synaps cable-nervous-month --orders 6 --waves 1 --disruptions 2 --machines-per-stage 2 --drum-pool 24`

Full (local): command at the top of this note. JSON under `benchmark/results/`
is gitignored; this RFC is the tracked evidence.
