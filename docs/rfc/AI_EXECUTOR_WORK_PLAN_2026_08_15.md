# Consolidated AI-executor work plan — 2026-08-15 (post-chat synthesis)

- **Repo:** SynAPS standalone (`C:\plans\SynAPS`). GridPlan / MobiRoute out of scope.
- **Claim boundary:** synthetic + public OSINT. Not Moskabelmet MES, not INFIMUM, not SOTA, not N-1/SAIDI.
- **Authority order:** this plan sequences the *open* findings mined from the full session
  (hyper-algebra audit 11.08 → Waves 11–15 → P0–P4 → cable C0–C6b). It does not re-open
  closed items. Each wave keeps its own RFC + Red Team delta.
- **Execution discipline for the AI:** one wave at a time; every wave ships
  code + tests + CHANGELOG + a hostile delta. No wave may weaken the RHC theorem
  (`FEASIBLE ⇒ proven_hard_violations = ∅`, stabilize converged).
  External-evidence pass is required only where marked; local mechanical steps skip it.

## 0. What is already closed (do not re-open)

| Closed | Where |
|--------|-------|
| RHC/ALNS false-FEASIBLE (notary, stabilize converged, forged base, empty repair) | A15-P0, RT-20 |
| LBBD invalid cuts (S1–S3), horizon-leak post-assembly, KI-S3 landmine | W12–W15 |
| `strict_setup_matrix` optimizer/checker divergence | Wave 14 |
| 50k / 500k GREEDY_COVER FEASIBLE (FIFO) | 2e3af19, 93eda33 |
| Campaign gate snapped to due slot | N-P0-2 |
| 1600@8 infeasibility | N-R1 closed (family + wheel + exhaust stay) |
| 8-stage seed distribution | C6a (5 seeds, all feasible, notary 0) |
| Freeze vs insert pair + occupancy vs span | C6b (occupancy 21 ≪ pool 48) |
| C6c weighted ALNS residual (search, not COVER) | 1600@8 seeds 1..5; PVC tard −478..−25; scalar 4/5 |
| K2 MAB + native rank leftovers (P2) | UCB1 opt-in determinism + pulls; ALNS-300 stays roulette; ceil snap already tested; `p_{o,m}` ABI still deferred |
| K3 wall-clock stamp | boolean matches wall cut; not a CI error; not bitwise identity |

## 1. Priority stack (do in this order)

### Wave C6c — Tardiness quality in residual search — **DONE 2026-08-15**

400@8 is **not** the quality instance (native 10k cliff; 80@8 tardiness 0).
Quality = C6a shop. ALNS-300 destroy 300 did 1 iter/90 s. Residual
`max_destroy=24` at ≥10k. PVC tardiness dropped on 5/5 vs cover; PVC
scalar beat makespan residual on 4/5 (seed 3 miss). Hole 48k–164k remains.
RT: `CABLE_C6C_REDTEAM_2026_08_15.md`.

### Wave C6-R1 — 8-stage weekly freeze waves (small) — **DONE 2026-08-15**

Hole: freeze evidence at 8/stage was a rush-insert pair, not four weekly
reshuffles. Ran `waves=4, disruptions=20`, seeds 1..2. Plumbing: stop chaining
dirty weeks; `notary_kinds` / `unrepaired_count`; CLI `nervous_report_ok`.
Seed 1 always green. Seed 2 `INFEASIBLE` once (notary=1, weeks 3–4), then
green on seven later months. Hamming path-dependent. Occupancy 21.
**Not claimed:** freeze works at 8-stage.
RT: `CABLE_C6R1_REDTEAM_2026_08_15.md`.

### Wave K2 — ALNS MAB + native rank leftovers (P2) — **DONE 2026-08-15**

UCB1 already existed (`mab_pair_selection`, Wave 6). K2 ships the seeded
greedy-repair determinism test, `mab_pair_pulls`, and a registry ratchet
(ALNS-300/500/1000 stay roulette). Default unchanged. Native ceil snap
already in `tests/test_alns_native_grain.py`. Full SDST `p_{o,m}` ABI stays
deferred. `stress_200` 2–3 s not claimed.
RT: `K2_ALNS_MAB_REDTEAM_2026_08_15.md`.

### Wave K3 — Determinism stamps (P2) — **DONE 2026-08-15**

`wall_clock_path_dependent` now matches a wall cut (`search_stop_reason`
starts with `wall_clock`), including ALNS pre-search ERROR. Informational:
not a CI error. Max-iterations runs stamp False. Residual: in-flight repair
still clamps to leftover wall. RT: `K3_WALL_STAMP_REDTEAM_2026_08_15.md`.

### Wave S4 — Delta notary (P1, real engineering) — **next**

Repair re-notaries all ~20k ops; dominates repair wall. Design: per-resource
occupancy segment tree keyed by drum pool; only re-check ops whose
`(wc, interval, aux)` neighbourhood changed plus frozen-window boundary.
Gate: prove delta ≡ exhaustive on the nervous month (both seeds) before
making it default. Exhaustive stays the default until then.

### Wave C-R2 — Documentation accuracy only

