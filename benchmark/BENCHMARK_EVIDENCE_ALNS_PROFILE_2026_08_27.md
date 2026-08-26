# BENCHMARK_EVIDENCE_ALNS_PROFILE_2026_08_27

K2.4. One cProfile of `ALNS-500` on unconstrained 5000@8 seed 1, named
`time_limit_s=300`. Same cell as И5.2 (`wall_clock_before_search`, ratio 0.0,
wall 253.388 s). Native off, Windows 11, CPython 3.12. Kernel `9fe0e481`.

## One line

конструирование O(n^2*m) в evaluate_gap

`synaps/solvers/_dispatch_support.py:527` `evaluate_gap`: 15 108 752 calls,
47.737 s tottime. `find_earliest_feasible_slot` cumtime 211.6 s of 250.3 s
profiled. Next: `dict.get` 80.4M, `uuid.__hash__` 172.0M. Constructive greedy
seed; ALNS search never starts.

Evidence: `benchmark/evidence/alns-profile-2026-08-27/`.

## Non-claims

Not a rewrite of hashed ALNS JSON. Not an incremental-neighbourhood patch.
