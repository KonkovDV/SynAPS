# SynAPS Benchmark Studies Index

> **Scope**: Index of `benchmark/studies/` directories. Primary studies carry dated names
> (`YYYY-MM-DD-*`). Scratch/diagnostic runs have `_`-prefixed or `test-*` names and are
> excluded from this index.

---

## Canonical Studies

| Directory | Date | Focus | Key Outcome |
|-----------|------|-------|-------------|
| `2026-04-12-rhc-50k` | 2026-04-12 | First 50K RHC-ALNS smoke run | Baseline feasibility established; 0 ALNS iterations on initial geometry |
| `2026-04-13-rhc-50k-v2` | 2026-04-13 | Window/overlap geometry sweep | Identified op-count starvation at 240/60 default |
| `2026-04-13-rhc-50k-machine-index` | 2026-04-13 | Machine-index acceleration | Native C extension validated for candidate scoring |
| `2026-04-13-rhc-50k-window-cap` | 2026-04-13 | ALNS per-window time cap tuning | `alns_inner_window_time_cap_s=180` established |
| `2026-04-14-rhc-alns-canonical-tuned` | 2026-04-14 | Canonical tuned profile baseline | Profile v1 with `alns_presearch_max_window_ops=5000` |
| `2026-04-14-rhc-alns-repair-guard` | 2026-04-14 | ALNS presearch budget guard evaluation | Budget guard threshold at 240s diagnosed as blocking at 180s cap |
| `2026-04-15-rhc-alns-early-stop-30-recheck` | 2026-04-15 | Early-stop sensitivity | `max_no_improve_iters=30` confirmed as stable default |
| `2026-04-19-rhc-500k-gated-50k-baseline` | 2026-04-19 | 50K feasibility gate for 500K planning | Established 50K solve as prerequisite smoke gate |
| `2026-04-19-rhc-50k-both-lanes` | 2026-04-19 | Throughput vs strict-reproducibility lanes | Two-lane framework validated; `num_workers=4` throughput, `num_workers=1` strict |
| `2026-04-20-rhc-50k-solver-audit` | 2026-04-20 | ALNS solver-level audit | Budget guard + SA calibration identified as bottlenecks |
| `2026-04-21-rhc-50k-full-run` | 2026-04-21 | Full 50K timed run | `scheduled_ratio ~ 0%` confirmed with 480/120 geometry + guard enabled |
| `2026-04-23-rhc-50k-full-rerun` | 2026-04-23 | Post-patch rerun baseline | Warm-start and backtracking enabled; ratio still ~0% |
| `2026-04-25-rhc-alns-postpatch-v5` | 2026-04-25 | Feasibility-first routing patch | Feasibility-first mode routes ops correctly; intermediate post-patch study |
| `2026-04-25-full-test-50k` | 2026-04-25 | Post-feasibility-routing validation | 0.0% → partial improvement with feasibility-first |
| `2026-04-26-rhc-alns-geometry-doe-validation-v1` | 2026-04-26 | **DOE geometry sweep (primary reference)** | 480/120 + full_scan = 1531 ops; 0 ALNS iters (guard fires, budget < 240s min). 240/60 = 81 iters, 228 ops. See `summary.md` for full decision matrix |
| `2026-04-26-rhc-50k-full-validation-v1` | 2026-04-26 | Post-DOE full validation | 0% scheduled with guard + `due_admission_horizon_factor=2.0` |
| `2026-04-26-rhc-alns-precedence-ready-v1` | 2026-04-26 | `precedence_ready_candidate_filter` ablation | Disabling filter increases pool by ~3× at startup |
| `2026-04-26-rhc-100k-alns-academic-v4` | 2026-04-26 | 100K scale academic validation | RHC-ALNS produces feasible windows at 100K with correct geometry |
| `2026-04-27-rhc-50k-audit-v2-current-head` | 2026-04-27 | Pre-audit baseline at current HEAD | Last measurement before HYPERDEEP_AUDIT_PLAN_2026_04_27 implementation |
| `2026-04-27-rhc-100k-audit-v4-current-head` | 2026-04-27 | 100K pre-audit baseline | Metrics captured before R1–R9 audit changes |
| `2026-05-01-rhc-50k-audit-v3-post-critical-fixes` | 2026-05-01 | Fresh 50K post-critical-fixes rerun | Scheduled ratio improved on both solvers under native-backed execution; still partial and not algorithm-only comparable to the pure-Python `v2` anchor |
| `2026-05-01-rhc-100k-audit-v5-post-critical-fixes` | 2026-05-01 | Fresh bounded 100K post-critical-fixes rerun | `RHC-GREEDY` improved to `9287/100000`; `RHC-ALNS` regressed to `0/100000` in `445s` with no fallback repair |
| `2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap` | 2026-05-08 | Bounded 100K acceptance rerun after initial-seed cap fix | `RHC-ALNS` reaches `7236/100000` in `90.255s`, matching same-run greedy parity without `solver_metadata.error` |

---

## Scratch / Diagnostic Directories (excluded from index)

Directories with `_` prefix (`_diagnostic_*`, `_post-fix-*`, `_test_*`) and `test-*` names
are transient artefacts from interactive debugging sessions. They are not archived and may
be deleted without affecting canonical evidence.

---

## Evidence Hierarchy

| Tier | Purpose | Files |
|------|---------|-------|
| **Primary DOE** | Window geometry × admission sensitivity | `2026-04-26-rhc-alns-geometry-doe-validation-v1/summary.md` |
| **Scale gate (latest)** | Fresh 50K post-critical-fixes rerun on pushed `master` | `2026-05-01-rhc-50k-audit-v3-post-critical-fixes/` |
| **50K pure-Python anchor** | Clean comparison point before the native-backed rerun | `2026-04-27-rhc-50k-audit-v2-current-head/` |
| **Admission ablation** | `precedence_ready_candidate_filter` impact | `2026-04-26-rhc-alns-precedence-ready-v1/` |
| **100K pure-Python anchor** | Bounded current-head comparison before the native-backed rerun | `2026-04-27-rhc-100k-audit-v4-current-head/` |
| **100K regression snapshot** | Native-backed bounded 100K stall before the initial-seed fix | `2026-05-01-rhc-100k-audit-v5-post-critical-fixes/` |
| **100K accepted rerun** | Bounded 100K same-run parity after the bounded seed-cap fix | `2026-05-08-rhc-100k-audit-v11-post-bounded-seed-cap/` |
