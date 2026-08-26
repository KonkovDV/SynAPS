# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Honesty close (2026-08-26):** GitHub About and README portfolio count are
  25 configs (CI: `tests/test_readme_portfolio_count.py`). Scale protocol in
  README now points at
  `benchmark/BENCHMARK_EVIDENCE_COVER_2026_08_26.md`; the May 2026 50K file
  is marked `SUPERSEDED` and kept. COVER rows below that used **seed=1 only**
  remain **point estimates** under the project DOE rule (`--repeats>1` + CI
  before citation). Cable generator seeds 1..10 and C6-R1 re-probe:
  `benchmark/BENCHMARK_EVIDENCE_CABLE_C6_2026_08_26.md` (C6-R1 INFEASIBLE not
  reproduced). Night-window 5k@8 (P2.3): **no** named config hit
  `scheduled_ratio=1.0` and `verified_feasible=true` on seeds 1/42/999
  (`benchmark/BENCHMARK_EVIDENCE_DEADZONE_5K_2026_08_26.md`). A remainder
  `--resume` had rewritten `summary.json` to `incomplete`; harness now globs
  all `run_*.json` and keeps the P2.3 freeze copies. Dependabot PRs #1–#7
  closed; action pins applied on HEAD
  (`docs/rfc/DEPENDABOT_TRIAGE_2026_08_26.md`). Domain placement:
  `docs/adr/0003-domain-layer-placement.md`,
  `docs/adr/0004-domain-repo-standard.md`.

### Added

- **Kernel leftovers (C7):** ingest ceils `release_date` /
  `earliest_start` and floors `latest_finish` onto the integer-minute
  grid (`due_date` untouched — tardiness, not a hard window);
  `sat_parameters` cannot override `random_seed` under `determinism="strict"`
  (workers were already F9); `objective_sort_key` and Pareto slice pick
  use `scalarize()`, ignoring leftover CP-SAT big-M `weighted_sum`.
  F5 `epsilon_primary` `2^62` overflow was already shipped — ledger
  closed, not re-implemented. Evidence:
  `docs/rfc/CABLE_C7_KERNEL_LEFTOVERS_REDTEAM_2026_08_15.md`.

- **COVER ATCS ready rule (opt-in):** native + Python list-schedule can pop the
  ready set by Pinedo ATCS log-score (`cover_ready_rule="atcs"`) then still
  place by earliest-end machine. Unbounded ATCS collapsed month coverage
  (2026-08-14). **Windowed (non-delay) ATCS is FEASIBLE at 16/stage
  (2026-08-15):** tardiness 16 588 → 1 922 min, setup 2.64e6 → 2.52e6, peak WIP
  159 → 94 vs FIFO on the same cover probe. Nervous-month CLI defaults to
  windowed ATCS; registry `RHC-GREEDY-COVER` stays FIFO (50k/500k unchanged).
  Family-dedicated PVC/XLPE lines are mix-sized by SKU share with one
  flex overflow machine when n≥3 (opt-in `--family-lines`; tardiness at
  16/stage 24 227 → 3 670 vs ATCS-only 1 922). Colour-phase campaign
  default on: hash%3 stagger at >8 machines/stage, 6-colour wheel at
  ≤8 (rush skips a wait that would pass due). Colour-dedicated lines
  (`--colour-lines`) are opt-in; they explode tardiness at 16/stage
  and drop 8-stage coverage. **1600@8 is COVER-feasible** (2026-08-15)
  with mix-sized family flex + 6-colour wheel + continuation exhaust
  (ready-queue zero-setup + hot-machine stay): 20 316/20 316, setup
  49.1 min/op (budget 83), tardiness 87 134 vs 1 922 at 16/stage.
  A general ATCS floor window of one colour SMED collapsed 16-stage
  coverage; extra drums (48→96) did not move 8-stage placement; C5a
  stays gated (hold-until-successor does not add machine-minutes).
  `add_rush_orders`, `pin_issued_plan`, IncrementalRepair aux-window
  append as before. Not Moskabelmet MES, not INFIMUM, not a 500k
  cable proof.

- **Nervous-month cable benchmark:** `python -m synaps cable-nervous-month`.
  Synthetic 30-day high-mix MTO (1 600 parents, 36 SKUs, 15% rush, 6 stages).
  Seed=1, 16 machines/stage, 96 drums: 20 316 ops, `RHC-GREEDY-COVER`
  `feasible`, exhaustive notary empty, stabilize converged, generate 0.97 s /
  cover 9.36 s / notary 0.31 s, makespan 39 660/43 200 min. Four freeze+repair
  waves all `feasible` (repair 5.1–6.0 s vs re-cover 9.25 s, Hamming \(R\)
  ≤0.00064). Same mix at 8/stage overflowed under FIFO (coverage 0.50);
  with family flex + 6-colour wheel + continuation exhaust it is
  **FEASIBLE** (20 316/20 316, 4.3 s cover, 49.1 min/op, tardiness 87 134).
  **C6a multiseed 1..5** (2026-08-15, waves=0): all five COVER-feasible,
  notary 0; tardiness min/median/max **48 269 / 87 134 / 164 355**.
  **C6b freeze-pair** (seeds 1–2): freeze repair stays FEASIBLE, issued
  Hamming 0; rush WIP Δ **−66 / +40** (sign flips); processing occupancy
  **21** vs pool 48 vs span 155–222. **C6c weighted residual** (2026-08-15):
  COVER then ALNS (`--weighted-residual`); 1600@8 seeds 1..5, 60 s,
  destroy 20. PVC tardiness 48 056–164 080 (Δ −478..−25 vs cover);
  PVC scalar beat makespan residual **4/5**. 400@8 is the native-dead
  zone (5148 ops). **C6-R1 weekly freeze waves** (2026-08-15): 1600@8
  seeds 1–2, `waves=4`. Seed 1 always `feasible`/notary 0. Seed 2
  `INFEASIBLE` once (weeks 3–4, notary=1); seven later months green.
  Hamming is path-dependent. Dirty weeks no longer chain. CLI exit 1
  if a week is dirty. Occupancy stayed 21. Not a freeze-quality proof.
  `--seeds`, `--freeze-pair`, `--weighted-residual`.
  Evidence: `docs/rfc/CABLE_C6_POST_OSINT_PLAN_2026_08_15.md`,
  `docs/rfc/CABLE_C6C_REDTEAM_2026_08_15.md`,
  `docs/rfc/CABLE_C6R1_REDTEAM_2026_08_15.md`. Acceleration:
  `docs/rfc/CABLE_NERVOUS_MONTH_ACCEL_2026_08.md`. Red Team:
  `docs/rfc/CABLE_NERVOUS_MONTH_REDTEAM_2026_08_14.md`,
  `docs/rfc/CABLE_C6_PLAN_REDTEAM_2026_08_15.md`. OSINT ledger:
  `docs/rfc/CABLE_MOSKABELMET_OSINT_REDTEAM_2026_08_15.md`. Not Moskabelmet
  MES, not INFIMUM, not the 500k synthetic cover.

- **ALNS MAB UCB1 (opt-in, K2):** Wave 6 already selected destroy×repair
  pairs via `mab_pair_selection`. K2 adds `mab_pair_pulls`, a seeded
  greedy-repair determinism test, and a registry ratchet: ALNS-300/500/1000
  stay roulette. Default unchanged. Not Hendel α-UCB. Native `p_{o,m}` ABI
  still deferred. Evidence: `docs/rfc/K2_ALNS_MAB_REDTEAM_2026_08_15.md`.

- **ALNS/RHC wall stamp (K3):** `wall_clock_path_dependent` now matches a
  wall cut (`search_stop_reason` starts with `wall_clock`), including
  pre-search ERROR. Not a CI error. Not bitwise identity. Repair still
  clamps to leftover wall on a max-iterations stop. Evidence:
  `docs/rfc/K3_WALL_STAMP_REDTEAM_2026_08_15.md`.

- **Delta notary (S4, opt-in):** IncrementalRepair accepts
  `notary="exhaustive"|"delta"|"shadow"` (CLI `--repair-notary`).
  Default remains **exhaustive**. Aux Cumulative is always a full
  TimeTable sweep (A4: one drum pool; neighbourhood aux is unsound).
  Serial unary may skip unchanged machines; parallel machines never
  skip. `shadow` fail-closes: the FEASIBLE claim uses exhaustive.
  Lemma I (inherited frozen-machine overlap) is a CI attack: delta
  misses, shadow mismatches. Local 1600@8 seeds 1–2, `waves=4`,
  `--repair-notary shadow`: 8/8 `repair_notary_mismatch=False`,
  independent wave notary 0; dirty 36–53 ops / 36–43 of 48 WCs;
  shadow notary 0.37–0.48 s of a 2.2–2.5 s repair (placement
  dominates; N-R7 “notary is the wall” falsified here). **Not** the
  new default. No segment tree. Evidence:
  `docs/rfc/CABLE_S4_DELTA_NOTARY_REDTEAM_2026_08_15.md`.

