# Wave 13 execution plan — architecture chain fix pack

| Step | ID | Exit |
|---|---|---|
| 13.1 | C13-1 | RHC offsets from original ops + frozen_context/aux + ceil; greedy uses real preds |
| 13.2 | C13-2 | ALNS ERROR if frozen ∧ virtualization |
| 13.3 | C13-3 | Native missing frozen pred → None |
| 13.4 | H13-3 | Reanchor failure → empty; RHC rejects window |
| 13.5 | H13-1 | BaseSolver publishes scalarize(caller weights) |
| 13.6 | H13-6 | Replay feasible only when verification performed |
| 13.7 | M13-1/2 | Overlap stays proven; contracts reject OOB workers |
| 13.8 | Verify + commit + push | Focused green |

Non-goals: native ABI, dmorill GPL, KI-S3 revival, TOU energy.
