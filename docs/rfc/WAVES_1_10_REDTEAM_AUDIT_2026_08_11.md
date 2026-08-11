# Red Team audit — Waves 1–10 (2026-08-11)

## Verdict

**pass-with-residuals** (deferred items now permanently classified)

Wave 10 implements the CP-SAT energy search term and locks the remaining
deferred items as permanent decisions (no silent reopen).

## Decisions verified

| Item | Claim | Verdict |
|---|---|---|
| CP-SAT energy arc term | Default weight 0; weight>0 prefers low energy | PASS — `test_cpsat_breaks_makespan_tie_by_energy_when_weighted` |
| Native ABI `p_{o,m}` | Permanent deferral | PASS — WAVE10_DEFERRED_DECISIONS + KI-F16 |
| dmorill GPL | Permanent forbid | PASS — KI-F16 / SDST README |
| KI-S3 | Keep accepted sentinel | PASS — xfail strict still registered |

## Wave scorecard (1–10)

| Waves | Verdict |
|---|---|
| 1–9 | Reconfirmed PASS (prior audits) |
| 10 | PASS |

## Accepted residuals

- Peak-power / TOU energy tariffs (out of scope)
- Further `_solve_core` decomposition
- Native duration-matrix ABI (permanent deferral)
- KI-S3 until a sound monotone LB exists

## Evidence

Focused: `tests/test_cpsat_solver.py` energy tests, architecture ratchet,
known-issues registry, prior wave residual suites as regression.
