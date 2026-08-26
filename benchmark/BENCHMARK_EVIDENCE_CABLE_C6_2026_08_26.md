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

[ОЦЕНКА] Student t 95% (df=9, t=2.262): mean ± 2.262·s/√10 ≈ 123722 ± 29916 → **[93806, 153638]**.
The helper in `evidence_common.summarize_seed` only emits a t-interval for n=3;
this interval is computed by hand from the same sample.

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
| `generator_seed_1_to_10.json` | `e978413d6e6c4ce9b997df4070d1ea9eb71535d9fad194fd15512a83f8cb34bd` |
| `solver_seed_fixed_instance.json` | `3a89bde5e070cffbc38924cadbcf8dd7c4f5246dc78ac2956a92be81ff07d00d` |
| `c6_r1_seed2_waves4.json` | `10948c01218df34f6f295218ea8f8d3d1c16d69096216375c20bb9a72970a40b` |
| `summary.json` | `20e27553fb282d616d2413eb27942be91bfe7a8f2976d0c215eb72bbdc3fab9a` |
| `environment.json` | `276fb9dad6265ce0e1e9ce6c4ec8e9a69eca35e6560f430794503740f5a8603a` |
| `SHA256SUMS.txt` | `fd6c7bb25d393b691c84a6d4c58da9f08dbca6b18c299f01718625fe93279175` |
