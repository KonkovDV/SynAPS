---
title: "SynAPS Glossary 2026-04"
status: "active"
version: "1.0.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, glossary, investor, terminology]
mode: "reference"
---

# SynAPS Glossary

Language: EN | [RU](GLOSSARY_2026_04_RU.md)

This glossary defines every technical term, acronym, and framework label used across the SynAPS investor pack. Terms are organized alphabetically. When a term first appears in any investor document, it should link here or be defined inline.

---

## Claim Confidence Levels

The investor pack uses a three-level confidence scale to separate what is proven from what is hypothesized.

| Level | Name | Meaning | Example |
|-------|------|---------|---------|
| **C1** | Hypothesis | A strategic or commercial assumption without sufficient external or runtime evidence. Useful for planning, not yet defensible as fact. | Market size projections, cross-industry portability, unit economics |
| **C2** | Internal evidence | Supported by repository artifacts, passing tests, internal benchmarks, or bounded technical proof. Credible for roadmap discussion, not yet externally validated. | Solver baseline works (27/27 tests pass), universal schema exists, benchmark harness runs |
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
| **E7** | Roadmap or strategy hypotheses | Pricing assumptions, wedge estimates, pilot thresholds — labeled C1 only |

---

## Acronyms and Technical Terms

### A

**ACV (Annual Contract Value):** the average annual revenue expected from one customer contract. In the SynAPS market model, ACV is an internal hypothesis (C1), not an externally validated price point.

**Advisory AI:** an AI layer that suggests, ranks, and explains scheduling alternatives but does not autonomously execute decisions. The human operator or the deterministic solver makes all final scheduling commitments. This is deliberately distinct from "autonomous AI" systems.

**APS (Advanced Planning and Scheduling):** a category of manufacturing software that simultaneously plans and schedules production based on available materials, labor, and plant capacity. APS systems replace or augment traditional MRP/ERP scheduling. Major incumbents include Asprova, DELMIA Ortems, DELMIA Quintiq, Siemens Opcenter APS, and Kinaxis.

**ARR (Annual Recurring Revenue):** the annualized value of recurring subscription revenue. Used in the market model to size the addressable market in software-revenue terms.

### B

**Benchmark harness:** the testing infrastructure that runs solver algorithms against standardized scheduling problem instances and measures key performance indicators (makespan, tardiness, setup time, wall time). SynAPS has a working benchmark harness verified at the smoke level (tiny 3×3 instance).

**Bounded repair:** see *Incremental repair*.

### C

**Canonical form:** the formal mathematical representation of the scheduling problem that SynAPS solves. See *MO-FJSP-SDST-ML-ARC*.

**Constraint-grounded scheduling:** scheduling where all plans must satisfy hard physical constraints (machine capacity, precedence, setup sequences) before being considered valid. This is the opposite of pure heuristic or ML-generated plans that may violate physical reality.

**Control plane:** a centralized governance layer that manages configuration, policies, and coordination across multiple production sites or solver instances. In the SynAPS long-horizon roadmap, this enables multi-site scheduling governance.

**CP-SAT:** Google's Constraint Programming with Boolean Satisfiability solver, part of OR-Tools. SynAPS uses CP-SAT as its exact solver engine. "CPSAT-10" means CP-SAT with a 10-second time limit; "CPSAT-60" means a 60-second time limit.

### D

**DES (Discrete Event Simulation):** a simulation approach that models a system as a sequence of discrete events over time. In SynAPS roadmap, DES is planned for digital twin capabilities.

**Deterministic core:** the scheduling engine component that produces physically feasible plans using exact mathematical methods rather than probabilistic or AI-based guessing. This core guarantees that every output plan respects all hard constraints.

**Digital twin:** a virtual replica of a physical production system that can simulate scheduling scenarios. This is a roadmap item for SynAPS, not a current capability.

### E

**EU AI Act (Regulation (EU) 2024/1689):** the European Union regulation on artificial intelligence, establishing rules for AI systems based on risk classification. SynAPS maintains awareness of this framework for future compliance readiness.

### F

**Feasibility gate (truth gate):** a hard check that rejects any proposed schedule that violates physical constraints. A schedule either passes the feasibility gate or it does not — there is no "partially feasible" state.

**Federated learning:** a machine learning approach where multiple production sites train models collaboratively without sharing raw data. In SynAPS, this is a long-horizon research option (15–25 year timeframe), not a current capability.

**FJSP (Flexible Job-Shop Scheduling Problem):** a scheduling problem where each operation can be processed on one of several eligible machines. This is the academic problem class that production scheduling belongs to.

### G

**GPAI (General-Purpose AI):** a regulatory classification under the EU AI Act for AI models that can be used across many different applications. SynAPS's advisory AI layer may fall under GPAI provisions depending on deployment scope.

**GREED (Greedy Dispatch):** the fast heuristic solver in SynAPS that produces a valid schedule quickly by making locally optimal choices at each step. Used as a baseline for comparison against exact solvers.

### H

**HGAT (Heterogeneous Graph Attention Network):** a type of graph neural network used to learn from scheduling problem structures. In SynAPS, HGAT is a research-stage technique for reducing aggregation losses in large-scale problems.

### I

**Incremental repair (bounded repair):** fixing only the affected portion of a schedule when a local disruption occurs (e.g., machine breakdown), rather than regenerating the entire schedule from scratch. This preserves stability for the unaffected parts of the production plan.

### K

**Kernel thesis (product-kernel thesis, scheduling kernel):** the central product hypothesis of SynAPS — that a single, reusable scheduling core can be parameterized across multiple industrial domains (metals, pharma, FMCG, electronics, etc.) rather than building a separate scheduling system for each industry. "Kernel" here means "core engine," not an operating system kernel.

