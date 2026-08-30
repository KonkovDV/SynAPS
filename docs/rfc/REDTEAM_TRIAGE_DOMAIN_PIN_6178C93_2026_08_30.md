# Red Team triage — domain pin bump to kernel `6178c93` (2026-08-30)

Claim level: **honesty**. Not a COVER rewrite. Not a hashed P2.3 Yes.
Not a 5k recapture. Not a plant pilot. Not N-1 / SAIDI / INFIMUM / live EL5 /
MAST. Not a reopen of KI-N12.

Kernel origin `main`: `6178c93b705ff58be21fa74a98651883a2da1169`.
Previous origin domain pin: `54ebf9f32bc871cc27283331d7536c1068c7e606`
([GridPlan #7](https://github.com/KonkovDV/SynAPS-GridPlan/pull/7),
[MobiRoute #4](https://github.com/KonkovDV/SynAPS-MobiRoute/pull/4)).

This bump: GridPlan **0.1.2** ([#8](https://github.com/KonkovDV/SynAPS-GridPlan/pull/8)),
MobiRoute **0.2.2** ([#5](https://github.com/KonkovDV/SynAPS-MobiRoute/pull/5)),
same full 40-char SHA. Worktree for GridPlan is `origin/main`, not the
diverged local 0.1.10 tree.

## Verdict

**ship.** ADR-0004 regressions on the new pin:

1. Fail-closed coverage: `EMPTY`+`FEASIBLE` is `ERROR`; CLI codes 0/2/3/1.
2. Non-empty `WorkCenter.calendar` is **encoded** by CP-SAT/ALNS/LBBD
   (occupancy in one shift) and clipped by greedy. Auto-route stays
   `CALENDAR_AWARE`. Domain tests that still expected `calendar_unsupported`
   refuse on this SHA would be false. They are encode tests now.
3. Kernel `python scripts/verify_claims.py` is already green on this SHA.

KI-N12 stays **closed**. Open-ended lag after 2026-09-09 remains forbidden.
Pin is a full SHA, never `main`.

## Closed this pass

| ID | Sev | Finding | Close |
| --- | --- | --- | --- |
| Domain pin lag | P3.3 | Origin domains still named `54ebf9f` while kernel origin is `6178c93` | New pin 0.1.2 / 0.2.2; not a float; not N12 reopen |
| Calendar refuse vs encode | P1 | Kernel `2795faf` encodes occupancy; domain refuse tests would fail | `test_cpsat_alns_lbbd_encode_nonempty_calendar` (mirror kernel node) |
| Local GridPlan as product | P1 | Local `main` is 0.1.10 / `6fd3393`, 14 ahead / 28 behind origin | Edit only a worktree of `origin/main`. Do not merge that history |

## Fell before the bump (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_synaps_pin_regression.py::test_pin_is_residuals_kernel_sha` | asserted `54ebf9f32bc871cc27283331d7536c1068c7e606` |
| `tests/test_synaps_pin_regression.py::test_cpsat_alns_lbbd_refuse_nonempty_calendar` | `calendar_unsupported is True` and empty assignments on `6178c93` |

## Attacks

| Attack | Result |
| --- | --- |
| Cite local GridPlan 0.1.10 / `6fd3393` as the origin pin | **blocked** — product is origin `main` (was 0.1.1 / `54ebf9f`) |
| Reopen KI-N12 | **blocked** — N12 closed on #7/#4; this is a new pin |
| Float the pin on kernel `main` | **blocked** — full 40-char SHA in code, lockfile, CI |
| Keep refuse tests on an encode kernel | **blocked** — encode node; `auto_greedy_warm_start=False` |
| Claim packing Yes / hashed P2.3 Yes / remainder 5k@4 Yes | **blocked** — matching leftover 38 / 117 / 122; freeze stays no |
| Rewrite hashed kernel JSON | **blocked** |
| Cite domain jury/emergency/scale as kernel 50k/500k | **blocked** — different algebra |
| Claim N-1 / SAIDI / live plant / operator pilot | **blocked** |
| Retune `global_greedy_cover_min_ops` or `_NATIVE_LIST_SCHEDULE_MIN_OPS` | **blocked** — both stay 10_000 |
| Merge diverged local GridPlan 14 commits into this bump | **blocked** |

## Residuals (not this commit)

| Residual | Why it stays |
| --- | --- |
| Local GridPlan 0.1.10 tree | Separate history; not the public product |
| Hashed P2.3 / night analog leftover | Unchanged; not a domain KPI |
| Kernel origin `main` ruleset | Domain and kernel docs land via PR if direct push is rejected |
| Open-ended lag after 2026-09-09 | Still forbidden; this bump is 2026-08-30 |

## Non-claims

- Not a Yes on hashed 5k@8, hashed COVER 100k seed 42, hashed remainder, or
  hashed calendar-3000.
- Not a three-seed night analog Yes.
- Not GridPlan analog of MobiRoute `a2-16` unless asked.
- Not a live plant calendar. Night analog is per-op windows.
- Not MicroPhoenix. Not `C:\plans`.
