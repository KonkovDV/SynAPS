---
title: "SynAPS Pitch Memo 2026-04"
status: "active"
version: "2.0.1"
last_updated: "2026-04-05"
date: "2026-04-05"
tags: [synaps, investor, pitch, startup]
mode: "reference"
---

# Pitch Memo: SynAPS

**Date:** April 2026
**Sector:** Industrial Optimization / Advanced Planning & Scheduling

> All terms, acronyms, and confidence labels (C1 / C2 / C3): [GLOSSARY](GLOSSARY_2026_04.md).

## 1. What I'm building

Take a metals plant, a pharma line, an FMCG bottling hall, and an electronics assembly site. Physically, they look nothing alike. Mathematically, their scheduling problems share the same deep structure: flexible job-shop with sequence-dependent setups, auxiliary resources, and multiple objectives. SynAPS translates all of them into that shared representation, then solves them with a hybrid stack.

The deterministic layer makes sure every plan is physically feasible - the math won't produce a schedule that violates real constraints. The AI layer sits above it, searching for better routes and sequences and explaining why they help. It recommends. It doesn't decide.

My core bet is simple: one optimization kernel, sold across verticals by adjusting domain parameters. Not one codebase per industry.

## 2. The problem I'm solving

Most factory APS projects break in one of two predictable ways.

Either the domain model is too narrow - hard-coded for one industry, impossible to transfer without heavy rework. Or the planning engine itself is fragile: a pile of manual rules that collapse on edge cases, or an opaque ML model that produces plans nobody on the floor trusts because they might violate physical constraints.

The fallout is always the same. Setup losses nobody tracks properly. Chaotic replanning every time a machine goes down. Tooling that sits underutilized. Energy bills higher than they need to be. And every new factory site needs practically a new system instead of configuring something that already works.

## 3. Why this moment

Four things lined up at once.

APS buyers already pay serious money for real scheduling. Look at Asprova, DELMIA Ortems, DELMIA Quintiq - they sell finite-capacity planning and rescheduling, not AI buzzwords. This market exists and it validates exactly what I'm building.

The computational foundation is finally mature enough to build on. Google OR-Tools - over 13,300 stars on GitHub, 150 contributors, Apache 2.0, version 9.15 - has become the standard framework for constraint-based scheduling. I don't need to reinvent that wheel.

Industrial AI has to be explainable. NIST's AI Risk Management Framework and their OT security guidance both point the same direction: auditable, transparent systems. I agree with that direction - it's the right one, and it's where my architecture naturally sits.

And on-prem inference now works for real. Open models plus local inference stacks mean I can deploy an AI advisory layer without asking a factory to send its production data off-site.

## 4. How it works

SynAPS formalizes the operational loop as a graph-based scheduling problem. The base canonical form is `MO-FJSP-SDST-ARC`; when raw-material loss accounting matters, it extends to `MO-FJSP-SDST-ML-ARC` (the [GLOSSARY](GLOSSARY_2026_04.md) breaks down every abbreviation).

There are two layers, and their separation is fundamental.

The planning engine handles precedence, capacity limits, resource occupancy, tooling availability, and physical feasibility. Every output schedule passes a constraint check before it goes anywhere. No exceptions. The AI advisor evaluates the space of feasible solutions - it finds better sequences, explains why a given route cuts setup time or reduces tardiness. But it recommends only. Execution is deterministic.

The solver stack has three gears. A fast heuristic (GREED) for initial global allocation. An exact solver (CP-SAT) when I need optimal answers on bottleneck subproblems. And incremental repair for when something breaks mid-shift - fix the affected section of the schedule rather than regenerating everything from scratch. Eventually I want to add an on-prem LLM copilot as an operator interface to ERP/MES data, but that's a roadmap item, not something I can show today.

## 5. What makes this hard to replicate

I've thought carefully about where the technical depth actually lives.

The universal operations abstraction is the first piece. One data model on top of SQL/DDD, configured per domain through attributes, setup matrices, auxiliary resources, and policy packs. It's not "we'll abstract it eventually" - the schema already carries metals, pharma, FMCG, and electronics examples.

The hybrid solver portfolio is the second. Heuristics give me speed. Exact solving (CP-SAT) handles bottleneck machines. And I have an evolution path toward Logic-Based Benders Decomposition for the hardest subproblems, where you need to coordinate multiple scheduling layers simultaneously.

Incremental repair is the third. When a machine goes down, I fix the affected area. Most APS systems regenerate the entire schedule, which risks destabilizing parts of the plan that were already good.

Auxiliary resource awareness is the fourth. I plan around tooling, containers, molds, dies, and maintenance windows - not just machines and raw materials. Most scheduling systems treat these as afterthoughts.

And there's a research runway beyond current capabilities: HGAT for aggregation losses, Digital Twin on DES, Offline RL for safe repair policies, federated learning for holding-level optimization without sharing plant data across sites.

## 6. Where the money comes from

I target factories where scheduling mistakes cost money in obvious, measurable ways. Metals, pharma, FMCG, electronics, energy, assembly, recipe-based, and similar production chains where constraints are tight and margins are real.

The value proposition is concrete, not abstract. Cutting sequence-dependent setup time. Smoothing energy consumption across tariff windows. Reducing downtime from unplanned disruptions. Better utilization of rotating tooling. Fewer hidden losses during transitions - between batches, alloys, recipes, cassettes.

For market sizing, I start from official data and add my own assumptions on top. Full methodology: [MARKET_MODEL](MARKET_MODEL_2026_04.md).

The hard data: 25,799 U.S. manufacturing sites with 100+ employees (Census 2022), and $16.64 trillion in global manufacturing value added (World Bank 2024). That's solid ground.

