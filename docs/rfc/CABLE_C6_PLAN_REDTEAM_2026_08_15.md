# C6 plan + multiseed Red Team — 2026-08-15

Hostile pass on `CABLE_C6_POST_OSINT_PLAN_2026_08_15.md`,
`--seeds` / `run_nervous_month_multiseed`, and the 1600@8×5 cover
probe. Claim level: **experiment**. Not live MES. Not INFIMUM.

## Verdict

**ship with residuals.** C6a closed seed distribution for cover+notary.
C6b freeze stays FEASIBLE; rush WIP delta **flips sign** (seed 1 −66,
seed 2 +40). Occupancy 21 ≪ pool 48 ≪ span 155–222 — C5a stays gated
and would likely *hurt* the drum pool. Do not advertise −24% drums,
a confidence interval, or due-date quality.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **N-R6 cover** | P1 | seed=1 only on 1600@8 | Seeds 1..5 all COVER-feasible, notary 0, stabilize True, 4.28–4.46 s. Ops 19 860–20 316 (generator packing, not a bug). |
| **C6-P0-1** | P0 | Plan as a C5a license | C6d restates the occupancy-vs-span gate. 8-stage already fits (\(\bar\sigma\) 49–53 < 83). |
| **C6-P0-2** | P0 | No way to reproduce five seeds | `--seeds` + aggregator. Tiny GREED CI; 20k remains local. |
| **C6-P1-1** | P1 | Quoting 87 134 as *the* tardiness | It is the **median**. Mean ≈ 103 179. Range 48 269–164 355 (3.4×). |
| **C6b-P0** | P0 | Freeze vs insert unmeasured at 8-stage | Seeds 1–2, `--freeze-pair`: freeze repair FEASIBLE, notary 0, issued Hamming 0. Insert = full COVER of mutant. |
| **C6b-P1** | P1 | Occupancy vs span unknown | `peak_processing_drums` = 21 vs pool 48 vs span 155–222 on both seeds. |

## Attacks that had to land

| Attack | Result |
|--------|--------|
| n=5 is a CI / t-test / “robust” | **lands** — five points, no CI. Report min/median/max. |
| waves=0 hides freeze failure at 8-stage | **closed C6b** — freeze repair feasible; steal-window Hamming ≤ open |
| \(D_{\max}\) vs pool 48 ⇒ open C5a | **blocked** — occupancy 21 ≪ 48 ≪ span 155–222. C5a hold would push occupancy toward span > pool |
| `allow_freeze_break=True` on new-parent repair is insert-anywhere | **lands** — issued ops are not in neighbourhood. Insert arm is full COVER |
| Freeze always cuts drums (plant −24%) | **blocked** — seed 1 ΔWIP −66, seed 2 ΔWIP **+40**. Sign flips |
| Steal 20 freeze-window ops reproduces LEAN freeze | **blocked** — ΔWIP 0, Hamming ≤ 0.001 |
| Seed=1 was cherry-picked because it looked good | **blocked** — it is the median; seed 2 is worse (164 355) |
| FEASIBLE ⇒ due dates solved | **blocked** — tardiness 48k–188k vs 1 922 at 16-stage |
| `--seeds` / `--freeze-pair` change 50k/500k FIFO COVER | **blocked** — nervous CLI only |
| Tiny GREED tests prove the month | **blocked** — CI proves the aggregator; 20k tables are local |
| Plan C6c sneaks weights into list-schedule | **blocked** — ALNS/CP-SAT only |
| Colour cells / extra drums / ATCS window 240 as C6 closer | **blocked** — already falsified |
| Mix Fujikura −58% WIP / INFIMUM 39k/40 min | **blocked** |
| Architecture ratchet | **blocked** — new helpers ≤80 (`run_freeze_insert_pair` 60) |

## Live residuals (do not paper over)

| ID | Sev | Finding | Why it stays |
|----|-----|---------|--------------|
| **C6-R1** | P2 | Weekly freeze *waves* still seed=1 @16 | **run**: 1600@8 seeds 1..2, `waves=4`. Plumbing shipped. Stable all-green **not** claimed (`CABLE_C6R1_REDTEAM_2026_08_15.md`) |
| **C6-R2** | P1 | 8-stage tardiness still 48k–164k | C6c residual cut 25–478 min (0.02–0.55 %). Hole remains. `CABLE_C6C_REDTEAM_2026_08_15.md` |
| **C6-R3** | P1 | Span 155–222 vs occupancy 21 vs pool 48 | Occupancy has slack. C5a would consume it. Gated |
| **C6-R6** | P1 | Rush WIP delta flips sign | Two seeds only. Not a freeze-quality proof |
| **C-R1 construction** | P1 | COVER still ignores `CABLE_PVC_WEIGHTS` | Intentional. Search path closed in C6c |
| **C6c-R1** | P2 | Seed 3 PVC scalar lost to makespan residual | Cmax/setup move. Weights are not a dominance theorem |
| **C-R7** | P2 | `allow_freeze_break` is a boolean | Unchanged. No-op on new-parent-only neighbourhood |

## Forbidden claims (repeat)

Do not add: INFIMUM 39k/40 min, +78M ₽, 27 days, launches −10×, Zhu −9.8%,
Prysmian −25%, Fujikura −30%/−58% as Zavod freeze, SynAPS 499 770/145 s
as cable, “5 seeds prove robustness”, “median tardiness is plant ATP”,
“WIP 3× pool means C5a”, “freeze always cuts drums”, “we replaced INFIMUM”,
“8-machine FIFO is FEASIBLE”, “C6a closed freeze”.

## Next honest step

K3 wall-stamp honesty. Do not open C5a:
occupancy 21 ≪ pool 48. Do not quote ΔWIP −66 without the seed-2 +40.
Do not quote C6c −478 tardiness without seeds 2–5 and the seed-3 scalar miss.
Do not claim C6-R1 four-week freeze is stably FEASIBLE.
