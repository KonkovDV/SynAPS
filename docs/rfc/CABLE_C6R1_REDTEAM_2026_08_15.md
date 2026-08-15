# C6-R1 weekly freeze-wave Red Team — 2026-08-15

Hostile pass on `waves=4`, `disruptions=20`, 1600@8, pool 48, seeds 1..2.
Claim level: **experiment**. Not live MES. Not INFIMUM. Not a freeze-quality
proof. External-evidence skip: local IncrementalRepair / native COVER probe
of an already-shipped neighbourhood. No new vendor API.

## Verdict

**ship plumbing; fail the stable pass gate.** Four weekly reshuffles are no
longer unrun. Seed 1 was `feasible` / notary 0 on every probe. Seed 2 was
`INFEASIBLE` with one hard notary hit on weeks 3–4 in the **first** probe,
then `feasible` / notary 0 on **seven** later seed-2 months. Hamming is
**not** bitwise across repeats (`PYTHONHASHSEED=0` does not pin it). Do not
claim “freeze works at 8-stage”.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **N-R10 run** | P2 | Waves only at 16-stage seed=1 | 1600@8 seeds 1..2, `waves=4`. Typical probe: all eight weeks `feasible`, notary 0, occupancy **21** |
| **C6-R1-P0** | P0 | Infeasible week still chained | `_run_reshuffle_waves` stops; later weeks are not measured on a dirty incumbent |
| **C6-R1-P1** | P1 | Wave row had a count, not a kind | `notary_kinds`, `notary_sample`, `unrepaired_count` |
| **C6-R1-P2** | P1 | CLI treated skipped/missing dirty as OK | `nervous_report_ok` / `waves_all_feasible`; process exit 1 |

## Typical probe (this machine, native COVER, not the first run)

Cover matches C6a. `used_cpsat_fallback=False`. `unrepaired_count=0`.
`notary_kinds=[]`. Freeze calendar: day \(3+7w\).

| Seed | Cover tard / WIP / proc | w0 ham / tard | w1 ham | w2 ham / tard | w3 ham / tard / WIP |
|------|-------------------------|---------------|--------|---------------|---------------------|
| 1 | 87 134 / 155 / **21** | 0.00094 / 87 134 | 4.9e-5 | 0.00059 / **87 012** | 0.00015 / 87 012 / **154** |
| 2 | 164 355 / 206 / **21** | 0.00015 / 164 355 | **0** | 0.00030 / **164 185** | 0.00030 / 164 113 / 206 |

Wave-1 \(R=0\) on seed 2 is a **no-move** (N-R4), not freeze quality.
Repair 2.8–3.3 s. Wave 0 also ran a full re-cover (~4.4 s).

## First probe (kinds not captured; JSON later overwritten)

| Seed | Weeks |
|------|-------|
| 1 | 4/4 `feasible`, notary 0. Hamming **≠** typical (w0 \(R=0.00059\)) |
| 2 | w0–w1 `feasible`, notary 0, w1 \(R=0\). **w2 `infeasible` notary=1** \(R=0.00040\), tard 164 355→176 778, WIP 206→207, repair 4.44 s. **w3 chained** from that incumbent (`infeasible` notary=1). Contaminated |

Violation **kind** on the fail was not stored (pre-`notary_kinds`). Seven
later seed-2 months did not reproduce the fail, including four dedicated
retries. Hamming on those retries still moved (w2 \(R\) in
\(\{0.00030,0.00040,0.00050,0.00055\}\)). One feasible retry shared the
fail’s w2 Hamming \(0.00039694\) — same move-count is not the same oracle.

`PYTHONHASHSEED=0` twice: both all-feasible, Hamming **still differed**
(seed 1 w0 \(0.00059\) vs \(0.00069\)). Hash seed is not the control.

## Attacks that had to land

| Attack | Result |
|--------|--------|
| Four green weeks on seed 1 ⇒ freeze holds at 8-stage | **blocked** — seed 2 failed once; Hamming never bitwise |
| Wave-1 \(R=0\) ⇒ issued plan is frozen | **lands as N-R4** — no-move of the 20 targets, not a policy proof |
| Hamming 0.0003 is a campaign rewrite | **blocked** — ~3–19 ops of ~20k; neighbourhood 22–27 |
| Occupancy hit the pool ⇒ open C5a | **blocked** — proc **21** vs pool 48 vs span 154–207 |
| `allow_freeze_break=True` would make weeks green | **not used**. Would void the freeze |
| Infeasible week is a kernel false-FEASIBLE | **unproven** — IncrementalRepair returned `INFEASIBLE` with notary=1. Honest neighbourhood miss *or* a rare checker/repair disagreement. Kind unknown |
| `PYTHONHASHSEED=0` makes the month bitwise | **lands** — Hamming still moves. Native COVER / repair path-dependence (K3-adjacent) |
| Tiny GREED `waves=1` proves the month | **blocked** — plumbing only |
| CLI exit 0 while a week is dirty | **blocked** after this wave |
| Chain week 4 from week 3’s dirty assignments | **blocked** after this wave |

## Live residuals

| ID | Sev | Finding |
|----|-----|---------|
| **C6-R1-R1** | P1 | Seed-2 week 3 **can** be `INFEASIBLE` (1 observed / 8 seed-2 months). Kind not captured. Do not average it into a tardiness table |
| **C6-R1-R2** | P1 | Freeze-wave Hamming is path-dependent at 8-stage. Not a `wall_clock_path_dependent` stamp (repairs are 3–5 s). Neighbour of K3 |
| **C-R9** | P1 | Tardiness stays 87k / 164k. Wave cuts are tens–hundreds of minutes |
| **C6-R3** | P1 | Occupancy 21 ≪ pool 48 ≪ span. C5a still gated |
| **S4** | P1 | Exhaustive notary still re-checks ~20k ops / wave |

## Forbidden claims

Do not add: “four weekly waves are FEASIBLE at 8-stage”, “Hamming 0 means
the freeze held”, INFIMUM 39k/40 min, +78M ₽, LEAN −24% drums, OPTIMAL,
C5a, `allow_freeze_break` as the closer, PYTHONHASHSEED as a bitwise pin,
50k/500k FIFO change.

## Next honest step

S4 (delta notary). Do not open C5a. Do not put weights into COVER.
A gated IncrementalRepair determinism RFC is allowed only if a later
kernel wave needs bitwise repair; it is not a C5a license.

Reproduce (local evidence, not CI):

```
python -m synaps cable-nervous-month --orders 1600 --machines-per-stage 8 --drum-pool 48 --waves 4 --disruptions 20 --new-rush 0 --seeds 1,2
```
