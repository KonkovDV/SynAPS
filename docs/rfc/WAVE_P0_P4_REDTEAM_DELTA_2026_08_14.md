# P0–P4 Red Team delta — 2026-08-14

Hostile pass on COVER ATCS, cable encode-first (family lines, colour phase,
issued-plan pin, new-parent rush), IncrementalRepair aux cache, GridPlan pin
hygiene, and MobiRoute residuals. Claim level: **experiment**.

## Verdict

**ship with residuals.** Unbounded ATCS remains falsified. **Windowed
(non-delay) ATCS is the nervous-month default** (FEASIBLE at 16/stage,
tardiness 1 922, 2026-08-15). Registry `RHC-GREEDY-COVER` stays FIFO.
Family-dedicated lines are mix-sized: opt-in at 16/stage (tardiness 3 670
vs 1 922); default **on** at ≤8. Colour phase stays default-on (hash%3
at 16/stage, 6-colour wheel at ≤8). Continuation exhaust (Mahmoodi/Dooley
+ Flynn stay) is default at ≤8. C5a stays gated. Delta notary is not
shipped. **1600@8 is COVER-feasible** (20 316/20 316, 49.1 min/op,
tardiness 87 134) with family + wheel + exhaust stay.

## Attacks that had to land before merge

| Attack | Result |
|--------|--------|
| ATCS changes 50k/500k FIFO cover | **blocked** — registry kwargs omit `cover_ready_rule`; Python passes extra native kwargs only when `ready_rule != 0` |
| ATCS among min-floor only | **now the rule** — unbounded scan collapsed coverage; windowed ATCS scores `floor <= min(ready)+0`. Regression: `test_cover_atcs_does_not_jump_future_floor` |
| Non-metric SDST / missing last state | min-setup over eligible machines; first pop has `last_state=None` → setup 0 (same as GREED cold start) |
| Aux delay ignored by ATCS key | ATCS chooses the ready op; placement is still earliest-end + aux bump (same as FIFO) |
| `latest_finish` / horizon cap | slack uses `min(horizon, latest_finish)`; placement still caps at that |
| Tie-break vs FIFO uuid_rank | score, then lower floor, lower seq, lexicographically smaller op-id string (native `uuid_rank` is argsort of those strings) |
| Native/Python heap corruption | ATCS treats the ready set as a list after the first pop; FIFO still `heapq` |
| `issued_assignments` unknown kwargs | solvers take `**kwargs`; pin mutates the problem before solve |
| `allow_freeze_break` as security | documented boolean policy, not ACL (C-R7) |
| Delta notary blind to frozen | **not shipped**. One drum pool ⇒ neighbourhood slice == full occupancy. Repair still exhaustive |
| Family split with 1 machine/stage | falls back to all machines of the group |
| Colour phase past due | gate snaps back to unshifted release gate |
| 6-colour wheel vs hash%3 | wheel only when machines_per_stage ≤8; 16/stage keeps hash%3 (tardiness 6 017 vs 1 922) |
| ATCS floor window = one SMED | 240 min delay on *any* job collapsed 16-stage coverage (0.986); default window 0 |
| Exhaust = general ATCS window | **blocked** — `cover_atcs_exhaust_window` scores only zero-setup continuations and prefers the hot machine; 16-stage exhaust stays 0 |
| Extra drums close 8-stage | **falsified** — pool 48 and 96 placed the same ops; 8-stage closed by exhaust stay, not drums |
| S6 C5a “for 8-machine cover” | still gated; leftover calendar is setup minutes, not drum hold |
| GREED `temporal_stabilization_converged=True` | tiny CLI reports `None` / `n/a (GREED)` |
| Mixing 499770/145s into cable | forbidden; worlds stay split in CHANGELOG/RFC |
| S6 C5a “for speed” | still gated (`peak_wip_drums` vs pool is quality, not cover time) |

## Closed this wave (code + tests)

| ID | Close |
|----|-------|
| S1 | `cover_ready_rule=atcs` native `list_schedule.rs` + Python parity via `compute_atcs_log_score`; `cover_atcs_exhaust_window` continuation + hot-machine stay |
| S2 | `family_dedicated_lines` PVC vs XLPE `eligible_wc_ids` |
| S3 | `MachineIndex.add` appends aux windows instead of dropping the frozen cache |
| S5 | `colour_phase` campaign; freeze as `pin_issued_plan` / IncrementalRepair (L-RHO analogue is policy, not GNN) |
| N-R3 | `add_rush_orders` + `new_rush` report row (repair vs full on the **mutated** instance) |
| N-R8 | GREED reports `n/a (GREED)` |
| C-R1 | `CABLE_PVC_CPSAT_WEIGHTS` integer vector; CP-SAT test |
| C-R3 | `solve_schedule(..., issued_assignments=, freeze_horizon_end=)` |
| C-R5/C-R7/C-R8 | `docs/domains/cable.md` |
| P4 M2/M4/M5 | LBBD out of scope; native CI already present; GPU refused in limitations |

