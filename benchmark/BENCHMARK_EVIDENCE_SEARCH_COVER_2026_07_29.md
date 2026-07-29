# SynAPS SEARCH_COVER + Coverage-Pace Guard — Evidence (2026-07-29)

> **Status**: Artifact-bound evidence for the 2026-07 changes (coverage-pace
> guard, `RHC-ALNS-SEARCH-COVER`, `.fjs` loader). Not a universal performance
> guarantee.
> **Scope**: Reproducible bounded experiments on generated instances plus a
> synthetic public-format round-trip. Honest non-claims and one newly localized
> pre-existing RHC boundary.

---

## 1. What was measured

Three questions, one deterministic instance family, fixed seeds, equal wall
budgets:

1. **W1/W2** — Does the `SEARCH_COVER` geometry + coverage-pace guard enter the
   ALNS search regime without regressing the outer `scheduled_ratio` KPI
   relative to the historical `BALANCED` baseline?
2. **W1/W2 boundary** — How does independent feasibility scale with instance
   size under `SEARCH_COVER`?
3. **W3** — Does the standard `.fjs` loader integrate end-to-end and yield
   feasible, quality-ordered schedules on the pure-FJSP subset?

Environment: Python 3.13.7, OR-Tools 9.15.6755, `synaps_native` present
(native acceleration active). Feasibility is judged by the independent
`FeasibilityChecker`, never by solver self-report.

---

## 2. W1/W2 — A/B/C experiment (`industrial-2k`, seed 42, 60 s budget)

Instance: 2082 operations, 50 machines, 300 orders, horizon 6645 min
(≈ 25 windows at 360/90 geometry).

| Config | scheduled_ratio | inner_fallback_ratio | pace interventions | makespan (min) | wall (s) | verified feasible | violations |
|---|---|---|---|---|---|---|---|
| A — `BALANCED` baseline (480/120, guard off) | **0.386** | 1.00 | 0 | 479.8¹ | 122.8 | no | 1284 |
| B — `SEARCH_COVER` (360/90, guard **on**) | **1.000** | 0.857 | 0 | 2378.4 | 25.1 | no | 117 |
| C — `SEARCH_COVER` geometry, guard **off** | 1.000 | 0.857 | 0 | 2378.4 | 26.4 | no | 117 |

¹ Baseline's *lower* makespan is an artifact of partial coverage: it scheduled
only 38.6 % of operations, so the makespan is over a smaller set. This is
exactly the coverage/objective-contour trap the change set targets — a lower
objective on an incomplete schedule is not "better".

### Findings

- **Geometry effect is large and real.** `SEARCH_COVER` lifts coverage
  `0.386 → 1.000` and cuts independent violations `1284 → 117` (≈ 11×) versus
  the historical baseline, at ~5× less wall time (the smaller 360-min windows
  respect the budget instead of one oversized window overrunning to 122 s).
- **The pace guard behaves correctly, not cosmetically.** `pace_ratio` reached
  1.18 (> threshold 1.0), i.e. the commit rate already projected full coverage,
  so the guard correctly *did not* intervene (`interventions = 0`). B and C are
  therefore identical — the guard is a safety net that stays out of the way when
  coverage is on track. Its intervention path is exercised by the unit tests in
  `tests/test_coverage_pace_guard.py`, not by this on-track instance.
- **Guard adds no overhead when idle**: B vs C wall time differs by ~1 s (noise).

---

## 3. W1/W2 boundary — feasibility vs scale (`SEARCH_COVER`, 45 s)

| Preset | ops | windows | violations | breakdown |
|---|---|---|---|---|
| `large` | 184 | 7 | 3 | aux only |
| `industrial` | 791 | 14 | 26 | 20 precedence + 6 aux |
| `industrial-2k` | 2082 | — | 115 | 107 precedence + 8 aux |

### Newly localized pre-existing RHC boundary (not introduced by this change set)

Cross-window **precedence** violations grow with the window count. Makespan
(2378 min) sits well below the horizon (6645 min), so this is **not** horizon
clipping. Root cause: under a tight per-window budget on dense instances the
inner ALNS returns an infeasible incumbent (`inner_status = error`) and RHC
commits it; successor operations in later windows then start before a
predecessor committed in an earlier window finishes.

This is **pre-existing and orthogonal to W1/W2**: the `BALANCED` baseline
exhibits it more severely (1284 violations). The change set *reduces* it (11×)
but does not eliminate it. A proper fix (feasibility-gated window commit, or
cross-window precedence repair before commit) is a separate, higher-risk
initiative and is intentionally **not** attempted here.

**Claim boundary**: `SEARCH_COVER` improves coverage and reduces violations; it
does **not** currently guarantee a fully feasible schedule on dense
`industrial-2k`+ instances within short budgets.

### Update (2026-07-29, iteration 3): commit-time precedence gate closes the precedence component

