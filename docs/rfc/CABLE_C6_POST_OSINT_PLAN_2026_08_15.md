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

### C6b — Freeze vs insert \(D_{\max}\) pair (next)

Plant freeze came **before** APS. Encode-first success criterion 2 is
still unmeasured on the month pack.

**Do:** same seed (start with 1 and 2 — median and worst tardiness).
Cover once. Then (i) freeze 72 h + rush admission `allow_freeze_break=False`;
(ii) same rushes with freeze off / insert-anywhere. Compare
`peak_wip_drums` and tardiness. Directional only.

**Pass:** freeze does not lose FEASIBLE; report the delta even if WIP
does not fall.

**Fail / stop:** if freeze makes cover `error`, fix policy, do not open
C5a.

**Forbidden:** claim −24% drums, Fujikura −58% WIP, INFIMUM tare turnover.

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

Open C5a **only if** C6b freeze + C6c weights leave
\(D_{\max}\gg\) processing-pool **and** a processing-aux peak on the
same assignments is materially smaller (occupancy ≠ span). Write a
separate kernel RFC. Atomic delivery.

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

## Tooling shipped with C6a

- `parse_nervous_seeds` / `run_nervous_month_multiseed`
- CLI `--seeds 1,2,3,4,5` (overrides `--seed`)
- Tiny GREED tests only. The 20k table above is **local evidence**, not CI.

Reproduce C6a:

```
python -m synaps cable-nervous-month --orders 1600 --machines-per-stage 8 --drum-pool 48 --waves 0 --new-rush 0 --seeds 1,2,3,4,5
```

## Next session start here

1. C6b freeze pair on seeds 1 and 2.
2. Stop. Write the C5a/C6c gate from those two numbers.
3. Only then C6c downscaled weighted residual.

Estimated effort: C6b 0.5–1 d, C6c 1–2 d, C6d 1–2 w **if** the gate
opens. C6a is done.
