# ADR-0005: Work-center shift calendar is a kernel primitive

- **Status:** Accepted. Kernel gates OPEN on merge
  `9b5063422f25d6a3cd26b18f6749fc7720541398` (PR #11, 2026-08-26T20:22:50Z).
  Linux required jobs run
  [33007702599](https://github.com/KonkovDV/SynAPS/actions/runs/33007702599)
  (`lint`, `contract-schema-drift`, `typecheck`, `test-fast (3.12)`,
  `test-fast (3.13)`, `benchmark-smoke`, `control-plane` all success).
  Occupancy notary, calendar-aware routing whitelist, empty-success
  demotion. CP-SAT encodes occupancy in one `ShiftInterval`; ALNS clips via
  greedy insertion; LBBD uses the CP-SAT subproblem. Auto-route for a
  non-empty calendar stays in `CALENDAR_AWARE`. Native COVER encodes
  occupancy `[start-setup, end]` in one published shift (empty calendar
  stays 24/7).
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
2. Occupancy `[start_time − setup_minutes, end_time]` must sit inside **one**
   interval (an operation cannot straddle a closed period). **Decision (И3.3):**
   calendar-aware dispatch **clips setup together with processing**. An instance
   whose setup+processing cannot fit a published shift is unplaced / refused —
   it is not silently allowed. The notary emits `CALENDAR_VIOLATION` on
   occupancy, not only on processing.
3. Per-op `earliest_start` / `latest_finish` remain; the feasible slot is the
   intersection of op window, machine open interval, release, and horizon.
4. Freeze / notary: `CALENDAR_VIOLATION` is a hard checker kind.
   `FEASIBLE` still means `proven_hard_violations = ∅`.
5. Native `list_schedule_cover` encodes occupancy `[start-setup, end]` in one
   published shift. An empty CSR row (no published intervals on that machine)
   is 24/7. Gate `_NATIVE_LIST_SCHEDULE_MIN_OPS` stays 10_000; n=3000 stays
   Python unless a process-local probe bypasses the gate.

## Two estimates (not a schedule)

| | (a) Kernel field (this ADR) | (b) Domain unrolling to per-op windows |
| --- | --- | --- |
| What | `ShiftInterval` on `WorkCenter` | GridPlan/signs emit many `earliest_start`/`latest_finish` |
| Notary | New kind `CALENDAR_VIOLATION` | Existing window kinds only; night analog already measured |
| Native COVER | Encodes occupancy; empty CSR row is 24/7 | Unchanged; still blind to “machine closed” |
| Conformance matrix | GREED/COVER/BEAM clip; CP-SAT/ALNS/LBBD encode occupancy | No new field; same 5k hole |
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
- Non-empty machine calendar → a config in `CALENDAR_AWARE`
  (`GREED` / `GREED-K1-3` / `BEAM-3` / `BEAM-5` / `RHC-GREEDY` /
  `RHC-GREEDY-COVER`) for **any** `(policy × latency)` including
  `latency=None` and `exact_required`. `CALENDAR_REFUSING` (CP-SAT / ALNS /
  LBBD / RHC-ALNS / RHC-CPSAT) is never selected. Table:
  `docs/architecture/CALENDAR_ROUTING.md`.
- Hard per-op windows without a calendar still block ALNS when a latency
  hint would otherwise pick it (`RHC-GREEDY` below the COVER 10k gate).
- Incomplete coverage (`MISSING_ASSIGNMENT`) is not `verified_feasible`.
- Do not lower `global_greedy_cover_min_ops` to chase a Yes.

## Gate

Kernel gates are **open** on merge `9b506342` / Linux run
[33007702599](https://github.com/KonkovDV/SynAPS/actions/runs/33007702599)
(2026-08-26): occupancy notary, calendar-aware routing whitelist,
empty-success `ERROR`. Do not promise night/emergency work in a new domain
layer until that SHA is the pin. GridPlan/MobiRoute pin lag stays under
ADR-0004 until 2026-09-09.

## Partial ship

Kernel field + checker occupancy `[start − setup, end]` + greedy/COVER/BEAM
clip of **setup and processing** + native occupancy ABI (empty CSR row
24/7) are in the tree. CP-SAT encodes
occupancy in one published shift (processing literals + `su_start >= open` on
SDST arcs). ALNS/LBBD inherit that encoding (greedy clip / CP-SAT
subproblem). Auto-route for a non-empty calendar remains `CALENDAR_AWARE`.
CLI/harness process codes 0/2/3/1 are implemented. Pareto-slice stamps empty
inner results. KI-N7 notary gap is closed.
