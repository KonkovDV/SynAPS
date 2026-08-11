# Hyper Red Team — architecture / algebra / chains (Wave 13)

Date: 2026-08-11. Post Wave 12 (`d6592bd`).

## Verdict

**fail-open → Wave 13 required**

Wave 12 unit fixes hold. Production **RHC composition** nullifies frozen-predecessor algebra. ALNS diverges from CP-SAT on frozen×parallel. BaseSolver republishes makespan-only `weighted_sum`.

## CRITICAL

| ID | Finding |
|---|---|
| **C13-1** | RHC clears preds then builds dead offsets; omits `frozen_context_*` |
| **C13-2** | ALNS virtualizes parallel then silently drops frozen occupancy |
| **C13-3** | Native greedy missing pred → `0.0` |

## HIGH

| ID | Finding |
|---|---|
| **H13-1** | BaseSolver `scalarize(DEFAULT)` ignores caller weights |
| **H13-3** | Reanchor stall returns illegal schedule for commit |
| **H13-6** | Replay pretends verified when metadata absent |

## MEDIUM

M13-1 demote MACHINE_OVERLAP; M13-2 contracts num_workers clamp; M13-3 native silence.
