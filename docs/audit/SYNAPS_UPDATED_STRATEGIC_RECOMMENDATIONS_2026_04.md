---
title: "SynAPS Updated Strategic Recommendations (April 2026 Trends)"
status: "active"
version: "2.0.0"
date: "2026-04-16"
tags: [synaps, scheduling, recommendations, alns, rl, epsilongrid, 2026]
mode: "explanation"
---

# SynAPS: Updated Strategic Recommendations (April 2026)

Этот документ обновляет стратегическую дорожную карту SynAPS на основе:
1. Реального состояния текущего ядра (ALNS, RHC, ParetoSliceCpSatSolver, LBBD-HD, deterministic router).
2. Верифицированных внешних трендов на апрель 2026.
3. Правила claim-boundary: разделение `implemented` и `target`.

## 0. Claim Boundary (обязательно)

### Implemented now
1. Deterministic solver kernel и портфель решателей в `synaps/solvers/`.
2. RHC/ALNS масштабирование и telemetry в metadata результатов.
3. ParetoSliceCpSatSolver как epsilon-constrained двухэтапный exact-path.

### Target (не выдается за реализованное)
1. RL-driven operator policy внутри ALNS.
2. Полноценный MOALNS с nondominated archive.
3. LLM planner/explainer в production-контуре.
4. Forward/backward frontier sweep в RHC.

## 1. External Evidence Snapshot (April 2026)

| Topic | Source | Date | Maturity | Practical takeaway |
|---|---|---|---|---|
| Learning-guided rolling horizon for long-horizon FJSP | arXiv:2502.15791 | 2025-02 | pilot->prod | Нейросетевой guidance для RHC снижает redundant recomputation и ускоряет solve на длинном горизонте |
| LLM-driven full-component ALNS evolution | arXiv:2603.06996 | 2026-03 | pilot | Эволюция destroy/repair/selection/acceptance модулей через LLM-loop даёт стабильный gain на крупных instances |
| Dynamic shop-floor adaptive heuristic portfolio | arXiv:2603.27628 | 2026-03 | pilot | Портфель разнообразных правил + онлайн отбор лучше single-rule под disruptions |
| Critical-path-aware graph RHO | arXiv:2604.10073 | 2026-04 | pilot | Graph-based critical-path bias улучшает long-horizon FJSP в режиме zero-shot/generalization |
| CP-SAT industrial baseline | Google OR-Tools docs | 2024-08 | production | Exact solver baseline и status semantics остаются опорным production стандартом |

## 2. Strategic Direction by Horizons

## 2.1 Now (0-6 weeks)

### A. ALNS adaptive control without full RL
1. Ввести contextual bandit поверх текущих destroy/repair операторов.
2. Использовать текущие metadata поля как state features (`repair_rejection_reasons`, `cpsat_repairs`, `feasibility_failures`, `due_pressure`).
3. Сохранить deterministic fallback: при деградации bandit политика отключается.

KPI:
1. `iterations_to_best` -15% на 10K/50K benchmark наборах.
2. `feasibility_failures` не выше baseline.
3. `cpsat_repair_timeouts` не растёт более чем на 10%.

Kill-switch:
1. Если за 3 consecutive benchmark runs quality хуже baseline > 2%, adaptive mode auto-off.

### B. MO readiness on top of ParetoSlice
1. Стандартизировать epsilon-grid policy: coarse-to-fine sweep.
2. Добавить sparse-front targeting: усиливать sampling в разреженных областях фронта.
3. Не переходить к full MOALNS до стабильного replay-corpus.

KPI:
1. Front coverage (diversity index) +20% при равном time budget.
2. Не ухудшать best weighted solution относительно текущего профиля.

Kill-switch:
1. Если grid sweep превышает budget > 1.3x без фронтового прироста, возвращаться к fixed epsilon profiles.

### C. RHC frontier hygiene
1. Добавить frontier health метрики: `candidate_pressure`, `spillover_count`, `due_drift`.
2. Внедрить bounded backward mini-pass после forward windows (не полный rewrite).

KPI:
1. `spillover_count` -25%.
2. `due_drift` -15%.

Kill-switch:
1. Если backward pass увеличивает wall-clock > 20% без улучшения due-drift, отключать backward path.

