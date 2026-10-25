# Architecture Overview

<details>
<summary>🇷🇺 Обзор архитектуры</summary>

SynAPS строится как модульный монолит с чёткими границами контекстов. Сервисная декомпозиция допустима только после подтверждённых bottleneck'ов. Все решения по планированию аудитируемы. AI-рекомендации — advisory, не authoritative.

</details>

## Design Principles

| ID | Principle | Rationale |
|----|-----------|-----------|
| P1 | **Model-first** | Canonical mathematical form precedes any code. The current kernel is MO-FJSP-SDST-ARC; the extended MO-FJSP-SDST-ML-ARC label is reserved for future advisory layers. |
| P2 | **Deterministic baseline** | Every AI/ML recommendation has a deterministic fallback. If ML advisory is unavailable, the system produces a valid schedule using rule-based solvers alone. |
| P3 | **Evolutionary architecture** | Start as a modular monolith. Extract services only when production evidence (load, change cadence, team boundaries) justifies the operational cost. |
| P4 | **Event-ready** | The standalone repo models state so that replay and eventing can be layered on later, but it does not currently ship an event bus or workflow runtime. |
| P5 | **Explainability** | The current runtime exposes routing reasons, replay artifacts, and repair diffs; richer operator-facing XAI remains a target layer. |
| P6 | **Industrial safety** | Degraded modes are explicit and operator-visible. A silent fallback that hides instability is a defect, not a feature. |

## System Context (C4 Level 1)

```mermaid
graph TB
    ERP["ERP System<br/>(orders, products, due dates)"]
    MES["MES<br/>(routing, technological cards)"]
    IOT["IoT / SCADA / OPC-UA<br/>(machine states, telemetry)"]
    USERS["Operators & Managers"]
    APS["SynAPS Platform"]
    ANALYTICS["BI & Analytics"]
    ALERTS["Alert Channels<br/>(dashboards, notifications)"]

    ERP -->|batch import + reconciliation| APS
    MES -->|routing sync + change feed| APS
    IOT -->|async subscriptions| APS
    USERS -->|interact| APS
    APS -->|projections, exports| ANALYTICS
    APS -->|notifications| ALERTS

    style APS fill:#e3f2fd,stroke:#1565c0,stroke-width:2px
```

## Container Diagram (C4 Level 2)

```mermaid
graph TB
    subgraph SynAPS["SynAPS"]
        UI["[Target] Operator UI<br/>React + TypeScript"]
        BFF["Contract BFF<br/>TypeScript + Fastify"]
        CORE["Planning Core<br/>Python kernel + orchestration"]
        OPT["Solver Portfolio<br/>GREED · CP-SAT · LBBD · LBBD-HD"]
        RT["[Target] Realtime Engine<br/>Eventing + workflows"]
        INT["Integration Layer<br/>CLI, schemas, adapters"]
        ML["[Target] ML Advisory<br/>Ranking / hints only"]
        REP["Feasibility + Replay<br/>truth gate + artifacts"]
    end

    subgraph Data["Data Platform"]
        SCHEMA["Checked-in JSON Schemas<br/>and runtime contracts"]
        PG["[Target] PostgreSQL 17+<br/>Canonical OLTP"]
        BUS["[Target] Event backbone<br/>JetStream / workflows"]
        AUX["[Target] Cache / object / analytics"]
    end

    UI -.-> BFF
    BFF --> CORE
    CORE --> OPT
    OPT --> REP
    CORE -.-> RT
    ML -.->|advisory| OPT
    INT --> CORE
    BFF --> SCHEMA
    CORE -.-> PG
    RT -.-> BUS
    ML -.-> AUX

    style SynAPS fill:#e3f2fd,stroke:#1565c0
    style Data fill:#e8f5e9,stroke:#2e7d32
```

## Component View (Planning Core)

```mermaid
graph LR
    API["Solve / Repair API"] --> IMPORT["Import & Normalize"]
    IMPORT --> PROFILE["Problem Profile"]
    PROFILE --> ROUTER["Deterministic Router"]
    ROUTER --> SOLVE["Solver Portfolio<br/>(GREED / CP-SAT / LBBD)"]
    SOLVE --> FEAS["Feasibility Checker"]
    FEAS --> REPLAY["Replay Artifact + Metadata"]
    ROUTER --> REPAIR["Repair Engine<br/>(bounded patching)"]
    REPAIR --> FEAS

    style SOLVE fill:#fff9c4,stroke:#f57f17
    style REPAIR fill:#fff9c4,stroke:#f57f17
```

