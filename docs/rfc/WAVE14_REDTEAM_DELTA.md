# Wave 14 delta (post-fix)

| ID | Post |
|---|---|
| C14-crash | `per_window_limit = 0.0` before branch |
| C14-1 | Offsets threaded into ALNS CP-SAT repair + reanchor |
| C14-2 | Skip virtualization under frozen (metadata flag) |
| H14-1/5 | Reanchor `[]`; no `0.0` offset default |
| H14-nogood | Empty nogood raises |

Lit: RHO FJSP / Graph-RHO 2026 — frozen prefixes need live boundary constraints in the inner solver, not only outer CP-SAT.
