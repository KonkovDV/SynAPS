# ADR-0005: Work-center shift calendar is a kernel primitive

- **Status:** Accepted for the contract; implementation is partial (KI-N7).
- **Date:** 2026-08-26
- **Related:** ADR-0003 (domain placement), night-window dead-zone evidence

## Why coverage stops at 0.75–0.88 on the night analog

[АРТЕФАКТ: `benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md`, 2026-08-26,
seeds 1/42/999]

The 5k@8 protocol stamps each operation with a single 8-hour
`[earliest_start, latest_finish]` starting 22:00. That is **not** a machine
calendar: the work center is still 24/7. A chain of ops on consecutive nights
looks like a calendar to a human and like disjoint per-op windows to the
solver. List-schedule COVER and RHC 8h/6h windows then leave
`MISSING_ASSIGNMENT` (ratio 0.75–0.88). ALNS-500 spends the box on
constructive seed and returns `status=error`, `ops_scheduled=0`,
`search_stop_reason=wall_clock_before_search`.

A new heuristic, a lower `global_greedy_cover_min_ops`, or a wider night
window would change the experiment, not add the missing primitive. Those
levers are forbidden as retunes (E4 / honesty protocol).

## Minimal contract

1. `WorkCenter.calendar: list[ShiftInterval]`. Empty list = 24/7 open.
2. Processing `[start_time, end_time]` must sit inside **one** interval
   (an operation cannot straddle a closed period). Justification: the night
   analog already forbade crossing midnight per op; SDST setup occupancy
   before `start` is **not** clipped in this iteration (KI-N7 follow-up).
3. Per-op `earliest_start` / `latest_finish` remain; the feasible slot is the
   intersection of op window, machine open interval, release, and horizon.
4. Freeze / notary: `CALENDAR_VIOLATION` is a hard checker kind.
   `FEASIBLE` still means `proven_hard_violations = ∅`.
5. Native `list_schedule_cover` does not encode calendars: skip to Python
   when any calendar is non-empty.

## Two estimates (not a schedule)

| | (a) Kernel field (this ADR) | (b) Domain unrolling to per-op windows |
| --- | --- | --- |
| What | `ShiftInterval` on `WorkCenter` | GridPlan/signs emit many `earliest_start`/`latest_finish` |
| Notary | New kind `CALENDAR_VIOLATION` | Existing window kinds only; night analog already measured |
| Native COVER | Must skip or gain a calendar ABI | Unchanged; still blind to “machine closed” |
| Conformance matrix | GREED/COVER/BEAM clip processing; CP-SAT/ALNS/LBBD refuse calendar | No new field; same 5k hole |
| 25 named configs | Same names; windowed or calendar 5k@400s must not route to ALNS-500 | Domain unrolling still looks like per-op windows |
| Breaks | CP-SAT `FEASIBLE` can fail the checker until shifts are in the model | Urban night ТОиР still cannot say “the crew is off at 06:00” as a resource |

## Proposed result / exit codes (E2)

| Coverage | Solver status allowed as “success”? | Proposed process code |
| --- | --- | --- |
| empty (0 assignments) | no (`ERROR`) | 3 |
| incomplete (`0 < ratio < 1`) | not a success; may still be `FEASIBLE` on the object | 2 |
| full + notary empty | `FEASIBLE` / `OPTIMAL` | 0 |
| crash / `worker_error` | `ERROR` | 1 |

Empty schedule with `FEASIBLE`/`OPTIMAL` is forbidden (`synaps.solvers.coverage_outcome`).

## Routing fail-closed (E)

- Unconstrained 5k@400s → `ALNS-500` (A15-P1-3). Measured empty plan is
  `ERROR`, not `FEASIBLE`. Empty + success is forbidden.
- Hard windows or non-empty calendar → `RHC-GREEDY` when a latency hint
  would otherwise pick ALNS (below the COVER 10k gate). Without a latency
  hint, 5k still selects `LBBD-10-HD`, which then **refuses** a non-empty
  calendar (`ERROR`), not `RHC-GREEDY`.
- Incomplete coverage (`MISSING_ASSIGNMENT`) is not `verified_feasible`.
- Do not lower `global_greedy_cover_min_ops` to chase a Yes.

## Gate

Without this contract, do not start a fourth domain repository and do not
promise night/emergency work in a new domain layer. GridPlan/MobiRoute pin
lag stays under ADR-0004 until those repos regression-run this primitive.

## Partial ship

Kernel field + checker + greedy/COVER/BEAM clip of **processing** + native skip
are in the tree. BEAM uses the same `find_earliest_feasible_slot` as GREED, so
processing is clipped; ADR table row “BEAM silent” was wrong for processing.
CP-SAT/ALNS/LBBD do not encode shifts: they **refuse** a non-empty calendar
(`calendar_unsupported`, empty `ERROR`). SDST setup occupancy before `start`
is still not clipped (KI-N7 follow-up). CLI/harness process codes 0/2/3/1 are
implemented. That gap is KI-N7, not a Yes.
