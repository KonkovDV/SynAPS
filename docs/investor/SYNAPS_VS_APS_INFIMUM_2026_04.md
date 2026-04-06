---
title: "SynAPS vs APS Infimum 2026-04"
status: "active"
version: "1.0.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, aps-infimum, competition, investor, diligence]
mode: "explanation"
---

# SynAPS vs APS Infimum 2026-04

> **Terms and confidence labels are defined in [GLOSSARY](GLOSSARY_2026_04.md).** | [GLOSSARY (RU)](GLOSSARY_2026_04_RU.md)

Language: EN | [RU](SYNAPS_VS_APS_INFIMUM_2026_04_RU.md)

Date: 2026-04-02
Status: active
Scope: investor-grade comparison between the open SynAPS kernel thesis and the publicly presented APS Infimum product

## 1. Executive Conclusion

SynAPS and APS Infimum are not the same type of asset.

APS Infimum currently looks stronger as a vertically deployed cable-plant APS product.

SynAPS currently looks stronger as an open, auditable, cross-industry kernel thesis that an external technical investor can inspect in detail on GitHub.

The most defensible comparison is therefore not "which one wins overall?" but:

1. which one is more operationally real today in one narrow manufacturing vertical;
2. which one is easier to diligence as a reusable scheduling kernel and venture-scale technical thesis.

Current answer:

1. APS Infimum leads on deployed vertical product reality;
2. SynAPS leads on open technical proof, reproducibility, and honesty about what's proven versus what's planned.

## 2. Evidence Standard Used In This Comparison

This comparison uses different evidence classes with different weights.

| Evidence class | Example used here | Weight | Main limitation |
| --- | --- | --- | --- |
| Open code and tests | schema, solver, tests, benchmark runner | highest | proves only what is actually in repo |
| Repo-grounded diligence docs | SynAPS investor pack, claim register, verification report | high | still internal authorship |
| Public product pages | MOSITLAB `aps-infimum` and `mes` pages | medium | self-reported vendor claims |
| Lecture-slide evidence | April 2026 lecture photos supplied during diligence | medium | presentation evidence, not auditable source code |
| Corporate ecosystem pages | MOSITLAB and MKM site surfaces | medium | confirms product packaging, not implementation internals |

Interpretation rule:

1. SynAPS proof is strongest where the claim is backed by code, tests, and local reruns.
2. APS Infimum proof is strongest where the claim is about public productization, pricing, UI, and operational packaging.
3. APS Infimum proof is weaker where the claim depends on self-reported ROI, self-reported deployment breadth, or slide-derived architecture reconstruction.

## 3. What The Comparison Says In One Sentence

APS Infimum proves that setup-heavy industrial scheduling has real product value in one vertical, while SynAPS shows a more transparent and portable way to present an industry-agnostic scheduling kernel to technical investors.

## 4. Side-By-Side Scorecard

| Dimension | APS Infimum | SynAPS | Current edge | Why it matters |
| --- | --- | --- | --- | --- |
| Product form | Publicly sold vertical APS product for cable production | Open kernel thesis with a directly inspectable technical codebase | APS Infimum | Investors discount pure concepts and reward visible product packaging |
| Deployment evidence | Public product pages claim operation at Moskabelmet and other cable plants | No pilot or customer deployment evidence yet | APS Infimum | Live operating context matters more than architecture slides |
| Pricing surface | Public list price from MOSITLAB product page | No public price or commercial packaging | APS Infimum | Pricing makes the business asset more concrete |
| Vertical specificity | Deep cable-production framing | Industry-agnostic abstraction | APS Infimum for today, SynAPS for breadth | One is better for immediate fit, the other for category expansion |
| Cross-industry portability | Claimed through corporate industry list, but centered on cable domain | Explicit schema examples across multiple domains | SynAPS | Portable kernel story requires visible parametrization evidence |
| Code visibility | No public source code discovered | Full repo-visible schema, solvers, tests, benchmark runner | SynAPS | External technical diligence is much easier with open code |
| Reproducibility | No public rerunnable benchmark or test pack found | active evidence pack records a fully documented `149/149` pass snapshot, a fresh `175`-test collection boundary, and a rerunnable benchmark smoke path | SynAPS | Reproducibility is stronger than polished product language |
| AI transparency | Product page and lecture slides show an AI-centered architecture signal | Current repo states ML advisory as a roadmap-adjacent layer, not a proven runtime core | mixed | APS Infimum looks more AI-forward; SynAPS is more honest about current AI depth |
| Mathematical explicitness | Slide-derived weighted objective and architecture can be reconstructed, but not from open formal docs | Canonical problem form, robust extension, and research references are explicit in repo docs | SynAPS | Investors trust systems they can reason about formally |
| UI and operations proof | Public screenshots: batching, Gantt, workstations, schedule views | No comparable UI proof in current public SynAPS surface | APS Infimum | Screens and workflows reduce abstraction risk |
| Integration proof | Publicly positioned with MES, 1C, SQL, BI, RFID, and adjacent MOSITLAB products | Integration remains architecture-level and not yet wired | APS Infimum | Integration determines whether APS is real or only algorithmic |
| Claim honesty | Strong claims, but economic numbers drift across public surfaces (`~1.2B` in slides vs `~1.4B` on product page) | Explicit claim register, diligence packet, and non-claim list | SynAPS | Trust rises when the boundary between proof and ambition is explicit |
| Benchmark transparency | No public benchmark corpus or methodology found | Benchmark protocol, harness, smoke evidence, and evidence packet exist | SynAPS | Public benchmarks matter more than vendor adjectives |
| Investor diligence readiness | Product pages are concrete but not built for adversarial review | Full diligence packet, red-team appendix, methods appendix, and claim register | SynAPS | Sophisticated investors value scoped honesty |
| Ecosystem packaging | Clear surrounding suite: CoMod, MES Cable Plant, Perimeter, Cable Justice | Strong kernel documents but no equivalent live ecosystem packaging | APS Infimum | Buyers often buy workflows, not only optimizers |
| Open collaboration surface | No visible public OSS contribution path | MIT license, contribution files, visible repo structure | SynAPS | Open collaboration broadens technical credibility |

