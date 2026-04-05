---
title: "SynAPS Investor One-Pager 2026-04"
status: "active"
version: "2.0.1"
last_updated: "2026-04-05"
date: "2026-04-05"
tags: [synaps, investor, one-pager, startup]
mode: "reference"
---

# SynAPS - Investor One-Pager

> Confidence labels (C1 / C2 / C3) and all terms: [GLOSSARY](GLOSSARY_2026_04.md).

## In brief

I've spent years watching factories bleed money on scheduling problems that should not exist. Setup time wasted between runs. Bottleneck machines standing idle while operators chase replanning spreadsheets. Downtime that was avoidable but wasn't avoided, because the planning system couldn't adapt fast enough.

SynAPS is my answer. It's a scheduling engine - one engine - that I configure per industry rather than rewriting for each vertical. Metals, pharma, FMCG, electronics: same kernel, different constraint parameters.

I want to be clear. This is not an "AI replaces the planner" story. The core is deterministic. Every schedule it produces is physically feasible - the math guarantees it. AI sits above, as an advisor: it suggests better sequences, explains tradeoffs, but the constraint layer always has the final word.

## Why now

The timing works for four independent reasons.

First, real APS buyers already pay for real scheduling. Asprova, DELMIA Ortems, DELMIA Quintiq - these products sell finite-capacity planning and rescheduling, not AI slogans. The market validates what I'm building.

Second, the computational foundation is mature. Google OR-Tools (over 13,300 GitHub stars, Apache 2.0) has become the industry standard for constraint-based scheduling. I build on that foundation rather than reinventing it.

Third, industrial AI has to be explainable. NIST's AI Risk Management Framework and OT security guidance both push toward transparent, auditable systems. Black boxes don't belong on a factory floor - and I agree with that position.

Fourth, on-prem inference finally works. Open models and local inference stacks mean I can ship an AI advisory layer without making factories send their data to someone else's cloud.

## What I've built (C2 - internally verified)

The universal schema and domain examples are working. The Python solver, both heuristic and exact, passes all 120 current tests. I have a benchmark harness: on the verified smoke instance, `CPSAT-10` improves makespan from `106.67` to `82.0` minutes, or about `23.1%` versus `GREED`. Broader benchmark coverage remains open. There are published research notes, benchmark methodology surfaces, and architecture docs. And the investor pack you're reading tags every claim by evidence level.

## Why this engine

I've designed SynAPS around five properties that are each ordinary alone but rarely appear together.

A universal schema that adapts per domain - I don't hard-code for one vertical. Multiple solvers under one roof: a fast heuristic for speed, CP-SAT for quality, incremental repair for stability. When a machine goes down, I patch the affected section of the schedule instead of throwing out the whole plan. The entire system is built for factory environments - on-prem by default, explainable outputs, data stays within the perimeter. And I'm honest about the boundaries: what works today is the scheduling kernel. Digital twin, multi-site coordination, federated learning - those are roadmap items, and I label them as such.

## What I haven't proven yet

I don't have customer ROI data - that requires a pilot deployment with before-and-after KPIs. My benchmark coverage is still thin: one smoke run instead of a publication-grade family across instance sizes. Regulatory readiness - control mapping, audit trails, formal compliance evidence - hasn't been done. And the dependency stack needs a dedicated freshness program.

I list these gaps openly. Closing each one moves specific claims from C2 to C3.

## Market context

I start the market model from official statistics and layer my assumptions on top. The methodology is in [MARKET_MODEL](MARKET_MODEL_2026_04.md).

There are 25,799 U.S. manufacturing sites with 100+ employees - that's U.S. Census 2022 data, hard numbers. Global manufacturing value added reached $16.64 trillion in 2024 according to the World Bank.

Now here's where my assumptions begin. I'm hypothesizing an $80K ACV - that's not validated pricing. At a 20% wedge and 1% penetration, that gives a base TAM of roughly $2.06B, SAM of about $413M, and an early SOM near $4.2M. These numbers are designed to be replaced by real figures the moment I have pilot pricing data.

## Where I stand

The technical foundation is solid. Internal verification is done. External validation hasn't started. That's an honest starting point - and a stronger one than claiming production-readiness before earning it.

## Read next

1. [INVESTOR_DILIGENCE_PACKET](INVESTOR_DILIGENCE_PACKET_2026_04.md) - diligence entry point
2. [INVESTOR_QA](INVESTOR_QA_2026_04.md) - Q&A for live conversations
3. [INVESTOR_DECK](INVESTOR_DECK_2026_04.md) - slide narrative
4. [GLOSSARY](GLOSSARY_2026_04.md) - terms and acronyms

---

### Sources

1. Asprova: [asprova.com](https://www.asprova.com/en/) (vendor-reported, accessed 2026-04-01). DELMIA Ortems: [delmia.com/scheduling](https://www.3ds.com/products/delmia/delmia-ortems) (accessed 2026-04-01). DELMIA Quintiq: [delmia.com/quintiq](https://www.3ds.com/products/delmia/delmia-quintiq) (accessed 2026-04-01).
2. Google OR-Tools: [github.com/google/or-tools](https://github.com/google/or-tools) - v9.15, 13,300+ stars, 150 contributors, Apache 2.0 (accessed 2026-04-01).
3. NIST AI Risk Management Framework 1.0: [nist.gov/ai-rmf](https://www.nist.gov/artificial-intelligence/ai-risk-management-framework). NIST SP 800-82 Rev. 3: OT security guidance.
4. U.S. Census Bureau, County Business Patterns 2022, NAICS 31-33 (Manufacturing): [census.gov/programs-surveys/cbp.html](https://www.census.gov/programs-surveys/cbp.html).
5. World Bank, Manufacturing value added (current US$), indicator NV.IND.MANF.CD: [data.worldbank.org](https://data.worldbank.org/indicator/NV.IND.MANF.CD).