My assumptions - and I want to be explicit that these are assumptions: $80K ACV, 20% wedge fraction, 1% penetration. Those give a base TAM of roughly $2.06B, SAM near $413M, and an early SOM around $4.2M. Every one of those pricing numbers is designed to be swapped out for real figures once I have pilot data.

## 7. Business model

Platform license plus implementation revenue plus recurring support. The universal kernel is the base product. Vertical constraint packs - configured for specific industries - are what drive expansion.

Pricing is per-site, scaled by production lines, optimization depth, and premium modules. Digital twin, energy scheduling, multi-site learning - those are add-on tiers. But I'm honest: pricing is still a hypothesis. I haven't validated it in the field yet.

For go-to-market, I start with complex multi-stage plants that have expensive setup changes and visible replanning pain. The strategy scales through reusable schema across industries and a pilot-to-rollout motion that converts technical proof into recurring revenue.

## 8. What exists today

I want to be precise here. SynAPS in its current state is a venture thesis backed by a working architectural-mathematical formalization. It's not a deployed APS runtime - I won't pretend otherwise. The strongest asset right now isn't product KPIs. It's a well-formulated kernel with universal economic logic across manufacturing domains, an explicit mathematical formulation, and a clear trajectory from the current heuristic core to an academically validatable hybrid stack.

The universal schema works - DDL plus domain examples. The solver - both heuristic and exact - is currently covered by a 175-test suite in the repository, while the last fully recorded full-suite pass in the active evidence packet remains `149/149` from the earlier April verification snapshot. I've also closed SDST parity for exact solve, repair, and feasibility checking. The benchmark harness supports a verified smoke-instance result on `tiny_3x3`: `CPSAT-10` improves makespan from `106.67` to `82.0` minutes, or about `23.1%` versus `GREED`. Broader benchmark coverage remains open. Research documentation is published.

What's not built: digital twin runtime, industrial connectors, a broad benchmark corpus, pilot KPI data, head-to-head comparison against named APS competitors, and full solver-side auxiliary-resource modeling across all constructive paths. I name these because hiding them would waste everyone's time.

The April 2026 verification pass came back clean on the current documented scope: technical checks passed, the benchmark smoke path is live, and the investor evidence pack is internally consistent.

## 9. Risks - and how I'm handling them

There's a real gap between having a sound architecture and proving field ROI. I deal with that by building the market model, running broader benchmarks, and writing a pilot KPI protocol before making external claims.

Scope inflation is a constant temptation - everybody wants to grow toward a full APS suite. I resist that by framing SynAPS as a kernel and platform foundation, not an end-to-end supply chain system.

The auxiliary-resource model isn't fully solver-native in all execution paths yet. I've called that out, truth-gated it, and prioritized it for staged hardening.

Integration burden could easily overshadow the optimization value at deployment. That's why I treat ERP/MES and shop-floor connectivity as first-class product work rather than something to figure out later.

Dependency freshness lags behind documentation polish - that's a real imbalance, and I've set up separate programs with separate gates for each.

## 10. Confidence map

**C1 - hypotheses:** TAM/SAM/SOM sizing, cross-industry portability claims, unit economics, federated learning effects, long-range research upside. I believe in them, but I can't prove them with today's evidence.

**C2 - internal proof exists:** problem formalization, architecture, universal schema, solver baseline, benchmark harness, research roadmap. An investor can verify each of these directly.

**C3 - external validation (not yet):** KPI uplift, solver superiority against alternatives, benchmark leadership. All need pilot data and third-party comparison. I haven't claimed them because I haven't earned them.

## 11. Compliance

The base product assumes on-prem deployment. Factory ERP/MES data and planning logic often can't leave the enterprise perimeter - I designed for that constraint from the start.

Industry-specific packs will need separate compliance work: GMP and GxP for pharma, traceability for regulated manufacturing, data residency for critical sites. None of that has been done yet, and I won't claim regulatory readiness until I have control mapping, audit trails, and real evidence to back it up.

## 12. Read next

1. [GLOSSARY](GLOSSARY_2026_04.md) - terms and confidence levels
2. [INVESTOR_ONE_PAGER](INVESTOR_ONE_PAGER_2026_04.md) - fastest summary
3. [INVESTOR_DILIGENCE_PACKET](INVESTOR_DILIGENCE_PACKET_2026_04.md) - diligence entry point
4. [CLAIM_EVIDENCE_REGISTER](CLAIM_EVIDENCE_REGISTER_2026_04.md) - claim tracking
5. [MARKET_MODEL](MARKET_MODEL_2026_04.md) - market sizing
6. [MARKET_COMPETITION_REPORT](MARKET_COMPETITION_REPORT_2026_04.md) - competitive analysis

---

### Sources

1. Asprova: [asprova.com](https://www.asprova.com/en/). DELMIA: [3ds.com/delmia](https://www.3ds.com/products/delmia) (vendor-reported, accessed 2026-04-01).
2. Google OR-Tools v9.15: [github.com/google/or-tools](https://github.com/google/or-tools) (accessed 2026-04-01).
3. NIST AI RMF 1.0: [nist.gov/ai-rmf](https://www.nist.gov/itl/ai-risk-management-framework). NIST SP 800-82 Rev. 3: OT security.
4. U.S. Census Bureau, CBP 2022, NAICS 31-33: [census.gov/programs-surveys/cbp.html](https://www.census.gov/programs-surveys/cbp.html).
5. World Bank, NV.IND.MANF.CD: [data.worldbank.org](https://data.worldbank.org/indicator/NV.IND.MANF.CD) (accessed 2026-04-01).
