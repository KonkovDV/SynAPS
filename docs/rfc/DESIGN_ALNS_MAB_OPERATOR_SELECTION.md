# Design note: MAB selection of ALNS destroy/repair pairs (T-34)

- **Status:** Implemented (Wave 6) + K2 determinism gate (2026-08-15).
  UCB1 over destroy×repair pairs (`cpsat|greedy`) via `mab_pair_selection`.
  Default remains legacy roulette (ALNS-300/500/1000 kwargs omit the flag).
  Seeded greedy-repair test: `tests/test_alns_mab.py`.
  Not Hendel (2022) α-UCB. D5 quality DOE is **not** this wave.
- **Date:** 2026-08-11; K2 2026-08-15

## Current behavior

ALNS already maintains adaptive operator weights (score / effort) and SA
acceptance. Selection is weight-proportional over individual destroy and repair
operators, not over pairs, and has no explicit regret accounting.

## Proposal

Layer a bandit over **pairs** `(destroy_i, repair_j)`:

| Algorithm | Pros | Cons |
|---|---|---|
| UCB1 | Simple, proven regret bounds | Needs careful reward scaling |
| Thompson (Beta/Gaussian) | Stable under sparse rewards | Extra hyperparameters |

**Reward:** normalized improvement
`max(0, (cost_before - cost_after) / max(1, cost_before))` on accepted moves;
small negative on rejected moves (optional). Keep existing weight updates as a
fallback prior for cold start.

## Evaluation protocol (D5)

- Suites: `tests/test_alns_*` smoke + DOE via `benchmark/study_*` with
  `--repeats ≥ 5` and 95% CI on makespan / coverage.
- Success: mean makespan improvement with CI not overlapping zero on
  `medium_stress_20x4` and one industrial smoke, without timebox overshoot.
- **K2 did not run D5.** Seeded determinism ≠ quality. Residual **K2-R1**.

## Non-goals

- Replacing SA acceptance
- Learning across instances (leave to `ml_advisory` k-NN)
