# Red Team triage — night windows, calendar encode, papers (2026-08-28)

Claim level: **honesty**. Not a hashed P2.3 Yes. Not a hashed remainder Yes.
Not a rewrite of `cover-ladder-2026-08-25/` or `beam-alns-box-2026-08-26/`.
Not a retune of `global_greedy_cover_min_ops` (still 10_000).
Not a 24/7 allow on `WorkCenter.calendar`.

## Plan vs this drop

| Problem | This drop | Still open |
| --- | --- | --- |
| Night analog 0.75–0.88 | Window leftover scan kept. COVER list-schedule stays at 10_000. List-schedule session 0.7446. Rolling recapture 0.7688 / 0.7836 / 0.7714, all `wall_clock` ~128 s | Hashed P2.3 freeze stays **no** |
| 5k/8k remainder holes | Window leftover scan kept. Hashed `worker_error` kept. Session `remainder-window-scan-2026-08-28/` is `wall_clock` + `MISSING_ASSIGNMENT` (8k@12 has no `MACHINE_OVERLAP` here) | Not a Yes |
| Hashed ALNS 5k unconstrained 0.0 | Already closed in `alns-5k-list-schedule-2026-08-27/` | Epoch JSON stays 0.0 |
| Calendar in CP-SAT/ALNS/LBBD | Occupancy encoded: processing in one shift + `su_start >= open` on SDST. ALNS clips. LBBD via CP-SAT. Auto-route stays `CALENDAR_AWARE` | Native COVER still skips. Not a live plant calendar |
| Unboxed BEAM 12-cell | Still deferred past 2026-09-14 | Measurement, not a code box |
| Linux BEAM timebox | Job on `native-accelerator` | Run [33151732222](https://github.com/KonkovDV/SynAPS/actions/runs/33151732222) |
| COVER 100k seed 42 papers | Hashed STALL kept; Python session 40.137 s | This Windows process has `native_available=false`. Hashed 100k@200 remains two of three |
| Two 500k columns | Cite only `cover-ladder-2026-08-25/` | Historical dump stays behind `non-claims` |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_dispatch_support_regression.py::test_window_gap_scan_fills_interior_hole` | append after last daytime job sits outside the 8 h window |
| `tests/test_rhc_cover.py::test_residual_greedy_uses_window_scan_when_leftover_has_hard_windows` | leftover fill used `gap_scan=append` at large n even with `latest_finish` |
| `tests/test_alns_append_seed.py::test_list_schedule_seed_allows_hard_windows` | ALNS seed returned `None` on any `earliest_start`/`latest_finish` |
| `tests/test_calendar.py::test_cpsat_alns_lbbd_encode_nonempty_calendar` | CPSAT/ALNS/LBBD returned empty `ERROR` / `calendar_unsupported` |
| `tests/test_calendar.py::test_cpsat_clips_setup_into_open_shift` | CP-SAT without encoding would place setup on a closed shift |
| list-schedule 5k@8 seed 1 | ratio 0.7446 in 1.165 s, `global_greedy_cover=true` — not a Yes |
| rolling 5k@8 three seeds | `wall_clock` at ~128 s, ratios 0.7688 / 0.7836 / 0.7714 — same class as hashed |

## Attacks

| Attack | Result |
| --- | --- |
| Lower `global_greedy_cover_min_ops` | **blocked** — still 10_000 |
| Re-enable list-schedule at n>=2000 for windowed 5k | **blocked** — session 0.7446 is not a Yes |
| Raise named `time_limit_s` to manufacture a night Yes | **blocked** |
| Rewrite hashed deadzone / COVER / ALNS epoch JSON | **blocked** |
| Cite hashed P2.3 as Yes | **blocked** — freeze answer stays `no` |
| Drop CP-SAT calendar refuse without occupancy encoding | **blocked** — occupancy is in the model; auto-route still clip family |
| Silent 24/7 on a non-empty calendar | **blocked** — `test_cpsat_alns_lbbd_encode_nonempty_calendar` |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** |

## Session numbers (not hashed)

| Cell | Config | seed | ratio | wall s | note |
| --- | --- | --- | --- | --- | --- |
| 5k@8 boxed GREED | GREED | 1 | 0.122 | 120.182 | `status=timeout`; hashed GREED was unbounded stall |
| 5k@8 list-schedule | RHC-GREEDY | 1 | 0.7446 | 1.165 | `global_greedy_cover=true`; not a Yes |
| 5k@8 rolling | RHC-GREEDY | 1/42/999 | 0.7688 / 0.7836 / 0.7714 | 128.074 / 128.046 / 127.661 | `wall_clock`; hashed 0.7702 / 0.7812 / 0.7708 |
| remainder seed 1 | RHC-GREEDY | 1 | 0.401 / 0.7714 / 0.8514 / 0.25975 / 0.547375 / 0.766375 | ~128–136 | 5k@4/8/12 then 8k@4/8/12; `MISSING_ASSIGNMENT` only |

Folders:
`benchmark/evidence/deadzone-5k-2026-08-25/sessions/night-window-scan-2026-08-28/`
`.../night-rhc-rolling-2026-08-28/`
`.../remainder-window-scan-2026-08-28/`.

## Non-claims

- Not a Yes on hashed 5k@8, hashed COVER 100k seed 42, or hashed remainder cells.
- Not native COVER on this machine (`native_available=false`).
- Not a live plant calendar. Night analog is per-op windows.
- Not a P2.3 Yes from list-schedule or rolling recapture.
- Unboxed BEAM 12-cell stays after 2026-09-14.
