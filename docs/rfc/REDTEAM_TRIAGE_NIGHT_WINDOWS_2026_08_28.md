# Red Team triage — night windows, calendar encode, papers (2026-08-28)

Claim level: **honesty**. Not a hashed P2.3 Yes. Not a hashed remainder Yes.
Not a rewrite of `cover-ladder-2026-08-25/` or `beam-alns-box-2026-08-26/`.
Not a retune of `global_greedy_cover_min_ops` (still 10_000).
Not a 24/7 allow on `WorkCenter.calendar`.
Not a hashed calendar-3000 Yes.

## Plan vs this drop

| Problem | This drop | Still open |
| --- | --- | --- |
| Night analog 0.75–0.88 | Window leftover scan kept. `min_ops` stays 10_000. Windowed n>=2000 list-schedules (EDD, window-gap inserts, placement floor = pred end + published window). Session `night-window-edd-2026-08-28/` 0.8352 / 0.8258 / 0.8198. Fell-before 0.7446 kept. Rolling recapture still `wall_clock` | Hashed P2.3 freeze stays **no**. SDST vs 8 h night is not full cover |
| 5k/8k remainder holes | Session `remainder-window-fix-2026-08-28/` is `completed`. 5k@12 seed 1 is 0.9994 (3 leftover). Hashed `worker_error` kept | Not a Yes |
| Hashed ALNS 5k unconstrained 0.0 | Already closed in `alns-5k-list-schedule-2026-08-27/` | Epoch JSON stays 0.0 |
| Calendar in CP-SAT/ALNS/LBBD/native | Occupancy encoded in CP-SAT, ALNS clip, LBBD via CP-SAT, native `list_schedule_cover` shift delay. Auto-route stays `CALENDAR_AWARE` | Not a live plant calendar |
| Machine-calendar 3000@8 | Session seeds 1/42/999 ratio 1.0 / `verified_feasible=true` (`calendar-list-schedule-2026-08-28/`). Python list-schedule (`native_available=false` here) | Hashed JSON keeps `CALENDAR_VIOLATION` |
| Unboxed BEAM 12-cell | Still deferred past 2026-09-14 | Measurement, not a code box |
| Linux BEAM timebox | Job on `native-accelerator` | Run [33151732222](https://github.com/KonkovDV/SynAPS/actions/runs/33151732222) |
| COVER 100k seed 42 papers | Hashed STALL kept; Python session 40.137 s. PR CI adds 100k@200 seed 42 `--ci-gate` | This Windows process has `native_available=false`. Hashed 100k@200 remains two of three |
| Two 500k columns | Cite only `cover-ladder-2026-08-25/` | Historical dump stays behind `non-claims` |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_dispatch_support_regression.py::test_window_gap_scan_fills_interior_hole` | append after last daytime job sits outside the 8 h window |
| `tests/test_rhc_cover.py::test_residual_greedy_uses_window_scan_when_leftover_has_hard_windows` | leftover fill used `gap_scan=append` at large n even with `latest_finish` |
| `tests/test_rhc_cover.py::test_list_schedule_inserts_into_idle_gap_when_tail_blocked` | unconstrained 64-insert cap left windowed ops on a closed tail |
| `tests/test_rhc_cover.py::test_cover_placement_floor_ignores_inflated_chain_earliest_on_windows` | RHC chain-LB sat past realized pred end inside the night |
| `tests/test_alns_append_seed.py::test_list_schedule_seed_allows_hard_windows` | ALNS seed returned `None` on any `earliest_start`/`latest_finish` |
| `tests/test_calendar.py::test_cpsat_alns_lbbd_encode_nonempty_calendar` | CPSAT/ALNS/LBBD returned empty `ERROR` / `calendar_unsupported` |
| `tests/test_calendar.py::test_list_schedule_cover_clips_setup_into_open_shift` | list-schedule without occupancy delay would start at t=0 on a closed shift |
| list-schedule 5k@8 seed 1 | ratio 0.7446 in 1.165 s, `global_greedy_cover=true` — not a Yes |
| rolling 5k@8 three seeds | `wall_clock` at ~128 s, ratios 0.7688 / 0.7836 / 0.7714 — same class as hashed |

## Attacks

| Attack | Result |
| --- | --- |
| Lower `global_greedy_cover_min_ops` | **blocked** — still 10_000 |
| Silent list-schedule at n>=2000 without packing | **blocked** — 0.7446 session stays the fell-before |
| Raise named `time_limit_s` to manufacture a night Yes | **blocked** |
| Rewrite hashed deadzone / COVER / ALNS / calendar epoch JSON | **blocked** |
| Cite hashed P2.3 as Yes | **blocked** — freeze answer stays `no` |
| Cite hashed calendar-3000 as Yes | **blocked** — hashed keeps `CALENDAR_VIOLATION` |
| Cite night analog 0.8352 as a P2.3 Yes | **blocked** — `verified_feasible=false`, leftovers, SDST vs 8 h |
| Drop CP-SAT calendar refuse without occupancy encoding | **blocked** — occupancy is in the model; auto-route still clip family |
| Silent 24/7 on a non-empty calendar | **blocked** — `test_cpsat_alns_lbbd_encode_nonempty_calendar` |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** |

## Session numbers (not hashed)

| Cell | Config | seed | ratio | wall s | note |
| --- | --- | --- | --- | --- | --- |
| 5k@8 boxed GREED | GREED | 1 | 0.122 | 120.182 | `status=timeout`; hashed GREED was unbounded stall |
| 5k@8 list-schedule fell-before | RHC-GREEDY | 1 | 0.7446 | 1.165 | `global_greedy_cover=true`; not a Yes |
| 5k@8 rolling | RHC-GREEDY | 1/42/999 | 0.7688 / 0.7836 / 0.7714 | 128.074 / 128.046 / 127.661 | `wall_clock`; hashed 0.7702 / 0.7812 / 0.7708 |
| 5k@8 window-aware list-schedule | RHC-GREEDY | 1/42/999 | 0.8352 / 0.8258 / 0.8198 | 4.978 / 5.636 / 5.879 | `completed`; not a Yes |
| remainder seed 1 (scan) | RHC-GREEDY | 1 | 0.401 / 0.7714 / 0.8514 / 0.25975 / 0.547375 / 0.766375 | ~128–136 | 5k@4/8/12 then 8k@4/8/12; `wall_clock` |
| remainder seed 1 (fix) | RHC-GREEDY | 1 | 0.4058 / 0.8376 / 0.9994 / 0.2695 / 0.564875 / 0.836125 | 5.319 / 5.756 / 0.69 / 8.507 / 10.824 / 10.367 | `completed`; 5k@12 has 3 leftover |
| calendar 3000@8 list-schedule | RHC-GREEDY | 1/42/999 | 1.0 / 1.0 / 1.0 | 0.282 / 0.303 / 0.286 | `verified_feasible=true`; not hashed; not P2.3 |

Folders:
`benchmark/evidence/deadzone-5k-2026-08-25/sessions/night-window-scan-2026-08-28/`
`.../night-rhc-rolling-2026-08-28/`
`.../night-window-edd-2026-08-28/`
`.../remainder-window-scan-2026-08-28/`
`.../remainder-window-fix-2026-08-28/`
`benchmark/evidence/calendar-3000-8m-2026-08-27/sessions/calendar-list-schedule-2026-08-28/`.

## Non-claims

- Not a Yes on hashed 5k@8, hashed COVER 100k seed 42, hashed remainder, or hashed calendar-3000.
- Not native COVER on this machine (`native_available=false`). Calendar-3000 session is Python list-schedule.
- Not a live plant calendar. Night analog is per-op windows. Calendar-3000 is `WorkCenter.calendar`.
- Not a P2.3 Yes from list-schedule or rolling recapture.
- Unboxed BEAM 12-cell stays after 2026-09-14.
