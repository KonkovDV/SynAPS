# SynAPS External Evidence Base

> **Terms and confidence labels (C1 / C2 / C3) are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-01
Status: active
Scope: external evidence synthesis for SynAPS product positioning and investor-facing honesty about what's proven

## Goal

Turn the remaining evidence gap in `PITCH_MEMO.md` into explicit product rules and positioning boundaries.

This document is not a marketecture dump.

It separates what is now supported by internal repo artifacts from what still requires pilots, broader benchmarks, and source-backed market work.

## Internal Surfaces Used

1. `docs/investor/PITCH_MEMO.md`
2. core SynAPS README and technical overview
3. research literature review
4. benchmark protocol
5. long-horizon research roadmap

## External Official Sources Used

1. Google OR-Tools, The Job Shop Problem
   URL: https://developers.google.com/optimization/scheduling/job_shop
2. NIST AI Risk Management Framework
   URL: https://www.nist.gov/itl/ai-risk-management-framework
3. NIST SP 800-82 Rev. 3, Guide to Operational Technology Security
   URL: https://csrc.nist.gov/pubs/sp/800/82/r3/final
4. DELMIA Quintiq
   URL: https://www.3ds.com/products/delmia/quintiq
5. DELMIA Ortems
   URL: https://www.3ds.com/products/delmia/ortems
6. Asprova
   URL: https://www.asprova.com/en/

## Evidence To Decision Mapping

## 1. APS buyer baseline is still finite-capacity scheduling, rescheduling, visibility, and integration

### What matters

Asprova leads with finite-capacity scheduling, visual management, integration with existing systems, and cross-industry applicability. DELMIA Ortems leads with constraint-based finite-capacity optimization, what-if analysis, ERP integration, and short-term rescheduling. DELMIA Quintiq extends the same baseline into KPI planning, scenario modeling, and broader planning synchronization.

### Operational implication

SynAPS should lead with the deterministic scheduling kernel, realistic finite-capacity scheduling, local repair, and integration seams.

It should not lead with frontier AI claims.

### Product control

1. Keep CP-SAT plus heuristic scheduling as the product center of gravity.
2. Keep rescheduling and bottleneck repair as first-class product capabilities.
3. Treat ERP, MES, and shop-floor integration boundaries as core product concerns, not later polish.
4. Position AI as advisory, not as the primary trust anchor.

## 2. Full-suite APS incumbents operate above the initial SynAPS scope

### What matters

DELMIA Quintiq positions itself as end-to-end supply chain planning and optimization across production, logistics, workforce, analytics, and business KPI planning. That is materially broader than the current SynAPS kernel.

### Operational implication

SynAPS should not claim parity with end-to-end supply chain suites.

### Product control

1. Describe SynAPS as an industry-agnostic scheduling kernel and extensible APS platform.
2. Avoid messaging that implies full IBP, workforce planning, or global control-tower parity.
3. Keep the roadmap language, but separate present kernel scope from future suite ambition.

## 3. Exact scheduling logic remains a valid and necessary foundation

### What matters

The official OR-Tools job-shop guidance still centers the problem around precedence constraints, machine no-overlap constraints, interval variables, and makespan minimization. This confirms that exact or constraint-based modeling remains the canonical backbone for serious scheduling systems.

### Operational implication

SynAPS is correct to keep a deterministic exact layer instead of presenting AI as a black-box replacement for constraint satisfaction.

### Product control

1. Keep exact scheduling logic visible in the product story.
2. Use AI to rank, tune, explain, or guide search, not to replace hard feasibility guarantees.
3. Keep benchmark reporting grounded in explicit solver regimes and constraints.

## 4. Industrial AI claims need trust and risk controls, not only model ambition

### What matters

NIST AI RMF frames AI risk management around trustworthy design, development, use, and evaluation. The framework is voluntary, but it explicitly raises the bar for how AI system claims should be governed.

### Operational implication

For SynAPS, this means auditability, honest claim boundaries, deterministic fallbacks, and explicit separation between recommendation and execution.

### Product control

1. Keep claim confidence tags in investor-facing material.
2. Keep the advisory AI approach in core messaging.
3. Require evidence artifacts before introducing quantitative claims about uplift, speed, or autonomy.

## 5. OT deployment constraints are product requirements for industrial APS, not enterprise nice-to-haves

### What matters

NIST SP 800-82 Rev. 3 emphasizes that OT security has to preserve performance, reliability, and safety in systems interacting with the physical world.

### Operational implication

