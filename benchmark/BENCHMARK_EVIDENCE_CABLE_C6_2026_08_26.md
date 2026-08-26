# Cable C6a / C6-R1 — 2026-08-26

> Not Moskabelmet MES. Not INFIMUM. Not a freeze-quality proof.

[АРТЕФАКТ: `benchmark/evidence/cable-c6-2026-08-25/`, 2026-08-26]

Command: `python -m benchmark.study_cable_variance`

## P1.1 — generator seeds 1..10 (1600@8, waves=0)

All ten COVER-feasible, notary 0.

Tardiness minutes by generator seed:

| seed | ops | tardiness |
| --- | --- | --- |
| 1 | 20316 | 87134 |
| 2 | 20154 | 164355 |
| 3 | 19860 | 131980 |
| 4 | 20136 | 84156 |
| 5 | 19932 | 48269 |
| 6 | 20208 | 151960 |
| 7 | 20004 | 112047 |
| 8 | 20154 | 124644 |
| 9 | 19968 | 145731 |
| 10 | 20544 | 186947 |

min / median / max = **48269 / 128312 / 186947**.
mean 123722, sample sd 41810, CV 0.338.
max/min = **3.87×** (was 3.40× on seeds 1..5).

[КОД: `benchmark.evidence_common.summarize_seed`] Student t 95% (n=10, df=9,
t=2.2621571627409915): mean 123722.3, sample sd 41810.256, half-width 29909.255
→ **[93813.045, 153631.555]**.
The previous hand row (mean 123722, ±29916 → [93806, 153638]) was rounding of
the same sample; hashed JSON was not rewritten.

### Is the 3.4× (now 3.87×) spread the instance, the generator, or the solver?

Fixed instance (`generate_nervous_month` seed=1, 1600@8, family+colour-phase)
re-solved with `RHC-GREEDY-COVER` `random_seed` ∈ {1, 42, 999}:

tardiness **87134, 87134, 87134**. CV 0. Identical coverage 20316/20316.

**Answer: generator / instance.** The COVER list-schedule does not move when only
the solver seed changes. Different generator seeds produce different op counts
(19860–20544) and a 3.87× tardiness range. Do not quote 87134 as “the” 8-stage number.

## P1.2 — C6-R1 seed 2, waves=4

This run: cover feasible, notary 0; weeks 0–3 all `feasible`, `notary_kinds=[]`.
Hamming path-dependent (wave 1 R=0 is a no-move).

**INFEASIBLE on weeks 3–4 was not reproduced.** The historical fail remains
**unconfirmed**. Kind is still unknown. Do not describe the freeze as a
stable pass.

## SHA-256

| File | SHA-256 |
| --- | --- |
| `generator_seed_1_to_10.json` | `4cca14189895f7c7642dc2ce998244dddfd3a9d73fcbd7983e44aba9b23740b1` |
| `solver_seed_fixed_instance.json` | `937a0db63eaafc5fd25502e2f4503c2ab7037de616be1c5783e3ce9c018b36b9` |
| `c6_r1_seed2_waves4.json` | `940389c492dd70466e7be1245f06673229d187a9c23ede2fca4ba49b4b32c7a3` |
| `summary.json` | `b30c05dbefcb5c8cf8d24fab7bc138ebbf4e17482238f3b84645831df231fbfb` |
| `environment.json` | `2cff46cd3e13efb2f81617c9dea08ce2fb5c466acf7970294c7eb7df0a6e3e7e` |
| `SHA256SUMS.txt` | `addaa87109f0cd54c3e1b113321c829f5b15a6b0dca7fe73e0ae02fea77ad43c` |
