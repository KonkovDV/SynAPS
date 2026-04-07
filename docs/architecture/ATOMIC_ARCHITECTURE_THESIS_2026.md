---
title: "SynAPS Atomic Architecture Thesis 2026"
status: "active"
version: "1.0.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, architecture, target-platform, edge, solver, xai]
mode: "explanation"
---

# SynAPS Atomic Architecture Thesis 2026

**Синтез киберфизической системы планирования: от транзистора до нейросети.**

Этот документ фиксирует **target-state architecture thesis** для SynAPS на весну 2026 года.

Он не доказывает, что все перечисленные здесь рантаймы, аппаратные профили, версии и интеграционные слои уже существуют в текущем репозитории. Для текущего доказанного состояния используйте:

1. [../../README.md](../../README.md)
2. [01_OVERVIEW.md](01_OVERVIEW.md)
3. [03_SOLVER_PORTFOLIO.md](03_SOLVER_PORTFOLIO.md)
4. [05_DEPLOYMENT.md](05_DEPLOYMENT.md)
5. [../partners/TECHNICAL_VERIFICATION_REPORT_2026_04.md](../partners/TECHNICAL_VERIFICATION_REPORT_2026_04.md)

## 1. Boundary of Truth

Этот документ описывает архитектурную цель, а не закрытый фактологический пакет.

Ключевые boundary conditions:

1. Python free-threaded builds в ветке 3.13 остаются экспериментальными и не могут считаться безусловным production baseline.
2. По официальной release-странице Kubernetes на `2026-04-02` стабильной веткой является `1.35.x`, а `1.36` относится к upcoming release track.
3. Talos Linux действительно соответствует zero-touch модели: immutable, API-managed, без SSH.
4. Temporal действительно соответствует durable execution модели и подходит для долгоживущих workflow вычислительной оркестрации.

Следствие:

Любая конкретная версия или vendor-specific привязка ниже должна читаться либо как **current fit**, либо как **target candidate**, но не как автоматически доказанный production fact.

## 2. Architectural Thesis in One Sentence

SynAPS должен развиваться как **полиглотная киберфизическая система**, где:

1. аппаратная топология подчинена latency и memory-locality constraints;
2. control plane отделён от solver hot path;
3. deterministic scheduling остаётся обязательным baseline;
4. ML и LLM работают только как advisory и XAI-слой над детерминированным ядром.

## 3. Layer 0 — Bare-Metal Physics

На уровне железа SynAPS нельзя проектировать как «обычный enterprise backend». Scheduling и repair workloads для NP-трудных задач чувствительны к locality, NUMA и memory bandwidth.

Целевые принципы:

1. **NUMA awareness**: solver workers не должны мигрировать между memory domains без явной причины.
2. **Large-L3 fit**: структуры локального поиска и feasibility checking должны проектироваться в data-oriented форме, чтобы максимизировать cache locality.
3. **Pinned hot path**: Rust-ядра ALNS, neighborhood evaluation и feasibility loops должны закрепляться за предсказуемыми CPU sets.
4. **Optional RDMA lane**: при высокой плотности телеметрии допустим переход к RDMA / zero-copy fabric, но только после доказанного network bottleneck.

Это не означает, что SynAPS обязан стартовать сразу с RDMA и pinning везде. Это означает, что его solver kernel не должен проектироваться так, будто locality не существует.

## 4. Layer 1 — Immutable Edge and Data Motion

Zero-touch factory deployment требует отказа от mutable node administration.

Целевая модель:

1. **Talos Linux** или аналогичный immutable Kubernetes OS как node baseline;
2. **Kubernetes** как orchestration substrate, с чёткой версионной дисциплиной;
3. **Cilium** как eBPF-first dataplane и kube-proxy replacement candidate;
4. **NATS JetStream** как миллисекундная event fabric;
5. **Temporal** как durable workflow layer для многоминутных и многочасовых расчётов.

### Operational rule

Если в цехе исчезает питание или отваливается worker node, система не должна терять run-level intent. Она должна либо:

1. восстановить workflow из durable state;
2. либо явно деградировать в операторски-понятный режим;
3. но не начинать планирование «с нуля» как будто ничего не произошло.

## 5. Layer 2 — Persistent State and Analytical Memory

Данные SynAPS не должны жить в одной универсальной СУБД «на все случаи». Нужен целевой split по физике нагрузки.

| Concern | Target storage role | Why |
| --- | --- | --- |
| Transactional truth | PostgreSQL 17/18 | ACID, role graph, work orders, BOM, event-backed state |
| Telemetry time series | TimescaleDB or equivalent time-series plane | high-ingest SCADA/IoT streams |
| Heavy OLAP and replay analytics | ClickHouse | columnar scans, solver history, KPI and XAI analytics |
| Similarity memory / RAG over historical schedules | Qdrant or equivalent vector store | nearest-neighbour retrieval over historical scheduling situations |
| Cache and distributed locks | Valkey | open governance, low-latency coordination, lock primitives |

Design rule:

PostgreSQL stores the authoritative operational truth. Columnar and vector systems remain derived or advisory planes unless explicitly promoted by contract.

## 6. Layer 3 — Algorithmic Core

Это центр тяжести платформы. Здесь особенно вреден single-language absolutism.

### 6.1 Language placement

1. **Python** — orchestration of exact solvers, ML pipelines, data validation, simulation, research velocity.
2. **Rust** — hot-path heuristics, ALNS operators, feasibility kernels, future native repair loops.
3. **TypeScript** — not here. It belongs at the control-plane edge, not inside the combinatorial kernel.

