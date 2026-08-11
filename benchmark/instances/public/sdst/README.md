# Public FJSP-SDST slice (Wave 5 / KI-F16c)

Tiny hand-authored fixture for loader smoke tests. Full Shen / Fattahi-SDST /
dmorill packs remain deferred (license + size); see
`docs/audit/SDST_BENCHMARKS_T31_2026_08_11.md` and `docs/rfc/WAVE5_EXECUTION_PLAN.md`.

Format: `*.sdstfjs` — standard `.fjs` body, then one `N x N` integer setup
matrix per machine (job-to-job changeover; row = predecessor job index,
column = successor job index; diagonal ignored / zero).
