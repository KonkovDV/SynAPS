# SynAPS Market Competition Report

> **Terms and confidence labels are defined in [GLOSSARY](GLOSSARY_2026_04.md).** | [GLOSSARY (RU)](GLOSSARY_2026_04_RU.md)

Language: EN | [RU](MARKET_COMPETITION_REPORT_2026_04_RU.md)

Date: 2026-04-01
Status: active
Scope: qualitative external evidence for APS buyer baseline, competition boundaries, and how honest SynAPS claims should be

## Goal

Translate official vendor and standards material into practical positioning rules for SynAPS.

This report is qualitative.

It does not attempt to produce TAM, SAM, or SOM numbers.

## Sources Used

### Neutral technical and governance sources

1. Google OR-Tools, The Job Shop Problem
   URL: https://developers.google.com/optimization/scheduling/job_shop
2. NIST AI Risk Management Framework 1.0
   URL: https://www.nist.gov/itl/ai-risk-management-framework
3. NIST SP 800-82 Rev. 3, Guide to Operational Technology Security
   URL: https://csrc.nist.gov/pubs/sp/800/82/r3/final

### Vendor positioning sources

1. Asprova
   URL: https://www.asprova.com/en/
2. DELMIA Ortems
   URL: https://www.3ds.com/products/delmia/ortems
3. DELMIA Quintiq
   URL: https://www.3ds.com/products/delmia/quintiq

## 1. APS Buyer Baseline Visible In Official Sources

| Capability visible in public sources | External evidence |
| --- | --- |
| Finite-capacity scheduling | Asprova leads with finite-capacity scheduling. DELMIA Ortems leads with constraint-based, finite-capacity resource optimization. |
| Short-horizon rescheduling | DELMIA Ortems emphasizes short-term scheduling and rescheduling. |
| Scenario analysis | DELMIA Ortems emphasizes what-if analysis. DELMIA Quintiq emphasizes unlimited what-if scenario planning. |
| Integration with existing enterprise systems | Asprova emphasizes system integration. DELMIA Ortems explicitly positions ERP integration. |
| Visibility for planners | Asprova emphasizes visual management. DELMIA Ortems emphasizes centralized planning visibility. DELMIA Quintiq emphasizes real-time visibility and KPI planning. |
| Constraint-based optimization | Google OR-Tools still frames job shop scheduling around precedence constraints, no-overlap constraints, interval variables, and makespan minimization. |

## 2. Competitive Boundary Map

| Surface | Official positioning | Implication for SynAPS |
| --- | --- | --- |
| Asprova | Production scheduling system with finite-capacity scheduling, visual management, system integration, and a public claim of 3,300+ sites with support across 44 countries | Confirms that APS buyers expect practical scheduling, operational visibility, and mature integration and rollout surfaces |
| DELMIA Ortems | Agile planning, scheduling, and production with constraint-based, finite-capacity optimization, bottleneck handling, what-if analysis, ERP integration, and short-term rescheduling | Confirms that fast replanning under real shop-floor constraints is table stakes, not a premium differentiator |
| DELMIA Quintiq | End-to-end supply chain planning and optimization across production, logistics, workforce, analytics, KPI planning, and virtual-twin-enabled optimization | Confirms that full-suite supply-chain parity is broader than the current SynAPS kernel and should not be implied |

## 3. What SynAPS Can Credibly Claim Against This Baseline

1. SynAPS can credibly position itself as an industry-agnostic scheduling kernel rather than a full-suite supply-chain platform.
2. SynAPS can credibly emphasize deterministic scheduling logic plus advisory AI, because OR-Tools still reflects constraint-based scheduling as the canonical backbone.
3. SynAPS can credibly emphasize local repair and focused replanning as a product direction, because incumbent APS products clearly treat rescheduling and operational responsiveness as core buyer expectations.
4. SynAPS can credibly emphasize on-prem deployment for critical operational sites, because OT guidance continues to prioritize performance, reliability, and safety in cyber-physical environments.

## 4. What SynAPS Should Not Claim Yet

1. Full parity with end-to-end planning suites such as DELMIA Quintiq.
2. Externally validated ROI uplift versus incumbent APS vendors.
3. Proven benchmark leadership versus named commercial alternatives.
4. Regulator-ready or audit-ready status for sector-specific manufacturing domains.
5. Source-backed TAM, SAM, or SOM figures.

## 5. AI Trust and OT Deployment

The NIST AI RMF is a trust reference, not a market-size source. It supports honest claim boundaries, auditability, and clear separation between recommendation and execution.

NIST SP 800-82 Rev. 3 remains directly relevant to industrial APS deployment because it frames OT security around performance, reliability, and safety requirements in systems that interact with the physical world.

For SynAPS this means:

1. AI should remain advisory in current messaging.
2. Deterministic fallbacks and well-scoped execution should stay central.
3. On-prem deployment should remain the default for regulated or mission-critical sites.

## 6. Go-to-Market Implications

1. Lead with scheduling accuracy, constraint realism, and replanning responsiveness - not with frontier AI language.
2. Treat ERP, MES, and shop-floor integration as a first-order product concern.
3. Target sites where setup losses, bottlenecks, auxiliary resources, and rescheduling pain have immediate economic impact.
4. Treat digital twin, multi-site learning, and broader control-tower behavior as roadmap items, not present-day category parity.

## 7. What We Can and Can't Claim

| Claim area | Current maximum confidence | Reason |
| --- | --- | --- |
| Industry-agnostic APS kernel | C2 | Backed by the current SynAPS schema, solver baseline, domain examples, and research docs |
| Deterministic scheduling foundation | C2 partial | Backed by current solver baseline and OR-Tools-aligned framing; SDST parity is now covered across exact solve, repair, and feasibility checking, while auxiliary-resource handling is still only partially solver-native |
| APS buyer baseline understanding | C2 | Backed by official vendor positioning for Asprova, DELMIA Ortems, and DELMIA Quintiq |
| Full-suite supply-chain parity | C1 and should not be claimed | Vendor surfaces show materially broader scope than the current SynAPS kernel |
| External ROI and benchmark superiority | C1 | No pilot data or named head-to-head benchmark pack yet |
| TAM, SAM, SOM, and unit economics | C1 | No source-backed market model yet |

## 8. Remaining Evidence Gaps

1. A source-backed TAM, SAM, and SOM model with date, method, assumptions, and scenarios.
2. A pilot KPI protocol with before-and-after operational measurements.
3. A broader benchmark family with publishable result tables.
4. A quantitative head-to-head comparison against transparent baselines and, where possible, named APS alternatives.

## Bottom Line

Current external evidence supports a narrower but defensible SynAPS pitch:

SynAPS is best framed today as an industry-agnostic scheduling kernel with deterministic logic, local repair, and on-prem deployment.

It is not yet supportable to describe SynAPS as a full-suite APS replacement, a proven ROI winner against incumbents, or a source-backed market-size story.

## 9. Vertical Comparator Note: APS Infimum

Broad market baselines are not the only useful comparison class.

A publicly presented vertical APS product such as APS Infimum is also important because it shows what an operating manufacturing buyer surface can look like in a setup-heavy domain.

Why it matters for SynAPS:

1. APS Infimum makes plant economics, batching, changeovers, alternative work centers, and operational UI much more concrete than most category-level vendor pages.
2. It gives SynAPS a useful reality check: productization, packaging, pricing, and factory workflows still matter as much as solver design.
3. At the same time, SynAPS currently exceeds APS Infimum on open technical proof, reproducibility, and honesty about what's proven versus what's planned.

For the full analysis, use `SYNAPS_VS_APS_INFIMUM_2026_04.md`.