See [06_LANGUAGE_AND_RUNTIME_STRATEGY.md](06_LANGUAGE_AND_RUNTIME_STRATEGY.md) for the language contract.

### 6.2 Mathematical target shape

The intended algorithmic stack is hybrid:

1. constructive heuristics for immediate feasible baselines;
2. CP-SAT for exact bottleneck sequencing;
3. HiGHS or equivalent MIP engine for relaxed master problems;
4. ALNS / NSGA-family methods for repair and many-objective improvement;
5. strict feasibility verification as a separate truth gate.

### 6.3 Specific modelling principles

1. **AddCircuit / transition-aware sequencing** is the right direction for sequence-dependent setups where order itself is a first-class variable.
2. **OptionalIntervalVar** and related interval modelling remain central for auxiliary-resource consumption and operator occupancy.
3. **Repair radius control** matters more than full replan purity in live operations.
4. **Declarative rule layers** should absorb plant policy before it contaminates solver code.

### 6.4 Rule engine boundary

Hardcoding plant policy into heuristics is a long-term maintenance trap.

Target direction:

1. JSON/JDM or equivalent rule packs for process policy;
2. optional Rust-native rule execution paths such as GoRules / ZEN Engine class solutions;
3. solver kernels consume normalized rule outputs, not ad hoc business exceptions.

## 7. Layer 4 — Cognitive Advisory and XAI

LLM and GNN layers are not allowed to become the primary scheduling authority.

They exist for four functions only:

1. compressing the search space before solve;
2. recommending weights or dispatch parameters;
3. translating solver diffs into operator language;
4. supporting audited interaction loops such as text-to-SQL and override explanation.

### 7.1 GNN / pre-solver role

HGAT-style models are a good fit for:

1. bottleneck detection;
2. objective-weight suggestion;
3. dispatch parameter tuning;
4. disruption classification.

Inference should remain CPU-first when possible through ONNX Runtime, with GPU dependence justified only by measured workload shape.

### 7.2 LLM role

An on-prem LLM such as GLM-5.1 is a **candidate advisory runtime**, not the mathematical planner.

Its acceptable duties are:

1. XAI narration over solver provenance;
2. operator-facing explanation of why a repair occurred;
3. text-to-SQL and analytics assistance over bounded schemas;
4. guardrail feedback during manual override attempts.

Its forbidden duties are:

1. replacing feasibility checking;
2. issuing unaudited schedule commitments;
3. bypassing deterministic solver outputs.

## 8. Hardware–Software Synergy Matrix

The highest-performance SynAPS deployment is not “software on random servers”. It is a deliberately matched hardware/software system.

| Synergy zone | Software layer | Hardware priority | Why |
| --- | --- | --- | --- |
| Compute node | Rust ALNS + Python exact solvers | high clock speed, large L3, many memory channels | combinatorial search is locality- and bandwidth-sensitive |
| Data plane | PostgreSQL + JetStream + Temporal + ClickHouse | enterprise NVMe, high IOPS, PLP, large RAM | durable state and analytics die on poor storage behavior |
| AI advisory | vLLM + ONNX + GNN inference | multi-GPU or NPU pool, fast interconnect | large-context XAI and LLM serving are VRAM/interconnect constrained |
| Network fabric | Cilium + event transport | low-latency NICs, optional RDMA | telemetry and event latency can dominate repair responsiveness |

## 9. Profiled Node Topology

Production-grade SynAPS should be thought of as at least three node classes, not one homogeneous cluster.

| Node class | Main responsibility | Hardware bias |
| --- | --- | --- |
| **Compute nodes** | CP-SAT, ALNS, feasibility, repair | high-frequency CPU, large L3, 8-channel ECC memory |
| **AI inference nodes** | LLM XAI and heavyweight advisory inference | 4–8 accelerator cards or equivalent NPU density |
| **Control/data nodes** | PostgreSQL, ClickHouse, NATS, Temporal, control plane | enterprise NVMe, high RAM, predictable IO latency |

This does not mean SynAPS must begin life on three dedicated bare-metal classes. It means scaling should move toward specialization instead of pretending all workloads are equivalent.

## 10. Adoption Ladder

To avoid architecture cosplay, adoption should be staged.

1. **Current proof stage**: Python solver baseline, benchmark harness, bounded repair, feasibility checking.
2. **Product boundary stage**: stable API, operator workflow, explicit runtime split, audit trail, replay discipline.
3. **Performance stage**: native Rust kernel extraction for measured hotspots, profiled hardware, richer repair portfolio.
4. **Zero-touch edge stage**: immutable nodes, eBPF-first fabric, air-gapped artifact pipeline, specialized node pools.

## 11. What This Thesis Does Not Prove

This document does **not** prove:

1. that every named component is already deployed in the current repository;
2. that every vendor/version combination listed here is already field-validated;
3. that a Kubernetes `1.36` baseline is current fact on `2026-04-02`;
4. that no-GIL Python alone solves all compute bottlenecks;
5. that LLM-based explanation implies autonomous scheduling legitimacy.

## 12. Bottom Line

The strongest defensible reading of this thesis is:

SynAPS should evolve into a **zero-touch, polyglot, hardware-aware cyber-physical planning platform** where deterministic scheduling remains the source of operational truth, ML narrows and explains the search, and the underlying compute fabric is shaped around locality, durability, and auditability rather than generic enterprise convenience.
