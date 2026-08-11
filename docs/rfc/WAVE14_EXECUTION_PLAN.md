# Wave 14 execution plan

| Step | ID | Exit |
|---|---|---|
| 14.1 | C14-crash | Init `per_window_limit` before branching |
| 14.2 | C14-1 | Thread op-id offsets into ALNS CP-SAT repair + reanchor |
| 14.3 | C14-2 | Skip virtualization under frozen (metadata flag) |
| 14.4 | H14-1/5 | Reanchor `[]` + refuse missing offset |
| 14.5 | H14-nogood | Raise on empty nogood apply |
| 14.6 | Verify + commit + push | Focused green |

Non-goals: native ABI, GPL, KI-S3 revival, full RHC mega-decompose.