- **Drum KPI split (C-R2):** `cable_kpis` publishes three peaks:
  `peak_wip_drums` (reel span), `peak_processing_drums` (`[start, end)`),
  `peak_aux_hold_drums` (`[start−setup, end)` stamp / checker F1).
  C6b occupancy **21** is processing, not F1 and not WIP span 155–222.
  C5a stays gated. Evidence:
  `docs/rfc/CABLE_CR2_DRUM_METRICS_REDTEAM_2026_08_15.md`.

- **Native wheel interpreter (OPS-WHEEL):** maturin must target the probe
  CPython (`--interpreter C:\py313\python.exe` / `py -3.13`). Default
  3.12 on this machine does not load under 3.13. `docs/gridplan/`
  gitignored. Evidence: `docs/rfc/OPS_WHEEL_REDTEAM_2026_08_15.md`.

- **Cable domain (encode-first, Moskabelmet-shaped):** `docs/domains/cable.md`
  is domain 9. Adapter writes metres→`base_duration_min`, pre-splits reels,
  parametric colour/section/compound SDST, drum aux, campaign
  `earliest_start` buckets, `cable_kpis` (`peak_wip_drums`, Hamming R),
  named `CABLE_PVC_WEIGHTS` (does not change `DEFAULT_WEIGHTS`). CLI
  `python -m synaps cable-demo`. Repair freeze: `freeze_horizon_end` on
  `RepairRequest` / IncrementalRepair kwargs so a rush cannot steal
  issued-plan slots (breakdown of that op still can). Not live-factory
  data, not INFIMUM, not C5 hold-until-successor.

### Changed

- **Cable campaign gate:** `apply_campaign_windows` opens a shared
  `earliest_start` at the earliest **release** in a `(state, due-slot)` group.
  Snapping the gate to the due-date slot forbade starting until the due bucket
  and made a loaded month horizon-infeasible. Regression:
  `test_campaign_gate_is_release_not_due`.

- **500k GREEDY_COVER evidence:** model cap is 500_000 operations.
  Native parallel SGS (Kolisch ready-heap, integer `ceil(base/speed)`
  grain, SDST, horizon/`latest_finish`, aux delay on every eligible
  machine, PREFETCHT0, no AVX-512) at ≥10k ops.
  `generate_large_instance(500000, n_machines=1000, n_aux_resources=100,
  machine_flexibility=0.05, horizon_hours=720, seed=1)` → 499 770 ops
  (order-packing undershoot on this seed), `FEASIBLE`, notary empty,
  stabilize converged, 3 leftovers into residual, makespan 31 656 /
  43 200 min, ~145 s solve / ~28 s generate, ~2.3 GB RSS. Same load
  class as 50k@100 machines. Not SOTA.
  200k@400 machines / 40 aux: 200 000 ops, `FEASIBLE`, ~45 s.
  100k@200: 100 000 ops, `FEASIBLE`, ~26 s.