### L

**LBBD (Logic-Based Benders Decomposition):** a mathematical optimization technique that breaks large scheduling problems into smaller subproblems that can be solved more efficiently. In SynAPS, LBBD is planned for bottleneck machine optimization but is not yet live.

### M

**Makespan:** the total time from start to finish of a production schedule. Lower makespan means faster completion. This is one of the primary optimization objectives.

**MO-FJSP-SDST-ML-ARC:** the full notation for the SynAPS canonical scheduling problem: Multi-Objective Flexible Job-Shop Scheduling Problem with Sequence-Dependent Setup Times, Material Loss handling, and Auxiliary Resources and Constraints. Each component:
- **MO** = multi-objective (optimizing several goals simultaneously: makespan, tardiness, setup cost)
- **FJSP** = flexible job-shop (operations can go to multiple eligible machines)
- **SDST** = sequence-dependent setup times (changing from product A to product B takes different time than B to A)
- **ML** = material loss (accounting for raw material waste during processing)
- **ARC** = auxiliary resources and constraints (tooling, molds, containers, energy windows)

### N

**NIST AI RMF (AI Risk Management Framework):** a voluntary U.S. framework published by the National Institute of Standards and Technology for managing risks in AI systems. SynAPS aligns with its principles for trustworthy, explainable, and bounded AI.

**NIST SP 800-82 Rev. 3:** a U.S. publication on security guidance for operational technology (OT) environments — the factory-floor control systems that SynAPS would interact with in deployment.

### O

**OT (Operational Technology):** the hardware and software systems that monitor and control physical industrial processes — PLCs, SCADA systems, MES, factory-floor equipment. Distinct from IT (information technology). OT environments have strict security and availability requirements.

**OR-Tools:** Google's open-source software suite for combinatorial optimization, including the CP-SAT solver used by SynAPS. Latest version: v9.15 (January 2026). 13,300+ GitHub stars. Apache 2.0 license.

### P

**Penetration rate:** the fraction of addressable market sites expected to become customers. In the SynAPS market model, this is an internal assumption (C1), not an externally validated conversion rate.

**Pilot KPI evidence:** measurements from actual customer deployments (before/after comparison of scheduling performance). SynAPS does not yet have pilot KPI evidence — this is an explicitly acknowledged open gap.

**Product-kernel thesis:** see *Kernel thesis*.

**Publication-grade (benchmark):** a benchmark evidence packet that would be credible in a peer-reviewed academic publication or an industry white paper. Requirements include: multiple instance families (not just smoke), repeated runs with statistics, hardware disclosure, solver configuration disclosure, and reproducible commands.

### Q

**QUBO (Quadratic Unconstrained Binary Optimization):** a mathematical optimization formulation compatible with quantum computing hardware. In SynAPS, QUBO compatibility is a distant research option (25–45 year horizon) contingent on quantum hardware economics.

### R

**Red-team (adversarial review):** a practice borrowed from military and cybersecurity where a team deliberately tries to find weaknesses in a system or argument. The SynAPS Investor Red Team Appendix applies this to the investment case: what are the hardest objections, and how do they stand up to scrutiny?

### S

**SAM (Serviceable Addressable Market):** the subset of TAM that SynAPS can realistically target given its current product scope and go-to-market strategy. Calculated as: eligible sites × wedge fraction × ACV.

**SBOM (Software Bill of Materials):** a complete inventory of all software components, libraries, and dependencies in a product. Increasingly required for enterprise software supply-chain security and regulatory compliance.

**SDST (Sequence-Dependent Setup Times):** the property where the time needed to set up a machine between products depends on the specific sequence. Changing from steel alloy A to alloy B may take 45 minutes, while changing from B to A takes 90 minutes. This is a key cost driver in multi-product manufacturing.

**Smoke instance (smoke test):** a minimal test that verifies a system works end-to-end on a simple case. The SynAPS smoke benchmark uses a tiny 3×3 instance (3 jobs, 3 machines). Smoke testing proves the harness works but does not prove broad performance.

**SOM (Serviceable Obtainable Market):** the portion of SAM that SynAPS realistically expects to capture in early commercial phases. Calculated as: SAM sites × penetration rate × ACV.

**Solver portfolio:** the combination of multiple solving strategies (fast heuristic, exact solver, incremental repair) that SynAPS uses. Different strategies are appropriate for different problem sizes and time constraints.

### T

**TAM (Total Addressable Market):** the total revenue opportunity if every eligible manufacturer purchased the product. In SynAPS: calculated from official U.S. Census establishment counts × assumed ACV. The denominator (site count) is E2 evidence; the ACV is a C1 assumption.

**Tardiness:** how much a production schedule exceeds its due dates. Zero tardiness means all orders finish on time. This is the second major optimization objective after makespan.

**Truth gate:** see *Feasibility gate*.

### U

**Universal schema:** SynAPS's data model designed to represent scheduling problems from any manufacturing domain (metals, pharma, FMCG, electronics) through parameterization rather than industry-specific hard-coding.

### W

**Wedge fraction:** the percentage of total addressable manufacturers that match SynAPS's initial target profile (multi-stage production, significant setup costs, bottleneck economics). In the market model, this is an internal assumption (C1).

---

## How to Use This Glossary

When reading any SynAPS investor document:

1. If a term appears in **bold** or is followed by "(see Glossary)," look it up here.
2. The confidence labels **C1**, **C2**, **C3** appear throughout — they always mean Hypothesis, Internal Evidence, and External Validation respectively.
3. The evidence tiers **E1–E7** are ordered from strongest (official standards) to weakest (internal hypotheses).
4. Market numbers always carry a source tag: official sources are E2, pricing assumptions are C1/E7.