On-prem deployment, graceful degraded modes, and explicit operational boundaries are natural requirements for SynAPS in critical cyber-physical settings.

### Product control

1. Keep on-prem deployment as the default assumption.
2. Keep offline-capable and degraded deterministic modes in the architecture story.
3. Do not market the product as cloud-first by default for regulated or critical operational sites.

## 6. Cross-industry applicability is credible only when backed by domain examples and constraint mapping

### What matters

Asprova explicitly shows adoption across multiple manufacturing sectors and ties value to concrete scheduling constraints. That supports the category thesis that one scheduling core can span multiple industries if the model handles domain-specific constraints cleanly.

### Operational implication

The SynAPS universal-schema thesis is credible as a C2 internal-evidence claim because the current codebase includes domain examples and domain documentation. It is not yet a C3 external-validation claim.

### Product control

1. Keep cross-industry applicability as an internal-evidence thesis for now.
2. Do not convert portability into ROI claims until there are pilots or external benchmarks.
3. Use domain examples, schema examples, and benchmark instances as the evidence for portability.

## Current Internal Evidence Status

| Evidence area | Current status | Artifact path | Confidence |
| --- | --- | --- | --- |
| Universal schema draft | present | schema definitions and domain examples | C2 |
| Dedicated solver baseline | present; SDST parity is now covered across CP-SAT, repair, and feasibility checking, while auxiliary-resource capacity is enforced in the feasibility truth gate and solver-side constructive modeling remains partial | solver package | C2 partial |
| Benchmark harness | present | benchmark package | C2 |
| Benchmark protocol | present | benchmark protocol | C2 |
| Research foundation | present | research documentation | C2 |
| Cross-domain parametrization examples | present | domain examples and domain notes | C2 |
| Broad benchmark corpus | partial | current benchmark instance set | C2 partial |
| Digital twin / DES runtime | missing | roadmap only | C1 |
| Pilot KPI protocol with field data | missing | no pilot artifact yet | C1 |
| Quantitative comparison against named APS alternatives | missing | this report is qualitative only | C1 |
| Industrial connectors and live ERP/MES integrations | missing | architecture-only surfaces | C1 |

## What We Can and Can't Claim Today

| Claim area | Current confidence | Why |
| --- | --- | --- |
| Industry-agnostic APS kernel | C2 | Backed by universal schema, domain examples, and research docs |
| Hybrid exact plus heuristic architecture | C2 partial | Backed by solver package, benchmark harness, and OR-Tools-aligned problem framing; SDST invariants are now exercised across exact solve, repair, and feasibility paths, while auxiliary-resource modeling is still only partially solver-native |
| Advisory AI layer as product direction | C2 | Backed by internal architecture and external AI trust guidance |
| External KPI uplift versus incumbents | C1 | No pilot or third-party benchmark evidence yet |
| TAM, SAM, SOM, and unit economics | C1 | No source-backed market model yet |
| Compliance-ready or regulator-ready status | C1 | Requires sector-specific control mapping and evidence bundle |
| Full-suite supply-chain platform parity | C1 and should not be claimed | Incumbents operate at a broader scope than the current SynAPS kernel |

## Recommended Pitch Positioning

1. Lead with deterministic scheduling plus repair, not with AI-first language.
2. Position SynAPS as an extensible APS kernel with universal constraint modeling.
3. Treat AI, digital twin, federated learning, and quantum as roadmap multipliers, not current proof points.
4. Explicitly separate current internal evidence from future external validation.

## Remaining Evidence Gaps

1. A source-backed TAM, SAM, and SOM model with method, date, and scenarios.
2. A broader benchmark family with publishable result tables across multiple instance classes.
3. A quantitative comparison packet against named APS alternatives or at least against transparent open baselines.
4. A pilot KPI protocol with before-and-after measurement discipline.
5. A sector-specific control mapping for regulated manufacturing claims.

## Recommended Follow-up To `PITCH_MEMO.md`

1. Update the internal evidence snapshot so it reflects the current SynAPS codebase and technical materials.
2. Keep market-size and ROI claims at C1 until a source-backed model exists.
3. Add this evidence base as the canonical support document for investor-facing updates.

## Bottom Line

The current SynAPS codebase materially upgrades the product from pure concept memo to a documented C2 product-kernel thesis with a real schema, solver baseline, benchmark harness, and research backbone.

It does not yet justify C3 claims about field ROI, benchmark leadership, regulatory readiness, or deployment-grade completeness of auxiliary-resource handling across the current solver stack.

That is the honest investor and product position today.