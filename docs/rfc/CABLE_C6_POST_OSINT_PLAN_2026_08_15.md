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

### C6c — Tardiness quality without touching COVER defaults

C6a shows tardiness varies **3.4×** across seeds (48k–164k). That is
the remaining CFO-shaped hole.

**Do:** on a **downscaled** nervous instance (≤400 parents, GREED or
COVER), pass `CABLE_PVC_WEIGHTS` / `CABLE_PVC_CPSAT_WEIGHTS` into
**ALNS residual or CP-SAT**, never into list-schedule construction.

**Pass:** material+tardiness scalar improves vs makespan-only on the
same instance; coverage stays 1.0.

**Fail / stop:** if the only way to cut tardiness is a general ATCS
floor window — that already collapsed 16-stage coverage. Leave it off.

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

## Tooling shipped with C6a–C6b

- `parse_nervous_seeds` / `run_nervous_month_multiseed` / `run_freeze_insert_pair`
- CLI `--seeds`, `--freeze-pair` (`--new-rush` → n_rush, `--disruptions` → n_steal)
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

## Next session start here

1. **C6c** downscaled weighted residual/ALNS (`CABLE_PVC_WEIGHTS`). Tardiness is still the CFO-shaped hole; freeze did not close it.
2. Stop. Do not open C5a: occupancy 21 ≪ pool 48.
3. Do not ingest 1С.

C6a and C6b are done. C6d stays gated.
