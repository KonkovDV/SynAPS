# Red Team triage — night windows, calendar encode, papers (2026-08-28)

Claim level: **honesty**. Not a hashed P2.3 Yes. Not a hashed remainder Yes.
Not a rewrite of `cover-ladder-2026-08-25/` or `beam-alns-box-2026-08-26/`.
Not a retune of `global_greedy_cover_min_ops` (still 10_000).
Not a 24/7 allow on a work center that publishes a shift.
Not a hashed calendar-3000 Yes.
Not a kernel retune of `_NATIVE_LIST_SCHEDULE_MIN_OPS` (still 10_000).

## Plan vs this drop

| Problem | This drop | Still open |
| --- | --- | --- |
| Night analog 0.75–0.88 | Window leftover scan kept. Exclusive 1:1 homes, same-night fifo home-before-steal, home tail+gap before steal tail, same-machine earlier hole over a feasible late tail, foreign-home reserve in the main pass, leftover steal after residents pack, leftover retry, single 1-swap eject. Matching session `night-window-match-2026-08-28/` 0.9924 / 0.9766 / 0.9756 leftover 38 / 117 / 122. FFD packing session `night-window-state-2026-08-28/` 0.9912 / 0.9806 / 0.9818 kept. EDD 0.8352 / 0.8258 / 0.8198 kept. Fell-before 0.7446 kept. Rolling still `wall_clock` | Hashed P2.3 freeze stays **no**. Matching is not uniformly denser than FFD. Not a three-seed Yes. Do not restore global (all-nights) home-before-steal |
| 5k/8k remainder holes | Session `remainder-window-state-2026-08-28/` 0.547 / 0.9936 / 1.0 / 0.3605 / 0.715625 / 0.9815. 5k@12 seed 1 is a session Yes. Hashed epoch kept. Processing LB vs 28×480×m: 5k@4 and 8k@4/8 seed 1 are overloaded (pmin 72543 / 115977 / 111534 vs cap 53760 / 53760 / 107520) | Six-cell remainder is not a Yes. Overloaded cells are not a packing hole |
| Hashed ALNS 5k unconstrained 0.0 | Already closed in `alns-5k-list-schedule-2026-08-27/` | Epoch JSON stays 0.0 |
| Calendar in CP-SAT/ALNS/LBBD/native | Occupancy encoded in CP-SAT, ALNS clip, LBBD via CP-SAT, native `list_schedule_cover` shift delay. Auto-route stays `CALENDAR_AWARE` | Not a live plant calendar |
| Machine-calendar 3000@8 | Python session seeds 1/42/999 ratio 1.0 (`calendar-list-schedule-2026-08-28/`). Native probe seed 1 ratio 1.0 wall 0.164 s (`native-calendar-3000-seed1-2026-08-28/`, `bypass_gate=true`) | Hashed JSON keeps `CALENDAR_VIOLATION`. Kernel gate stays 10_000 |
| Unboxed BEAM 12-cell | Still deferred past 2026-09-14 | Measurement, not a code box |
| Linux BEAM timebox | Job on `native-accelerator` | Runs [33151732222](https://github.com/KonkovDV/SynAPS/actions/runs/33151732222) and [33159561321](https://github.com/KonkovDV/SynAPS/actions/runs/33159561321) |
| COVER 100k seed 42 papers | Hashed STALL kept. Python session 40.137 s. Linux CI [33159561321](https://github.com/KonkovDV/SynAPS/actions/runs/33159561321): 18.068 s native. Windows native session 9.926 s (`native-100k-seed42-2026-08-28/`) | Hashed 100k@200 remains two of three. Not a hashed three-seed Yes |
| Native calendar occupancy | Shift delay in `list_schedule_cover`. Empty CSR row is 24/7. Mixed-fleet tests in `test_calendar.py` / `test_accelerators.py` | n<10_000 still Python unless a probe bypasses the gate |
| 80-line ratchet | Wrapper extracted; packing helpers split instead of grandfathering | Do not put new functions on `_LONG_FUNCTION_RATCHET` |
| Two 500k columns | Cite only `cover-ladder-2026-08-25/` | Historical dump stays behind `non-claims` |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_dispatch_support_regression.py::test_window_gap_scan_fills_interior_hole` | append after last daytime job sits outside the 8 h window |
| `tests/test_rhc_cover.py::test_residual_greedy_uses_window_scan_when_leftover_has_hard_windows` | leftover fill used `gap_scan=append` at large n even with `latest_finish` |
| `tests/test_rhc_cover.py::test_list_schedule_inserts_into_idle_gap_when_tail_blocked` | unconstrained 64-insert cap left windowed ops on a closed tail |
| `tests/test_rhc_cover.py::test_cover_placement_floor_ignores_inflated_chain_earliest_on_windows` | RHC chain-LB sat past realized pred end inside the night |
| `tests/test_rhc_cover.py::test_list_schedule_continues_windowed_state_instead_of_idle_machine` | earliest-end put the second same-state night op on idle M3 and paid SDST |
| `tests/test_rhc_cover.py::test_list_schedule_keeps_two_night_families_off_one_machine` | aggregate FFD put two near-full families on one 8 h machine and leftover the second after SDST |
| `tests/test_rhc_cover.py::test_list_schedule_fills_home_before_steal_when_family_uuid_sorts_later` | fifo `(due, state_id)` popped a steal onto empty M1 before the resident 150-min family |
| `tests/test_rhc_cover.py::test_list_schedule_same_night_fifo_does_not_defer_steal_behind_later_nights` | global home-before-steal delayed night-1 leftover past `latest_finish` |
| `tests/test_rhc_cover.py::test_list_schedule_inserts_home_gap_before_steal_tail` | appending SGS stole idle M2 instead of inserting into the 0-200 hole on the home |
| `tests/test_rhc_cover.py::test_list_schedule_inserts_home_gap_before_feasible_home_tail` | a feasible late home tail skipped the interior hole |
| `tests/test_rhc_cover.py::test_window_night_key_groups_after_midnight_with_evening_siblings` | `earliest_start.date()` split a 22:00-06:00 family after midnight |
| `tests/test_rhc_cover.py::test_list_schedule_reserves_foreign_home_when_heap_pops_steal_first` | heap-order steal occupied empty M1 while 3x150 A was unfinished |
| `tests/test_rhc_cover.py::test_list_schedule_previous_night_state_does_not_steal_before_resident` | night-1 last_state popped a night-2 steal onto the new home |
| `tests/test_alns_append_seed.py::test_list_schedule_seed_allows_hard_windows` | ALNS seed returned `None` on any `earliest_start`/`latest_finish` |
| `tests/test_calendar.py::test_cpsat_alns_lbbd_encode_nonempty_calendar` | CPSAT/ALNS/LBBD returned empty `ERROR` / `calendar_unsupported` |
| `tests/test_calendar.py::test_list_schedule_cover_clips_setup_into_open_shift` | list-schedule without occupancy delay would start at t=0 on a closed shift |
| `tests/test_calendar.py::test_alns_native_greedy_skips_nonempty_calendar` | native `greedy_repair_batch` has no occupancy ABI |
| `tests/test_accelerators.py::test_native_list_schedule_mixed_fleet_empty_row_is_24_7` | empty CSR row is 24/7 when a sibling publishes a shift |
| list-schedule 5k@8 seed 1 | ratio 0.7446 in 1.165 s, `global_greedy_cover=true` — not a Yes |
| rolling 5k@8 three seeds | `wall_clock` at ~128 s, ratios 0.7688 / 0.7836 / 0.7714 — same class as hashed |
| `tests/test_architecture.py::test_function_length_ratchet` | `accelerators.py::list_schedule_cover_native` 83 lines, new, on [33159561321](https://github.com/KonkovDV/SynAPS/actions/runs/33159561321) |

## Attacks

| Attack | Result |
| --- | --- |
| Lower `global_greedy_cover_min_ops` | **blocked** — still 10_000 |
| Lower `_NATIVE_LIST_SCHEDULE_MIN_OPS` in the kernel | **blocked** — still 10_000. Calendar probe mutates the process only |
| Silent list-schedule at n>=2000 without packing | **blocked** — 0.7446 session stays the fell-before |
| Raise named `time_limit_s` or night width to manufacture a night Yes | **blocked** |
| Loop 1-swap eject six times | **blocked** — measured regression (0.989 to 0.9864); single eject only |
| Rewrite hashed deadzone / COVER / ALNS / calendar epoch JSON | **blocked** |
| Cite hashed P2.3 as Yes | **blocked** — freeze answer stays `no` |
| Cite hashed calendar-3000 as Yes | **blocked** — hashed keeps `CALENDAR_VIOLATION` |
| Cite night analog 0.8352, 0.9912, or 0.9924 as a P2.3 Yes | **blocked** — `verified_feasible=false`, leftovers |
| Cite exclusive matching as uniformly denser than FFD packing | **blocked** — seeds 42/999 leftover grew (117 / 122 vs 97 / 91) |
| Restore global (all-nights) home-before-steal | **blocked** — seed 1 leftover 553, ratio 0.8900 |
| Cite a scratch 5k fifo probe as denser than matching | **blocked** — generator IDs are `uuid4`; leftover is not a recapture delta |
| `_window_night_key` is calendar `date()` | **closed** — key is the window close; see `docs/rfc/REDTEAM_TRIAGE_HOME_GAP_NIGHT_KEY_2026_08_28.md` |
| Cite remainder 5k@12 session Yes as a six-cell / P2.3 Yes | **blocked** — one cell, seed 1; hashed epoch untouched |
| Drop CP-SAT calendar refuse without occupancy encoding | **blocked** — occupancy is in the model; auto-route still clip family |
| Native greedy_repair 24/7 on a published calendar | **blocked** — `_native_repair_skip_reason` returns `calendar`; Python ALNS clips |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** |
| Grandfather packing helpers onto the 80-line ratchet | **blocked** — split instead |
| Cite Linux 18.068 s or Windows 9.926 s as hashed 100k@200 seed 42 Yes | **blocked** — hashed JSON stays STALL |
| Cite calendar-3000 CI 0.492 s as native COVER | **blocked** — n=3000 is below the kernel gate; Python list-schedule |
| Cite native probe 0.164 s as a kernel-default native calendar-3000 | **blocked** — `bypass_gate=true`; default stays 10_000 |
| Silent 24/7 when calendar kwargs are omitted on n>=10_000 | **blocked** — `_pack_native_calendars` adds CSR when any WC publishes a shift; empty CSR is 24/7 by contract |

## Session numbers (not hashed)

| Cell | Config | seed | ratio | wall s | note |
| --- | --- | --- | --- | --- | --- |
| 5k@8 boxed GREED | GREED | 1 | 0.122 | 120.182 | `status=timeout`; hashed GREED was unbounded stall |
| 5k@8 list-schedule fell-before | RHC-GREEDY | 1 | 0.7446 | 1.165 | `global_greedy_cover=true`; not a Yes |
| 5k@8 rolling | RHC-GREEDY | 1/42/999 | 0.7688 / 0.7836 / 0.7714 | 128.074 / 128.046 / 127.661 | `wall_clock`; hashed 0.7702 / 0.7812 / 0.7708 |
| 5k@8 window-aware list-schedule | RHC-GREEDY | 1/42/999 | 0.8352 / 0.8258 / 0.8198 | 4.978 / 5.636 / 5.879 | `completed`; not a Yes |
| 5k@8 family packing (FFD) | RHC-GREEDY | 1/42/999 | 0.9912 / 0.9806 / 0.9818 | 5.616 / 7.866 / 7.51 | leftover 44 / 97 / 91; not a P2.3 Yes |
| 5k@8 exclusive matching | RHC-GREEDY | 1/42/999 | 0.9924 / 0.9766 / 0.9756 | 3.647 / 11.0 / 9.877 | leftover 38 / 117 / 122; not uniformly denser than FFD; not a P2.3 Yes |
| remainder seed 1 (scan) | RHC-GREEDY | 1 | 0.401 / 0.7714 / 0.8514 / 0.25975 / 0.547375 / 0.766375 | ~128–136 | 5k@4/8/12 then 8k@4/8/12; `wall_clock` |
| remainder seed 1 (fix) | RHC-GREEDY | 1 | 0.4058 / 0.8376 / 0.9994 / 0.2695 / 0.564875 / 0.836125 | 5.319 / 5.756 / 0.69 / 8.507 / 10.824 / 10.367 | `completed`; 5k@12 has 3 leftover |
| remainder seed 1 (packing) | RHC-GREEDY | 1 | 0.547 / 0.9936 / 1.0 / 0.3605 / 0.715625 / 0.9815 | 52.285 / 4.344 / 0.385 / 110.263 / 127.733 / 21.673 | 5k@12 seed 1 session Yes; six-cell not a Yes |
| calendar 3000@8 list-schedule | RHC-GREEDY | 1/42/999 | 1.0 / 1.0 / 1.0 | 0.282 / 0.303 / 0.286 | `verified_feasible=true`; not hashed; not P2.3; Python |
| Linux COVER 100k@200 | RHC-GREEDY | 42 | 1.0 | 18.068 | native; 119 leftover then greedy repair; run 33159561321; not hashed |
| Windows COVER 100k@200 | RHC-GREEDY | 42 | 1.0 | 9.926 | native; `native-100k-seed42-2026-08-28/`; not hashed |
| Linux calendar 3000 seed 1 | RHC-GREEDY | 1 | 1.0 | 0.492 | Python list-schedule; run 33159561321 |
| Calendar 3000 native probe | RHC-GREEDY | 1 | 1.0 | 0.164 | `bypass_gate=true`; not a kernel-default retune |

Folders:
`benchmark/evidence/deadzone-5k-2026-08-25/sessions/night-window-scan-2026-08-28/`
`.../night-rhc-rolling-2026-08-28/`
`.../night-window-edd-2026-08-28/`
`.../night-window-state-2026-08-28/`
`.../night-window-match-2026-08-28/`
`.../remainder-window-scan-2026-08-28/`
`.../remainder-window-fix-2026-08-28/`
`.../remainder-window-state-2026-08-28/`
`benchmark/evidence/calendar-3000-8m-2026-08-27/sessions/calendar-list-schedule-2026-08-28/`
`.../native-calendar-3000-seed1-2026-08-28/`
`benchmark/evidence/cover-ladder-2026-08-25/sessions/native-100k-seed42-2026-08-28/`.

## Non-claims

- Not a Yes on hashed 5k@8, hashed COVER 100k seed 42, hashed remainder, or hashed calendar-3000.
- Not a P2.3 Yes from EDD list-schedule, FFD family packing, exclusive matching, or rolling recapture.
- Not a six-cell remainder Yes. 5k@12 seed 1 is a session Yes only.
- Not a live plant calendar. Night analog is per-op windows. Calendar-3000 is `WorkCenter.calendar`.
- Unboxed BEAM 12-cell stays after 2026-09-14.
- Linux 18.068 s and Windows 9.926 s are session/CI cells, not a rewrite of hashed `run_100k_at_200_seed42.json`.
- Calendar native probe is process-local `bypass_gate`. Kernel `_NATIVE_LIST_SCHEDULE_MIN_OPS` stays 10_000.
- Empty native calendar CSR row is 24/7. A work center that publishes a shift is not 24/7.
