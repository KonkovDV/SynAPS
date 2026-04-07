---
title: "SynAPS Glossary 2026-04"
status: "active"
version: "1.0.2"
last_updated: "2026-04-07"
date: "2026-04-07"
tags: [synaps, glossary, partner, terminology]
mode: "reference"
---

# SynAPS Glossary

Language: EN | [RU](GLOSSARY_2026_04_RU.md)

This glossary defines every technical term, acronym, and framework label used across the SynAPS partner pack. Terms are organized alphabetically. When a term first appears in any partner document, it should link here or be defined inline.

Terms explicitly marked `[ROADMAP]` describe target or research surfaces rather than shipped runtime capability in the current public repository.

---

## Claim Confidence Levels

The partner pack uses a three-level confidence scale to separate what is proven from what is hypothesized.

| Level | Name | Meaning | Example |
|-------|------|---------|---------|
| **C1** | Hypothesis | A strategic or commercial assumption without sufficient external or runtime evidence. Useful for planning, not yet defensible as fact. | Market size projections, cross-industry portability, unit economics |
| **C2** | Internal evidence | Supported by repository artifacts, passing tests, internal benchmarks, or bounded technical proof. Credible for roadmap discussion, not yet externally validated. | Solver portfolio runs, universal schema exists, benchmark harness and runtime contracts validate in-repo |
| **C3** | External validation | Supported by pilot data, third-party benchmarks, audited controls, or official external sources. Defensible as a public claim. | KPI uplift from a pilot deployment, independent benchmark comparison, regulatory certification |

**Key rule:** an official data source (e.g., World Bank statistics) combined with internal assumptions (e.g., pricing per site) produces a C2 hybrid, not pure C3.

---

## Evidence Hierarchy

The pack uses a seven-tier evidence hierarchy. Higher tiers constrain lower-tier claims, not the reverse.

| Tier | Evidence class | Examples in the pack |
|------|---------------|---------------------|
| **E1** | Official standards and public frameworks | NIST AI RMF 1.0, NIST SP 800-82 Rev. 3, EU AI Act |
| **E2** | Official statistics | World Bank manufacturing value-added data, U.S. Census establishment counts |
| **E3** | Official technical documentation | Google OR-Tools scheduling guidance |
| **E4** | Public vendor positioning | Asprova, DELMIA Ortems, DELMIA Quintiq product pages |
| **E5** | Public open-source comparables | Supabase, PostHog, Airbyte GitHub presentation patterns |
| **E6** | Internal repository verification | Passing tests, benchmark runs, architecture checks, docs closure |
| **E7** | Roadmap or strategy hypotheses | Pricing assumptions, wedge estimates, pilot thresholds - labeled C1 only |

---

## Acronyms and Technical Terms

### A

**ACV (Annual Contract Value):** the average annual revenue expected from one customer contract. In the SynAPS market model, ACV is an internal hypothesis (C1), not an externally validated price point.

**Advisory AI:** an AI layer that suggests, ranks, and explains scheduling alternatives but does not autonomously execute decisions. The human operator or the deterministic solver makes all final scheduling commitments. This is deliberately distinct from "autonomous AI" systems.

**APS (Advanced Planning and Scheduling):** a category of manufacturing software that simultaneously plans and schedules production based on available materials, labor, and plant capacity. APS systems replace or augment traditional MRP/ERP scheduling. Major incumbents include Asprova, DELMIA Ortems, DELMIA Quintiq, Siemens Opcenter APS, and Kinaxis.

**ARR (Annual Recurring Revenue):** the annualized value of recurring subscription revenue. Used in the market model to size the addressable market in software-revenue terms.

### B

**Benchmark harness:** the in-repo infrastructure that runs solver configurations against standardized scheduling problem instances and records key performance indicators such as makespan, tardiness, setup time, and wall time. SynAPS ships a working harness with smoke and medium-scale verification surfaces.

**Bounded repair:** see *Incremental repair*.

### C

**Canonical form:** the formal mathematical representation of the scheduling problem that SynAPS solves. See *MO-FJSP-SDST-ML-ARC*.

**Constraint-grounded scheduling:** scheduling where all plans must satisfy hard physical constraints (machine capacity, precedence, setup sequences) before being considered valid. This is the opposite of pure heuristic or ML-generated plans that may violate physical reality.

**Control plane:** in the current SynAPS repository, the minimal TypeScript BFF layer that validates checked-in runtime contracts and invokes the Python kernel. Broader multi-site governance and coordination remain roadmap surfaces.