## 2.2 Next (6-16 weeks)

### D. RL-Driven ALNS (production-candidate)
1. Offline training policy (PPO/SAC или bandit->RL migration).
2. Online inference budget: < 1-5 ms на decision step.
3. Policy input только из нормализованных solver state features.
4. Policy output ограничен whitelist операторов (никакого bypass feasibility checker).

KPI:
1. Solve wall-clock -20..30% на больших instances при неизменной feasibility.
2. Quality (weighted objective / pareto dominance rate) лучше baseline.

Risk controls:
1. Shadow mode вначале: policy предлагает, deterministic path исполняет.
2. Gated rollout по instance size.

### E. MOALNS with nondominated archive
1. Вести bounded non-dominated archive (size-capped + epsilon-dominance pruning).
2. Selection pressure на разрежённые зоны фронта.
3. Repair objective conditioning по frontier region.

KPI:
1. Hypervolume +15%.
2. Stable archive update cost внутри budget.

Risk controls:
1. Archive memory cap.
2. Time-sliced archive maintenance.

### F. Bounded LLM Planner/Explainer
1. LLM слой выполняет только выбор тактики и объяснение trade-off.
2. Выполнение всегда делает deterministic solver kernel.
3. Explainability output связывается с replay artifact.

KPI:
1. Time-to-operator-decision -20% в what-if сценариях.
2. Operator acceptance rate >= baseline.

Risk controls:
1. Policy firewall: запрет на прямой solver override.
2. Mandatory feasibility check after every plan variant.

## 2.3 Later (16+ weeks)

1. Graph-native RHO guidance как отдельный accelerator path.
2. Multi-agent scheduling copilot в bounded orchestration framework.
3. Hardware-aware optimization lane (SIMD/GPU/NPU) только после профилирования bottlenecks.

## 3. Recommendation Ledger for Proposed Topics

### 3.1 RL-Driven ALNS
Status: `target` (high-priority)

Do now:
1. Contextual bandit + replay logging.
2. Dataset curation из production-like benchmark traces.

Do later:
1. Full RL policy training + shadow rollout.

### 3.2 Full MOALNS
Status: `target` (medium-high)

Do now:
1. Epsilon-grid governance + sparse-front heuristics.

Do later:
1. Archive-driven MOALNS integration.

### 3.3 LLM Multi-Agent Orchestration
Status: `target` (medium)

Do now:
1. Planner/explainer contracts и bounded tool policy.

Do later:
1. Multi-agent tactical decomposition with strict state provenance.

### 3.4 RHC Frontier Control (forward/backward)
Status: `partial` (short-term feasible)

Do now:
1. Bounded backward sweep prototype и A/B benchmark lane.

## 4. Immediate Technical Tip (actionable)

Текущий high-impact quick win:

`max_no_improve_iters` сделать функцией от `due_pressure` и `candidate_pressure`:
1. Низкое давление -> ранний stop для ускорения cheap windows.
2. Высокое давление -> увеличить tolerance к no-improve streak.

Proposed rule (example):
1. `effective_no_improve = base * (1 + alpha * due_pressure + beta * candidate_pressure)`
2. Clamp в диапазоне `[min_iters, max_iters]`.

## 5. Governance and Acceptance Criteria

Перед переводом любого `target` трека в `implemented`:
1. Replay-verified uplift vs deterministic baseline.
2. Нулевая регрессия feasibility.
3. Документированный fallback + kill-switch.
4. Обновлённые архитектурные и audit surfaces с тем же claim boundary.

## References

1. Learning-Guided Rolling Horizon Optimization for Long-Horizon Flexible Job-Shop Scheduling, arXiv:2502.15791.
2. Large Language Model-Driven Full-Component Evolution of Adaptive Large Neighborhood Search, arXiv:2603.06996.
3. DSevolve: Enabling Real-Time Adaptive Scheduling on Dynamic Shop Floor with LLM-Evolved Heuristic Portfolios, arXiv:2603.27628.
4. Graph-RHO: Critical-path-aware Heterogeneous Graph Network for Long-Horizon Flexible Job-Shop Scheduling, arXiv:2604.10073.
5. Google OR-Tools CP-SAT and Scheduling Guides, last updated 2024-08-28.
