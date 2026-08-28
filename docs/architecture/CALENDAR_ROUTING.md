# Calendar routing (ADR-0005)

Router input: non-empty `WorkCenter.calendar`. Sets live in
`synaps.solvers.registry`: `CALENDAR_AWARE` (clip occupancy into a shift) and
`CALENDAR_REFUSING` (not auto-routed). Configs in `CALENDAR_REFUSING`
**encode** occupancy `[start − setup, end]` in one `ShiftInterval` when
selected. `route_solver_config` still returns a name from `CALENDAR_AWARE`
for any `(portfolio_policy × latency ∈ {None, 1, 60, 180, 400, 900} ×
exact_required)`. A 5k calendar instance is not a CP-SAT/ALNS coverage route.
Per-op windows without a calendar are a different bit (`has_per_op_windows`).

Default 5k + calendar + BALANCED + no latency hint → `RHC-GREEDY` (clips).
Unconstrained 5k@400s (no calendar) still → `ALNS-500`.

| Config | Understands calendar (clips / encodes) | Understands per-op windows | Auto-route on non-empty calendar |
| --- | --- | --- | --- |
| `GREED` | yes clip | yes | yes |
| `GREED-K1-3` | yes clip | yes | yes |
| `BEAM-3` | yes clip | yes | yes |
| `BEAM-5` | yes clip | yes | yes |
| `CPSAT-10` | yes encode occupancy | yes | no |
| `CPSAT-30` | yes encode occupancy | yes | no |
| `CPSAT-120` | yes encode occupancy | yes | no |
| `CPSAT-PARETO-SKETCH-SETUP` | yes encode (inner CP-SAT) | yes | no |
| `CPSAT-EPS-SETUP-110` | yes encode (inner CP-SAT) | yes | no |
| `CPSAT-EPS-TARD-110` | yes encode (inner CP-SAT) | yes | no |
| `CPSAT-EPS-MATERIAL-110` | yes encode (inner CP-SAT) | yes | no |
| `LBBD-5` | yes encode (CP-SAT subproblem) | yes | no |
| `LBBD-10` | yes encode (CP-SAT subproblem) | yes | no |
| `LBBD-5-HD` | yes encode (CP-SAT subproblem) | yes | no |
| `LBBD-10-HD` | yes encode (CP-SAT subproblem) | yes | no |
| `LBBD-20-HD` | yes encode (CP-SAT subproblem) | yes | no |
| `ALNS-300` | yes clip (greedy seed / repair) | yes (but not a coverage route on windows) | no |
| `ALNS-500` | yes clip | yes (but not a coverage route on windows) | no |
| `ALNS-1000` | yes clip | yes (but not a coverage route on windows) | no |
| `RHC-ALNS` | yes via inner ALNS clip | via inner ALNS | no |
| `RHC-ALNS-100K` | yes via inner ALNS clip | via inner ALNS | no |
| `RHC-ALNS-SEARCH-COVER` | yes via inner ALNS clip | via inner ALNS | no |
| `RHC-CPSAT` | yes via inner CP-SAT | via inner CP-SAT | no |
| `RHC-GREEDY` | yes clip | yes | yes |
| `RHC-GREEDY-COVER` | yes (Python clip; native skips) | yes | yes |

Typical calendar route:

| ops | per-op windows | calendar | policy | latency | config | calendar-aware |
| --- | --- | --- | --- | --- | --- | --- |
| 5000 | no | yes | BALANCED | `None` | `RHC-GREEDY` | yes |
| 5000 | no | yes | BALANCED | 1 | `GREED` | yes |
| 5000 | no | yes | BALANCED | 180/400/900 | `RHC-GREEDY` | yes |
| 5000 | no | yes | any | `exact_required` | `RHC-GREEDY` | yes |
| >10000 | no | yes | any | any | `RHC-GREEDY-COVER` | yes |
| 5000 | no | no | BALANCED | 400 | `ALNS-500` | no (no calendar) |