## 5. What APS Infimum Clearly Does Better Today

### 5.1 It looks like an operating product, not only a research kernel

The MOSITLAB product surface gives APS Infimum a stronger immediate commercial reality signal.

Concrete strengths visible in public pages:

1. public pricing;
2. product packaging inside a broader manufacturing software suite;
3. workflow screenshots and operational UI;
4. concrete claims about batching, changeovers, alternative work centers, stockpiles, and MES/1C integration.

### 5.2 It frames the economic story in factory language

APS Infimum speaks directly in the language of plant economics:

1. changeover losses;
2. equipment loading;
3. work in progress;
4. production rescheduling;
5. operating profit and quarterly effect.

SynAPS currently explains the category well, but APS Infimum is closer to how a plant manager or operations executive hears value.

### 5.3 It demonstrates a concrete adjacent-system ecosystem

Public MOSITLAB surfaces show APS Infimum next to:

1. 1C: MES Cable Plant;
2. CoMod;
3. Perimeter RFID;
4. Cable Justice;
5. other manufacturing and operational products.

This matters because APS buyers rarely buy a naked optimizer. They buy a planning surface that fits into operational execution.

### 5.4 The lecture slides materially strengthen the architecture signal

The lecture-slide set adds important detail beyond the product page.

The slides indicate a planning pipeline with:

1. `50,000` operations reduced to `10,000` aggregated operations;
2. `100` work centers;
3. `25` replacement groups;
4. `25` container types;
5. `700,000` setup variants;
6. `100,000` setup-length variants;
7. a `GREED -> Encoder -> AI -> GREED` path plus `GEN` and a database of optimal variants;
8. self-reported `8%` equipment-loading improvement and `27 days / ~1.2B RUB per year` enterprise gain.

That does not prove the internal implementation, but it does prove a much more specific operational narrative than a generic brochure.

## 6. What SynAPS Clearly Does Better Today

### 6.1 SynAPS is easier to technically verify from first principles

An investor or technical diligence team can inspect:

1. the schema DDL;
2. the solver baseline;
3. the repair logic;
4. the benchmark runner;
5. the test suite;
6. the research foundation.

That is a major advantage over a proprietary competitor whose best evidence is still presentation and corporate product copy.

### 6.2 SynAPS is more disciplined about the difference between proof and roadmap

SynAPS explicitly separates:

1. what exists today;
2. what is only partially implemented;
3. what is research or roadmap;
4. what is not claimed yet.

That is stronger investor hygiene than product pages that mix proven product value with broader strategic ambition.

### 6.3 SynAPS is more portable as a kernel thesis

APS Infimum is stronger inside cable production.

SynAPS is stronger as a reusable kernel story because it already exposes:

1. multi-domain schema templates;
2. cross-industry abstraction as a first-class design goal;
3. a formal problem statement intended to survive domain changes.

### 6.4 SynAPS is better packaged for adversarial diligence

The SynAPS investor pack includes:

