# Red Team triage — home gap over late tail, night key (2026-08-28)

Claim level: **honesty**. Not a hashed P2.3 Yes. Not a hashed remainder Yes.
Not a rewrite of hashed epoch JSON. Not a retune of
`global_greedy_cover_min_ops` (still 10_000) or
`_NATIVE_LIST_SCHEDULE_MIN_OPS` (still 10_000).
Not a three-seed night analog Yes. Not a new 5k session.

Parent packing RFC:
`docs/rfc/REDTEAM_TRIAGE_NIGHT_WINDOWS_2026_08_28.md`.
Fifo/home-first parent:
`docs/rfc/REDTEAM_TRIAGE_FIFO_HOME_GAP_2026_08_28.md`.

## Verdict

**ship.** Windowed list-schedule on one machine prefers an earlier hole over
a feasible late tail (Artigues 2005 insertion SGS). Gap rank uses the
predecessor on that machine. Night key is the window close
`(latest_finish.date(), hour, minute)` so 22:00 and 01:00 siblings stay
one family. Matching session `night-window-match-2026-08-28/` stays the
5k packing pin. Hashed P2.3 stays **no**. Kernel origin `main` after
PR #20 is `54577ef`; this drop needs a follow-up PR.

## Closed this pass

| ID | Sev | Finding | Close |
| --- | --- | --- | --- |
| Home tail before gap | packing | Late home continuation that still fits left the interior hole unused | `_earlier_same_machine_gap`. `test_list_schedule_inserts_home_gap_before_feasible_home_tail` |
| Gap rank `last_state=None` | packing | Interior insert did not score same-state continuation | `_predecessor_on_machine` |
| Night key `date()` | packing | After-midnight earliest split a 22:00-06:00 family | `_window_night_key` uses the window close. `test_window_night_key_groups_after_midnight_with_evening_siblings` |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_rhc_cover.py::test_list_schedule_inserts_home_gap_before_feasible_home_tail` | 80-min A at minute 200; 90-min sibling appended at 280 instead of filling 0-200 |
| `tests/test_rhc_cover.py::test_window_night_key_groups_after_midnight_with_evening_siblings` | 22:00 and 01:00 earliest with the same 06:00 close had different keys |

## Attacks

| Attack | Result |
| --- | --- |
| Lower `global_greedy_cover_min_ops` | **blocked** — still 10_000 |
| Lower `_NATIVE_LIST_SCHEDULE_MIN_OPS` | **blocked** — still 10_000 |
| Unconstrained non-delay list-schedule uses insertion first | **blocked** — tail-then-gap remains when the op has no hard windows |
| Restore `earliest_start.date()` as the night key | **blocked** — splits after midnight |
| Cite a scratch 5k probe as denser than matching | **blocked** — generator IDs are `uuid4`; leftover is not a recapture delta |
| Cite matching 0.9924 as a P2.3 Yes | **blocked** — leftover; hashed freeze stays `no` |
| Recapture remainder 5k@4 / 8k@4/8 as a packing Yes | **blocked** — processing LB vs night cap |
| Restore global (all-nights) home-before-steal | **blocked** — leftover 553, ratio 0.8900 |
| Rewrite hashed deadzone / COVER / ALNS / calendar JSON | **blocked** |
| Raise `time_limit_s` or night width | **blocked** |
| 6-pass eject | **blocked** |
| Grandfather packing helpers onto the 80-line ratchet | **blocked** — split |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** |
| Reopen KI-N12 because origin is `54577ef` | **blocked** — that lag is a new pin, not N12 |

## Residuals (not this commit)

| Residual | Why it stays |
| --- | --- |
| Continuation is machine-global | `_windowed_op_has_direct_tail` treats `last_state == op.state_id` as direct even when `last_end` is a previous night. Slot ranking still prefers the night home |
| Foreign-home reserve while the resident is unfinished | Full no-steal leftover 417. Leftover retry must still steal |
| No new 5k session | `uuid4` IDs. Pin stays `night-window-match-2026-08-28/` leftover 38 / 117 / 122 |
| Hashed P2.3 / remainder / 5k@4 / 8k@4/8 | Freeze and processing LB unchanged |
| Origin `main` ruleset | Direct push requires a PR |

## Non-claims

- Not a Yes on hashed 5k@8, hashed COVER 100k seed 42, hashed remainder, or hashed calendar-3000.
- Not a three-seed night analog Yes.
- Not a uniformly denser packing than FFD.
- Not a domain pin bump past `54ebf9f`.
- Not a live plant calendar. Night analog is per-op windows.
