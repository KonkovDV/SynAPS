# K2 ALNS MAB Red Team — 2026-08-15

Hostile pass on UCB1 destroy×repair selection. Claim level: **plumbing**.
Not a quality DOE. Not SOTA. Not cable ATP.

External frame (not a bake-off): Ropke & Pisinger (2006) select destroy and
repair **independently** by roulette. The `alns` 7.x package ships Hendel
(2022) **α-UCB on pairs** and a MABWiser wrapper
([docs](https://alns.readthedocs.io/en/latest/api/select.html)). BALANCE
(AAAI 2024) is bi-level MAB over destroy + neighbourhood size. Balans
(IJCAI 2025; arXiv:2412.14382) treats each destroy×repair pair as one arm.
SynAPS already did pair-UCB1 in Wave 6 (`mab_pair_selection`). K2 is the
seeded-determinism gate the 2026-08-15 executor plan still listed as open.

## Verdict

**ship with residuals.** UCB1 stays **opt-in**. ALNS-300/500/1000 kwargs do
not set the flag (default roulette). Two greedy-repair MAB runs at
`random_seed=123` matched makespan, iteration count, and `mab_pair_pulls`.
`use_cpsat_repair` default remains True — that path is **not** the K2
claim. Native `p_{o,m}` ABI stays deferred (KI-F16 / Wave 10). Native
rank already snaps `base/speed` to ceil grain (`tests/test_alns_native_grain.py`,
Wave 15 F2). `stress_200` 2–3 s is **not** claimed.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **K2-P0** | P0 | “Ship UCB1” as if it were missing | Flag exists since Wave 6. K2 does not re-implement the bandit |
| **K2-P1** | P1 | No seeded MAB determinism test | `test_mab_alns_seeded_determinism`: greedy repair, same seed, matching cost + pulls |
| **K2-P2** | P1 | Default could silently flip | `test_mab_pair_selection_defaults_off_and_registry_stays_roulette` |
| **K2-P3** | P2 | Pulls invisible | metadata `mab_pair_pulls` via `pair_pulls` |
| **K2 native snap** | P2 | Rank leftover unread | F2 tests still pin ceil grain; ABI leftover is `p_{o,m}`, not the snap |

## Attacks that had to land

| Attack | Result |
|--------|--------|
| K2 changes ALNS-300 default to UCB1 | **blocked** — registry kwargs omit the flag |
| Seeded test with default CP-SAT repair proves bitwise MAB | **blocked** — test forces `use_cpsat_repair=False` |
| Classic UCB1 is Hendel α-UCB / Balans | **lands as wording** — reward is normalized Δcost / −0.05 reject, not Hendel scores or Balans four-way SA outcomes |
| D5 95% CI on `medium_stress_20x4` | **not run** — design protocol remains a residual. No “MAB beats roulette” |
| `wall_clock_path_dependent=False` when 12/12 iters finish | **lands** — the boolean is **hardcoded True**. Live discriminator is `search_stop_reason` (`max_iterations` on the K2 fixture). Fixing the boolean is K3 |
| PairBandit uses `random` | **blocked** — `test_pair_bandit_select_is_rng_free` |
| Open C5a / put weights into COVER / claim freeze waves | **blocked** — out of wave |
| Native SDST `p_{o,m}` ABI this wave | **blocked** — permanent deferral |
| `stress_200` is now 2–3 s | **blocked** |

## Live residuals

| ID | Sev | Finding |
|----|-----|---------|
| **K2-R1** | P1 | Design D5 quality protocol unrun. Opt-in ≠ better |
| **K2-R2** | P2 | Default ALNS still CP-SAT-repairs; MAB×CP-SAT not in the seed test |
| **K3** | P2 | **closed**: boolean matches wall cut; repair clamp residual remains |
| **K2 ABI** | P2 | Native pack is still not a duration matrix ABI |
| **P4-M1** | P3 | `stress_200` ~8.1 s claim unchanged |

## Forbidden claims

Do not add: “UCB1 is now the ALNS default”, “MAB closed tardiness”, Hendel
α-UCB, Balans IJCAI as SynAPS evidence, OPTIMAL, SOTA, INFIMUM, C5a,
`p_{o,m}` native ABI shipped, 2–3 s `stress_200`.

## Next honest step

S4 delta notary (prove ≡ exhaustive before default).
Do not change ALNS defaults.
