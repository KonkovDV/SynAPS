# Red Team triage — foreign-home reserve, same-night continuation (2026-08-30)

Claim level: **honesty**. Not a hashed P2.3 Yes. Not a hashed remainder Yes.
Not a rewrite of hashed epoch JSON. Not a retune of
`global_greedy_cover_min_ops` (still 10_000) or
`_NATIVE_LIST_SCHEDULE_MIN_OPS` (still 10_000).
Not a three-seed night analog Yes. Not a new 5k session.

Parent packing RFC:
`docs/rfc/REDTEAM_TRIAGE_NIGHT_WINDOWS_2026_08_28.md`.
Home-gap / night-key parent:
`docs/rfc/REDTEAM_TRIAGE_HOME_GAP_NIGHT_KEY_2026_08_28.md`.

## Verdict

**ship.** Main-pass steal skips a foreign exclusive home while that
resident still has unscheduled same-night ops. Leftover retry then
steals into leftover slack (full no-steal leftover 417; do not restore).
Fifo continuation is same-night only: yesterday's `last_state` cannot
pop a steal ahead of tonight's home. Matching session
`night-window-match-2026-08-28/` stays the 5k packing pin. Hashed P2.3
stays **no**. Kernel origin `main` after PR #21 is `501f449`.

## Closed this pass

| ID | Sev | Finding | Close |
| --- | --- | --- | --- |
| Foreign-home reserve | packing | Heap-order steal occupied empty M1 while 3x150 A was unfinished | `_foreign_homes_to_reserve` in the main pass and leftover wave 1. Wave 2 steals. `test_list_schedule_reserves_foreign_home_when_heap_pops_steal_first` |
| Previous-night continuation | packing | Night-1 B on M1 made night-2 steal B look direct; 20+40+450 > 480 | `_windowed_op_has_direct_tail` requires `last_end` on this night. `test_list_schedule_previous_night_state_does_not_steal_before_resident` |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_rhc_cover.py::test_list_schedule_reserves_foreign_home_when_heap_pops_steal_first` | with fifo disabled, B-20 sat on empty M1 and leftover an A |
| `tests/test_rhc_cover.py::test_list_schedule_previous_night_state_does_not_steal_before_resident` | night-1 B continuation popped a night-2 steal onto A's home |
| `tests/test_rhc_cover.py::test_list_schedule_overflow_fits_in_home_slack` | full no-steal leftover the 50-min overflow after the resident packed; leftover retry must still steal |

## Attacks

| Attack | Result |
| --- | --- |
| Lower `global_greedy_cover_min_ops` | **blocked** — still 10_000 |
| Lower `_NATIVE_LIST_SCHEDULE_MIN_OPS` | **blocked** — still 10_000 |
| Restore main-pass no-steal without leftover steal | **blocked** — leftover 417; overflow test requires steal after residents pack |
| Restore machine-global continuation as fifo direct | **blocked** — previous night last_state is not tonight's family |
| Cite a scratch 5k probe as denser than matching | **blocked** — generator IDs are `uuid4`; leftover is not a recapture delta |
| Cite matching 0.9924 as a P2.3 Yes | **blocked** — leftover; hashed freeze stays `no` |
| Recapture remainder 5k@4 / 8k@4/8 as a packing Yes | **blocked** — processing LB vs night cap |
| Restore global (all-nights) home-before-steal | **blocked** — leftover 553, ratio 0.8900 |
| Rewrite hashed deadzone / COVER / ALNS / calendar JSON | **blocked** |
| Raise `time_limit_s` or night width | **blocked** |
| 6-pass eject | **blocked** |
| Grandfather packing helpers onto the 80-line ratchet | **blocked** — split |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** |
| Reopen KI-N12 because origin is `501f449` | **blocked** — that lag is a new pin, not N12 |

## Residuals (not this commit)

| Residual | Why it stays |
| --- | --- |
| No new 5k session | `uuid4` IDs. Pin stays `night-window-match-2026-08-28/` leftover 38 / 117 / 122 |
| Hashed P2.3 / remainder / 5k@4 / 8k@4/8 | Freeze and processing LB unchanged |
| Origin `main` ruleset | Direct push requires a PR |

## Non-claims

- Not a Yes on hashed 5k@8, hashed COVER 100k seed 42, hashed remainder, or hashed calendar-3000.
- Not a three-seed night analog Yes.
- Not a uniformly denser packing than FFD.
- Not a domain pin bump past `54ebf9f`.
- Not a live plant calendar. Night analog is per-op windows.
