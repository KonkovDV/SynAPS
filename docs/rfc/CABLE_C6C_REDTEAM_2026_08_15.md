# C6c weighted residual Red Team — 2026-08-15

Hostile pass on cover-then-ALNS with `CABLE_PVC_WEIGHTS`. Claim level:
**experiment**. Not live MES. Not INFIMUM. Not OPTIMAL.

External frame (not a SOTA claim): Pinedo/Lee ATCS is a *construction*
index (Pfund ATCSR 2008). Residual improvement is a second phase
(Ropke & Pisinger 2006 ALNS; Kasapidis et al., *EJOR* 320:479–495, 2025,
ALNS-CP after a feasible cover). Wiring the named weights into list-schedule
would change 50k/500k FIFO. C6c searches; it does not reconstruct.

## Verdict

**ship with residuals.** C6c closed the plumbing hole (C-R1 *search*):
COVER still ignores `CABLE_PVC_WEIGHTS`; ALNS residual seeded from that
cover *does* search them. On the C6a shop (1600@8, seeds 1..5, 60 s,
destroy 20) PVC residual cut tardiness on **5/5** seeds vs cover, and beat
the makespan residual on the PVC scalar on **4/5**. Seed 3 is the counter-
example: makespan-only ALNS found a Cmax/setup move that won the PVC
scalar. The CFO hole is **not** closed: cuts are 25–478 min against a
48 269–164 355 cover range.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **C-R1 search** | P1 | Weights only `scalarize` after GREEDY | `run_weighted_residual_pair`: same cover seed, two ALNS arms, canonical `evaluate`+`scalarize(CABLE_PVC_WEIGHTS)`. CLI `--weighted-residual` |
| **C6c-P0-1** | P0 | 400@8 as the quality instance | 5148 ops < native 10k cliff; Python GREED still running at 6 min (killed). 80@8 GREED is feasible in 11 s with **tardiness 0** (shop slack). Quality probe is the C6a shop |
| **C6c-P0-2** | P0 | ALNS-300 `max_destroy=300` on 20k | 1 greedy repair / 90 s, 0 improvements, Hamming 0. Residual now `max_destroy=24` at ≥10k ops (**not** a registry default change) |
| **C6c-P1** | P1 | Internal `weighted_sum` units | Arms compared only via `scalarize(evaluate(), CABLE_PVC_WEIGHTS)` |

## Measured (this machine, 1600@8, native COVER, 60 s ALNS, destroy 20)

Cover matches C6a (notary 0, coverage 1.0). Warm start used on every arm.

| Seed | Ops | Cover tard | MS residual tard / iters / ham | PVC residual tard / iters / ham | PVC scalar vs MS | Δ tard vs cover |
|------|-----|------------|--------------------------------|---------------------------------|------------------|-----------------|
| 1 | 20 316 | 87 134 | 87 134 / 16 / 0 | **86 656** / 20 / 0.0055 | **yes** 425 960→425 482 | **−478** |
| 2 | 20 154 | 164 355 | 164 355 / 20 / 0 | **164 080** / 22 / 0.0058 | **yes** 508 879→508 604 | **−275** |
| 3 | 19 860 | 131 980 | 131 980 / 14 / 0.00010 | **131 955** / 15 / 0.0013 | **no** 490 302 vs 490 305 | **−25** |
| 4 | 20 136 | 84 156 | 84 156 / 15 / 0 | **84 026** / 22 / 0.0037 | **yes** 424 555→424 425 | **−130** |
| 5 | 19 932 | 48 269 | 48 269 / 12 / 0 | **48 056** / 14 / 0.0012 | **yes** 388 137→387 924 | **−213** |

PVC tardiness min/median/max = **48 056 / 86 656 / 164 080** (cover was
48 269 / 87 134 / 164 355). Relative cuts 0.02–0.55 %. Setup and material
did not move on seeds 1,2,4,5. Seed 3 makespan-arm: Cmax 39 505→39 441,
setup 1 048 320→1 048 200, material +5.

Makespan residual: 0 improvements on 4/5 seeds. PVC residual: 1–6
improvements / 14–22 iterations. Notary 0. Coverage 1.0. Hamming ≤0.006.

## Attacks that had to land

| Attack | Result |
|--------|--------|
| 400 parents is a free downscale of C6a | **lands** — native list-schedule gate is 10k ops. 400@8 = 5148 Python GREED. 80@8 zeros tardiness |
| ALNS-300 defaults search 20k cable | **lands** — destroy 300 ⇒ 1 iter / 90 s, Hamming 0. Micro-destroy is a C6c residual knob, not a portfolio change |
| PVC weights always beat makespan residual on the PVC scalar | **lands on seed 3** — Cmax/setup move under makespan-only won `scalarize(CABLE_PVC_WEIGHTS)` by 2.7 |
| Δ tard −478 closes C-R9 / ATP | **blocked** — hole is still 48k–164k. Hundreds of minutes ≠ tens of thousands |
| Hamming 0.005 = campaign rewrite | **blocked** — ~24–116 ops of 20k; destroy 20 × ~20 iters |
| Warm start rejected ⇒ reconstructed GREEDY with weights | **blocked** — `warm_start_used=True`, cover Hamming 0 on makespan-arm 4/5 |
| Weights entered list-schedule / 50k FIFO | **blocked** — COVER path unchanged; tiny test `solver_config==GREED` |
| 60 s ALNS is OPTIMAL | **blocked** — wall stop, 12–22 iters, `wall_clock_path_dependent` |
| CI tiny GREED proves the month | **blocked** — plumbing only |
| Open C5a / ATCS floor window | **blocked** — occupancy gate unchanged; floor window still falsified |

## Live residuals

| ID | Sev | Finding |
|----|-----|---------|
| **C-R1 construction** | P1 | COVER/ATCS still ignore the vector. Intentional |
| **C-R9** | P1 | 8-stage tardiness still 48k–164k after residual |
| **C6c-R1** | P2 | Seed 3: makespan residual can beat PVC weights on the PVC scalar |
| **C6c-R2** | P2 | 60 s / destroy 20 is a local box, not a quality frontier |
| **C6-R1** | P2 | 8-stage weekly freeze waves still unrun (`waves=0` in C6a) |
| **S4** | P1 | Delta notary still not shipped |

## Forbidden claims

Do not add: INFIMUM 39k/40 min, +78M ₽, Zhu −9.8%, Prysmian −25%,
“weights closed ATP”, “5 seeds prove robustness”, “400@8 was the quality
run”, “ALNS-300 searched 20k”, “we replaced INFIMUM”, OPTIMAL, SOTA,
C5a, ATCS floor window, 50k/500k FIFO change.

## Next honest step

C6-R1: `waves=4` freeze at 8/stage, seeds 1..2. Do not open C5a
(occupancy 21 ≪ pool 48). Do not put `CABLE_PVC_WEIGHTS` into COVER.

Reproduce (local evidence, not CI):

```
python -m synaps cable-nervous-month --weighted-residual --orders 1600 --machines-per-stage 8 --drum-pool 48 --seeds 1,2,3,4,5 --residual-time-limit 60 --residual-max-iterations 400
```