**CP-SAT:** Google's Constraint Programming with Boolean Satisfiability solver, part of OR-Tools. SynAPS uses CP-SAT as its exact solver engine. Current shipped time-boxed profiles include `CPSAT-10`, `CPSAT-30`, and `CPSAT-120`; epsilon-constraint variants ship as `CPSAT-EPS-SETUP-110`, `CPSAT-EPS-TARD-110`, and `CPSAT-EPS-MATERIAL-110`.

### D

**[ROADMAP] DES (Discrete Event Simulation):** a simulation approach that models a system as a sequence of discrete events over time. In SynAPS roadmap, DES is planned for digital twin capabilities.

**Deterministic core:** the scheduling engine component that produces physically feasible plans using exact mathematical methods rather than probabilistic or AI-based guessing. This core guarantees that every output plan respects all hard constraints.

**[ROADMAP] Digital twin:** a virtual replica of a physical production system that can simulate scheduling scenarios. This is a roadmap item for SynAPS, not a current capability.

### E

**EU AI Act (Regulation (EU) 2024/1689):** the European Union regulation on artificial intelligence, establishing rules for AI systems based on risk classification. SynAPS maintains awareness of this framework for future compliance readiness.

### F

**Feasibility gate (truth gate):** a hard check that rejects any proposed schedule that violates physical constraints. A schedule either passes the feasibility gate or it does not - there is no "partially feasible" state.

**FeasibilityChecker:** the independent post-solve validator that checks completeness, eligibility, precedence, machine capacity, setup gaps, auxiliary-resource usage, and horizon bounds before a schedule is treated as valid.

**[ROADMAP] Federated learning:** a machine learning approach where multiple production sites train models collaboratively without sharing raw data. In SynAPS, this is a long-horizon research option (15-25 year timeframe), not a current capability.

**FJSP (Flexible Job-Shop Scheduling Problem):** a scheduling problem where each operation can be processed on one of several eligible machines. This is the academic problem class that production scheduling belongs to.

### G

**GPAI (General-Purpose AI):** a regulatory classification under the EU AI Act for AI models that can be used across many different applications. SynAPS's advisory AI layer may fall under GPAI provisions depending on deployment scope.

**GREED (Greedy Dispatch):** the fast heuristic solver in SynAPS that produces a valid schedule quickly by making locally optimal choices at each step. Used as a baseline for comparison against exact solvers.

### H

**[ROADMAP] HGAT (Heterogeneous Graph Attention Network):** a type of graph neural network used to learn from scheduling problem structures. In SynAPS, HGAT is a research-stage technique for reducing aggregation losses in large-scale problems.

### I

**Incremental repair (bounded repair):** fixing only the affected portion of a schedule when a local disruption occurs (e.g., machine breakdown), rather than regenerating the entire schedule from scratch. This preserves stability for the unaffected parts of the production plan.

### K

**Kernel thesis (product-kernel thesis, scheduling kernel):** the central product hypothesis of SynAPS - that a single, reusable scheduling core can be parameterized across multiple industrial domains (metals, pharma, FMCG, electronics, etc.) rather than building a separate scheduling system for each industry. "Kernel" here means "core engine," not an operating system kernel.

**K-parameters (ATCS):** the tuning parameters in the Apparent Tardiness Cost with Setups heuristic. In the current SynAPS implementation, $K_1$ controls tardiness look-ahead, $K_2$ scales setup influence, and $K_3$ scales material-loss influence.

### L

**LBBD (Logic-Based Benders Decomposition):** a two-level optimization method where a relaxed master problem assigns work and CP-SAT subproblems sequence exact bottlenecks. Current shipped profiles are `LBBD-5` and `LBBD-10`.

**LBBD-HD:** the hierarchical LBBD variant for large industrial instances. It adds balanced partitioning, greedy warm-start, parallel subproblem execution via `ProcessPoolExecutor`, and topological post-assembly. Current shipped profiles are `LBBD-5-HD`, `LBBD-10-HD`, and `LBBD-20-HD`.

### O

**Operational regime:** one of the router contexts that changes solver selection and latency expectations. Current shipped regimes are `NOMINAL`, `RUSH_ORDER`, `BREAKDOWN`, `MATERIAL_SHORTAGE`, `INTERACTIVE`, and `WHAT_IF`.

### P

**Pareto Slice:** a two-stage epsilon-constraint variant of CP-SAT used for multi-objective trade-off exploration. Current shipped profiles are `CPSAT-EPS-SETUP-110`, `CPSAT-EPS-TARD-110`, and `CPSAT-EPS-MATERIAL-110`.

**Portfolio Router:** the deterministic solver-selection engine that maps regime, latency budget, and instance size to a named solver profile. It is explainable and does not rely on ML or randomness in the current repository.