A commit-time precedence gate
(`filter_commit_candidates_by_precedence`, opt-in
`commit_precedence_gate_enabled`, enabled in the `SEARCH_COVER` preset) now
defers commit candidates that would bake a cross-window precedence violation
into the frozen schedule; deferred ops are re-placed by later windows or the
residual greedy fill. Re-run of the §3 protocol (same seeds/budgets):

| Preset | before gate | after gate | coverage | deferred ops (unique) | makespan |
|---|---|---|---|---|---|
| `industrial` | 20 precedence + 6 aux | **0 precedence** + 4 aux | 1.000 | 134 | 2018 |
| `industrial-2k` | 107 precedence + 8 aux | **0 precedence** + 8 aux | 1.000 | 336 | 2237–2357¹ |

¹ Makespan varies across repeat runs because per-window budgets are
wall-clock-derived; the precedence-violation count is 0 in every observed run.
`deferred ops` counts unique operations ever deferred by the gate (a
carried-over op re-deferred in a later window is counted once).

The precedence component of the §3 boundary is eliminated at both scales with
no coverage loss and no systematic makespan penalty. Remaining residual:
AUX_RESOURCE_CAPACITY violations (aux reservation across setup+processing
windows is a different mechanism — event-sweep-aware commit gating — and
remains the next boundary).

---

## 4. W3 — `.fjs` public-format round-trip

Synthetic Brandimarte-style instance (10 jobs × 6 machines, 55 operations,
no SDST — pure FJSP subset), loaded through `benchmark.run_benchmark.load_problem`
(extension dispatch → `benchmark/fjs_loader.py`):

| Solver | makespan (min) | assignments | wall (s) | verified feasible |
|---|---|---|---|---|
| `GREED` | 259.0 | 55/55 | 0.01 | yes |
| `BEAM-3` | 228.0 | 55/55 | 0.02 | yes |
| `CPSAT-30` | 124.0 | 55/55 | 30.1 | yes |

The loader integrates end-to-end and the quality ordering
(`CPSAT-30 < BEAM-3 < GREED`) is the expected FJSP behavior — CP-SAT roughly
halves the greedy makespan. All schedules pass independent feasibility.

---

## 5. Non-claims

1. **Not a world record / not cross-instance portable** — numbers are bound to
   the generator, seeds, geometry, and hardware above.
2. **Not algorithm-only** — native acceleration is active and contributes to
   throughput; a pure-Python parity lane is maintained separately.
3. **Not full feasibility at scale** — `industrial-2k`+ schedules retain
   cross-window precedence violations (§3); coverage 1.0 is *placement*
   coverage, not a feasibility guarantee.
4. **`.fjs` makespans are not comparable** to per-pair-exact published results
   on heterogeneous-duration instances (min-duration mapping; see
   `benchmark/fjs_loader.py` `describe_fjs_mapping()`).

---

## 6. Known pre-existing test brittleness (localized; fixed in iteration 3)

Eight tests in `tests/test_alns_rhc_scaling.py` failed **locally when
`synaps_native` is built** and under OR-Tools 9.15. Confirmed **pre-existing**
by re-running them on the parent commit `85b6b92` (before the 2026-07 change
set) in an isolated `git worktree` — all eight fail there too, so this is not a
regression from the coverage-pace / SEARCH_COVER work.

Root cause: when native acceleration is present, ALNS seeds via the
`native_greedy` fast path (`alns_solver.py`, gated by
`native_initial_seed_enabled`, ~L2732), short-circuiting the `beam`/`greedy`
seed branch. Tests assert `initial_solver == "beam"`, exact
`FeasibilityChecker.check` call counts, or a specific `inner_status`, all of
which assume the non-native seed path (as in CI, where native is absent).

Recommended separate initiative: make these tests native-agnostic — either set
`native_initial_seed_enabled=False` where the test targets the Python seed path,
or widen the accepted `initial_solver` set to include `native_greedy`. Not
attempted here because the eight tests have heterogeneous root causes and live
in a file untouched by this change set (avoid masking semantics).

### Update (2026-07-29, iteration 3): hardened

All eight tests were made native-agnostic without masking their intent:

1. Tests targeting the Python beam/greedy seed lane now pass
   `native_initial_seed_enabled=False` explicitly (the lane CI exercises).
2. The fixed `time.monotonic` mark sequence in the budget-exhaustion test was
   replaced by a state-based clock robust to instrumentation call counts.
3. The recovery test pins `max_iterations=0` so the checker call sequence is
   deterministic again (the search loop invokes the checker once per
   iteration — the original "call #2 = final" assumption predated that).
4. The RHC budget-scaling test now derives its expected numbers from the
   ALNS window time cap instead of the remaining-time fraction, and the
   full-horizon inner-solve test opts out of the newer window-bounded
   sub-horizon default it never intended to exercise (root cause of its
   `inner_status=error`: a 36-op sub-problem cannot fit a 360+90-minute
   bounded sub-horizon by construction).

