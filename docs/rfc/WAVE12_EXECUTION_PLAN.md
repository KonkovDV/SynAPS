# Wave 12 execution plan — Lit + Hyper Red Team

- **Inputs:** `HYPER_REDTEAM_AUDIT_2026_08_11_W12.md`, `LIT_AUG2026_SYNAPS_BRIEF.md`
- **Date:** 2026-08-11

## Priority

| Step | ID | Exit |
|---|---|---|
| 12.1 | C12-1 | Frozen↔free SDST disjunctives in CP-SAT |
| 12.2 | C12-2 | Frozen aux intervals in cumulatives |
| 12.3 | C12-3+H12-3 | Refuse missing pred; `ceil` offsets |
| 12.4 | C12-4 | Fail loud on collapsed frozen intervals |
| 12.5 | H12-1 | Drop capacity from demotion set |
| 12.6 | H12-2 | CP-SAT weight normalize (`material` alias, DEFAULT defaults) |
| 12.7 | H12-4+H12-5 | BFF reject OOB; README honesty |
| 12.8 | M12-3/5/6 | ge=0 energy/material; SDST warn; ML registry names |
| 12.9 | Verify + commit + push | Focused green |

## Non-goals

Native ABI, GPL pack, TOU energy, RHC mega-decompose.