## Still residual (honest)

| ID | Status |
|----|--------|
| S4 delta notary | **not shipped** — one drum pool; exhaustive remains default |
| S6 C5a | **gated** — C6b occupancy 21 ≪ pool 48 ≪ span 155–222. Hold would stress the pool. |
| N-R1 1600@8 | **closed COVER-feasible** (2026-08-15). Family flex + 6-colour wheel + continuation exhaust (ready-queue + hot-machine stay): 20 316/20 316, 49.1 min/op (budget 83), tardiness 87 134. Colour cells dropped coverage to 0.854. Extra drums 48→96 identical. C5a still gated. |
| N-R6 seeds 1..5 | **C6a closed cover+notary** (2026-08-15). Tardiness 48 269–164 355 (median 87 134). Freeze waves still seed=1. No CI. |
| N-R4 Hamming 0 | still a no-move explanation, not freeze quality |
| N-R7 | full notary on repair still dominates if cache miss |
| K1 full pytest | **1120 passed, 2 skipped, 1 xfailed** in 2096 s (2026-08-14, this machine). Sentinel `test_guard_s3_bhk_bound_subset_monotone` remains xfail. |
| K3 A15-P2 | keep `wall_clock_path_dependent` stamp; **no** strict CI error |
| K2 MAB | design already destroy×repair UCB1 (`DESIGN_ALNS_MAB_OPERATOR_SELECTION.md`); default roulette |
| K2 ALNS native rank | snaps `base/speed` to ceil grain after native (Wave 15 F2) |
| K2 full SDST native pack | not `p_{o,m}` ABI; leftover, not this wave |
| P4 M1 | `stress_200` still ~8.1 s; 2–3 s not claimed |
| P4 M3 | VIA/quota exist; ALNS never OPTIMAL |

## Probe table (this machine, seed=1, 2026-08-14)

| Probe | status | placed | wall | setup min | notes |
|-------|--------|--------|------|-----------|-------|
| 1600@16 FIFO+colour | **feasible** | 20 316/20 316 | 7.6 s | 2 636 200 | tardiness 16 588, WIP 159 (cover-only, 2026-08-15) |
| 1600@16 windowed ATCS+colour | **feasible** | 20 316/20 316 | 8.9 s | 2 518 440 | tardiness 1 922, WIP 94; nervous-month default |
| 1600@16 FIFO mix-sized family | **feasible** | 20 316/20 316 | 5.6 s | 2 511 240 | tardiness 26 647; 50/50 was error |
| 1600@16 ATCS+family | **feasible** | 20 316/20 316 | 6.8 s | 2 488 800 | tardiness 24 227 — worse than ATCS-only |
| 1600@8 FIFO+colour | error | 10 084 (0.496) | 11.8 s | — | N-R1 |
| 1600@8 windowed ATCS | error | 10 664 (0.525) | 12.6 s | — | N-R1 |
| 1600@16 ATCS+family flex | **feasible** | 20 316/20 316 | 12.3 s | 2 411 760 | tardiness **3 670** (was 24 227 without flex) |
| 1600@8 ATCS 6-colour wheel | error | 13 901 (0.684) | 8.5 s | — | was 0.525 without wheel |
| 1600@8 ATCS+family+wheel | error | 15 905 (0.783) | 7.8 s | 1 568 600 | without exhaust stay |
| 1600@8 family+wheel+exhaust stay | **feasible** | 20 316/20 316 | 4.3 s | 997 600 | tardiness 87 134, 49.1 min/op; N-R1 closed |
| 1600@8 C6a seeds 1..5 | **all feasible** | 19 860–20 316 | 4.28–4.46 s | 0.998–1.048e6 | tardiness 48 269–164 355, notary 0 |
| tiny CLI GREED | feasible | — | — | — | notary 0, converged n/a (GREED), CI |

C6a closed cover+notary across seeds 1..5. Freeze waves still seed=1.
Do not quote INFIMUM, +78M ₽, Zhu −9.8%, Prysmian −25%, N-1, SAIDI, SOTA,
or “repair 10×”. Plan/RT: `docs/rfc/CABLE_C6_POST_OSINT_PLAN_2026_08_15.md`,
`docs/rfc/CABLE_C6_PLAN_REDTEAM_2026_08_15.md`.
