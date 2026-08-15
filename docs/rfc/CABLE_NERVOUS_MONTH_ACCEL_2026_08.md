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

## A1 windowed ATCS + mix-sized family (2026-08-15, seed=1, this machine)

Unbounded ATCS jumped later-ready ops and collapsed coverage. Cover ATCS
now scores only inside the current non-delay floor class
(`floor <= min(ready floors) + 0`). Same-floor ATCS still prefers zero
setup (unit test). Native ABI adds optional `floor_window` (default 0).

Family lines are sized by SKU-catalog share (nervous mix 12 PVC / 24 XLPE
→ ~1/3 of machines), not 50/50.

Cover-only probes, colour phase on, `time_limit_s=45`:

| Shop | Rule | Family | Status | Wall | Setup min | Tardiness | Peak WIP |
|------|------|--------|--------|------|-----------|-----------|----------|
| 16/stage, pool 96 | FIFO | off | **feasible** | 7.6 s | 2 636 200 | 16 588 | 159 |
| 16/stage, pool 96 | ATCS windowed | off | **feasible** | 8.9 s | 2 518 440 | 1 922 | 94 |
| 16/stage, pool 96 | FIFO | mix-sized | **feasible** | 5.6 s | 2 511 240 | 26 647 | 113 |
| 16/stage, pool 96 | ATCS windowed | mix-sized | **feasible** | 6.8 s | 2 488 800 | 24 227 | 100 |
| 8/stage, pool 48 | FIFO | off | error | 11.8 s | — | — | coverage 0.496 |
| 8/stage, pool 48 | ATCS windowed | off | error | 12.6 s | — | — | coverage 0.525 |
| 8/stage, pool 48 | FIFO | mix-sized | error | 7.3 s | — | — | coverage 0.554 |

Nervous-month COVER default is windowed ATCS (CLI / `run_nervous_month`).
Registry `RHC-GREEDY-COVER` stays FIFO so 50k/500k cover does not change.
Family lines stay opt-in at 16/stage: mix-sized is feasible but tardiness
is worse than ATCS-only. 1600@8 under this A1-only table was infeasible
(best coverage 0.554); exhaustive stay closed it later in this RFC.
Peak WIP 94 vs drum pool 96 is a cover-only KPI, not a C5a close.

Full default month (1 600 @ 16, FIFO, colour, `--new-rush 2`, 4 waves):
cover 9.25 s, exhaustive notary 0.77 s with 0 hard violations,
`temporal_stabilization_converged=1`; new-parent rush insert repair 3.9 s
vs full re-solve 10.7 s on the **mutated** instance (2.75×, N-R3); four
reshuffle waves repair 6.1–7.4 s vs full 10.9 s. Total CLI wall ≈ 66 s.

## Algebra, papers, and the 8-machine residual (2026-08-15)

Processing on the 1 600-order month is 385 818 min. An 8/stage calendar is
2 073 600 min → 19% utilisation if setups were free. Minutes left for
setups: ~1.69e6. To place all 20 316 ops the mean setup must be **≤83 min/op**.
Observed ~175 min/op on the ops that fit under FIFO, ~99 min/op under
family+wheel — still above the 83 min budget. This is a changeover problem,
not a raw machine-hour shortage.

C5a hold-until-successor occupies drums longer; it does not add those
1.69e6 setup minutes. Doubling the drum pool (48→96) left 8-stage
placement **unchanged** (15 905 ops). C5a stays gated.

Kolisch (1996): parallel SGS = non-delay; the non-delay set is not
dominant. Artigues, Lopez, Ayache (Ann. OR 2005 / arXiv:cs/0606043):
appending SGS is not active under SDST; insertion SGS is. Lee–Bhaskaran–
Pinedo ATCS (IIE 1997 / EJOR 1997): k1/k2 are look-ahead *scales*, not a
licence to jump the ready floor. A 240 min ATCS floor window (one colour
SMED) on this append-only cover collapsed 16-stage coverage (0.986) and
exploded tardiness — the same stranded-tail failure as unbounded ATCS,
milder. Native month cover remains append-only (gap inserts = 0).

Tried and rejected as defaults:

| Lever | 16/stage | 8/stage | Keep? |
|-------|----------|---------|-------|
| ATCS floor window 240 / 400 | error (0.986) / not default | 0.48–0.57 | **no** — `--cover-atcs-window` stays 0 |
| Merge 16+35 mm² into one colour gate | tardiness 1 922 → 4 430 | — | **no** — section SDST 360 min mixes |
| 6-colour wheel at 16/stage | tardiness 1 922 → 6 017 | — | **no** at 16; **yes** at ≤8 |
| Colour-dedicated lines | feasible, tardiness 154 657 | coverage 0.77 | opt-in `--colour-lines` |
| Extra drums 48→96 | — | identical 15 905 ops | not the bottleneck |

## Exhaustive stay closes 1600@8 (2026-08-15)

Processing 385 818 min vs 8/stage calendar 2 073 600 min leaves **≤83 min/op**
for setups. A general ATCS floor window (any job) collapsed 16-stage coverage.
Mahmoodi/Dooley (IJPR 1991) exhaustive group scheduling plus Flynn (JOM 1987)
repetitive lots: do not switch family while a continuation can run, and stay
on the hot machine even when a colder machine would finish earlier. Pfund
ATCSR bounds that idle; we use one colour SMED (240 min) **only** for
zero-setup continuations (`cover_atcs_exhaust_window`), never as a general
floor window.

Cover-only, seed=1, ATCS window 0, `time_limit_s=45`, no fallback repair:

| Shop | Family | Colour lines | Wheel | Exhaust stay | Status | Wall | Setup | Tardiness | Notes |
|------|--------|--------------|-------|--------------|--------|------|-------|-----------|-------|
| 16/stage, pool 96 | off | off | hash%3 | 0 | **feasible** | 13.7 s | 2 518 440 | **1 922** | default unchanged |
| 8/stage, pool 48 | 1 flex | off | 6-wheel | 240 + hot machine | **feasible** | 4.3 s | 997 600 | 87 134 | **49.1 min/op** |
| 8/stage, pool 48 | off | off | 6-wheel | 240 + hot machine | **feasible** | 9.8 s | 1 094 680 | 246 509 | family not required for cover |
| 8/stage, pool 48 | 1 flex | off | 6-wheel | 0 | error | 5.2 s | 1 577 120 | — | coverage 0.793 |
| 8/stage, pool 48 | 1 flex | off | off | 240 + hot machine | error | 8.0 s | 1 492 960 | — | coverage 0.939 |
| 8/stage, pool 48 | 1 flex | inside family | off | 240 + hot machine | error | 4.4 s | 1 519 600 | — | coverage 0.854; cells fragment |

Nervous-month CLI at ≤8/stage now defaults to family flex + colour wheel +
exhaust stay. `--colour-lines` stays opt-in. `--no-family-lines` remains
feasible with worse tardiness. C5a stays gated. 16-stage family stays opt-in.

What shipped (cover-only, seed=1, colour phase on, window 0, `time_limit_s=45`):

| Shop | Family flex | Colour lines | Cycle | Status | Wall | Setup | Tardiness | Notes |
|------|-------------|--------------|-------|--------|------|-------|-----------|-------|
| 16/stage, pool 96 | off | off | hash%3 | **feasible** | 15.2 s | 2 518 440 | **1 922** | default restored |
| 16/stage, pool 96 | 1 flex | off | hash%3 | **feasible** | 12.3 s | 2 411 760 | **3 670** | was 24 227 without flex |
| 8/stage, pool 48 | off | off | 6-wheel | error | 8.5 s | — | — | coverage **0.684** (was 0.525) |
| 8/stage, pool 48 | 1 flex | off | 6-wheel | error | 7.8 s | 1 568 600 | — | coverage **0.783**, 98.6 min/op |
| 8/stage, pool 96 | 1 flex | off | 6-wheel | error | 7.8 s | 1 568 600 | — | same placement as pool 48 |

Family lines stay opt-in at 16/stage: flex recovered most of the due-date routing
(Nyhuis/Schmidt 2025; Schaller/Gupta family tardiness) but 3 670 > 1 922.
At ≤8/stage they default **on** because they cut tardiness on the feasible
cover (87 134 vs 246 509 without family). Peak WIP 94 vs drum pool 96 is a
cover-only KPI, not a C5a close.

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
| **A1** | ATCS ready pop in native COVER | Unbounded ATCS falsified (2026-08-14). **Windowed (non-delay) ATCS FEASIBLE at 16/stage** (2026-08-15): tardiness 16 588 → 1 922. Floor window 240 collapsed 16-stage coverage. Continuation exhaust (not a general window) + hot-machine stay makes **1600@8 FEASIBLE**. Registry stays FIFO. | Yes — default on month CLI only |
| **A2** | Family-dedicated `eligible_wc_ids` | Mix-sized + 1 flex: **FEASIBLE at 16/stage**, tardiness 3 670 > ATCS-only 1 922 (opt-in). At ≤8 default **on**: tardiness 87 134 vs 246 509 without family on the feasible cover. | No |
| **A3** | Incremental aux calendar in IncrementalRepair | `MachineIndex.add` appends aux windows; `extend(frozen)` instead of per-row add. Wave repair 6.1–7.4 s vs cover 9.25 s (still ~1.4×, not <1 s). | Repair path |
| **A4** | Delta notary | **Not shipped.** One drum pool ⇒ neighbourhood slice == full occupancy. Exhaustive remains default. | — |
| **A5** | Colour-phase campaign | **Default on.** hash%3 at >8; 6-colour wheel at ≤8. Required for 8-stage cover (0.939 without wheel). `--colour-lines` opt-in (tardiness 154k at 16; coverage 0.854 at 8). | No |
| **A6** | C5a hold-until-successor | Still gated. Algebra: leftover calendar was setup minutes; exhaust stay cut mean setup 98 → 49 min/op. Drum pool 48→96 did not move placement. | Gated C5 |

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

C6a multiseed (local): `python -m synaps cable-nervous-month --orders 1600 --machines-per-stage 8 --drum-pool 48 --waves 0 --new-rush 0 --seeds 1,2,3,4,5`

Full 16-stage (local): command at the top of this note. JSON under
`benchmark/results/` is gitignored; this RFC is the tracked evidence.

C6a (2026-08-15, this machine): seeds 1..5 all COVER-feasible, notary 0,
cover 4.28–4.46 s. Tardiness min/median/max 48 269 / 87 134 / 164 355.

C6c weighted residual (local): `python -m synaps cable-nervous-month --weighted-residual --orders 1600 --machines-per-stage 8 --drum-pool 48 --seeds 1,2,3,4,5 --residual-time-limit 60 --residual-max-iterations 400`

C6c (2026-08-15): PVC tardiness 48 056 / 86 656 / 164 080; Δ vs cover
−478..−25; scalar vs makespan residual 4/5. Destroy 20 (not ALNS-300’s 300).
Plan: `CABLE_C6_POST_OSINT_PLAN_2026_08_15.md`. RT: `CABLE_C6C_REDTEAM_2026_08_15.md`.
