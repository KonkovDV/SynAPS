# ADR-0004: Domain-repository portfolio standard and kernel pin lag

- **Status:** Accepted
- **Date:** 2026-08-26
- **Related:** ADR-0003 (placement)

## Standard (all public domain repos)

| Field | Rule |
| --- | --- |
| GitHub default branch | Recorded in the README table. Kernel: `master`. GridPlan GitHub default: `main`. MobiRoute: `master`. Do not mass-rename in this iteration. |
| README header | Table with **Version**, **SynAPS pin** (link to the full commit URL), **Maturity** (ISO 16290 TRL + one-line not-claim). |
| Kernel pin | Full SHA in code + README. Never `main`/`master` as a pin. CI must fail if the declared SHA and the install pin diverge. |
| `docs/` | At least: architecture or constraints, limitations/non-claims, evidence or benchmark protocol. |
| `APPLICATION.md` | Required if the repo is (or was) a contest/customer packet. Kernel has no product application; domains that apply must keep this file. |
| Rust | Optional unless the domain claims a native checker/kernel as part of the product (GridPlan checker: optional acceleration of the same rules; MobiRoute insertion: **required** for greedy/beam/ALNS). State the role in the README table. |
| Status vocabulary | `heuristic_feasible` — search returned a schedule; independent checker not yet the claim. `verified` — independent checker reports `proven_hard_violations = ∅` (or domain equivalent). `optimal` — only if the exact solver proved OPTIMAL **and** the independent checker is empty. Never “industrial deployment”. |

## Pin lag (P3.3)

GridPlan pin: `bd09d13561b3bd690845d07546def59b4521b16c` (kernel HEAD at the
2026-08-26 close).
MobiRoute pin: `5168fc71005653945097e1f07ada1ce9cbc02eec`.

Kernel HEAD at the honesty-gate round is `515488b`. Pins stay. **Sync date:
2026-09-09.** Until that date, pin lag is allowed under the four conditions
below. After 2026-09-09 the lag rule closes: a domain pin bump must
regression-run:

1. Fail-closed coverage (`EMPTY`+`FEASIBLE` is `ERROR`; CLI codes 0/2/3/1).
2. Non-empty `WorkCenter.calendar` is refused by CP-SAT/ALNS/LBBD and clipped
   by greedy paths.
3. `python scripts/verify_claims.py` (explicit non-claims markers, not a
   `не`/`not` skip).

Until then, night/emergency work in a domain layer is not a kernel calendar
promise: only greedy-family configs clip shifts, and windowed coverage on the
night analog is 0.75–0.88 (`benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md`).

**Until 2026-09-09**, divergence is allowed when all of the following hold:

1. The domain does not call kernel APIs introduced after its pin, or it does not call the kernel solver at all (MobiRoute: engineering reference / adapter pin, own DARP search).
2. README and a `SYNAPS_COMMIT` constant match.
3. The lag reason is written (this ADR + domain README).
4. Bumping the pin is a domain release, not a courtesy sync.

**Not allowed:** floating “latest SynAPS”, or claiming GridPlan/MobiRoute results as kernel 50k/500k evidence (different algebra).

GridPlan is **not** bumped to `fe1c6a8` in this iteration: the kernel added
`WorkCenter.calendar` after `bd09d13`; a pin bump without a GridPlan
regression run would be a false hygiene signal. MobiRoute stays `5168fc7`
(DARP search is not the COVER path).

MobiRoute is **not** bumped to `bd09d13` in this iteration: DARP search is not the kernel COVER path; a pin bump without a domain regression run would be a false hygiene signal.

## Applied this iteration

- GridPlan README already matches the header table (Version 0.1.1, pin `bd09d13`, TRL 4). `APPLICATION.md` present. Rust checker optional.
- MobiRoute README header and `APPLICATION.md` brought to this standard. Version on disk is **0.2.1** (not 0.1.1). Pin stays `5168fc7` under the lag rule. Rust insertion kernel is required for the listed heuristics.
