# Hyper Red Team — Wave 11 delta (post-fix)

Date: 2026-08-11

| ID | Pre | Post |
|---|---|---|
| C1 | CP-SAT fallback ignored frozen | frozen + pred end offsets wired; fail-closed incomplete |
| C2 | FEASIBLE with unrepaired ops | `INFEASIBLE` + `unrepaired_count` |
| H1 | Global demotion on any UNPROVEN | WC-scoped demotion |
| H2 | Silent serial `max_parallel` | ERROR refuse |
| H3 | ALNS weight drift | `scalarize` + aliases |
| H4 | Advisory KeyError only | + ValueError |
| H5 | Silent clamp 600 | reject OOB `[1,7200]` |
| M1 | Dead applicator landmine | raise on retired kinds |

## Residual (deferred)

- M2 benchmark README polish
- M3 native exception fallthrough telemetry
- M4 SDST negative setup drop honesty
- Permanent: native ABI, dmorill GPL, KI-S3 cut revival
