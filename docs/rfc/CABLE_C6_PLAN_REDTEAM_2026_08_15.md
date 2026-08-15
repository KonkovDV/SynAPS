# C6 plan + multiseed Red Team — 2026-08-15

Hostile pass on `CABLE_C6_POST_OSINT_PLAN_2026_08_15.md`,
`--seeds` / `run_nervous_month_multiseed`, and the 1600@8×5 cover
probe. Claim level: **experiment**. Not live MES. Not INFIMUM.

## Verdict

**ship with residuals.** C6a did what the OSINT RFC asked: five
independent covers, all `feasible`, notary 0. The plan’s remaining
order (freeze pair **before** C5a, weights **outside** COVER) is the
correct plant-shaped sequence. Do not advertise a confidence interval,
due-date quality, or −24% drums.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **N-R6 cover** | P1 | seed=1 only on 1600@8 | Seeds 1..5 all COVER-feasible, notary 0, stabilize True, 4.28–4.46 s. Ops 19 860–20 316 (generator packing, not a bug). |
| **C6-P0-1** | P0 | Plan as a C5a license | C6d restates the occupancy-vs-span gate. 8-stage already fits (\(\bar\sigma\) 49–53 < 83). |
| **C6-P0-2** | P0 | No way to reproduce five seeds | `--seeds` + aggregator. Tiny GREED CI; 20k remains local. |
| **C6-P1-1** | P1 | Quoting 87 134 as *the* tardiness | It is the **median**. Mean ≈ 103 179. Range 48 269–164 355 (3.4×). |

## Attacks that had to land

| Attack | Result |
|--------|--------|
| n=5 is a CI / t-test / “robust” | **lands** — five points, no CI. Report min/median/max. |
| waves=0 hides freeze failure at 8-stage | **lands** — N-R6 closed for cover+notary only. C6b is the next gate. |
| Ops count moves with seed, so tardiness is not paired | **lands as honesty** — 19 860–20 316. Compare distributions, not a paired delta. |
| Seed=1 was cherry-picked because it looked good | **blocked** — it is the median; seed 2 is worse (164 355). |
| FEASIBLE ⇒ due dates solved | **blocked** — tardiness 48k–164k vs 1 922 at 16-stage. C-R9 stays. |
| \(D_{\max}\) 146–238 vs pool 48 ⇒ open C5a now | **blocked** — span KPI, not Cumulative occupancy. Same residual as C-R2. Freeze (C6b) is the cheaper plant move. |
| `--seeds` changes 50k/500k FIFO COVER | **blocked** — nervous CLI only. Registry kwargs unchanged. |
| Tiny GREED `--seeds 1,2` proves the month | **blocked** — CI proves the aggregator; 20k table is local. |
| Empty `--seeds` / `" , "` silently becomes seed 1 | **blocked** — `parse_nervous_seeds` raises `ValueError`. |
| Plan C6c sneaks weights into list-schedule | **blocked** — text forbids COVER construction; ALNS/CP-SAT only. |
| Plan order C6c before freeze copies INFIMUM (APS first) | **blocked** — C6b freeze pair is next. Plant did freeze before APS. |
| Colour cells / extra drums / ATCS window 240 as C6 closer | **blocked** — already falsified. Not in the sequence. |
| Mix Fujikura −58% WIP into C6b success | **blocked** — forbidden table. |
| INFIMUM 39k/40 min as C6 runtime target | **blocked**. |
| Probe JSON `_c6a_multiseed.json` as tracked evidence | **blocked** — numbers live in the plan RFC; temp file deleted. |
| `all_feasible` true if one seed has notary>0 but status feasible | **blocked** — aggregator requires both. |
| Architecture ratchet: `_add_cable_nervous_parser` / `_run_cable_nervous` / `run_nervous_month` | **blocked** — 76 / 30 / 75 lines. New helpers ≤80. |
| Multiseed in CI for 1600@8 | **blocked** — plan non-goal. ~27 s local. |

## Live residuals (do not paper over)

| ID | Sev | Finding | Why it stays |
|----|-----|---------|--------------|
| **C6-R1** | P1 | Freeze waves never run at 8-stage | C6b. 16-stage waves remain the only freeze evidence. |
| **C6-R2** | P1 | Tardiness 3.4× across seeds | COVER stay optimises setups, not due dates. C6c. |
| **C6-R3** | P1 | \(D_{\max}\) WIP 146–238 vs pool 48 on every seed | Span ≠ occupancy. Not a C5a trigger by itself. |
| **C6-R4** | P2 | Generator op-count jitter | Reel packing depends on seed lengths. Honest, not normalised. |
| **C6-R5** | P2 | No seed>5, no 16-stage multiseed | Out of this gate. 16-stage tardiness 1 922 is still seed=1. |
| **C-R1** | P1 | COVER still ignores `CABLE_PVC_WEIGHTS` | Intentional. C6c. |
| **C-R7** | P2 | `allow_freeze_break` is a boolean | Unchanged. C6b must keep it false on the freeze arm. |

## Forbidden claims (repeat)

Do not add: INFIMUM 39k/40 min, +78M ₽, 27 days, launches −10×, Zhu −9.8%,
Prysmian −25%, Fujikura −30%/−58% as Zavod freeze, SynAPS 499 770/145 s
as cable, “5 seeds prove robustness”, “median tardiness is plant ATP”,
“WIP 3× pool means C5a”, “we replaced INFIMUM”, “8-machine FIFO is
FEASIBLE”, “C6a closed freeze”.

## Next honest step

C6b: freeze vs insert-anywhere on seeds **1 and 2** (median and worst
tardiness). If freeze loses FEASIBLE, stop. If WIP does not move, write
the C5a gate note from occupancy vs span — still no kernel change by
ambition.