Result: `tests/test_alns_rhc_scaling.py` is green with native built (96/96)
and the fixed tests stay green with `SYNAPS_DISABLE_NATIVE_ACCELERATION=1`
(CI lane preserved).

---

## 7. Reproducibility

```bash
# W1/W2 A/B/C (deterministic; native active)
#   generate industrial-2k seed 42, run BALANCED vs SEARCH_COVER(guard on/off),
#   report scheduled_ratio / inner_fallback_ratio / pace metadata / feasibility.

# W3 round-trip
python -m benchmark.run_benchmark <instance>.fjs --solvers GREED BEAM-3 CPSAT-30 --compare
```

Ad-hoc experiment drivers used for this note live under
`archive/dev-scratch-2026-07/` (gitignored, not part of the tracked tree).
Unit coverage for the new behavior is tracked:
`tests/test_coverage_pace_guard.py`, `tests/test_fjs_loader.py`,
`tests/test_ml_advisory_json_model.py`.

---

## 8. Next steps

1. ~~Feasibility-gated window commit~~ — **done (iteration 3)** for the
   precedence component. The auxiliary-resource residual is **not** closed;
   see §9 for the iteration-4 negative result and the corrected approach.
2. ~~Native-agnostic hardening of the eight §6 tests~~ — **done (iteration 3)**.
3. Full 50K matrix run of `RHC-ALNS-SEARCH-COVER` vs `RHC-GREEDY-COVER` under
   the canonical evidence protocol.
4. Auxiliary-resource feasibility (see §9): bounded cluster re-solve — extract
   each aux-violating operation's precedence+machine neighbourhood and repair
   it jointly with CP-SAT / aux-constrained LNS (the LBBD decompose-and-repair
   pattern), since local gating, forward-shifting, and point-repair are all
   shown non-viable.

---

## 9. Iteration 4 — auxiliary-resource boundary: negative result (2026-07-29)

**Goal.** Close the last residual class from §3: `AUX_RESOURCE_CAPACITY`
(industrial: 4, industrial-2k: 8 after precedence reached 0).

**Root cause (confirmed).** Unlike precedence (a *pairwise* edge constraint
closed by the commit gate), aux-capacity is a *cumulative temporal* constraint
— `Σ q_o ≤ cap(r)` over every op holding `r` at time `t` across the
`[start−setup, end)` reservation window. The violations are **born in the
final `stabilize_temporal_consistency` + `recompute_assignment_setups` pass**
(`_solver.py`), which moves operations forward to repair precedence/machine
conflicts and recomputes setups — both slide aux reservation windows, and
that stabilizer is aux-agnostic. Diagnostic: with `fallback_repair=False` the
5 aux violations persist on the commit path itself, so residual greedy fill
(which *is* aux-aware via `find_earliest_feasible_slot`) is not the source.

**Two approaches attempted and rejected (with evidence):**

1. *Commit-time aux gate* (event-sweep mirroring FeasibilityChecker §5,
   defer-and-refill like the precedence gate). Unit-correct (12 tests) but it
   runs *before* the stabilizer, so it does not address where the violations
   arise: industrial stayed 4→6, industrial-2k 8→8. Not a fix.
2. *Aux-aware forward-shift inside the stabilizer* (a third shift type
   alongside precedence/machine). It **diverges**: the three forward shifts
   conflict and do not converge within the pass budget — industrial-2k
   regressed 8→76 violations (56 precedence + 9 overlap + 3 setup + 8 aux).
   Forward-only shifting is the wrong tool for a cumulative shared-resource
   constraint.
3. *Post-stabilize point-repair* (remove aux-violating ops, re-place them
   through the aux-aware `find_earliest_feasible_slot`). It **cascades**:
   moving a violating op forward leaves its successors starting before the
   op's new end, so precedence breaks — industrial 4 aux → 3 aux + 12
   precedence; industrial-2k 8 → 6 + 26. Local re-placement cannot hold a
   globally coupled schedule feasible.

All three were reverted; no aux code shipped this iteration (the honest
outcome is knowledge, not a false-progress commit).

**Why the residual is hard.** The remaining aux violations are small in count
(<1% of operations: 4/791, 8/2082) but they are **globally coupled**: any
local move that fixes an aux overrun perturbs precedence, machine setup, or
another resource's timeline, which re-introduces violations elsewhere. A
commit-time gate is too early (the stabilizer runs after it); a forward-shift
is non-convergent; a point-repair cascades. The constraint is inherently
joint.

**Corrected approach for the next iteration.** Solve the coupling jointly, not
locally: extract the connected cluster of each aux-violating operation plus its
precedence closure and machine neighbours, and re-solve that bounded cluster
with CP-SAT (which already models aux as a cumulative constraint) or an
aux-constrained LNS repair, freezing the rest. This is the same
decompose-and-exactly-repair pattern LBBD already uses for bottleneck
sequencing, applied to aux-capacity clusters — the only shown-sound way to keep
precedence, machine, and aux simultaneously feasible.
