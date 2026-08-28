# Red Team triage — KI-N12 close, same-night fifo, home insertion (2026-08-28)

Claim level: **honesty**. Not a hashed P2.3 Yes. Not a hashed remainder Yes.
Not a rewrite of hashed epoch JSON. Not a retune of
`global_greedy_cover_min_ops` (still 10_000) or
`_NATIVE_LIST_SCHEDULE_MIN_OPS` (still 10_000).
Not a three-seed night analog Yes.

Parent packing RFC:
`docs/rfc/REDTEAM_TRIAGE_NIGHT_WINDOWS_2026_08_28.md`.

## Verdict

**ship.** Close KI-N12 (origin pin PRs merged). Windowed fifo prefers
same-night home/continuation before steal. List-schedule tries the
exclusive home tail and home gap before a steal tail. Matching session
`night-window-match-2026-08-28/` stays the 5k packing pin. Hashed P2.3
stays **no**.

## Closed this pass

| ID | Sev | Finding | Close |
| --- | --- | --- | --- |
| KI-N12 | MEDIUM | Domain pin PRs open until merge | GridPlan [#7](https://github.com/KonkovDV/SynAPS-GridPlan/pull/7) and MobiRoute [#4](https://github.com/KonkovDV/SynAPS-MobiRoute/pull/4) merged. Origin READMEs pin `54ebf9f32bc871cc27283331d7536c1068c7e606`. `tests/test_known_issues_registry.py` requires `| closed |` |
| Same-night fifo | packing | `(due, state_id)` popped steal onto an empty home | `test_list_schedule_fills_home_before_steal_when_family_uuid_sorts_later` |
| Global fifo | packing | All-nights home-before-steal leftover 553, ratio 0.8900 seed 1 | Preference is per `_window_night_key`. `test_list_schedule_same_night_fifo_does_not_defer_steal_behind_later_nights` |
| Home insertion | packing | Steal tail on idle M2 skipped a 0-200 hole on the home | `test_list_schedule_inserts_home_gap_before_steal_tail` |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_known_issues_registry.py` KI-N12 row | status was `open` after GridPlan #7 and MobiRoute #4 merged |
| `tests/test_rhc_cover.py::test_list_schedule_fills_home_before_steal_when_family_uuid_sorts_later` | fifo popped a 20-min steal onto empty M1; 40 SDST leftover the third 150-min A |
| `tests/test_rhc_cover.py::test_list_schedule_same_night_fifo_does_not_defer_steal_behind_later_nights` | global scan delayed night-1 leftover past `latest_finish` |
| `tests/test_rhc_cover.py::test_list_schedule_inserts_home_gap_before_steal_tail` | appending SGS stole idle M2 instead of inserting into the home hole |
| list-schedule 5k@8 seed 1 global fifo probe | leftover 553, ratio 0.8900, wall 43.984 s. Do not restore |

## Attacks

| Attack | Result |
| --- | --- |
| Leave KI-N12 open after merge | **blocked** — status `closed`; origin pins recorded in ADR-0004 |
| Cite a local GridPlan 0.1.10 / `6fd3393` checkout as the origin pin | **blocked** — origin README is 0.1.1 / `54ebf9f`. Local checkout is not the product pin |
| Reopen KI-N12 because kernel origin is `8be2830` | **blocked** — that lag is a new pin, not N12 |
| Lower `global_greedy_cover_min_ops` | **blocked** — still 10_000 |
| Lower `_NATIVE_LIST_SCHEDULE_MIN_OPS` | **blocked** — still 10_000 |
| Restore global (all-nights) home-before-steal | **blocked** — seed 1 leftover 553, ratio 0.8900 |
| Cite a scratch 5k fifo/home-gap probe as denser than matching | **blocked** — generator IDs are `uuid4`; leftover is not a recapture delta |
| Cite matching 0.9924 / FFD 0.9912 / fifo as a P2.3 Yes | **blocked** — leftovers; hashed freeze stays `no` |
| Skip home gap and steal an idle foreign tail | **blocked** — home tail+gap first |
| Rewrite hashed deadzone / COVER / ALNS / calendar JSON | **blocked** |
| Raise `time_limit_s` or night width | **blocked** |
| 6-pass eject | **blocked** — measured regression; single eject only |
| Grandfather packing helpers onto the 80-line ratchet | **blocked** — split |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** |
| Cite native list-schedule as carrying fifo/home-gap | **blocked** — native path is n>=10_000; windowed 5k is Python |

## Residuals (not this commit)

| Residual | Why it stays |
| --- | --- |
| `_window_night_key` is `earliest_start.date()` | A 22:00-06:00 window can split at midnight if earliest is after 00:00. Deadzone generator stamps one earliest per night (22:00), so 5k analog is one key. Staggered earliest inside that window is untested |
| Home tail still before home gap | If a late home tail fits, the interior hole is not used. Pre-existing tail-then-gap. Home-first only wins when the home tail is infeasible |
| Gap rank uses `last_state=None` | Interior insert does not score same-state continuation. Home preferred still wins on `wc_id in home_wcs` |
| Continuation is machine-global | `_windowed_op_has_direct_tail` treats `last_state == op.state_id` as direct even when `last_end` is a previous night. Slot ranking still prefers the night home |
| No new 5k session | `uuid4` IDs. Pin stays `night-window-match-2026-08-28/` leftover 38 / 117 / 122 |
| Hashed P2.3 / remainder / 5k@4 / 8k@4/8 | Freeze and processing LB unchanged |
| Origin `main` ruleset | Direct push may still require a PR. Local `29258e3` plus this drop sit on `main` |

## Non-claims

- Not a Yes on hashed 5k@8, hashed COVER 100k seed 42, hashed remainder, or hashed calendar-3000.
- Not a three-seed night analog Yes.
- Not a uniformly denser packing than FFD (matching seeds 42/999 leftover grew).
- Not a domain pin bump past `54ebf9f`.
- Not a live plant calendar. Night analog is per-op windows.
