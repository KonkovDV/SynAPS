---
title: "SynAPS Investor Q&A 2026-04"
status: "active"
version: "2.0.1"
last_updated: "2026-04-05"
date: "2026-04-05"
tags: [synaps, investor, qa, diligence]
mode: "how-to"
---

# SynAPS - Investor Q&A

> Confidence labels (C1 / C2 / C3): [GLOSSARY](GLOSSARY_2026_04.md).

## What's the product?

A scheduling engine for factories. I built one engine that works across metals, pharma, FMCG, electronics - configured per industry, not rebuilt each time. The planning core is deterministic: every schedule it outputs is physically feasible, guaranteed by the math. AI sits on top as an advisor - suggests better sequences, explains tradeoffs, but doesn't make autonomous decisions.

## Is it production-ready?

No. I'm not going to pretend otherwise.

What exists is a C2 product kernel - working code, passing tests, internal benchmarks. Credible enough for serious roadmap discussions, but not validated externally through pilots or independent benchmarks yet. The full confidence scale is in [GLOSSARY](GLOSSARY_2026_04.md).

## What's actually built?

The universal schema and domain examples are working. The Python solver, both heuristic and exact, passes 120 out of 120 current tests. The benchmark harness runs, and the active evidence packet confirms a verified smoke-instance result on `tiny_3x3`: `CPSAT-10` improves makespan from `106.67` to `82.0` minutes, or about `23.1%` versus `GREED`. Broader benchmark coverage remains open. The documentation stack is published too: research notes, benchmark methodology, architecture docs, all tagged by evidence level.

## What's the moat?

It's not "I use AI." Everyone says that.

The real depth comes from four properties that are each common alone but rarely show up together. Cross-industry reuse: one scheduling model across metals, pharma, FMCG, electronics - not locked to one vertical. Multiple solver strategies: fast heuristic, exact solver (CP-SAT), and incremental repair - I don't depend on one algorithm. Local repair: when something breaks, I fix the affected section of the schedule rather than throwing out the entire plan. And factory-native trust: deterministic fallback, advisory-only AI, on-prem deployment. Factories can't afford systems that do unexpected things.

## Why not Asprova, DELMIA Ortems, or Quintiq?

I'm not saying incumbents are useless - they're battle-tested products with real customers. But there's room for a more modular scheduling kernel that reuses better across industries (one core, many domains instead of one system per vertical), offers a cleaner path from deterministic scheduling to AI-assisted planning, and separates what's proven from what's claimed.

They're stronger on deployed product scope. I'm stronger on open technical proof, cross-industry abstraction, and intellectual honesty about the current state. The full comparison: [MARKET_COMPETITION_REPORT](MARKET_COMPETITION_REPORT_2026_04.md).

## Why does GitHub presentation matter?

Because at this stage, the repo is a major part of the proof. Clear docs, reproducible tests, explicit claim boundaries - these reduce diligence friction. If you want to verify something, you can. The code is right there.

## What's the market model based on?

Official statistics for the floor. My assumptions for the ceiling.

Site counts: 25,799 U.S. manufacturers with 100+ employees - U.S. Census 2022, hard data. Global context: $16.64 trillion in manufacturing value added - World Bank 2024, also hard data. Pricing: $80K ACV, 20% wedge, 1% penetration - those are my assumptions, C1, not validated. They produce TAM near $2.06B, SAM near $413M, SOM near $4.2M. All of those pricing numbers are designed to be replaced by real figures from pilot engagements.

Full methodology with Conservative, Base, and Full scenarios: [MARKET_MODEL](MARKET_MODEL_2026_04.md).

I deliberately avoid citing Gartner, Mordor Intelligence, or IDC - their reports are paywalled and unverifiable. The reasoning is reflected in [MARKET_MODEL](MARKET_MODEL_2026_04.md) and [CLAIM_EVIDENCE_REGISTER](CLAIM_EVIDENCE_REGISTER_2026_04.md).

## What's still missing?

Customer ROI - I need before-and-after KPI data from a real pilot. Broad benchmarks - I have a smoke run, not a publication-grade family. Regulatory readiness - control mapping, audit trails, formal compliance evidence. Real pricing data - field win rates and actual deal sizes to replace my C1 numbers.

## What should investors focus on?

Whether the kernel is technically sound - check the solver, schema, and benchmark harness directly. Whether I'm honest about scope - look at what I don't claim in the [CLAIM_EVIDENCE_REGISTER](CLAIM_EVIDENCE_REGISTER_2026_04.md). Whether the team can convert this into pilot evidence - that's the next-phase question. And whether the market wedge is large enough - multi-stage manufacturers with high setup costs and bottleneck economics, where the pain is real and the sites are numerous.