`peak_wip_drums` (span) vs `peak_processing_drums` (occupancy) vs Cumulative
aux (setup-hold): keep all three visible in `cable_kpis`; update
`docs/domains/cable.md` if any claim drifts. No kernel change — C5a stays
**gated** (C6b: occupancy 21 ≪ pool 48 ≪ span 155–222; hold-until-successor
would stress the pool).

### Wave OPS — Tooling hygiene (P3)

- OPS-WHEEL: document that maturin defaults to py3.12 while probes run on
  `C:\py313` junction; add `--interpreter` to the build note in
  `docs/domains/cable.md` / CONTRIBUTING.
- Repo hygiene: `.cursor-*.png`, `.cursor-tmp-diff.txt`, `docs/gridplan/`
  stay untracked; add `.cursor-*` to `.gitignore` if not present.

## 2. Explicit non-goals (permanent until a new RFC)

| Forbidden | Why |
|-----------|-----|
| C5a hold-until-successor | C6b falsified the trigger (occupancy ≪ pool) |
| C5d cross-order `predecessor_op_id` | Validator rejects; campaign snap is the honest approx |
| Colour-dedicated lines as 8-stage default | Coverage 0.854 |
| General ATCS floor window ≥240 on any job | Collapsed 16-stage coverage |
| Extra drums to fix coverage | Falsified (48→96 identical placement) |
| 1С:КоМод / MES / RFID ingest | APS without PDM is a different product |
| GPL FJSSP-SDST vendor, AVX-512, rayon main loop, DRL engine | Standing forbids |
| LRAT / proof-logging CP-SAT | Note only (OR-Tools 9.13+); out of scope this plan |
| LBBD as Benders on medium+ | Degraded to nogood enumeration by design (S2) |

## 3. Kernel findings from the 11.08 algebra audit — status ledger

| Finding | Status | Action for executor |
|---------|--------|---------------------|
| `evaluate()` phantom setup on lane-less parallel machines | Closed W14/W15 (lane-aware evaluator, `_build_lane_sequences`) | Regression tests only |
| Checker greedy lane inference incomplete (false rejects) | Mitigated: `LANE_INFERENCE_UNPROVEN` = hard UNKNOWN (W16b-1) | Keep; do not demote |
| DURATION_MISMATCH 1-min inter-solver tolerance | Intentional (commit 46a8ed3) | Do not remove without cross-solver parity run |
| CP-SAT sub-minute release truncation vs checker datetime compare | Open (P3) | Wave C7: normalize releases to minute grain at ingest; test with second-grain fixture |
| `epsilon_primary` big-M lacks the overflow guard | Open (P2) | Wave C7: same `2^62` guard as weighted branch + test |
| `sat_parameters` override can set `num_workers` → breaks strict determinism | Open (P2) | Wave C7: block `num_workers`/`random_seed` override under `strict` |
| `weighted_sum` units diverge (CP-SAT big-M vs 0.0 ALNS/LBBD) | Open (P2) | Wave C7: portfolio tie-break must use `scalarize()` on canonical `evaluate()`, not raw `weighted_sum`; regression test on tie |
| BHK `compute_machine_tsp_lower_bound` docstring over-claim on non-metric matrices | Guarded by sentinel test; cuts removed | Keep cut ban; fix docstring wording only |
| LBBD post-assembly `max_passes` non-convergence → silent infeasible | Closed (S2/A15): unproven ⇒ no cut, no FEASIBLE claim | — |
| Chain-only precedence (no DAG) | Scope decision | Document; do not extend without RFC |

## 4. Evidence rules for the executor

1. Never quote a single seed as a distribution (C6a rule: min/median/max).
2. Never mix vendor marketing (INFIMUM 39k/40 min, +78M ₽, −24% drums) with
   synthetic measurements.
3. Every `feasible` claim needs the notary line (`proven_hard_violations = 0`,
   `temporal_stabilization_converged` for RHC paths).
4. 20k-op tables are local evidence, not CI. Tiny GREED tests prove plumbing.
5. Function-length ratchet ≤80 lines for new helpers; `_run_python_cover_loop`
   stays exactly 80.
6. On Windows use `py -3.13`; native wheel via `--interpreter C:\py313\python.exe`.

## 5. Wave acceptance checklist (each wave)

- [ ] Focused pytest green (`tests/test_domain_cable.py`, `tests/test_cli.py`,
      `tests/test_architecture.py::test_function_length_ratchet` minimum).
- [ ] CHANGELOG entry under Unreleased.
- [ ] Red Team delta doc: closed / landed / forbidden / next honest step.
- [ ] No regression: 16-stage windowed ATCS tardiness stays 1 922 (seed 1).
- [ ] No C5a/C5d, no COVER default changes, no 50k/500k FIFO regression.

## 6. Immediate next command for the executor

```
python -m synaps cable-nervous-month --orders 1600 --machines-per-stage 8 \
  --drum-pool 48 --waves 4 --disruptions 20 --new-rush 0 --seeds 1,2
```

S4 delta notary. Do not open C5a. Do not put weights into COVER.
Do not claim C6-R1 waves are stably FEASIBLE. Do not flip ALNS to UCB1.
