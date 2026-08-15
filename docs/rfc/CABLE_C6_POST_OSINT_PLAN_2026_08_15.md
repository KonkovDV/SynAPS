# C6 post-OSINT work plan — 2026-08-15

- **Repo:** SynAPS standalone. Not GridPlan. Not live MES.
- **Claim boundary:** synthetic nervous month + public plant narrative.
  Not INFIMUM. Not SOTA. Not a factory schedule.
- **Authority:** `CABLE_MOSKABELMET_EXECUTION_PLAN_2026_08.md` C0–C5 still
  bind. This plan is the *next sequential wave* after OSINT Red Team
  `CABLE_MOSKABELMET_OSINT_REDTEAM_2026_08_15.md`.
- **External-evidence skip:** C6a is a local probe of an already-shipped
  COVER policy. No new vendor/API claim.

## Why this wave exists

Coverage at 8 machines/stage is closed (family + colour wheel + exhaust
stay). Plant-shaped pain that is still **unmeasured as a distribution**
or **untested as a policy pair**:

| Residual | Plant analogue | What C6 must not do |
|----------|----------------|---------------------|
| N-R6 seed=1 only | — | Quote 87 134 tardiness as *the* 8-stage number |
| C-R9 tardiness | CFO due-date / ATP | Reopen a general ATCS floor window |
| C-R2 \(D_{\max}\) ≫ pool | LEAN freeze −24% drums | Open C5a because WIP looks big |
| C-R1 weights unused | scrap metres | Put `CABLE_PVC_WEIGHTS` into COVER (50k/500k) |
| C-R4 campaign ≠ merge | INFIMUM launches ÷10 | Illegal cross-order `predecessor_op_id` |

Stop rule: one gate at a time. A failed gate does not unlock C5.

## Sequence (do in this order)

### C6a — Multiseed cover+notary @ 1600×8 — **DONE 2026-08-15**

**Do:** seeds 1..5, default tight-shop levers, `waves=0`, `new_rush=0`,
pool 48, exhaustive notary. CLI: `--seeds 1,2,3,4,5`.

**Pass:** every seed `feasible`, notary 0, stabilize converged, coverage 1.0.

**Fail:** stop. Do not average an `error` into a tardiness table.

**Measured (this machine, native COVER, 27 s wall for five seeds):**

| Seed | Ops | Status | Notary | Cover s | Setup min | min/op | Tardiness | \(D_{\max}\) WIP |
|------|-----|--------|--------|---------|-----------|--------|-----------|------------------|
| 1 | 20 316 | feasible | 0 | 4.28 | 997 600 | 49.1 | 87 134 | 155 |
| 2 | 20 154 | feasible | 0 | 4.29 | 1 012 680 | 50.2 | **164 355** | 206 |
| 3 | 19 860 | feasible | 0 | 4.28 | 1 048 320 | 52.8 | 131 980 | 238 |
| 4 | 20 136 | feasible | 0 | 4.29 | 998 520 | 49.6 | 84 156 | 152 |
| 5 | 19 932 | feasible | 0 | 4.46 | 998 680 | 50.1 | **48 269** | 146 |

Tardiness min/median/max = **48 269 / 87 134 / 164 355**. Mean ≈ 103 179.
Seed=1 was the **median**, not a lucky outlier. Setup stays under the
83 min/op budget on every seed. \(D_{\max}\) WIP is 146–238 vs pool 48
on every seed — still the **span** KPI, not Cumulative occupancy.

N-R6 is **closed for cover+notary**. It is **not** closed for freeze
waves or new-parent rush on the 8-machine shop.

### C6b — Freeze vs insert \(D_{\max}\) pair — **DONE 2026-08-15**

CLI: `python -m synaps cable-nervous-month --freeze-pair --orders 1600 --machines-per-stage 8 --drum-pool 48 --new-rush 2 --disruptions 20 --seeds 1,2`

Insert-anywhere is **full COVER of the mutated shop**, not `allow_freeze_break=True` on new-op neighbourhood (that flag is a no-op when issued ops are not in `disrupted_op_ids`). Steal-window pair *does* flip the flag on freeze-window ops.

**Pass:** freeze arms stay `feasible`, notary 0. Measured (this machine):

| Seed | Cover WIP / proc / tard | Rush freeze WIP / tard / \(R\) | Rush insert WIP / tard | WIP Δ (freeze−insert) | Steal freeze \(R\) | Steal open \(R\) | Steal WIP Δ |
|------|-------------------------|--------------------------------|------------------------|-----------------------|--------------------|------------------|-------------|
| 1 | 155 / **21** / 87 134 | 156 / 118 823 / **0** | **222** / 188 221 | **−66** | 0 | 0.00084 | 0 |
| 2 | 206 / **21** / 164 355 | 206 / 168 285 / **0** | **166** / 114 304 | **+40** | 0.00050 | 0.00119 | 0 |

12 new ops from 2 rush parents. Freeze Hamming 0 on issued ops (calendar held). Steal of 20 freeze-window ops does **not** move \(D_{\max}\). Processing occupancy is **21 vs pool 48 vs span 155–222**.

Sign of rush WIP delta **flips by seed**. Do not claim freeze reduces drums. Do not claim −24%.

### C6c — Tardiness quality without touching COVER defaults — **DONE 2026-08-15**

C6a tardiness varies **3.4×** across seeds (48k–164k). That remains the
CFO-shaped hole. Construction still ignores `CABLE_PVC_WEIGHTS` (C-R1).

