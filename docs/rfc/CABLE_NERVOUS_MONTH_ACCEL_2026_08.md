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

## A1/A2/A5 measured outcome (2026-08-14, seed=1, this machine)

Cover probes on the 1 600-order month (colour phase on, family split off
unless noted). `error` = cover could not place all ops before the horizon;
fallback repair stopped at the coverage deadline.

| Shop | Ready rule | Status | Placed | Wall | Setup min |
|------|-----------|--------|--------|------|-----------|
| 16/stage, pool 96 | FIFO (default) | **feasible** | 20 316/20 316 | 9.25 s | 2 651 760 |
| 16/stage, pool 96 | ATCS k1=2.0 k2=0.5 | error | 13 033 | 185.9 s | 1 724 320 |
| 16/stage, pool 96 | ATCS k1=50 k2=0.1 | error | 14 138 | 194.4 s | 2 000 440 |
| 16/stage, pool 96 | ATCS k1=200 k2=0.05 | error | 14 145 | 183.1 s | 1 642 120 |
| 16/stage, pool 96, family lines | FIFO | error | 18 811 | 14.2 s | — |
| 8/stage, pool 48 | FIFO | error | 9 755 (0.480) | 22.5 s | 1 758 640 |
| 8/stage, pool 48 | ATCS k1=2.0 | error | 11 388 (0.561) | 167.1 s | 1 084 880 |

Findings:

1. **A1 is falsified as the month cover rule.** ATCS collapses coverage
   (100% → 62–70% placed) at every k tested. Root cause is topological, not
   parametric: the cover is an append-only non-delay SGS, so an
   out-of-floor-order pick jumps a machine tail to the picked op's release
   floor and strands the capacity behind it; the drum pool is then held
   across the gap and blocks successors. At month scale the slack term
   (`cap` up to 43 200 min vs `p_bar` ≈ 130) also dwarfs the setup term at
   classic k1 ≈ 2, degenerating ATCS to EDD. Per-op setup among placed ops
   does drop (~116 vs ~130 min/op) — the scoring works, the cover topology
   does not admit it. ATCS stays as an opt-in flag
   (`--cover-ready-rule atcs`, Python/native parity, unit-tested); FIFO
   remains the default everywhere. A windowed ATCS (score only among ops
   whose floor ≤ current min tail) is future work, not this wave.
2. **A2 family-dedicated lines are infeasible at 16/stage**: the PVC/XLPE
   split halves per-family capacity while XLPE serves ⅔ of the mix → 1 505
   ops unscheduled even under FIFO. Shipped as opt-in (`--family-lines`),
   default off. Would need a sized split (e.g. 6/10) tuned to the mix.
3. **A5 colour phase is a measurable win at zero cost**: same shop, FIFO —
   tardiness 134 224 → 40 580 min, peak WIP drums 265 → 183, setup
   2 746 120 → 2 651 760, makespan 39 660 → 38 315. Default on;
   `--no-colour-phase` recovers the 2026-08-14 baseline.
4. **1 600 @ 8 stays infeasible under both rules** (best coverage 0.561).
   The 8-machine shop needs a capacity or quality lever (S6 gate), not a
   ready rule.

Full default month (1 600 @ 16, FIFO, colour, `--new-rush 2`, 4 waves):
cover 9.25 s, exhaustive notary 0.77 s with 0 hard violations,
`temporal_stabilization_converged=1`; new-parent rush insert repair 3.9 s
vs full re-solve 10.7 s on the **mutated** instance (2.75×, N-R3); four
reshuffle waves repair 6.1–7.4 s vs full 10.9 s. Total CLI wall ≈ 66 s.

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

| Rank | Move | Outcome (2026-08-14) | Kernel? |
|------|------|----------------------|---------|
| **A1** | ATCS ready pop in native COVER | **Falsified as month cover.** Coverage 100% → 62–70% at k1∈{2,50,200}. Flag ships opt-in; FIFO stays default. Windowed ATCS is future work. | Yes — shipped, not default |
| **A2** | Family-dedicated `eligible_wc_ids` | **Infeasible at 16/stage** (even split, XLPE ⅔ of mix). Opt-in `--family-lines`. Needs mix-sized split. | No |
| **A3** | Incremental aux calendar in IncrementalRepair | `MachineIndex.add` appends aux windows; `extend(frozen)` instead of per-row add. Wave repair 6.1–7.4 s vs cover 9.25 s (still ~1.4×, not <1 s). | Repair path |
| **A4** | Delta notary | **Not shipped.** One drum pool ⇒ neighbourhood slice == full occupancy. Exhaustive remains default. | — |
| **A5** | Colour-phase campaign | **Default on.** Tardiness 134 224 → 40 580; peak WIP 265 → 183; setup 2.75e6 → 2.65e6. `--no-colour-phase` recovers baseline. | No |
| **A6** | C5a hold-until-successor | Still gated. 1600@8 infeasible under FIFO (0.480) and ATCS (0.561). | Gated C5 |

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
