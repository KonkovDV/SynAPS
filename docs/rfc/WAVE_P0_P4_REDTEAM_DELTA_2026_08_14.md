# P0–P4 Red Team delta — 2026-08-14

Hostile pass on COVER ATCS, cable encode-first (family lines, colour phase,
issued-plan pin, new-parent rush), IncrementalRepair aux cache, GridPlan pin
hygiene, and MobiRoute residuals. Claim level: **experiment**.

## Verdict

**ship with residuals.** ATCS is falsified as the month cover rule
(coverage collapses 100% → 62–70% at every k tested; root cause in
`CABLE_NERVOUS_MONTH_ACCEL_2026_08.md`); it ships only as an opt-in flag
with Python/native parity and unit tests. FIFO is the default in the
registry, `run_nervous_month`, and the CLI. Family-dedicated lines are
opt-in (infeasible at 16/stage). Colour phase is default-on (measured
tardiness/WIP win). C5a hold-until-successor stays gated. Delta notary is
not shipped. 1600@8 is **not FEASIBLE** under either ready rule — recorded,
not claimed.

## Attacks that had to land before merge

| Attack | Result |
|--------|--------|
| ATCS changes 50k/500k FIFO cover | **blocked** — registry kwargs omit `cover_ready_rule`; Python passes extra native kwargs only when `ready_rule != 0` |
| ATCS among min-floor only | **blocked** — native/Python scan **all** ready ops |
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
| GREED `temporal_stabilization_converged=True` | tiny CLI reports `None` / `n/a (GREED)` |
| Mixing 499770/145s into cable | forbidden; worlds stay split in CHANGELOG/RFC |
| S6 C5a “for speed” | still gated (`peak_wip_drums` vs pool is quality, not cover time) |

## Closed this wave (code + tests)

| ID | Close |
|----|-------|
| S1 | `cover_ready_rule=atcs` native `list_schedule.rs` + Python parity via `compute_atcs_log_score` |
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
| S6 C5a | **gated** until a successor RFC + numbers |
| N-R1 1600@8 | **measured infeasible** under FIFO (0.480) and ATCS (0.561); not a ready-rule problem |
| N-R6 seeds 1..5 | not run this wave; single seed=1 only |
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
| 1600@16 FIFO+colour (default) | **feasible** | 20 316/20 316 | cover 9.25 s | 2 651 760 | notary 0, converged 1, tardiness 40 580, peak WIP 183 |
| 1600@16 ATCS k1=2.0 | error | 13 033 | 185.9 s | 1 724 320 | coverage collapse, not parametric |
| 1600@16 ATCS k1=50 k2=0.1 | error | 14 138 | 194.4 s | 2 000 440 | retune does not recover coverage |
| 1600@16 ATCS k1=200 k2=0.05 | error | 14 145 | 183.1 s | 1 642 120 | |
| 1600@16 FIFO family+colour | error | 18 811 | 14.2 s | — | family split halves per-family capacity |
| 1600@8 FIFO+colour | error | 9 755 (0.480) | 22.5 s | 1 758 640 | N-R1: not FEASIBLE |
| 1600@8 ATCS+colour | error | 11 388 (0.561) | 167.1 s | 1 084 880 | N-R1: best coverage, still not FEASIBLE |
| tiny CLI GREED | feasible | — | — | — | notary 0, converged n/a (GREED), CI |

N-R6 multiseed (1..5) is **not run** this wave; single seed=1 only. Do not
quote INFIMUM, +78M ₽, Zhu −9.8%, Prysmian −25%, N-1, SAIDI, SOTA,
or “repair 10×”.