**Do not** downscale to 400 parents for quality: 5148 ops miss the native
10k COVER path. 80@8 GREED is slack (tardiness 0). Quality instance = C6a
shop (1600@8).

**Do:** COVER, then two ALNS residuals from the same seed: `DEFAULT_WEIGHTS`
vs `CABLE_PVC_WEIGHTS`. Compare with `scalarize(evaluate(), CABLE_PVC_WEIGHTS)`.
At ≥10k ops residual `max_destroy=24` (ALNS-300’s 300-op destroy did 1
iter / 90 s). Registry unchanged.

**Measured** (this machine, 60 s, destroy 20, seeds 1..5): all arms
`feasible`, notary 0, coverage 1.0, warm start used. PVC tardiness
**48 056 / 86 656 / 164 080** vs cover 48 269 / 87 134 / 164 355.
Δ tard vs cover **−478 / −275 / −25 / −130 / −213**. PVC scalar beat
makespan residual on **4/5** seeds; seed 3 makespan-arm won the scalar
via Cmax 39 505→39 441. Relative cuts 0.02–0.55 %. Hamming ≤0.006.

**Pass (plumbing + weak quality):** coverage 1.0; scalar improved on 4/5;
tardiness dropped on 5/5 vs cover. **Fail / not claimed:** ATP closed,
OPTIMAL, weights-into-COVER.

CLI: `--weighted-residual`. Tiny GREED CI. 20k tables are local.

### C6-R1 — Weekly freeze waves at 8-stage — **DONE 2026-08-15 (plumbing; pass gate not stable)**

CLI: `python -m synaps cable-nervous-month --orders 1600 --machines-per-stage 8 --drum-pool 48 --waves 4 --disruptions 20 --new-rush 0 --seeds 1,2`

**Pass (stable):** all four weeks `feasible`, notary 0, both seeds, Hamming
reported honestly. **Measured:** seed 1 passed every probe. Seed 2 failed
weeks 3–4 once (`INFEASIBLE`, notary=1, tard 164 355→176 778) then passed
seven later months. Typical all-green Hamming is **not** bitwise across
repeats. Wave-1 \(R=0\) on seed 2 is a no-move. Occupancy stayed **21**.
Dirty weeks no longer chain. CLI exit 1 if any week is dirty.

**Fail / not claimed:** freeze works at 8-stage; PYTHONHASHSEED pins the
month; C5a.

RT: `CABLE_C6R1_REDTEAM_2026_08_15.md`.

### C6d — C5a gate note (still gated)

C6b measured occupancy **21** ≪ pool **48** ≪ span **155–222**. Hold-until-successor
would lengthen occupancy toward span and **stress** a pool that currently has
slack. Do not open C5a to “make drums honest” on this pack.

Open C5a **only if** a later freeze+C6c run shows processing occupancy
hitting the pool **and** span still ≫ occupancy after that. Separate kernel RFC.

Do not open C5a to “make 8 machines fit”. They already fit.

### C6e — Explicit non-goals (this wave and the next)

| Forbidden | Why |
|-----------|-----|
| 1С / MES ingest | Encode-first; APS without PDM is a different product |
| INFIMUM 39k/40 min bake-off | Unpublished algebra |
| Colour-dedicated lines as 8-stage default | Coverage 0.854 |
| Extra drums / C5a for coverage | Falsified 2026-08-15 |
| Cross-order lot merge | Validator (C5d) |
| GPL FJSSP-SDST, AVX-512, DRL factory engine | Standing forbids |
| CI for 1600@8×5 | ~27 s local, not a unit test |

## Tooling shipped with C6a–C6c

- `parse_nervous_seeds` / `run_nervous_month_multiseed` / `run_freeze_insert_pair`
- `run_weighted_residual_pair` / `run_weighted_residual_multiseed`
- CLI `--seeds`, `--freeze-pair`, `--weighted-residual`
- `peak_processing_drums` in `cable_kpis` (`[start, end)` occupancy, no setup-hold)
- Tiny GREED tests only. 20k tables are **local evidence**, not CI.

Reproduce C6a:

```
python -m synaps cable-nervous-month --orders 1600 --machines-per-stage 8 --drum-pool 48 --waves 0 --new-rush 0 --seeds 1,2,3,4,5
```

Reproduce C6b:

```
python -m synaps cable-nervous-month --freeze-pair --orders 1600 --machines-per-stage 8 --drum-pool 48 --new-rush 2 --disruptions 20 --seeds 1,2
```

Reproduce C6c:

```
python -m synaps cable-nervous-month --weighted-residual --orders 1600 --machines-per-stage 8 --drum-pool 48 --seeds 1,2,3,4,5 --residual-time-limit 60 --residual-max-iterations 400
```

## Next session start here

1. **OPS-WHEEL** maturin `--interpreter` note. `.cursor-*` / `docs/gridplan/` stay untracked.
2. Stop. Do not open C5a: occupancy 21 ≪ pool 48.
3. Do not put `CABLE_PVC_WEIGHTS` into COVER. Do not ingest 1С.
4. Do not claim C6-R1 freeze waves are stably FEASIBLE. Do not flip ALNS default to UCB1.
5. Do not flip the S4 notary default. Drum peaks: `CABLE_CR2_DRUM_METRICS_REDTEAM_2026_08_15.md`.

C6a, C6b, C6c, and C6-R1 plumbing are done. C6d stays gated.