## Architecture Decision Records

| ADR | Decision |
|-----|----------|
| ADR-001 | PostgreSQL is canonical source of truth |
| ADR-002 | Modular monolith first, selective extraction later |
| ADR-003 | Deterministic scheduler is mandatory baseline |
| ADR-004 | Target: JetStream/eventing and workflow orchestration stay outside the standalone runtime boundary |
| ADR-005 | ClickHouse is analytics plane, not operational truth |
| ADR-006 | AI is advisory, never sole feasibility authority |
| ADR-007 | Commercial UI components allowed only behind replaceable boundary |
| ADR-008 | Every publication/override action is auditable |
| ADR-009 | Integration adapters isolate external system quirks |
| ADR-010 | Degraded modes must be explicit and operator-visible |
| ADR-011 | Solver portfolio routes by problem regime |
| ADR-012 | Target: ONNX CPU-first inference; Python remains the experimentation surface |
| ADR-013 | Signed artifacts and SBOM are part of production readiness |
| ADR-014 | Target: Digital Twin via SimPy DES, not proprietary simulation |
| ADR-015 | Target: LLM Copilot on-prem only; no data leaves the perimeter |
| ADR-016 | Target: Federated Learning with differential privacy |
| ADR-017 | Target: Quantum readiness via QUBO formulation, classical fallback mandatory |
| ADR-018 | Language follows boundary and hot path: TypeScript at the edge, Python for optimizer and ML orchestration, Rust for native kernels |

## Rollout Model

```
Phase 0   →   Phase 1   →   Phase 2   →   Phase 3-4   →   Phase 5+
Discovery     Pilot Core    Repair +      Analytics +     Selective
& Contract    (1 line,      Realtime      ML Advisory     Extraction
Freeze        1 shift)      Loop                          & Evolution
```

**Key rule:** No service extraction before production evidence of bottlenecks. No ML promotion without replay-validated improvement over deterministic baseline.

## Language Boundary

SynAPS is intentionally polyglot at production scale:

1. **TypeScript** owns operator UI and control-plane edges.
2. **Python** owns exact solver orchestration, ML advisory, and simulation-heavy work.
3. **Rust** owns measured hot paths such as heuristic kernels, feasibility checks, and future metaheuristic workers.
4. **Rules and policy** should stay declarative where possible instead of being buried in solver code.
5. The current verified boundary to external runtimes is the JSON request/response contract under `schema/contracts/` plus the bounded CLI/package entrypoints.
6. The current public network proof is the minimal TypeScript BFF in `control-plane/`, which validates the runtime contract and invokes the Python kernel over the contract CLI.

See [Language & Runtime Strategy](06_LANGUAGE_AND_RUNTIME_STRATEGY.md) for the full contract.


### Solver Portfolio — Implementation Summary

The solver portfolio is the core engineering asset. The current shipped runtime is Python 3.12+ plus a minimal TypeScript BFF for HTTP contract validation, and an optional Rust (PyO3) accelerator.

