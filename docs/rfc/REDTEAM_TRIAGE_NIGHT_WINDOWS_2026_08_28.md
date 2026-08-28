# Red Team triage — night windows, remainder cells, papers (2026-08-28)

Claim level: **honesty**. Not a hashed P2.3 Yes. Not a hashed remainder Yes.
Not a rewrite of `cover-ladder-2026-08-25/` or `beam-alns-box-2026-08-26/`.
Not a retune of `global_greedy_cover_min_ops` (still 10_000).

## Plan vs this drop

| Problem | This drop | Still open |
| --- | --- | --- |
| Night analog 0.75–0.88 | Window-clipped gap scan; COVER list-schedule at n>=2000 when hard windows exist; ALNS seed allows windows | Hashed P2.3 freeze stays **no**. Session recapture of 5k@8 three seeds is the Yes, when run |
| 5k/8k remainder holes | Same window scan + windowed COVER list-schedule | Hashed `worker_error` kept. 8k@12 `MACHINE_OVERLAP` needs a recapture notary |
| Hashed ALNS 5k unconstrained 0.0 | Already closed in `alns-5k-list-schedule-2026-08-27/`; windows seed now matches night geometry | Epoch JSON stays 0.0 |
| Calendar in CP-SAT/ALNS/LBBD | Unchanged refuse | Occupancy `[start-setup, end]` in one `ShiftInterval` is a model drop, not silent 24/7 |
| Unboxed BEAM 12-cell | Still deferred past 2026-09-14 | Measurement, not a code box |
| Linux BEAM timebox | Job added on `native-accelerator` | Run id until this PR's job |
| COVER 100k seed 42 papers | Hashed STALL kept; session 40.137 s Python is the recapture | Hashed 100k@200 remains two of three |
| Two 500k columns | Cite only `cover-ladder-2026-08-25/` | Historical dump stays behind `non-claims` |

## Fell before the fix (node id + text)

| Node | Text |
| --- | --- |
| `tests/test_dispatch_support_regression.py::test_window_gap_scan_fills_interior_hole` | append after last daytime job sits outside the 8 h window |
| `tests/test_rhc_cover.py::test_residual_greedy_uses_window_scan_when_leftover_has_hard_windows` | leftover fill used `gap_scan=append` at large n even with `latest_finish` |
| `tests/test_rhc_cover.py::test_should_use_global_greedy_cover_only_for_large_greedy` | COVER list-schedule skipped at 5k because `min_ops=10_000` |
| `tests/test_alns_append_seed.py::test_list_schedule_seed_allows_hard_windows` | ALNS seed returned `None` on any `earliest_start`/`latest_finish` |

## Attacks

| Attack | Result |
| --- | --- |
| Lower `global_greedy_cover_min_ops` | **blocked** — still 10_000; windowed 5k uses a parallel n>=2000 gate |
| Rewrite hashed deadzone / COVER / ALNS epoch JSON | **blocked** |
| Cite hashed P2.3 as Yes | **blocked** — freeze answer stays `no` |
| Drop CP-SAT calendar refuse without occupancy encoding | **blocked** — would schedule 24/7 |
| C5a / COVER weights / N-1 / SAIDI / INFIMUM / live EL5 / MAST | **blocked** |

## Non-claims

- Not a Yes on hashed 5k@8 ALNS, hashed COVER 100k seed 42, or hashed remainder cells.
- Not native COVER on the 100k seed 42 session.
- Not a live plant calendar. Night analog is per-op windows.
- Not Linux-green for BEAM timebox until the PR job id exists.
