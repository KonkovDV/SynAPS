# ADR-0004: Domain-repository portfolio standard and kernel pin lag

- **Status:** Accepted
- **Date:** 2026-08-26
- **Related:** ADR-0003 (placement)

## Standard (all public domain repos)

| Field | Rule |
| --- | --- |
| GitHub default branch | Recorded in the README table. Kernel, GridPlan, and MobiRoute: `main`. |
| README header | Table with **Version**, **SynAPS pin** (link to the full commit URL), **Maturity** (ISO 16290 TRL + one-line not-claim). |
| Kernel pin | Full SHA in code + README. Never `main`/`master` as a pin. CI must fail if the declared SHA and the install pin diverge. |
| `docs/` | At least: architecture or constraints, limitations/non-claims, evidence or benchmark protocol. |
| `APPLICATION.md` | Required if the repo is (or was) a contest/customer packet. Kernel has no product application; domains that apply must keep this file. |
| Rust | Optional unless the domain claims a native checker/kernel as part of the product (GridPlan checker: optional acceleration of the same rules; MobiRoute insertion: **required** for greedy/beam/ALNS). State the role in the README table. |
| Status vocabulary | `heuristic_feasible` — search returned a schedule; independent checker not yet the claim. `verified` — independent checker reports `proven_hard_violations = ∅` (or domain equivalent). `optimal` — only if the exact solver proved OPTIMAL **and** the independent checker is empty. Never “industrial deployment”. |

## Pin lag (P3.3)

GridPlan pin: `54ebf9f32bc871cc27283331d7536c1068c7e606`
([b795361](https://github.com/KonkovDV/SynAPS-GridPlan/commit/b795361116739e0f613112d636f9027cb22e75b4)).
MobiRoute pin: the same kernel SHA
([066579b](https://github.com/KonkovDV/SynAPS-MobiRoute/commit/066579b561a93b36b2b55ae7b89a6fbca5fa2bc2)).

**2026-08-27:** waiting until 2026-09-09 is no longer the plan. Domain PRs
bumped to that kernel commit (full 40-char SHA, never `main`). The bump
regression-ran:

1. Fail-closed coverage (`EMPTY`+`FEASIBLE` is `ERROR`; CLI codes 0/2/3/1).
2. Non-empty `WorkCenter.calendar` is refused by CP-SAT/ALNS/LBBD and clipped
   by greedy paths.
3. Kernel `python scripts/verify_claims.py` on the pinned SHA (already green
   in kernel CI).

KI-N12 is **closed** on those domain SHAs. A later kernel merge-commit
(`09f7322`) is a descendant of the pin; domains do not float on `main`.

Night/emergency work in a domain layer is not a kernel calendar promise:
only greedy-family configs clip shifts, and windowed coverage on the night
analog is 0.75–0.88 (`benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md`).

**Not allowed:** floating “latest SynAPS”, or claiming GridPlan/MobiRoute
results as kernel 50k/500k evidence (different algebra).

## Applied this iteration

- 2026-08-26: GridPlan README header (Version 0.1.1, pin `bd09d13`, TRL 4).
  MobiRoute 0.2.1, pin `5168fc7` under the then lag rule.
- 2026-08-27: lag-until-2026-09-09 is withdrawn as a wait. Domain PRs
  merged: GridPlan [#7](https://github.com/KonkovDV/SynAPS-GridPlan/pull/7)
  `b795361`, MobiRoute [#4](https://github.com/KonkovDV/SynAPS-MobiRoute/pull/4)
  `066579b`, pin `54ebf9f`. KI-N12 closed.
