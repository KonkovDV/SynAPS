# Public FJSP-SDST slice (Wave 5–7 / KI-F16c)

Hand-authored fixtures for loader smoke tests (job×job setups, triangle-friendly).

| File | Jobs | Machines | Ops | Notes |
|---|---|---|---|---|
| `toy_2x2.sdstfjs` | 2 | 2 | 4 | Minimal smoke |
| `fattahi_style_3x3.sdstfjs` | 3 | 3 | 6 | Small Fattahi-shaped |
| `medium_4x3.sdstfjs` | 4 | 3 | 9 | Medium smoke |

**License gate (Wave 7.4):** do **not** vendor
[dmorill/FJSSP_SDST_Instances](https://github.com/dmorill/FJSSP_SDST_Instances)
into SynAPS — that pack is **GPL-3.0**. Keep only hand-authored public
fixtures here. Full Shen / Fattahi-SDST packs also remain deferred pending
explicit license clearance for third-party redistributions.

Format: `*.sdstfjs` — standard `.fjs` body, then one `N x N` integer setup
matrix per machine (job-to-job changeover; row = predecessor job index,
column = successor job index; diagonal ignored / zero).
