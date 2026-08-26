# Calendar routing (ADR-0005)

Router input: non-empty `WorkCenter.calendar`. Sets live in
`synaps.solvers.registry`: `CALENDAR_AWARE` (clip occupancy into a shift) and
`CALENDAR_REFUSING` (explicit empty `ERROR`, `calendar_unsupported`).

`route_solver_config` returns a name from `CALENDAR_AWARE` for any
`(portfolio_policy × latency ∈ {None, 1, 60, 180, 400, 900} × exact_required)`.
Per-op windows without a calendar are a different bit (`has_per_op_windows`).

Default 5k + calendar + BALANCED + no latency hint → `RHC-GREEDY` (clips).
Unconstrained 5k@400s (no calendar) still → `ALNS-500`.

| Config | Understands calendar (clips) | Understands per-op windows | Refuses non-empty calendar |
| --- | --- | --- | --- |
| `GREED` | yes | yes | no |
| `GREED-K1-3` | yes | yes | no |
| `BEAM-3` | yes | yes | no |
| `BEAM-5` | yes | yes | no |
| `CPSAT-10` | no | yes | yes |
| `CPSAT-30` | no | yes | yes |
| `CPSAT-120` | no | yes | yes |
| `CPSAT-PARETO-SKETCH-SETUP` | no | yes | yes (inner CP-SAT) |
| `CPSAT-EPS-SETUP-110` | no | yes | yes (inner CP-SAT) |
| `CPSAT-EPS-TARD-110` | no | yes | yes (inner CP-SAT) |
| `CPSAT-EPS-MATERIAL-110` | no | yes | yes (inner CP-SAT) |
| `LBBD-5` | no | yes | yes |
| `LBBD-10` | no | yes | yes |
| `LBBD-5-HD` | no | yes | yes |
| `LBBD-10-HD` | no | yes | yes |
| `LBBD-20-HD` | no | yes | yes |
| `ALNS-300` | no | yes (but not a coverage route on windows) | yes |
| `ALNS-500` | no | yes (but not a coverage route on windows) | yes |
| `ALNS-1000` | no | yes (but not a coverage route on windows) | yes |
| `RHC-ALNS` | no | via inner ALNS | yes (non-greedy inner) |
| `RHC-ALNS-100K` | no | via inner ALNS | yes (non-greedy inner) |
| `RHC-ALNS-SEARCH-COVER` | no | via inner ALNS | yes (non-greedy inner) |
| `RHC-CPSAT` | no | via inner CP-SAT | yes (non-greedy inner) |
| `RHC-GREEDY` | yes | yes | no |
| `RHC-GREEDY-COVER` | yes (Python clip; native skips) | yes | no |

Typical calendar route:

| ops | per-op windows | calendar | policy | latency | config | calendar-aware |
| --- | --- | --- | --- | --- | --- | --- |
| 5000 | no | yes | BALANCED | `None` | `RHC-GREEDY` | yes |
| 5000 | no | yes | BALANCED | 1 | `GREED` | yes |
| 5000 | no | yes | BALANCED | 180/400/900 | `RHC-GREEDY` | yes |
| 5000 | no | yes | any | `exact_required` | `RHC-GREEDY` | yes |
| >10000 | no | yes | any | any | `RHC-GREEDY-COVER` | yes |
| 5000 | no | no | BALANCED | 400 | `ALNS-500` | no (no calendar) |
