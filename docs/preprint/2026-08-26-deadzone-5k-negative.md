# Night-window 5k analog — negative result (draft preprint skeleton)

> Not a calendar model. Not COVER at ≥10k. Not a Yes. Not Moskabelmet. Not INFIMUM.

**Status:** skeleton for an external witness. Numbers are bound to hashed
JSON under `benchmark/evidence/deadzone-5k-2026-08-25/`. Stronger wording
than that artifact is a defect.

## Question

On a 5000-operation, 8-machine instance with consecutive 8-hour night-analog
windows (22:00, no machine calendar), does any of five named SynAPS configs
return `scheduled_ratio = 1.0` and independent `verified_feasible = true`
on seeds 1, 42, and 999?

## Answer

No. `winning_configs = []`.

[АРТЕФАКТ: `summary_p2_3_5000x8.json`, SHA-256
`25a4cf8bf27052eb106f06724e2af678f9d0e0500e171d5131d0368e87e1c62d`]

## Geometry

Kernel `WorkCenter` had no shift calendar at the epoch of the run. Night is
encoded as per-op `[earliest_start, latest_finish]`. An operation cannot
cross midnight.

## Protocol

Named configs only. Registry kwargs. Seeds 1/42/999. Independent
`FeasibilityChecker`. Isolation watchdog = named `time_limit_s` + 90 s
(GREED had no registry box at epoch; study used 600 s).

## Results (epoch of the hashes)

| Config | ratio / note |
| --- | --- |
| GREED | stall 600 s × 3 |
| ALNS-500 | 0.0, `wall_clock_before_search`, `status=error`, ~253 s |
| RHC-GREEDY | 0.770–0.781, `MISSING_ASSIGNMENT` |
| RHC-GREEDY-COVER | 0.753–0.767, `global_greedy_cover=false` (10k gate) |
| RHC-ALNS-SEARCH-COVER | 0.758–0.771 |

Remainder 3k/5k/8k × 4/8/12 (RHC-GREEDY only): no cell at 1.0; six of nine
cells `worker_error` exit 1 (stderr not captured in that protocol).

## Failure taxonomy

See the evidence file. Each class now has a `KI-*` row in `KNOWN_ISSUES.md`.

## Reproduction

```text
python -m benchmark.study_deadzone_5k
```

Do not retune `global_greedy_cover_min_ops`, ALNS `time_limit_s`, or night
width to chase a Yes.

## What this does not show

Linux. A machine calendar (added later as a primitive, KI-N7). COVER ladder
60k–500k (different geometry, wide horizon). Industrial deployment.
