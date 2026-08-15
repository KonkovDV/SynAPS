# OPS-WHEEL Red Team — 2026-08-15

Hostile pass on quoting native COVER times from the wrong CPython.
Claim level: **interpreter hygiene**. Not a kernel change. Not SOTA.

## Verdict

**ship the note.** `maturin` binds to the interpreter that invoked it.
On this Windows workstation the default was CPython 3.12 while
nervous-month probes use `py -3.13` (`C:\py313` junction). A 3.12 wheel
does not import under 3.13, so COVER stays on the Python loop without
an error. `CONTRIBUTING.md` and `docs/domains/cable.md` now say: build
with `--interpreter C:\py313\python.exe` (or `py -3.13 -m maturin`).
`.cursor-*` was already gitignored. `docs/gridplan/` is gitignored
(local GridPlan notes, not this kernel).

## Closed this pass

| ID | Sev | Hole | Close |
|----|-----|------|-------|
| **OPS-P0** | P2 | Probe 3.13 vs maturin 3.12 silent fallback | Documented; no auto-detect in COVER (would be a kernel change) |
| **OPS-P1** | P3 | `docs/gridplan/` untracked clutter | `.gitignore` |

## Attacks that had to land

| Attack | Result |
|--------|--------|
| 1600@8 4.3 s is therefore native | **blocked** — only if `synaps_native` imports in `py -3.13` |
| Change COVER’s 10k cliff | **blocked** |
| Vendor a second wheel into the repo | **blocked** |

## Live residuals

| ID | Sev | Finding |
|----|-----|---------|
| **OPS-R1** | P3 | COVER does not warn when the native module is missing for the running interpreter |
| **C7** | P2 | Release-grain, epsilon overflow, `sat_parameters` `num_workers`, `weighted_sum` units — kernel ledger, not this note |
| **S4-R1** | P1 | Notary default still exhaustive |

## Forbidden claims

Do not add: all 1600@8 numbers are native, AVX-512, C5a, INFIMUM.

## Next honest step

C7 kernel leftovers (ingest minute grain, epsilon `2^62`, block
`num_workers` under `strict`, portfolio `scalarize()`). Do not open C5a.
Do not flip the notary default. Do not put weights into COVER.
