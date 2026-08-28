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

GridPlan pin (2026-08-26 close): `bd09d13561b3bd690845d07546def59b4521b16c`.
MobiRoute pin (same era): `5168fc71005653945097e1f07ada1ce9cbc02eec`.

**2026-08-27:** waiting until 2026-09-09 is no longer the plan. Domain PRs
must bump to the kernel commit that lands this residuals drop (full 40-char
SHA, never `main`). That bump must regression-run:

1. Fail-closed coverage (`EMPTY`+`FEASIBLE` is `ERROR`; CLI codes 0/2/3/1).
2. Non-empty `WorkCenter.calendar` is encoded by CP-SAT/ALNS/LBBD (occupancy
   in one shift) and clipped by greedy paths. Auto-route stays `CALENDAR_AWARE`.
3. Kernel `python scripts/verify_claims.py` on the pinned SHA (already green
   in kernel CI).

Those domain PRs merged on 2026-08-28. Record the SHAs here and in each
domain README.

**2026-08-28:** GridPlan #7 and MobiRoute #4 merged. Both origin READMEs pin
`54ebf9f32bc871cc27283331d7536c1068c7e606`. KI-N12 is **closed**. Kernel origin
`main` is `8be2830` (night-window papers); local packing may be ahead of
origin. The next domain bump is a new pin to a kernel SHA on origin, still
before 2026-09-09. Do not treat a diverged local GridPlan checkout as the
product pin.

Night/emergency work in a domain layer is not a kernel calendar promise:
greedy-family configs clip shifts; exact/ALNS encode when selected; windowed
coverage on the night analog is 0.75–0.88
(`benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md`).

**Not allowed:** floating “latest SynAPS”, or claiming GridPlan/MobiRoute
results as kernel 50k/500k evidence (different algebra).

## Applied this iteration

- 2026-08-26: GridPlan README header (Version 0.1.1, pin `bd09d13`, TRL 4).
  MobiRoute 0.2.1, pin `5168fc7` under the then lag rule.
- 2026-08-27: lag-until-2026-09-09 is withdrawn as a wait. Domain PRs bump
  pins to kernel `54ebf9f32bc871cc27283331d7536c1068c7e606`
  ([GridPlan #7](https://github.com/KonkovDV/SynAPS-GridPlan/pull/7),
  [MobiRoute #4](https://github.com/KonkovDV/SynAPS-MobiRoute/pull/4))
  and must pass the three regression bullets above. KI-N12 stays open
  until those PRs merge.
- 2026-08-28: those PRs merged. Origin pins recorded. KI-N12 closed.
