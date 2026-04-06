---
title: "SynAPS Investor Deck 2026-04"
status: "active"
version: "2.0.2"
last_updated: "2026-04-06"
date: "2026-04-06"
tags: [synaps, investor, deck, presentation]
mode: "tutorial"
---

# SynAPS - Investor Deck

> Confidence labels (C1 / C2 / C3): [GLOSSARY](GLOSSARY_2026_04.md).

## Slide 1 - Title

**SynAPS** - one scheduling engine for any factory.

## Slide 2 - Problem

I keep seeing factory planning break the same way, everywhere.

The data model is too narrow. Hard-coded for one industry, impossible to move to a different plant without heavy rework. Or the planning engine is fragile - a rule-based system that collapses on edge cases, or an opaque AI that creates schedules nobody trusts.

The result is always familiar: hidden setup losses, emergency replanning, tooling sitting underutilized, energy costs higher than necessary. And every new site needs almost a new system.

## Slide 3 - Why now

Four things happened at once. APS buyers already pay for real scheduling - Asprova, DELMIA Ortems, DELMIA Quintiq sell constraint-based planning, not AI marketing. The computational tools are mature - Google OR-Tools (v9.15, 13,300+ stars) is the industry backbone, and I build on it. Industrial AI has to be explainable - NIST guidance confirms what I've always believed. And on-prem inference finally works - I can deploy an AI advisor without moving factory data off-site.

## Slide 4 - What SynAPS actually is

I'm not pitching an "AI factory brain."

SynAPS is a scheduling kernel with four properties. Physics-first planning - every output schedule is guaranteed feasible, because the math checks constraints before anything ships. Local repair - when a machine breaks, I patch the affected section rather than regenerating the whole plan. A universal schema - one data model adapted per industry through configuration, not hard-coding. And AI as advisor - it ranks and explains alternatives, but the operator keeps control.

## Slide 5 - What's hard to replicate

The universal schema adapts across metals, pharma, FMCG, electronics - I configure per domain, I don't rebuild. I run multiple solvers: a fast heuristic, CP-SAT for exact answers, and incremental repair for stability. When something breaks, I fix the part that's broken. I plan around auxiliary resources - tooling, molds, containers, energy windows - not just machines and materials. And the roadmap builds upward from this deterministic core: digital twin, multi-site coordination, advanced AI layers - all grounded in the kernel that already works.

## Slide 6 - What exists today (C2)

The universal schema and domain examples are working. The Python solver is currently covered by a 175-test suite in the repository; the last fully recorded full-suite pass in the active evidence packet remains `149/149` from the earlier April verification snapshot. The benchmark harness shows a verified smoke-instance result on `tiny_3x3`: `CPSAT-10` improves makespan from `106.67` to `82.0` minutes, or about `23.1%` versus `GREED`. Broader benchmark coverage remains open. Research notes, benchmark methodology, and architecture docs are published. This investor pack tags every claim by evidence level. And the GitHub trust layer is live: security policy, support, citation, contribution guide.

## Slide 7 - Market model

I start from official data, then add my assumptions. Full methodology: [MARKET_MODEL](MARKET_MODEL_2026_04.md).

Hard data: $16.64T global manufacturing value added (World Bank 2024). $2.79T for the EU alone (World Bank 2024). 25,799 U.S. manufacturers with 100+ employees (Census 2022).

My assumptions - and I separate them clearly: $80K ACV, 20% wedge, 1% penetration. That gives TAM roughly $2.06B, SAM near $413M, early SOM about $4.2M. These are placeholders. They exist so I can do arithmetic. They'll be replaced by real numbers the moment pilot data comes in. Conservative, Base, and Full scenarios: [MARKET_MODEL](MARKET_MODEL_2026_04.md), section 5.

## Slide 8 - Competitive position

Here's what I can say honestly today.

I'm building a scheduling kernel, not a full APS suite. I solve the scheduling core; I don't yet match the integration scope of Quintiq or Asprova. But what I do matches what buyers actually pay for - feasibility guarantees and rescheduling, not AI flash. And my AI is advisory - which is exactly where NIST guidance and industrial practice are heading.

Detailed analysis: [MARKET_COMPETITION_REPORT](MARKET_COMPETITION_REPORT_2026_04.md).

## Slide 9 - Go-to-market

I'm targeting multi-stage manufacturing sites with expensive setup changes, visible replanning pain, and on-prem environments first. Think metals, pharma, FMCG plants with five or more production lines and high changeover costs.

The packaging: kernel platform plus per-industry constraint packs plus optional integration services.

## Slide 10 - What's proven, what's open

Done (C2): the product thesis is clear, the GitHub trust layer ships, the kernel works and tests pass, and I have a source-backed market model. Still open: pilot KPI evidence, broad publishable benchmarks, regulatory control mapping, and a dependency freshness program.

## Slide 11 - Why invest now

I'm not claiming SynAPS is a finished product. The investment case is different.

The scheduling kernel is technically coherent - it works, it tests clean, the math is sound. The documentation is unusually thorough for this stage - an investor can verify claims directly rather than taking my word. I'm honest about what's missing, and every gap has a closing protocol. The remaining work is external validation, not figuring out what to build.

## Slide 12 - What the next round buys

The next round should produce evidence, not vanity metrics. Pilot KPIs - before-and-after data from real factory deployments. Benchmark breadth - a full family across instance sizes, with statistical reporting. Real pricing signals - to replace my $80K ACV assumption. And field integration proof - ERP/MES connectivity in production environments.

## Speaker notes

- High-level audiences: stop around slides 7-10.
- Technical audiences: route into [INVESTOR_DILIGENCE_PACKET](INVESTOR_DILIGENCE_PACKET_2026_04.md) and the [technical verification report](TECHNICAL_VERIFICATION_REPORT_2026_04.md).
- If market size gets challenged: open [MARKET_MODEL](MARKET_MODEL_2026_04.md) and walk through the hard-data vs. assumption split.
- For a Russian strategic-investor conversation with Mositlab-level diligence, route into [SYNAPS_MOSITLAB_INVESTOR_PITCH_2026_04.md](SYNAPS_MOSITLAB_INVESTOR_PITCH_2026_04.md).
- All terms and confidence labels: [GLOSSARY](GLOSSARY_2026_04.md).

---

### Sources

1. Asprova: [asprova.com](https://www.asprova.com/en/) (vendor-reported, accessed 2026-04-01). DELMIA: [3ds.com/delmia](https://www.3ds.com/products/delmia) (accessed 2026-04-01).
2. Google OR-Tools v9.15: [github.com/google/or-tools](https://github.com/google/or-tools) (accessed 2026-04-01).
3. NIST AI RMF 1.0: [nist.gov/ai-rmf](https://www.nist.gov/itl/ai-risk-management-framework). NIST SP 800-82 Rev. 3: OT security.
4. World Bank NV.IND.MANF.CD: [data.worldbank.org](https://data.worldbank.org/indicator/NV.IND.MANF.CD) (accessed 2026-04-01).
5. U.S. Census CBP 2022, NAICS 31-33: [census.gov/programs-surveys/cbp.html](https://www.census.gov/programs-surveys/cbp.html).