Line counts are a 2026-10 snapshot (`wc -l`, audit `docs/rfc/AUDIT_2026_10.md`); regenerate them instead of editing by hand. The authoritative per-component table lives in [Solver Portfolio §2.1](03_SOLVER_PORTFOLIO.md#21-implementation-evidence--code-line-counts).

| Component | Source | LOC | Primary Algorithm |
|-----------|--------|-----|-------------------|
| CP-SAT Exact Solver | `synaps/solvers/cpsat_solver.py` | 1 623 | OR-Tools CP-SAT: optional intervals + `AddCircuit` (SDST) + NoOverlap/Cumulative (ARC), hierarchical big-M objective |
| LBBD Decomposition | `synaps/solvers/lbbd_solver.py` | 1 431 | HiGHS MIP master (assignment + capacity relaxation) + CP-SAT subproblems + no-goods emitted only after optimal-status subproblems |
| LBBD-HD (Parallel) | `synaps/solvers/lbbd_hd_solver.py` | 1 655 | + ProcessPool subproblems + ARC-aware partitioning + topological post-assembly |
| Greedy ATCS / Beam | `synaps/solvers/greedy_dispatch.py` | 1 243 | Log-space ATCS index (Lee, Bhaskaran & Pinedo 1997); serial schedule generation, $O(N^2 \cdot \bar{E})$ worst case |
| ALNS | `synaps/solvers/alns_solver.py` + `_alns_config.py` | 4 915 | 7 destroy operators, greedy / micro-CP-SAT repair, SA acceptance, roulette or UCB1 operator selection |
| RHC | `synaps/solvers/rhc/` (12 modules) | 7 834 | Rolling-horizon windows over an inner solver; coverage-complete list-schedule path |
| Pareto Slice | `synaps/solvers/pareto_slice_solver.py` | 294 | Two-stage $\varepsilon$-constraint |
| Incremental Repair | `synaps/solvers/incremental_repair.py` | 508 | Neighbourhood radius + greedy fallback + micro-CP-SAT |
| Portfolio Router | `synaps/solvers/router.py` | 499 | Deterministic regime×size→config decision tree (6 regimes) |
| Graph Partitioning | `synaps/solvers/partitioning.py` | 268 | Coarsening (BFS) + FFD bin packing + refinement |
| Solver Registry | `synaps/solvers/registry.py` | 456 | 25 named configs |
| FeasibilityChecker | `synaps/solvers/feasibility_checker.py` | 1 379 | Independent notary: 10 constraint classes, exact lane inference, sweep-line capacity |
| Data Model | `synaps/model.py` | 622 | Pydantic v2 entities, DAG + SDST + mode validation |
| Control-Plane BFF | `control-plane/src/*.ts` | 3 964 | Fastify + AJV + Python bridge (TypeScript) |
| Native accelerator | `native/synaps_native/src/*.rs` | 2 781 | PyO3 + rayon kernels (ATCS scoring, list schedule, repair) |

The **Portfolio Router** automatically selects the solver based on: operational regime (NOMINAL, RUSH_ORDER, BREAKDOWN, MATERIAL_SHORTAGE, INTERACTIVE, WHAT_IF), time budget, and instance size. No ML — deterministic routing.

Since the 2026-10 audit the two largest solvers are explicit pipelines: `RhcSolver.solve` delegates to a single-use run engine (`_RhcRun`, typed `RhcRunConfig`) and `AlnsSolver` to `_AlnsRun` (typed `AlnsRunConfig`); no function in either exceeds 80 lines.


## Technology Stack

Only the Python kernel, checked-in contracts, replay and benchmark surfaces, and the minimal TypeScript BFF ship in the current standalone repository. The broader platform matrix below describes the intended integrated deployment stack rather than the present standalone runtime.

| Layer | Primary | Reserve / Alternative |
|-------|---------|----------------------|
| **Frontend** | React 19 + TypeScript + Vite | — |
| **State management** | TanStack Query + Zustand | — |
| **API / BFF** | TypeScript on Node.js or Bun | FastAPI or Axum for optimizer-adjacent service boundaries |
| **Solver kernel** | OR-Tools CP-SAT | HiGHS (LP/MIP), pymoo (NSGA-III) |
| **Heuristic core** | Custom GREED/ATCS (Rust or Python) | — |
| **Hyperparameter** | Optuna | — |
| **ML framework** | PyTorch + PyG (training) | — |
| **ML inference** | ONNX Runtime (CPU-first) | PyTorch (experimental) |
| **ML tracking** | MLflow + MinIO | — |
| **OLTP** | PostgreSQL 17 | — |
| **Telemetry store** | TimescaleDB | — |
| **OLAP** | ClickHouse | — |
| **Cache / locks** | Valkey | — |
| **Object store** | MinIO | — |
| **Event streaming** | NATS JetStream (target integrated stack) | — |
| **Workflow engine** | Temporal | — |
| **IAM** | Keycloak + OPA | — |
| **Workload identity** | SPIFFE / SPIRE | — |
| **Platform** | RKE2 / K3s | — |
| **Network** | Cilium + Hubble | — |
| **GitOps** | Argo CD | — |
| **Observability** | Prometheus + Grafana + Loki + Tempo | — |
| **Supply chain** | Syft + Grype + cosign | Trivy |
| **DES** | SimPy 4.x | Salabim |
| **LLM inference** | vLLM / Ollama | llama.cpp (CPU) |
| **RL** | Stable-Baselines3 | d3rlpy (offline RL) |

## Next

- [Canonical Form](02_CANONICAL_FORM.md) — mathematical formalization
- [Solver Portfolio](03_SOLVER_PORTFOLIO.md) — solver selection and routing
- [Data Model](04_DATA_MODEL.md) — universal schema and events
- [Deployment](05_DEPLOYMENT.md) — infrastructure and operations
- [Language & Runtime Strategy](06_LANGUAGE_AND_RUNTIME_STRATEGY.md) — polyglot boundaries and migration rules
- [Runtime Contract](07_RUNTIME_CONTRACT.md) — current TypeScript ↔ Python invocation boundary
