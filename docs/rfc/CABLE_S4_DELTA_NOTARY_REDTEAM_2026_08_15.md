# S4 delta notary Red Team — 2026-08-15

Hostile pass on IncrementalRepair’s final notary. Claim level: **opt-in
completeness**, not a wall-time win, not a default flip, not OPTIMAL.

External frame (not a SOTA claim, not a shipped Θ-tree):

| Source | Role here |
|--------|-----------|
| Vilím, CPAIOR 2004, Θ-tree unary overload | Search-time unary analogue. We do **not** vendor a Θ-tree. Lemma U is the sequence-identity skip. |
| Wolf & Schrader, INAP 2005, O(n log n) cumulative overload | Shared-pool occupancy is a **profile / TimeTable**, not a neighbourhood slice. |
| McKeeman, *Digital Technical Journal* 10(1):100–107, 1998 | Exhaustive `FeasibilityChecker.check` is the reference oracle. `shadow` is fail-closed differential testing. |

Accel RFC **A4** already stated: one drum pool ⇒ a neighbourhood aux slice equals the full occupancy check and is **unsound** if you skip the background. S4 keeps the full aux sweep.

## Verdict

**ship with residuals; do not promote to default.** `notary="exhaustive"|"delta"|"shadow"`.
Default remains **exhaustive**. `shadow` uses exhaustive for the FEASIBLE claim.
Wave-row `_notary_hits` stays exhaustive (independent oracle). CLI:
`--repair-notary`. No segment tree: a one-shot post-repair TimeTable is already
O(n log n); a tree would pay off for repeated insert/delete during search.

## Completeness (what we actually prove)

| Lemma | Statement | Enforcement |
|-------|-----------|-------------|
| **C** | Missing/duplicate + referential integrity are full id-set scans | Never scoped |
| **A** | Aux Cumulative is a full event sweep; occupancy starts on skipped *serial* machines come from setup stamps | `_check_aux_pools`; A4 CI test |
| **U** | Unchanged *serial* sequences may skip the overlap/SDST walk | Parallel (`max_parallel>1`) never skipped |
| **P / O** | Precedence edges incident to dirty ops; duration/release/horizon/eligible on dirty ops | Scoped loops |
| **I** | Skipping unchanged serial machines ≡ exhaustive(R) only if those sequences were already feasible in B | CI attack; `shadow` fail-closes |

Lemma I is **not** a bug in shadow/exhaustive. It is why delta is not the default.

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **S4-P0** | P0 | Neighbourhood-only aux on one drum pool | Full TimeTable always. `test_lemma_a_aux_overload_outside_neighbourhood_is_still_caught` |
| **S4-P1** | P1 | Fake segment tree / default swap | No tree. Default exhaustive. Gate not used as a silent promote |
| **S4-P2** | P1 | No differential oracle | `shadow` + McKeeman fingerprint `(kind, op, wc)` |
| **S4-P3** | P1 | Checker `check()` had no scope, so “delta” would still be O(n) | `NotaryScope` skips serial unary + per-op families |
| **S4-P4** | P1 | Inherited frozen-machine overlap | `test_lemma_i_inherited_overlap_delta_misses_shadow_fail_closes`: delta misses, shadow mismatches, claim uses exhaustive |
| **N-R7 measure** | P2 | “Notary dominates repair wall” | **Falsified on this machine.** Cover notary 0.22 s. Repair 2.23–2.46 s of which shadow notary 0.37–0.48 s (both checkers). Placement dominates. |

## Local probe (not CI) — 1600@8, `--repair-notary shadow`

`orders=1600`, `machines/stage=8`, `drum_pool=48`, `waves=4`, `disruptions=20`,
`new-rush=0`, seeds 1–2, `PYTHONHASHSEED=0`, this machine 2026-08-15.

| Seed | Ops | Cover | Cover notary | Waves | `repair_notary_mismatch` | Independent wave notary |
|------|-----|-------|--------------|-------|--------------------------|-------------------------|
| 1 | 20 316 | 4.26 s, FEASIBLE | 0.22 s, 0 | 4/4 `feasible` | **False** on all four | 0, kinds `[]` |
| 2 | 20 154 | 4.23 s, FEASIBLE | 0.23 s, 0 | 4/4 `feasible` | **False** on all four | 0, kinds `[]` |

Dirty set per wave: **36–53 ops**, **36–43 machines** (shop has 48 work centers).
Hamming can be 0 while `notary_delta_ops` is still ~40: freeze-boundary ops are
conservatively added to C. Unary skip therefore does **not** shrink the shop to
a small neighbourhood. Shadow notary 374–484 ms ≈ two exhaustive sweeps.

**Not claimed:** delta is faster; delta is the new default; freeze “works” at
8-stage (C6-R1 Hamming path-dependence remains; this probe happened to be all
green). Eight matching weeks on two seeds is **evidence**, not a proof for
infeasible baselines, parallel machines, or other seeds.

## Attacks that had to land

| Attack | Result |
|--------|--------|
| Neighbourhood aux on the shared drum pool (A4) | **blocked** — full sweep; CI plants frozen overlap off the dirty op |
| Skip serial unary ⇒ inherit a frozen MACHINE_OVERLAP (Lemma I) | **lands on delta**, **blocked on shadow/default** |
| Skip parallel lane inference via stamp-fill | **blocked** — `max_parallel>1` never skipped |
| Empty baseline + `notary=delta` | **blocked** — falls back to exhaustive |
| Promote default because 1600@8 matched | **blocked** — conservative reading of the gate; next RFC |
| Put `CABLE_PVC_WEIGHTS` into COVER / open C5a / UCB1 default | **blocked** |
| Wave-row notary uses delta so a mismatch can publish FEASIBLE | **blocked** — `_notary_hits` stays exhaustive |
| Segment tree as theatre | **blocked** — documented non-delivery |

## Live residuals

| ID | Sev | Finding |
|----|-----|---------|
| **S4-R1** | P1 | Default is still exhaustive. Promotion needs a dedicated RFC (more seeds, infeasible-injection, parallel WCs) |
| **S4-R2** | P2 | Freeze-boundary inflates C when Hamming is 0 (~40 ops / ~40 WCs). Tighten later |
| **S4-R3** | P2 | Shadow is slower than exhaustive (runs both). Use it as an oracle, not a hot path |
| **S4-R4** | P2 | Stamp-fill on skipped serial machines trusts `assignment.setup_minutes`; matrix-recomputed windows remain the exhaustive path |
| **C6-R1-R2** | P1 | Freeze-wave Hamming path-dependence is a different kernel |
| **C-R2** | P3 | `peak_wip_drums` vs occupancy vs Cumulative hold — docs only |

## Forbidden claims

Do not add: default delta, segment tree shipped, SOTA filtering, Vilím/Wolf
implemented, INFIMUM, C5a, “notary dominates repair so we are now <1 s”,
OPTIMAL, Moskabelmet MES, 8-stage freeze quality.

## Next honest step

C-R2 documentation accuracy (span vs occupancy vs Cumulative hold). C5a stays
gated. Do not put weights into COVER. Do not flip ALNS to UCB1. Do not flip
the notary default in the same breath as this probe.