1. a diligence packet;
2. a claim-evidence register;
3. a red-team appendix;
4. a methods appendix;
5. a verification report;
6. a market model with explicit assumptions.

That means the GitHub surface is built not only to impress, but to withstand scrutiny.

### 6.5 SynAPS is stronger as an open research-software asset

SynAPS already has the ingredients that matter to research-aware and developer-aware investors:

1. visible code;
2. reproducible tests;
3. benchmark methodology;
4. citation metadata;
5. domain examples.

APS Infimum may be operationally ahead, but SynAPS is easier to audit, extend, and discuss with technical depth.

## 7. What The Lecture Slides Change

The lecture slides should change how SynAPS is positioned against APS Infimum.

Before the slide evidence, APS Infimum could be dismissed as a vague marketing surface.

After the slide evidence, that dismissal is no longer credible.

The slides indicate that APS Infimum likely has:

1. a real multi-stage planning formulation;
2. explicit aggregation logic;
3. multi-criteria optimization;
4. a specific AI-guided planning architecture;
5. real operational Gantt and batching surfaces.

However, the slides still do not provide:

1. source code;
2. public benchmark protocol;
3. reproducible tests;
4. independent economic validation;
5. audited implementation details.

Therefore the correct investor stance is:

APS Infimum is stronger than a slide-only concept, but still weaker than SynAPS on open technical verifiability.

## 8. What SynAPS Should Learn From APS Infimum

### 8.1 Make the operating problem tangible earlier

APS Infimum starts with a real plant problem.

SynAPS should similarly lead with:

1. setup-heavy environments;
2. auxiliary-resource scarcity;
3. bounded replanning;
4. explicit factory economics.

### 8.2 Show the planning artifact, not only the architecture

SynAPS needs more visible proof of the actual planning result surface:

1. schedule outputs;
2. benchmark-derived Gantt views;
3. what-if and repair examples;
4. bottleneck and WIP analytics.

### 8.3 Speak in value levers before speaking in horizon language

SynAPS currently explains the future well.

APS Infimum explains the current operating pain more concretely.

SynAPS should copy that discipline.

### 8.4 Treat integration as part of the product thesis, not a future footnote

An APS buyer immediately asks how the planner touches ERP, MES, inventory, containers, maintenance, and execution.

APS Infimum answers this more concretely today.

## 9. What SynAPS Should Not Copy From APS Infimum

### 9.1 Self-reported ROI as a substitute for evidence

APS Infimum's public surfaces are commercially stronger, but their economic headline is still self-reported.

SynAPS should not imitate that approach to evidence.

### 9.2 Fully automated language without open proof

Claims such as "the system itself selects the best production scenario" are commercially attractive but too strong without public runtime evidence and safety framing.

### 9.3 Vertical overfitting as the whole story

APS Infimum benefits from cable-specific fit.

SynAPS should learn from that specificity without losing the broader kernel thesis.

## 10. What Has Become Better In SynAPS Relative To APS Infimum

This comparison is useful precisely because it shows where SynAPS already improved the GitHub investor package beyond what many real industrial products publish.

What is already better in SynAPS:

1. stronger separation between current proof and roadmap;
2. better technical transparency through open code and tests;
3. better benchmark methodology disclosure;
4. better claim-evidence tracking;
5. better investor-readiness for adversarial diligence;
6. stronger cross-industry framing without pretending those deployments already exist.

In other words, SynAPS is currently the more legible technical thesis even though APS Infimum is the more concrete vertical product.

## 11. What SynAPS Must Still Build To Close The Product-Reality Gap

The key risk is not that SynAPS is technically weak.

The key risk is that it still looks more inspectable than operational.

The highest-value next steps are:

1. medium and large benchmark corpus with publication-quality tables;
2. reference integration architecture or adapters for ERP and MES seams;
3. scenario and bounded-repair demonstrations with visible outputs;
4. pilot KPI evidence using the existing measurement protocol;
5. more concrete operations-facing surfaces such as reports, schedules, or synthetic dashboards;
6. release and dependency hygiene for a stronger production-readiness stance.

## 12. Bottom Line

APS Infimum and SynAPS should not be pitched as if they were the same maturity class.

The investor-grade position is:

1. APS Infimum validates that industrial scheduling pain is commercially real and that a cable-specific APS product can be packaged, sold, and publicly narrated;
2. SynAPS validates that a more open, cross-industry, technically auditable kernel can be built and diligenced with much greater transparency;
3. the strongest SynAPS story is not "we already beat APS Infimum," but "we are building the more portable, more inspectable, and more investor-legible kernel category that vertical products like APS Infimum prove is economically important."