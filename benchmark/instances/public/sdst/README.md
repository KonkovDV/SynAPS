# Public FJSP-SDST slice (Wave 5–6 / KI-F16c)

Hand-authored fixtures for loader smoke tests (job×job setups, triangle-friendly).

| File | Jobs | Machines | Ops | Notes |
|---|---|---|---|---|
| `toy_2x2.sdstfjs` | 2 | 2 | 4 | Minimal smoke |
| `fattahi_style_3x3.sdstfjs` | 3 | 3 | 6 | Small Fattahi-shaped |
| `medium_4x3.sdstfjs` | 4 | 3 | 9 | Medium smoke |

Full Shen / Fattahi-SDST / dmorill packs remain deferred pending explicit license
clearance for third-party redistributions. See
`docs/rfc/WAVE6_EXECUTION_PLAN.md`.

Format: `*.sdstfjs` — standard `.fjs` body, then one `N x N` integer setup
matrix per machine (job-to-job changeover; row = predecessor job index,
column = successor job index; diagonal ignored / zero).
