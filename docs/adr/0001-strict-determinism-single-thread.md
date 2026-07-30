# ADR-0001: Strict determinism via single-threaded CP-SAT with a deterministic-time stop

- **Status:** Accepted (2026-07, Red Team audit v3, defect N1)
- **Deciders:** maintainers (decision requested explicitly, not delegated to the agent)
- **Supersedes:** the original D1 fix (interleaved multi-threaded search bounded by
  `max_deterministic_time` alongside `max_time_in_seconds`)

## Context

SynAPS is branded **deterministic-first**: a fixed `random_seed` must yield a
byte-identical schedule. CP-SAT's wall-clock stop (`max_time_in_seconds`) is
inherently non-deterministic, so the first fix (audit v2, D1) added
`interleave_search` + `max_deterministic_time` for reproducible multi-threading
but **left `max_time_in_seconds` in place**. Both limits were active, and the
one that triggers first wins.

Deterministic time is a machine-independent abstract unit, not a second. Measured
wall-clock cost per deterministic unit (single-thread, `medium_stress_20x4`):

| `max_deterministic_time` | wall (idle) | ratio wall/det |
|---|---|---|
| 2.0 | 3.08 s | 1.54 |
| 4.0 | 5.17 s | 1.29 |
| 8.0 | 8.46 s | 1.06 |

Two facts drive the decision:

1. On 8 interleaved workers the deterministic budget maps to **~3× the wall
   time**, so `max_time_in_seconds = budget` cut first and the schedule was
   non-reproducible: 4 runs at one seed gave **4 distinct** makespans
   (204/202/196/192) — the D3 timebox fix silently killed the D1 determinism fix.
2. The wall/deterministic ratio **rises under CPU load** (measured >2× under a
   busy machine vs ~1.06 idle). Any scheme that lets a wall-clock limit pre-empt
   the deterministic stop — including a *calibrated* multi-threaded budget — is
   therefore non-reproducible whenever load changes between calibration and solve.

## Decision

In `determinism="strict"` (the default), CP-SAT runs **single-threaded**
(`num_workers=1`, a deterministic search order) and stops on
`max_deterministic_time = 0.5 * time_limit_s` as the **sole binding limit**. The
wall clock (`max_time_in_seconds = 2.0 * time_limit_s`) is only a loose runaway
safety. If the wall safety, not the deterministic stop, ends the search,
`metadata["determinism_violated"] = True` is recorded (never a silent return).

`determinism="fast"` keeps the multi-threaded wall-clock portfolio for callers
who want throughput over a byte-identical schedule.

The `0.5` fraction is chosen so that at the measured single-thread ratio (≤ ~2.4
including load headroom) the run still finishes within ~1.2× the wall budget.

## Consequences

- **Reproducibility is guaranteed** regardless of host speed or CPU load: the
  binding stop is machine-independent. Verified under load by
  `tests/test_cpsat_determinism.py` (asserts one fingerprint **and**
  `determinism_violated is False`) and by `synaps_redteam_repro_v3.py` tag `N1`.
- **Throughput cost:** strict is single-threaded, so large instances are slower.
  In practice the portfolio routes large instances to RHC/ALNS/LBBD, and CP-SAT
  is used for small/medium problems and (small) LBBD subproblems.
- **Quality:** measured *better* than the broken multi-threaded default on the
  audit instance (181 vs 192–204) — the racing workers wasted the budget.
- **Budget cost:** ~50% of the deterministic search budget is traded away for the
  wall headroom. This is the documented price of reproducibility.
- **Wall bound is soft under heavy load:** because the stop is deterministic, the
  wall time is `0.5 * budget * ratio`; under pathological load the wall may exceed
  1.2× the budget. `determinism_violated` surfaces the case where even the 2×
  safety engaged. Callers needing a hard wall bound use `determinism="fast"`.

## Alternatives considered

- **Calibrated multi-threaded budget** (`max_deterministic_time = budget / ratio
  * 0.8`, measured ratio): keeps parallelism and a tight wall bound, but the ratio
  is load-dependent, so a ratio measured at calibration time does not hold at
  solve time — intermittent non-reproducibility. Rejected as fragile.
- **Make `fast` the default:** honest and fast, but abandons the deterministic-
  first guarantee that is a core product promise. Rejected.
