# Hyper Red Team — Wave 12 delta (post-fix)

Date: 2026-08-11

| ID | Pre | Post |
|---|---|---|
| C12-1 | Frozen CP-SAT no SDST | Pairwise frozen↔free SDST + context ops |
| C12-2 | Frozen aux invisible | Fixed aux intervals in cumulative |
| C12-3 | Missing pred cleared | Refuse / return None |
| C12-4 | Collapsed frozen skipped | ValueError |
| H12-1 | Capacity demoted | Kept proven |
| H12-2 | `material` ignored | Alias + empty→legacy hierarchical |
| H12-3 | `int` truncate | `ceil` |
| H12-4 | BFF clamp 600 | Reject `[1,7200]` |
| H12-5 | README stale | Vendored Brandimarte + T-30 note |

Lit anchors: CJME/EJOR 2026 LBBD; TST 2026 RFJSP-SDST; IJAMT 2026 CP-SAT globals; JAIR 2026 frugal ASP.