- **50k GREEDY_COVER global list-schedule:** `RHC-GREEDY-COVER` at ≥10k
  ops places the full instance with one non-delay list-schedule (append
  after each machine's ready time) instead of quadratic gap insertion
  across ~90 rolling windows. Leftovers still use residual gap-fill.
  Horizon overflow is still `ERROR`. This is a coverage path, not a SOTA
  claim.
- **60k GREEDY_COVER evidence:** `generate_large_instance(60000,
  n_machines=100, horizon_hours=720, seed=1)` → 59 932 ops, `FEASIBLE`,
  notary empty, stabilize converged, makespan 41 298 / 43 200 min,
  ~6.7 s (6 leftovers into residual). Same generator at 120 machines:
  60 000 ops, makespan 34 056, ~7.7 s. Not SOTA.
- **Residual cover at 100k:** bulk-load `MachineIndex.extend` and bisect
  aux release times in `_candidate_starts` so leftover gap-fill does not
  scan every historical aux window on every machine gap. Evidence:
  `generate_large_instance(100000, n_machines=200, horizon_hours=720,
  seed=1)` → 100 000 ops, `FEASIBLE`, notary empty, stabilize
  converged, makespan 33 627 / 43 200 min, ~26 s (~157 leftovers into
  residual). Same load class as 50k@100 machines, not SOTA.
- **List-schedule insertion SGS:** when a ready op cannot append to a
  machine tail (aux delay / `latest_finish` / horizon), GREEDY_COVER
  inserts into the earliest idle gap and keeps the successor on the
  ready heap instead of dumping the chain into residual gap-fill.
  At most 64 in-pass inserts, and only below 80k ops: at 100k
  insertion fragments the calendar and residual gap-fill hangs.
- **List-schedule honors `Operation.latest_finish`:** the append-only
  cover caps the aux-bump horizon at the G11 latest-finish offset so an
  outage window cannot be parked past the declared finish
  (`HORIZON_BOUND_VIOLATION`). Gap insert uses the same cap via
  `find_earliest_feasible_slot`.
- **Long-horizon routing (RHO practice transfer):** instances with **>10k ops**
  now default to `RHC-GREEDY-COVER` instead of unvalidated `LBBD-HD` or
  monolithic `ALNS-500`. `5k@400s` stays `ALNS-500`; `60k@900s` and
  `100k@900s` also use `RHC-GREEDY-COVER` (the honest 50k `FEASIBLE`
  path). Named `RHC-ALNS` / `RHC-ALNS-100K` remain explicit registry
  profiles, not auto-routes. exact_required still uses LBBD-HD. Transfer
  from L-RHO (ICLR 2025, arXiv:2502.15791) and Graph-RHO (2026,
  arXiv:2604.10073) — rolling horizon, not a SOTA claim.
- **Native CPU prefetch (HPC §3.1):** `synaps_native` issues `PREFETCHT0` at
  distance 8 on RHC SoA/CSR gathers and `greedy_repair` SDST scans. AVX2/FMA3
  only (Raptor Lake; no AVX-512). Expected gain is at 500k+ L3 overflow, not
  a 50k wall-clock miracle.

### Fixed

- **CI (test-fast / lint / typecheck / control-plane):** native greedy
  repair records `aux_requirements` / `parallel_machines` skip reasons
  even when the Rust wheel is absent; ALNS seed-feasibility stub accepts
  `exhaustive=`; solve/repair OpenAPI schemas include 429; ruff 0.16 and
  mypy 2.3 `--strict` are green. Fastify/AJV `coerceTypes` mapped schema
  default `num_workers: null` to `0`; the BFF now treats coerced 0/null as
  unset and returns 422 (`AdmissionError`) for real out-of-range values
  instead of 500. Function-length ratchet: split `_attempt_alns_pair_repair`
  and `_run_python_cover_loop` after ruff wrap exceeded 80 lines. The
  `build-distributions` lock check now installs `uv` before `uv pip compile`
  (the job was previously unreachable behind red test-fast). Linux compile
  does not emit Windows-only `tzdata`; the lockfile matches that.

- **Wave 16 (Red Team atomicity close):**
  - **W16-P0-1** RHC `sealed_window_op_ids` no longer retains rewound ops;
    a rewound-and-not-recommitted op is no longer frozen at a stale position
    for the final stabilize pass.
  - **W16-P0-2** ALNS final claim now checks `frozen_assignments + incumbent`
    (plus `_violates_frozen_precedence`); a frozen-overlap incumbent is no
    longer returned FEASIBLE and committed by RHC.
  - **W16-P1** `IncrementalRepair.solve` runs a final `FeasibilityChecker`
    pass; a timed-out CP-SAT fallback that overlaps greedy placements no
    longer returns FEASIBLE.
  - **W16b-1** `proven_hard_violations` no longer demotes setup-gap
    violations on work centers verified under greedy lane inference; the
    claim is now `UNKNOWN`, not `FEASIBLE`, when `LANE_INFERENCE_UNPROVEN`
    is present.
  - **W16b-3** RHC `_evaluate_final` delegates to the canonical
    `synaps.objective.evaluate` (lane-aware setup, horizon-anchored
    tardiness for unscheduled orders).
  - **W16 / coverage notary:**
    - Native greedy repair skips aux/parallel kernels (aux-blind) and
      ignores `UNKNOWN_OPERATION` on frozen extra-ops so RHC windows
      after the first can use the native path.
    - `stabilize_temporal_consistency` refuses shifts past
      `latest_finish` / declared horizon, repairs aux occupancy, and
      sizes its pass budget from precedence-chain depth.
    - Reanchor fails closed on aux-dirty merged schedules.
    - ALNS acceptance/`_overlap` rejects aux-infeasible incumbents;
      final notary keeps frozen extra-ops as occupancy, not UNKNOWN.
    - IncrementalRepair virtualizes `max_parallel>1` into lanes.
    - Horizon extension remains a coverage tool: overflow past the
      declared `planning_horizon_end` is `ERROR`, not `FEASIBLE`.
    - RHC finalize notary uses `exhaustive=True` to match the customer
      oracle.
    - ALNS native initial seed tournaments against Python greedy when
      `n_ops <= initial_beam_op_limit` (native packing is complete, not
      quality; it was locking `test_alns_improves_over_initial` onto a
      worse-than-greedy incumbent).
    - ALNS `_reanchor_against_frozen` no longer `while True`s on stacked
      frozen extra-ops: jump by `max` overlapping end and abort if the
      earliest-start does not strictly increase (float dust on
      datetime→minutes). This is the hang that stalled a full pytest
      run around 37% with no failing names.
    - Accelerator tests that inject a fake `synaps_native` restore the
      real extension afterwards so later ALNS native tests are not
      poisoned (`_native_greedy_repair_batch is None`).
    - `greedy_repair_batch_native` fail-closes on an empty CSR row in
      Python even when an older wheel still emits machine-0 + 1e6.
    - ALNS window notary ignores `HORIZON_BOUND` on frozen extra-ops
      (prior-window occupancy past this subproblem's horizon) and still
      rejects real frozen/incumbent machine overlap via occupancy sweep.

### Added

- **Wave 15 close (algebra + portfolio honesty):**
  - **A15-P0-2 / P1-8** ALNS frozen precedence after pred-clear: `horizon_start`
    + offsets on every `_violates_frozen_precedence` site.
  - **A15-P0-3** setup-aware machine gap vs frozen on ALNS accept/repair.
  - **A15-P1-1…5** router `exact_required` first; ALNS-500 before ALNS-300;
    replay `feasible` = notary; seed + kwargs fingerprint;
    `effective_time_limit_s`.
  - **A15-P1-6** RHC stabilize does not move earlier windows
    (`immutable_op_ids`).
  - **A15-P2** native greedy `eligible=[]` expands to all WCs (empty CSR
    fail-closed); accel `native_available`/`native_module` share the full
    kernel OR; ALNS/RHC publish `wall_clock_path_dependent` (no bitwise
    identity claim under wall timeout); unknown ML advisory is stamped.
  - **G11** `Operation.earliest_start` / `latest_finish` honored by GREED,
    ALNS, CP-SAT, repair, RHC, checker, and LBBD cluster copies.

- **Wave 15 (algebra status theorem, partial):**
  - **A15-P0-1** RHC no longer claims `FEASIBLE` from coverage alone; final
    `FeasibilityChecker` + `proven_hard_violations` required.
  - **A15-P0-4** `stabilize_temporal_consistency` publishes `converged`; RHC
    refuses FEASIBLE when the pass cap left residual shifts.
  - **A15-P0-5** `repair_schedule` refuses empty `disrupted_op_ids` (would
    legalize a forged base plan).
  - Docs: `WAVE15_ALGEBRA_REDTEAM_PLAN_2026_08_12.md`,
    `WAVE15_REDTEAM_DELTA.md`.
  - Tests: `tests/test_algebra_rt15_probes.py`.
  - Closed in the follow-up close pass: A15-P0-2/3 and P1-1…10 (see above).

- **Wave 14 (RHC→ALNS composition + crash fix):**
  - RHC: always init `per_window_limit` (early-greedy UnboundLocal fix).
  - ALNS: thread op-id `frozen_predecessor_end_offsets` into CP-SAT repair; reanchor fail-closed; skip virtualization under frozen (not ERROR).
  - LBBD/HD: refuse empty/non-binding nogood apply.
  - Docs: `HYPER_REDTEAM_AUDIT_2026_08_11_W14.md`, `WAVE14_EXECUTION_PLAN.md`.
  - Tests: `tests/test_wave14_composition_rt.py`.

- **Wave 13 (architecture / chain / algebra Red Team):**
  - RHC: build frozen pred offsets **before** clear; pass `frozen_context_*` + aux; `ceil`; greedy uses original preds (C13-1).
  - ALNS refuses frozen×`max_parallel` virtualization (C13-2); native missing pred fail-closed (C13-3).
  - Reanchor failure returns empty; RHC will not commit illegal schedule (H13-3).
  - BaseSolver publishes `weighted_sum` with caller weights (H13-1); replay no longer pretends verified (H13-6).
  - `MACHINE_OVERLAP` stays proven; `SolveOptions.num_workers` rejects OOB.
  - Docs: `LIT_AUG2026_WAVE13_BRIEF.md`, `HYPER_REDTEAM_AUDIT_2026_08_11_W13.md`, `WAVE13_EXECUTION_PLAN.md`.
  - Tests: `tests/test_wave13_arch_rt.py`.

- **Wave 12 (Lit Aug 2026 + Hyper Red Team):**
  - CP-SAT frozen↔free SDST disjunctives + frozen aux cumulatives; refuse collapsed frozen / missing context (C12-1/2/4).
  - IncrementalRepair/ALNS: refuse missing frozen pred; `ceil` offsets (C12-3 / H12-3).
  - `proven_hard` no longer demotes physical `MACHINE_CAPACITY_VIOLATION` (H12-1).
  - CP-SAT accepts `material` alias; BFF rejects OOB time_limit/workers; Brandimarte README honesty.
  - ML advisory emits registry-valid `LBBD-5` / `LBBD-5-HD`; SDST negative setup warning; energy/material `ge=0`.
  - Docs: `LIT_AUG2026_SYNAPS_BRIEF.md`, `HYPER_REDTEAM_AUDIT_2026_08_11_W12.md`, `WAVE12_EXECUTION_PLAN.md`.
  - Tests: `tests/test_wave12_hyper_rt.py`.

- **Wave 11 (Hyper Red Team fix pack):**
  - IncrementalRepair: CP-SAT fallback honors frozen intervals/preds (C1); INFEASIBLE on unrepaired remainder (C2); refuses `max_parallel>1` (H2).
  - `proven_hard_violations` demotes greedy triggers per unproven WC only (H1).
  - ALNS `_objective_cost` unified with `DEFAULT_WEIGHTS` + `material`/`material_loss` aliases (H3).
  - Router advisory catches `ValueError`; `SolveOptions.time_limit_s` rejects OOB instead of silent 600 clamp (H4/H5).
  - LBBD/HD applicators refuse retired `setup_cost`/`machine_tsp` cuts (M1 / KI-S3).
  - Docs: `HYPER_REDTEAM_AUDIT_2026_08_11.md`, `WAVE11_EXECUTION_PLAN.md`.
  - Tests: `tests/test_wave11_hyper_rt.py`.

- **Wave 10 (CP-SAT energy + permanent deferrals):**
  - CP-SAT hierarchical objective includes scaled setup `energy_kwh` (default weight 0).
  - Permanent decisions: native `p_{o,m}` ABI deferred; dmorill GPL forbid; KI-S3 stays accepted.
  - Docs: `WAVE10_EXECUTION_PLAN.md`, `WAVE10_DEFERRED_DECISIONS.md`, RFC_E_FJSP update.
  - Tests: CP-SAT energy tie-break under non-zero weight.

- **Wave 9 (honesty / conformance / CI residuals):**
  - M0 conformance row for `machine_duration_overrides` (+ SOLVER_FIELD_CONFORMANCE).
  - GUARD-D3 soft cushion 1.5×; ALNS skips new repair when remaining wall < 1s.
  - LBBD/HD metadata `assignment_setup_lb` via `compute_assignment_setup_lb_total` (no KI-S3 cuts).
  - Extracted `_reanchor_against_frozen`; `_solve_core` ratchet 1681 → 1549.
  - RHC `_evaluate_final` includes setup energy.
  - Docs: `WAVE9_EXECUTION_PLAN.md`, `WAVES_1_9_REDTEAM_AUDIT_2026_08_11.md`.
  - Tests: `tests/test_wave9_residuals.py`.

- **Wave 8 (RT17 residuals + Red Team 1–8):**
  - `proven_hard_violations` + `verify_schedule_result` customer oracle (RT17-H2 / KI-F7 closed).
  - `_attach_canonical_objective` replaces full `ObjectiveValues` (RT17-M2).
  - Stronger energy ranking test; `docs/rfc/WAVE8_EXECUTION_PLAN.md`,
    `docs/rfc/WAVES_1_8_REDTEAM_AUDIT_2026_08_11.md`.
  - Tests: `tests/test_wave8_residuals.py`, exact-lane verify oracle.

- **Red Team Waves 1–7 audit** (`docs/rfc/WAVES_1_7_REDTEAM_AUDIT_2026_08_11.md`):
  pass-with-residuals; fixed RT17-H1 native repair metadata pretension
  (`native_greedy_repair_override_skips` observe-only); KI-F7 downgraded to
  `closed (envelope)` with portfolio oracle residual (RT17-H2).

- **Wave 7 (Wave 6 accepted residuals):**
  - `_destroy_worst` charges `energy_weight * energy_kwh` (native scorer skipped when weight > 0).
  - ALNS metadata: `native_greedy_repair_fallback_reason` / seed reason `machine_duration_overrides`.
  - Extracted `_attempt_alns_pair_repair` (+ CP-SAT/greedy lanes) from `_solve_core` (ratchet shrink).
  - SDST license gate: dmorill pack is GPL-3.0 — do not vendor (`benchmark/instances/public/sdst/README.md`).
  - Tests: `tests/test_wave7_residuals.py`.

- **Wave 6 (Wave 5 Red Team residuals):**
  - ALNS native greedy skipped when `machine_duration_overrides` present (H2).
  - ALNS search aggregates setup energy into objective/cost (`get_energy`, weight `energy`).
  - MAB `mab_pair_selection` selects destroy×repair pairs (`cpsat|greedy`).
  - SDST public slice: `fattahi_style_3x3`, `medium_4x3` (+ existing toy).
  - Tests: `tests/test_wave6_residuals.py`.

- **Wave 5 (open KI + Wave 3 RFC implementation):**
  - `docs/rfc/WAVE5_EXECUTION_PLAN.md` — execution order for KI-S3/F7/F16 and T-30/T-34/T-35.
  - **T-30 / p_{o,m}:** `Operation.machine_duration_overrides`; `duration_minutes_for` /
    `physical_processing_minutes_for`; `.fjs` loader fills UUID overrides; solvers/checker
    use `*_for`.
  - **T-35 / energy:** `ObjectiveValues.total_energy_kwh` aggregated in `evaluate` and
    published via BaseSolver boundary; `DEFAULT_WEIGHTS["energy"]=0`.
  - **T-34 / MAB:** `synaps.solvers._alns_mab.PairBandit` + opt-in `mab_pair_selection`.
  - **KI-F16c:** `benchmark/sdst_fjs_loader.py` + `benchmark/instances/public/sdst/toy_2x2.sdstfjs`.
  - Tests: `test_energy_and_pom`, `test_alns_mab`, `test_sdst_fjs_loader`, min-out fixed-set
    validity companion, F7 `LANE_INFERENCE_UNPROVEN`, solver-boundary energy publish.
  - **Impact (T-30):** heterogeneous `.fjs` alternatives are no longer the historical
    min-alternative relaxation — Brandimarte makespans under exact overrides are
    comparable to literature BKS when a solver claims OPTIMAL (KI-F16a).

- **Audit v4 Waves 1–4 (algebra correctness + governance):**
  - `synaps.timegrain.physical_processing_minutes` — feasibility floor distinct from the integer reservation grain.
  - Exact lane inference (`FeasibilityChecker._assign_lanes_exact` / `_exact_lane_assignment`) with greedy fallback (F7).
  - `compute_min_out_assignment_setup_lb` — cheap assignment-relaxation setup LB valid on any SDST matrix (F6 / T-23).
  - Architecture Rules 5–6 (`ObjectiveValues(` ratchet; public `*lb`/`*bound` helpers must be test-referenced).
  - `KNOWN_ISSUES.md` + `tests/test_known_issues_registry.py` (T-41 / F15): every redteam `xfail` must be registered.
  - Research artefacts: `docs/rfc/RFC_MACHINE_DEPENDENT_DURATIONS_P_OM.md` (T-30), `docs/rfc/RFC_E_FJSP_ENERGY_OBJECTIVE.md` (T-35), `docs/rfc/DESIGN_ALNS_MAB_OPERATOR_SELECTION.md` (T-34), `docs/adr/0002-proof-logging-veripb.md` (T-33 no-go), `docs/audit/OPTALCP_HEXALY_SPIKE_2026_08_11.md` (T-32), `docs/audit/SDST_BENCHMARKS_T31_2026_08_11.md` (T-31).
  - Tests: `test_checker_physical_floor`, `test_parallel_setup_occupancy`, `test_exact_lane_inference`, `test_alns_native_grain`, `test_unscheduled_tardiness`, `test_weighted_sum_boundary`, `test_evaluate_parallel_setup`, `test_tsp_lb_contract`, `test_cross_layer_setup_semantics`.
- `tests/test_model_field_conformance.py` + `docs/architecture/SOLVER_FIELD_CONFORMANCE.md` (M0): an executable solver×model-field matrix. For each representative solver (GREED/BEAM-3/CPSAT-10/LBBD-5/ALNS-300) × field (release_date, max_parallel, speed_factor, predecessor_op_id, setup_minutes) it builds a minimal instance where ignoring the field is demonstrably wrong and asserts the field is honored and the schedule feasible (25 checks, sub-second). Closes the architectural gap that let M1/M2 (silently-ignored fields) survive: fields are now regression-guarded, and the doc records the honor-or-explicitly-reject contract.
- `filter_commit_candidates_by_precedence` (`synaps/solvers/rhc/_window.py`) + opt-in `commit_precedence_gate_enabled` (default off; enabled in `SEARCH_COVER`): commit-time temporal precedence gate that defers candidates which would bake cross-window precedence violations into the frozen schedule; deferred ops are re-placed by later windows or residual greedy fill. Eliminates all PRECEDENCE_VIOLATIONs on `industrial` (20→0) and `industrial-2k` (107→0) at full coverage with slightly better makespan. Telemetry (emitted regardless of the flag): `commit_precedence_gate_enabled`, `commit_precedence_deferred_ops_total` (unique ops), per-window `commit_precedence_deferred_ops` (per-event, gate-on only). Tests: `tests/test_commit_precedence_gate.py`.
- `CoveragePaceController` (`synaps/solvers/rhc/_budget.py`): deterministic outer/inner objective alignment for RHC — projects final coverage from the observed per-window commit rate and, when the projection falls below threshold, reroutes the next window to the greedy commit path. Opt-in via `coverage_pace_guard_enabled` (default off; historical behavior unchanged). Telemetry: `coverage_pace_interventions`, `coverage_pace_final_ratio`.
- `RhcPolicy.SEARCH_COVER` preset and `RHC-ALNS-SEARCH-COVER` portfolio config: search-active DOE geometry (360/90, presearch cap 2000) combined with the coverage-pace guard and a 15% residual-fill time reserve, targeting 50K+ search-entry without scheduled_ratio regression.
- `benchmark/fjs_loader.py`: strict parser for the standard `.fjs` public FJSP benchmark format (Brandimarte / Hurink / DAFJS) with documented mapping caveats; `run_benchmark` now accepts `.fjs` files and directories.
- `JsonKnnRuntimeModel` + `RuntimePredictor.load_json()` (`synaps/ml_advisory.py`): torch-free deterministic k-NN solver advisor; `benchmark/train_runtime_advisor.py` trains the JSON artifact from `--compare` benchmark reports with a verified-feasible-only labeling gate (ADR-006).
- Tests: `test_coverage_pace_guard.py`, `test_fjs_loader.py`, `test_ml_advisory_json_model.py` (55 tests incl. reruns of touched suites).
- `benchmark/BENCHMARK_EVIDENCE_SEARCH_COVER_2026_07_29.md`: bounded A/B/C evidence — `SEARCH_COVER` lifts `industrial-2k` coverage 0.386→1.0 and cuts independent violations 11× vs the `BALANCED` baseline; documents a localized pre-existing RHC cross-window precedence boundary and pre-existing native-seed test brittleness (both confirmed on the parent commit).

### Fixed

- **Wave 5 residuals:**
  - **KI-F7:** greedy lane fallback that emits hard lane/setup faults now also emits
    advisory `LANE_INFERENCE_UNPROVEN` (`hard_violations` filters advisory kinds).
  - **KI-F16a:** when CP-SAT claims `OPTIMAL` on Brandimarte proven-OPT stems, assert
    equality to literature BKS (requires T-30 overrides).
  - **KI-S3:** status recorded as accepted sentinel; assignment LB fixed-set
    validity property tests land beside GUARD-S3 (no absolute subset-monotone claim).

- **Audit v4 Wave 1–2 algebra fixes:**
  - **F2/T-10:** `DURATION_MISMATCH` uses the physical floor (no 1-minute slop); ALNS native repair/seed snaps to ceil grain; optional `strict_grain` → `DURATION_BELOW_GRAIN`.
  - **F1/T-11:** parallel capacity sweep charges setup occupancy (`setup_window_start_by_op`).
  - **F7/T-12:** exact lane inference before greedy fallback.
  - **F3/T-13:** LBBD **and LBBD-HD** post-assembly are lane-aware (shared `synaps.solvers._lbbd_assembly`); `objective.evaluate` infers lanes; horizon overflow after shifts is unproven failure.
  - **F4/T-20:** BaseSolver boundary replaces the full `ObjectiveValues` vector from `evaluate` and sets `weighted_sum := scalarize(...)`.
  - **F5/T-14:** `epsilon_primary` shares the int64 overflow guard with big-M.
  - **F8/T-22:** CP-SAT release offsets use `ceil`; due offsets stay floored (documented).
  - **F9/T-15:** `num_workers` / `num_search_workers` rejected under `determinism="strict"` via `sat_parameters`.
  - **F10/T-21:** unscheduled orders charge tardiness against `planning_horizon_end` (evaluate, ALNS, HD via evaluate).
  - **F12/T-24:** LBBD **and LBBD-HD** master without incumbent under time limit → `TIMEOUT`, not spurious `INFEASIBLE`.
  - **F11/T-26:** ATCS / RHC window sizing / instance generator route through `physical_processing_minutes` (Rule-1 ratchet cleared to `{}`).
  - **F6/T-23:** BHK docstring contract corrected (fixed-set LB; no per-op discount); assignment LB added.
  - **F13:** checker docstring kinds aligned with emitted violation strings.
- **N1 (strict determinism restored; audit v3):** the D1 fix set `interleave_search` + `max_deterministic_time` but left `max_time_in_seconds` at the budget, so both limits were active and the wall clock (which on 8 interleaved workers maps to ~3× the deterministic budget, and whose wall/deterministic ratio rises further under CPU load) cut first — 4 runs at one seed gave 4 distinct makespans (204/202/196/192). The D3 timebox silently killed D1. Fix (see `docs/adr/0001-strict-determinism-single-thread.md`): `strict` (default) now runs CP-SAT single-threaded and stops on `max_deterministic_time = 0.5 * time_limit_s` as the SOLE binding limit (machine- and load-independent); the wall clock is only a loose 2× runaway safety, and `metadata["determinism_violated"]` is set if it, not the deterministic stop, ends the search. Verified: `redteam repro v3 N1` PASS (4/4 identical, wall ≤ 1.2× budget); `tests/test_cpsat_determinism.py` asserts one fingerprint AND `determinism_violated is False` under load. **Impact:** strict is single-threaded (throughput cost on large instances; ~50% of the search budget traded for wall headroom), but quality measured *better* than the broken multi-threaded default (181 vs 192–204). `determinism="fast"` keeps the multi-threaded portfolio.
- **N2 (LBBD master learns again; audit v3):** `cut_pool_fingerprint` keyed cuts on `(kind, bottleneck_ops, rhs)`; every no-good carries empty `bottleneck_ops` and `rhs=0.0`, so all no-goods collapsed to one fingerprint and the second (for a different assignment) was dropped as a duplicate — the master span-spun on one assignment (tiny_3x3: 20 iterations, pool size 1, 19 duplicates) and quality regressed (medium_stress_20x4 183→192). Fix: a no-good is fingerprinted by `frozenset(assignment_map.items())`; added `benders_active`/`quality_warning="lbbd_no_cuts_degenerate"`. Verified: `redteam repro v3 N2` PASS (tiny_3x3 pool 5, dup 0; medium_stress 178≤183); GUARD-S1/D2 green. `tests/test_lbbd_nogood_pool_growth.py`.
- **N3 (timebox not bypassable via sat_parameters; audit v3):** `_apply_sat_parameter_overrides` applied overrides after the limits and the docstring allowed it, so `sat_parameters={"max_time_in_seconds": 8000}` ran ~3× the budget. `max_time_in_seconds`/`max_deterministic_time` are now rejected with `ValueError`; the budget is owned only by `time_limit_s`. `tests/test_timebox_override_rejected.py`.
- **N4 (single metricity predicate + flag reaches solvers; audit v3):** `problem_profile._setup_matrix_is_metric` was a second copy of `synaps.validation.is_setup_matrix_metric` (its docstring said "Mirrors…"), and no `ScheduleResult` exposed the flag. Deleted the copy (profile calls the canonical predicate); `BaseSolver.__init_subclass__` injects `metadata["sdst_metric"]` for every solver. `tests/test_metricity_single_impl.py`.
- **N5 (raw LBBD relaxation reported, not clamped; audit v3):** reporting `min(relaxation, best_ub)` made `lb ≤ ub` true by construction, muffling the S1 invariant. New `_lbbd_cuts.reported_lower_bound` returns the raw relaxation plus `lower_bound_invariant_violated`; both LBBD solvers report the raw value and warn on violation. `tests/test_lower_bound_invariant.py`.
- **P0-4 grain switched to ceil (audit v3, Phase 3):** `timegrain.duration_minutes` now returns `max(1, ceil(base/speed))` instead of `round`. `round` rounded DOWN (3.333→3), reserving less than the physical processing time and baking that under-reservation into the makespan and the LBBD lower bound (the audit's "consistently wrong" concern). The earlier ceil attempt regressed ALNS only because the grain was inconsistent across call sites; now that every solver, the dispatch layer, and the feasibility checker route through the single `duration_minutes`, ceil is consistent and regresses nothing (verified: ALNS/e2e/incremental/LBBD/guards/conformance suites green). `FeasibilityChecker` DURATION_MISMATCH now compares the span against the canonical ceil grain exactly (the round-tolerant 1-minute slop is gone). **Impact:** makespan/bound figures on fractional-`speed_factor` instances shift up slightly and are superseded (`BENCHMARK_EVIDENCE_*` flagged). Verified: `redteam repro v3 P0-4` PASS (CPSAT 4.0 == GREEDY 4.0), `P0-3` PASS; `tests/test_timegrain.py`, `tests/test_duration_mismatch.py`.
- **Phase 0 safety net (audit v3):** built BEFORE further fixes, because the previous round created 5 new defects for lack of one. `tests/test_public_instances_bks.py` bundles Brandimarte mk01-mk10 with BKS thresholds (a claimed OPTIMAL or any LBBD lower bound above BKS fails CI); `tests/test_pyjobshop_cross_validation.py` cross-checks SynAPS makespan against an independent PyJobShop CP-SAT model (optional dep); `tests/test_model_field_conformance.py` extended to 9 model fields; `tests/test_architecture.py` enforces single-implementation/no-dead-code/function-length ratchets; `tests/test_redteam_guards.py` ports the repro GUARDS into the suite (GUARD-S3 an xfail sentinel until the machine-TSP monotonicity fix).
- Eight native/ortools-9.15-brittle tests in `tests/test_alns_rhc_scaling.py` hardened without masking intent: explicit `native_initial_seed_enabled=False` on Python-seed-lane tests, state-based fake clock instead of a fixed `time.monotonic` mark sequence, deterministic checker-call sequence via `max_iterations=0`, budget-scaling expectations derived from the ALNS window cap, and full-horizon inner-solve contract pinned via `window_bound_inner_horizon=False`. Suite green with native built (96/96) and on the native-disabled CI lane.
- `tests/test_e2e_rhc_alns_integration.py` zero-violation contract (pre-existing failure: 19 cross-window PRECEDENCE_VIOLATIONs on the 500-op fixture, reproduced on HEAD before this change) now holds by enabling the commit-time precedence gate in the E2E solve configuration.
- **P0-1 (correctness):** CP-SAT setup interval no longer welds `end_i` to `start_j`. The setup was modelled as an `IntervalVar` with `start=ends[i]`, `end=starts[j]` — and since a CP-SAT interval enforces `start + size == end`, this forced `start_j == end_i + setup` exactly, forbidding machine idle and right-shifting predecessors along precedence chains. It is now a right-justified window `[start_j - setup, start_j]` with its own start var (`su_start >= end_i` under the arc literal), which still feeds the aux-resource cumulative and matches the FeasibilityChecker setup-window semantics. Verified: a constructed idle-requiring instance returned makespan 150 (`OPTIMAL`) before and 110 after. Impact: CP-SAT (and LBBD subproblems using it) previously overstated makespan on any instance with non-zero setup plus machine idle; affected CP-SAT/LBBD numbers in prior `BENCHMARK_EVIDENCE_*` are superseded. Test: `tests/test_cpsat_setup_interval_regression.py`.
- **P0-2 (correctness):** CP-SAT symmetry breaking no longer cuts the optimum, and its default is now `False`. The old cut grouped machines by `(capability_group, speed_factor)` and imposed `sum(presences_a) >= sum(presences_b)` over operations for which the whole group was eligible — invalid whenever an operation was eligible on A but not B, since the machines are then not interchangeable. Symmetry classes are now strict: identical `capability_group`, `speed_factor`, `max_parallel`, setup-matrix signature, AND identical eligible-operation sets; the capacity ordering applies only within such a class. Verified: a construction with an M1-only operation returned makespan 110 with SB on vs 100 off before, and 100 in both after; a 200-instance property test asserts SB on/off agree. Impact: any prior CP-SAT result run with the default `enable_symmetry_breaking=True` may have been a cut optimum reported as `OPTIMAL`. Test: `tests/test_cpsat_symmetry_regression.py`.
- **S1 (correctness):** LBBD no longer emits the invalid `load_balance` cut that produced a fake optimality certificate. The cut added an unconditional master row `C_max >= max_k completion_k` (no `y` variables), where `completion_k` came from `_makespan_by_machine` — the incumbent's per-machine *finish times*, not its processing load (the variable was even named `machine_loads`). That asserts `C_max >= makespan(incumbent)` for every assignment, forbidding improvement and forcing the reported gap to ~0 in 1-2 iterations on any instance. Removed from both `lbbd_solver.py` and `lbbd_hd_solver.py` (the latter lacked even a `lb_rhs > lb` guard); `_makespan_by_machine` renamed to `_completion_time_by_machine` to prevent the naming confusion that caused the bug. The valid y-dependent load bound is already the master capacity constraint; the valid y-independent floor is `average_capacity_lb` in `lower_bounds.py`. Tests: `tests/test_lbbd_bound_validity.py`. **Impact:** every `lower_bound` / `gap` / `final_gap` value LBBD emitted before this change is invalid, so the LBBD convergence figures in `benchmark/BENCHMARK_EVIDENCE_*.md` are superseded. **Scope:** removing `load_balance` is necessary but NOT sufficient for a valid LBBD lower bound — the remaining optimization cuts also over-claim: `capacity`/`setup_cost`/`machine_tsp` discount only processing time (not setup) and may use a non-proven (TIMEOUT) subproblem right side (audit S2/S3), and `critical_path` uses the incumbent's realized (contention-inflated) longest path, over-claiming even on setup-free instances (observed raw master lb 186 vs proven optimum 141). A fully valid LBBD bound requires the S2 + S3 + critical-path cut rework, tracked as the next step; the `min(lb, best_ub)` clamp remains a defensive guard, not a validity guarantee.
- **S2/S3 (correctness):** LBBD lower bounds are now provably valid (never exceed the proven optimum). Building on the S1 `load_balance` removal, every remaining optimality cut was found to over-claim and was removed or replaced: (a) the `capacity` cut used the post-assembly makespan (an achieved upper bound, not a proven minimum) with a processing-only discount; (b) `setup_cost`/`machine_tsp` added `Σp + L(S)` where `L(S)` (`compute_machine_tsp_lower_bound` / `compute_sequence_independent_setup_lower_bound`) over-claims the true setup path (audit S3), so even a conditional no-good form was invalid (observed no-good right side 95 vs proven optimum 90); (c) `critical_path` used the incumbent's realized contention-inflated path. A deeper property was established: because the LBBD subproblem solves machine clusters independently and re-assembles them, `sub_makespan` is an upper bound on the fixed assignment's true cost — so nogood cuts cannot soundly tighten the reported lower bound. The fixes: emit only a full-assignment **no-good** cut when every cluster is proven OPTIMAL (S2 gate; TIMEOUT/ERROR subproblems emit nothing, tracked via `cut_pool.skipped_unproven_subproblem`); report the lower bound as the **cut-free master relaxation** (unique + capacity, CP-SAT duration rounding) capped at `best_ub`, which is provably valid; and treat a master-infeasible outcome with an existing incumbent as *search exhausted* (return the best schedule) rather than a spurious `INFEASIBLE`. Applied to both `lbbd_solver.py` and `lbbd_hd_solver.py`. **Impact:** LBBD now reports honest (weaker) bounds and larger gaps; all prior `lower_bound`/`gap` figures were fake and are superseded. Verified: reported lower bound ≤ CP-SAT proven optimum on bundled instances and 40 random setup+precedence instances (`tests/test_lbbd_bound_validity.py`), and `repro S1` passes. Obsolete tests asserting the removed `machine_tsp`/`critical_path` cut emission were removed with justification; `test_cut_pool_grows_with_iterations` was adapted to assert pool well-formedness (cut growth is no longer guaranteed). Follow-up: a validated setup lower bound could re-enable a sound analytic cut.
- **D3/D4 (timebox enforcement):** `time_limit_s` is now a hard wall-clock deadline in every long-running solver, honored jointly with `max_iterations` (whichever hits first wins). ALNS previously overshot an 8s budget up to 7.5× because the deadline check was gated behind `min_iterations` and each micro-CP-SAT repair got the full `repair_time_limit_s` regardless of remaining budget; the gate is removed and the repair budget is clamped to the remaining wall time each iteration. LBBD/LBBD-HD spent the full `sub_time_limit_s` per machine cluster with no global deadline (>15× overshoot on clustered instances); a shared `deadline` is now threaded into `_solve_subproblems`, `_solve_subproblems_parallel`, and `_solve_subproblems_sequential`, clamping each cluster's CP-SAT budget to the remaining time and refusing to start a cluster past the deadline. `pareto_slice_solver` clamps each ε-slice to the remaining budget and skips slices past the deadline. Verified: `redteam repro D3` worst overshoot 5.0×→1.0×; `tests/test_timebox_enforcement.py` asserts wall ≤ 1.2×budget+1s for ALNS/LBBD/LBBD-HD. **Impact:** wall-time figures for ALNS/LBBD/pareto in prior `BENCHMARK_EVIDENCE_*` reflect uncapped runs and are superseded; `max_iterations`-driven ALNS quality at a given budget may change because iterations now stop at the deadline.
- **D3 follow-up (LBBD master timebox):** the HiGHS assignment master (`_solve_master` / `_solve_precedence_aware_master`) ran with no time limit, so a single iteration on a non-trivial instance could exceed the whole solver budget — a `large` (177-op) LBBD-10 run blocked well past its 60s budget in one master solve. The master is now bounded per iteration to `min(remaining_deadline, sub_time_limit_s + 2)` via the HiGHS `time_limit` option, and the reported relaxation bound uses the proven `mip_dual_bound` (a valid lower bound) instead of the possibly-non-optimal primal incumbent `C_max`, preserving the S1/S2/S3 lower-bound-validity invariant on time-limited masters. Verified: the same 60s LBBD-10 run now returns in 60.0s with 5 iterations; bound-validity, determinism, and timebox suites stay green.
- **D1 (determinism):** CP-SAT is now reproducible at its default settings. With the previous default (`num_workers=8`, wall-clock limit) a fixed `random_seed` produced a different schedule on almost every run (measured 170/174/182 on `medium_stress_20x4`, ~7% makespan spread) because portfolio workers race under a wall-clock deadline. A new `determinism` mode (`"strict"` default, `"fast"` opt-out) enables OR-Tools' prescribed deterministic multi-threading — `interleave_search=True`, `interleave_batch_size=2*num_workers`, and `max_deterministic_time` in place of the wall-clock limit — so a fixed seed yields a byte-identical schedule; explicit `sat_parameters` overrides still win. The mode is recorded in `metadata["determinism"]`. Verified: `redteam repro D1` three runs identical (174.0 ×3); `tests/test_cpsat_determinism.py`. **Impact:** `strict` trades some speed/quality for reproducibility (a wall-clock portfolio can explore more in the same seconds), so CP-SAT/LBBD/ALNS-repair/pareto numbers produced under the old non-deterministic default in `BENCHMARK_EVIDENCE_*` are not reproducible and are superseded; `random_seed` only guarantees reproducibility in `strict`. README's "Deterministic-first / reproducible" claim is now scoped to `strict`.
- **D2 (determinism):** LBBD and LBBD-HD now return byte-identical schedules across runs at a fixed `random_seed`. Previously two runs gave the same makespan but different schedule fingerprints because `_solve_subproblems_parallel` collected cluster results in `as_completed` (completion) order, and the final assignment list had no stable order. Fix: cluster results are buffered by cluster index and merged in index order, and the returned assignments are sorted by the full stable key `(work_center_id, start_time, operation_id)`; combined with the D1 strict CP-SAT default this removes the remaining non-determinism. Verified: `redteam repro D2` two runs identical; `tests/test_lbbd_determinism.py`. **Impact:** restores the value of `replay.py`, `ScheduleResult.random_seed`, and the "auditable metadata" claim for LBBD.
- **D5 (quality-study repeats/statistics):** quality DOE studies were single-shot point estimates, uninformative given run-to-run spread. Added `benchmark/_stats.py` (`summarize_runs` — best/mean/std/coefficient-of-variation/95% CI + deviation-of-best-and-mean-from-BKS; `expand_seed_repeats` — distinct derived seeds per base seed) with `tests/test_benchmark_stats.py`. Wired a `quality_statistics` block into `study_rhc_alns_doe.py` (new `--repeats`/`--bks-makespan`), `study_rhc_alns_geometry_doe.py` (new `--repeats`), and `study_solver_scaling.py` (`quality_statistics_by_solver`); `study_routing_boundary.py` gained `--repeats` for seed coverage. `study_rhc_50k.py` already exposes `--runs` + `--seeds` + CVaR robustness. **Impact:** all prior single-shot DOE conclusions in `study_rhc_alns_*_doe.py` are point estimates and must be re-verified with `--repeats`>1 and confidence intervals before being cited (flagged in `STUDIES_INDEX.md`).
- **M1 (release_date honored):** an order's `release_date` (material not available before it) was declared on the model but ignored by every solver except the RHC layer — a 60-min op on an order released at H0+500min started at H0 in GREEDY/BEAM/CP-SAT/ALNS/LBBD, and the checker reported it CLEAN. Fixes: CP-SAT adds `start >= release_offset`; the greedy/beam dispatch seeds `earliest_start` with the release offset; ALNS native greedy repair and native initial seed floor each op's `min_start` at its release offset; and `FeasibilityChecker` gains a `RELEASE_DATE_VIOLATION` category (LBBD inherits the fix via its CP-SAT subproblems and greedy warm start). Verified: `redteam repro M1` PASS (no solver starts before release); `tests/test_release_date.py` (checker + CP-SAT + greedy). **Impact:** schedules on instances with release dates now respect material availability; any prior benchmark on such instances understated makespan/tardiness.
- **M3 (SDST metricity validated, not silent):** a setup matrix violating the triangle inequality (`s1→s3 = 100` while `s1→s2→s3 = 2`) was accepted with no validation surface. Added `synaps.validation.validate_setup_matrix_metricity` (enumerates every offending `(from, via, to)` triple per work center) and `is_setup_matrix_metric`, recorded `sdst_metric` on `ProblemProfile`, and documented the metricity dependence of `compute_machine_tsp_lower_bound`. Policy is **flag, don't forbid, don't rewrite**: non-metric matrices stay legal and are reported, never silently metric-closed (rewriting the user's setup data would mask the input, violating the audit's anti-masking rule). Verified: `tests/test_setup_metricity.py` (violation enumeration + `sdst_metric` in the profile). **Note:** `redteam repro M3`'s inline check asserts the *raw* matrix is metric, so it intentionally stays red under the flag-not-rewrite policy (making it green would require silently rewriting setup costs); the validation surface + `sdst_metric` flag are the actual remediation.
- **Q1 (beam search monotone in beam width):** beam makespan was non-monotone in the beam width (e.g. width 3/5 far worse than width 1 on `medium_stress_20x4`) because beams were ranked by a one-step ATCS score (incomparable across beams), Ow & Morton's second-stage completion-to-go projection was missing, and the final pick only considered last-step survivors. Fix: the ATCS index is now the first-stage child filter, a deterministic completion-to-go greedy rollout (earliest-feasible-completion, honoring precedence/release_date) is the second-stage beam ranking, and a global incumbent is kept over every completed rollout. Because beam search is not width-monotone in general, `BeamSearchDispatch.solve` returns the best schedule over effective widths 1..B, making makespan non-increasing in `beam_width` by construction. Removed the unsubstantiated "20-50% improvement" docstring claim. Verified: `redteam repro Q1` PASS (181→177.7→175.2→168.9→162.5→162.5); `tests/test_beam_monotonicity.py` (bundled + 12 random). `test_beam_width_1_equals_greedy` became `test_beam_width_1_not_worse_than_greedy` (beam-1 now uses the rollout, so it is ≤ greedy, not identical). **Impact:** BEAM configs now dominate GREEDY and are width-monotone; prior BEAM benchmark numbers are superseded.
- **Q3 (objective-bound units):** CP-SAT's `best_objective_bound` was the dual bound of the scalarized big-M objective (`makespan * secondary_bound + ...`), emitted with no units — 430797 on `tiny_3x3` at makespan 82 — so consumers misread it as a makespan bound and it was unusable as the LBBD S2 subproblem bound. Fix: publish the raw value as `scalarized_objective_bound`, and report `best_objective_bound` in makespan minutes with `objective_bound_units="makespan_minutes"` — `floor(bound / secondary_bound)` for the default weighted-sum objective (a valid makespan lower bound; the epsilon modes minimize makespan/primary directly, divisor 1). Verified: `redteam repro Q3` PASS (82 ≤ horizon); `tests/test_cpsat_objective_bound_units.py`. In `epsilon_primary` mode with a non-makespan primary the minimized objective is `primary*(H+1)+makespan`, so the dual bound is NOT a makespan bound — it is labeled `objective_bound_units="scalarized_objective"` instead of falsely claiming minutes (Red Team audit follow-up). Full staged-lexicographic replacement (brief P1-1) remains future work.
- **P0-4 (single canonical duration formula):** five call sites derived processing time divergently — CP-SAT/LBBD used `max(1, round(base/speed))` while the dispatch layer (`find_earliest_feasible_slot`) used the raw `base/speed`, so one operation was 3.0 min for CP-SAT and 3.333 for GREEDY and the solvers optimized numerically different problems. Added `synaps/timegrain.py::duration_minutes` as the single source of truth (`max(1, round(base/speed))` — integer minutes matching the CP-SAT/LBBD model; an earlier `ceil` attempt regressed ALNS reanchoring and was rejected, so `round` unifies the dispatch layer onto the established solver behavior rather than the reverse). CP-SAT, LBBD, LBBD-HD, and the dispatch layer now all call it; an architecture test (`tests/test_timegrain.py`) pins the formula and forbids a new inline `round(base/speed)` in any solver. Verified: `redteam repro P0-4` PASS (CPSAT 3.0 == GREEDY 3.0); dispatch/greedy/ALNS/e2e/LBBD/bound-validity suites green (no ALNS regression, unlike the ceil attempt). **Impact:** GREEDY schedules now use the same integer grain as CP-SAT; prior GREEDY/BEAM/ALNS makespan figures on fractional base/speed instances shift slightly and are superseded.
- **P0-3 (checker validates duration):** `FeasibilityChecker` never compared the assignment span to the operation's processing time, so an operation with `base_duration_min=10` on a `speed_factor=3` machine (3.33 min) submitted with a 1-minute span passed with zero violations. Added a `DURATION_MISMATCH` check that flags spans materially **shorter** than `base_duration_min / speed_factor` (a span too short to physically run the op), with a 1-minute tolerance to absorb the round/ceil/floor divergence between solvers (P0-4, a separate defect). Longer-than-expected spans (idle padding / the P0-4 speed-rounding divergence) are intentionally not flagged here. The M2 dispatch WC tie-break now also considers `material_loss` before the work-center id so a lower-material lane is still preferred when completion and setup tie. Verified: `redteam repro P0-3` PASS; `tests/test_duration_mismatch.py`. **Impact:** grossly-short operations are no longer certified feasible.
- **Q4 (ALNS discarded-search signal):** the final-violation recovery mechanism (unchanged, and correct) silently returned the initial seed with `status=feasible` when the whole search budget produced only an infeasible incumbent, so a portfolio could prefer it over a genuine improvement. ALNS now emits `metadata["quality_warning"] = "search_discarded_returned_seed"` when recovery fired (else `None`), exposing it to the portfolio winner selection. Verified: `tests/test_alns_quality_warning.py`.
- **M2 (max_parallel honored in dispatch):** a `max_parallel=2` work center with two 60-min ops in different states and a 600-min setup has optimum makespan 60 / setup 0 (run the lanes concurrently), but GREEDY/BEAM/ALNS serialized the machine and charged a phantom 600-min setup (makespan 720, a 12x error the checker missed) — only CP-SAT (which virtualizes lanes) was correct, flattering `--compare` for non-algorithmic reasons. Fix: the dispatch layer now virtualizes every `max_parallel > 1` work center into independent `max_parallel=1` lanes (the same model CP-SAT uses, but ungated on setups) before solving and unrolls `lane_id` back on the result; `GreedyDispatch`/`BeamSearchDispatch`/`AlnsSolver` gained a thin `solve` wrapper around `_solve_core`. The work-center choice for the ATCS-selected op is now the earliest-completion feasible slot (so an idle lane is used instead of queuing behind a busy one). LBBD was already correct via CP-SAT subproblems. Added `benchmark/instances/parallel_lanes_setup_2x2.json` to the corpus. Verified: `redteam repro M2` PASS (all five solvers makespan 60, setup 0, `lane_id` set); `tests/test_max_parallel_dispatch.py`. **Impact:** any `--compare` result on instances with parallel machines previously penalized the dispatch/ALNS lanes; those numbers are superseded.

### Changed

- Public GitHub surface hygiene: removed session audits/plans, Habr drafts, study JSON dumps, and debug scripts from the tracked tree; README trimmed to install / quick start / portfolio / claim boundary.
- `.gitignore` no longer blanket-ignores `docs/` or `benchmark/instances/`; local studies/audits stay on disk but unpublished.

### Added

- `RHC-GREEDY-COVER` portfolio config and `RhcPolicy.GREEDY_COVER` preset for coverage-complete constructive solves (time reserve, soft overrun; horizon extension is opt-in, default factor 1.0).
- RHC coverage knobs: `coverage_time_reserve_*`, `fallback_repair_on_timeout`, `fallback_repair_soft_budget_s`, `coverage_horizon_extension_factor`.
- `scripts/probe_coverage_10k.py` for quick industrial-10k coverage probes.
- Python lock files (`requirements-lock.txt`, `requirements-dev-lock.txt`) generated via `uv pip compile`.
- CycloneDX SBOM (`sbom.json`) generation and attestation in release workflow.
- Lock file freshness check in CI `build-distributions` job.
- `BENCHMARK_EVIDENCE_50K_2026_05_18.md` with reproducible protocol, non-claims, and failure taxonomy.
- 50K 3-seed matrix attempt documented (RHC-GREEDY `solver_error`; confirms 50K as stress boundary).
- Tenant ID abstraction in control-plane (`x-tenant-id` header, per-tenant rate limits, cross-tenant job ACL).
- `SYNAPS_CONTROL_PLANE_API_KEY_MAP` (JSON `{apiKey: tenantId}`) so multi-tenant identity is derived from credentials, not spoofable headers.
- Control-plane strips `assignments` on non-`feasible`/`optimal` solve responses and annotates `metadata.coverage_complete`.
- Control-plane admission gate: max ops/WCs/states/setup-cube, solver-class op caps, concurrent sync solve limit (default 2).
- `/metrics` and `/openapi.json` are private without auth unless `SYNAPS_CONTROL_PLANE_PUBLIC_METRICS` / `PUBLIC_OPENAPI` are set.
- `SYNAPS_REQUEST_ID` env var propagation to Python bridge for subprocess traceability.
- CI `benchmark-smoke` job for end-to-end solver validation on tiny instances.
- `installed-wheel-smoke` CI job that builds the wheel, installs it into a fresh venv, and runs `tests/smoke`.
- Smoke tests for installed wheel (`tests/smoke/test_installed_wheel.py`).
- Artifact provenance attestations in release workflow via `actions/attest-build-provenance`.
- Dependabot grouped updates for Python dev/runtime and GitHub Actions ecosystems.
- Dependabot coverage for npm (`control-plane`) and Cargo (`native/synaps_native`).

### Changed

- `industrial-*` instance generator planning horizon is now SDST-aware (`P/m×3 + 2×setup_LB`, floor `P/m×4.5`) so dense changeovers do not clip late ops.
- `benchmark/study_rhc_50k.py` GREEDY lane enables coverage-complete residual-fill knobs.
- Non-loopback control-plane binds refuse `ALLOW_ANONYMOUS`; require `API_KEY` or `API_KEY_MAP`.
- Shared API key ignores spoofable `x-tenant-id` unless `SYNAPS_CONTROL_PLANE_TRUST_TENANT_HEADER=1` or the key is mapped via `API_KEY_MAP`.
- `SYNAPS_PYTHON_EXEC_TIMEOUT_MS=0` is ignored unless `SYNAPS_PYTHON_EXEC_ALLOW_UNLIMITED_TIMEOUT=1` (defaults back to 300s).
- BFF defaults `SYNAPS_RESOURCE_GUARDS_FAIL_OPEN=0`; portfolio fail-closed when `SYNAPS_ENABLE_RESOURCE_GUARDS=1`.
- BFF defaults `SYNAPS_SOLVE_MEMORY_LIMIT_MB=4096` and samples RSS during guarded solves.
- ACL setup interpolation budget lowered to 50k with full `|W|×|S|²` pre-check.
- `SYNAPS_INSTANCE_DIR` refuses repository-root (or parent) mounts.
- All GitHub Actions in `.github/workflows/` pinned to full commit SHAs for supply-chain security.
- README updated with OpenSSF Scorecard badge and supply-chain hardening notes.
- `pyproject.toml` excludes `synaps/scripts` and `tests/fixtures` from ruff/mypy to avoid diagnostic noise on debug scripts.

### Fixed

- RHC no longer abandons residual greedy coverage solely because rolling windows exhausted the global timebox; soft overrun + reserved budget keep leftover ops fillable.
- Coverage reserve is capped at 50% of `time_limit_s` so short budgets cannot starve the window loop.
- RHC inner ALNS/CPSAT subproblems are window-horizon-bounded by default (`window_bound_inner_horizon`) to raise commit yield.
- ALNS Phase-1 seed/completion is hard-capped via `phase1_wall_fraction` (default 0.5); `frozen_initial_repair_max_ops` default raised to 2000 for RHC window sizes.
- Soft overrun is disabled when `SYNAPS_ENABLE_RESOURCE_GUARDS` is active so wall time cannot exceed the advertised solve timeout.
- `verified_feasible` always checks the caller's declared `planning_horizon_end` (solver placement-horizon extension no longer rewrites the contract).
- Async solve job GET requires exact tenant match (`null` only readable without a resolved tenant).
- `Makefile` `native-test` target indentation (was nested inside `native-build` recipe).
- `tests/smoke/__init__.py` invalid syntax.
- Removed accidentally tracked native wheel (`native-dist/synaps_native-0.3.0-cp313-cp313-win_amd64.whl`) from git index.

## [0.1.0] - 2026-05-14

### Added

- Initial public release with 23 solver configurations.
- Deterministic-first solver portfolio: Greedy ATCS, Beam, CP-SAT, LBBD, LBBD-HD, ALNS, RHC variants.
- Reproducible benchmark harness including 50K and 500K study runners.
- Optional Rust/PyO3 native acceleration (`synaps_native` v0.3.0) for ATCS/RHC hot paths.
- TypeScript Fastify control-plane with AJV validation, OpenAPI, and Python subprocess bridge.
- Stable JSON solve/repair contracts with schema examples.
- Feasibility checker independent of solver output.
- Property-based and metamorphic test coverage (Hypothesis).
