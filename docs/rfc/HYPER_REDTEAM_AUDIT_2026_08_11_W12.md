# Hyper Red Team audit — full codebase (2026-08-11, post–Wave 11)

Hostile pass after Wave 11 (`024dbf1`) + Aug 2026 literature brief.

## Verdict

**fail-open → Wave 12 required**

Wave 11 C1 is **partial**: frozen processing no-overlap is wired, but SDST/aux vs frozen and missing-pred clearing remain fail-open. Customer oracle demotes physical `MACHINE_CAPACITY_VIOLATION`. CP-SAT still ignores canonical `material` weights.

## CRITICAL

| ID | Finding |
|---|---|
| **C12-1** | CP-SAT frozen path: no SDST between frozen↔free (circuit free-only) |
| **C12-2** | CP-SAT aux cumulatives ignore frozen occupancy |
| **C12-3** | IncrementalRepair clears pred edge when pred missing from frozen (fail-open) |
| **C12-4** | Clamped/collapsed frozen intervals silently skipped |

## HIGH

| ID | Finding |
|---|---|
| **H12-1** | `proven_hard` demotes `MACHINE_CAPACITY_VIOLATION` (physical, not lane FP) |
| **H12-2** | CP-SAT weights: `material_loss` only; defaults ≠ `DEFAULT_WEIGHTS` |
| **H12-3** | Frozen pred offset uses `int()` truncate vs CP-SAT `ceil` |
| **H12-4** | BFF still clamps `time_limit_s` to 600 |
| **H12-5** | Benchmark README denies Brandimarte vendoring + stale min-alt narrative |

## MEDIUM

M12-1 unknown LBBD cut kinds silent in flat applicator; M12-2 `num_workers` silent clamp; M12-3 energy/material `ge=0`; M12-4 native exception swallow; M12-5 SDST negative drop; M12-6 ML advisory `LBBD`/`LBBD-HD` invalid names.

## Non-goals

Native `p_{o,m}` ABI; dmorill GPL; KI-S3 cut revival; full TOU peak-power.
