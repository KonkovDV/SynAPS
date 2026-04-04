---
title: "SynAPS Investor Diligence Packet 2026-04"
status: "active"
version: "1.1.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, investor, diligence, github, verification]
mode: "reference"
---

# SynAPS — Investor Diligence Packet

> **Terms and confidence labels (C1 / C2 / C3) are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: technical diligence packet for SynAPS — what's proven, what's not, and how to verify it

## 1. Executive Position

SynAPS is currently defensible as a **C2 product-kernel thesis** — backed by working code, passing tests, and internal benchmarks, but not yet validated externally through pilots or independent comparison.

Four narrow claims hold up today:

1. An industry-agnostic scheduling kernel with deterministic planning, local repair, and extensible constraint modeling.
2. Real, verifiable technical artifacts: schema, solver, benchmark harness, and research documentation.
3. A GitHub presence set up for external technical review — security policy, support, citation, contribution guide.
4. Clear separation between what I can show evidence for today and what still needs external validation.

**What I haven't proven yet:** market-validated pricing, field ROI, benchmark superiority versus named incumbents, or regulatory-ready deployment.

## 2. Why Now

1. APS incumbents still lead with constraint-based scheduling, rescheduling, and integration — not AI branding.¹
2. Google OR-Tools (v9.15, 13,300+ stars) confirms constraint-based scheduling as the computational standard.²
3. NIST AI RMF and SP 800-82 reinforce auditable, transparent AI for industrial and OT settings.³
4. Open-source infrastructure and local inference make on-prem advisory AI practical.

## 3. What Exists Today

### 3.1 What you can verify technically

| Artifact | Location | What it shows |
|---------|----------|---------------|
| Universal schema + examples | schema package | Domain-parameterized data model |
| Python solver baseline + repair | solver package | Working heuristic and exact solver |
| Benchmark harness + protocol | benchmark package | Reproducible performance measurement |
| Research foundation | research documentation | Literature review, roadmap, methods |

### 3.2 Investor and GitHub documentation

The full investor pack comprises 27 documents in this directory. Key documents:

- [PITCH_MEMO](PITCH_MEMO.md) — product narrative
- [EVIDENCE_BASE](EVIDENCE_BASE.md) — what we can and can't claim, and why
- [MARKET_MODEL](MARKET_MODEL_2026_04.md) — source-backed market sizing
- [MARKET_COMPETITION_REPORT](MARKET_COMPETITION_REPORT_2026_04.md) — competitive positioning
- [CLAIM_EVIDENCE_REGISTER](CLAIM_EVIDENCE_REGISTER_2026_04.md) — auditable claim registry
- Repository-root files: `SUPPORT.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `CITATION.cff`

## 4. Fresh Verification Status (April 2026)

| Check | Result | Evidence |
|-------|--------|----------|
| Python `pytest` | PASS | Standalone SynAPS test suite passed |
| `ruff check synaps tests benchmark --select F,E9` | PASS | Targeted standalone lint gate passed |
| `python -m build` | PASS | Source distribution and wheel built successfully |
| `twine check dist/*` | PASS | Packaging metadata and long description passed validation |
| Benchmark smoke run | PASS | GREED solved the smoke instance successfully |
| Optional investor-subtree removal rehearsal | PASS | SynAPS code and build still worked without `docs/investor/` |

## 5. Product Boundary

**What SynAPS is today:**

1. An industry-agnostic scheduling kernel and APS platform foundation.
2. Deterministic scheduling plus bounded repair.
3. Advisory AI — suggests and explains, does not execute autonomously.
4. On-premises by default for factory environments.

**What SynAPS is not today:**

1. A full-suite supply-chain planning replacement.
2. A proven ROI winner versus Asprova, Ortems, or Quintiq.
3. A regulatory-certified deployment package.
4. A production-hardened release train with fresh dependencies.

## 6. Competitive Positioning

| Incumbent | What they sell | SynAPS implication |
|-----------|---------------|-------------------|
| Asprova¹ | Finite-capacity scheduling, visual management, broad integration | Confirms the buyer baseline for realistic scheduling |
| DELMIA Ortems¹ | Constraint-based scheduling, what-if analysis, ERP integration | Confirms local replanning as table stakes |
| DELMIA Quintiq¹ | End-to-end supply-chain planning and optimization | Sets a scope ceiling SynAPS should not yet claim to match |

> All incumbent claims are vendor-reported from public product pages, not independently audited.

## 7. Investor Readiness Scorecard

| Dimension | Status | Notes |
|-----------|--------|-------|
| Product thesis clarity | **CLOSED** | Clear kernel thesis — what's claimed matches what's shown |
| GitHub presentation | **CLOSED** | Root README, security, support, citation files in place |
| Internal technical proof | **PARTIAL** | Schema, solver, benchmark harness, 27/27 tests |
| Competitive positioning | **CLOSED** | Explicit boundary, no full-suite parity claim |
| Academic legibility | **STRONG PARTIAL** | Citation metadata, methods appendix, claim register — no DOI release yet |
| Claim tracking | **CLOSED** | Active register with falsification triggers |
| Mathematical coherence | **PARTIAL-STRONG** | Canonical form, solver portfolio, benchmark protocol verified |
| Market model | **PARTIAL** | Official denominators exist; pricing/wedge are C1 assumptions |
| Pilot evidence | **OPEN** | No field deployment data — protocol exists, data does not |
| Regulatory evidence | **PARTIAL** | Trust matrix exists; audited controls do not |
| Dependency freshness | **OPEN** | 2 outdated Python packages still remain |
| External benchmark | **PARTIAL** | Smoke evidence exists; broad publishable family does not |

## 8. What Investors Can Take Away

1. SynAPS has moved from concept memo to working code you can actually check.
2. The thesis is narrower and more credible than "AI replaces industrial planning."
3. The documentation and verification rigor are unusually strong for this stage.
4. The main gap isn't narrative quality — it's external validation: pilots, broad benchmarks, and audited deployment.

## 9. What This Packet Intentionally Omits

- Fundraising amount or valuation language.
- Fabricated customer pipeline or pilot logos.
- Vanity metrics or unverifiable traction claims.
- Market numbers without source attribution.

## 10. Recommended Read Order

**Start here:**
1. [GLOSSARY](GLOSSARY_2026_04.md) — terminology and confidence-level definitions
2. [INVESTOR_ONE_PAGER](INVESTOR_ONE_PAGER_2026_04.md) — fastest summary
3. [INVESTOR_DECK](INVESTOR_DECK_2026_04.md) — slide narrative

**Core evidence:**
4. [PITCH_MEMO](PITCH_MEMO.md) — full product narrative
5. [EVIDENCE_BASE](EVIDENCE_BASE.md) — claim control
6. [MARKET_MODEL](MARKET_MODEL_2026_04.md) — source-backed market sizing
7. [MARKET_COMPETITION_REPORT](MARKET_COMPETITION_REPORT_2026_04.md) — competitive analysis
8. [technical verification report](TECHNICAL_VERIFICATION_REPORT_2026_04.md) — technical proof

**Deep diligence:**
9. [BENCHMARK_EVIDENCE_PACKET](BENCHMARK_EVIDENCE_PACKET_2026_04.md)
10. [PILOT_KPI_PROTOCOL](PILOT_KPI_PROTOCOL_2026_04.md)
11. [ACADEMIC_METHODS_APPENDIX](ACADEMIC_METHODS_APPENDIX_2026_04.md)
12. [COMPLIANCE_TRUST_MATRIX](COMPLIANCE_TRUST_MATRIX_2026_04.md)
13. [CLAIM_EVIDENCE_REGISTER](CLAIM_EVIDENCE_REGISTER_2026_04.md)
14. [INVESTOR_RED_TEAM_APPENDIX](INVESTOR_RED_TEAM_APPENDIX_2026_04.md)

**Audits and supplements (read as needed):**
15. [WORLD_CLASS_TECHNICAL_DILIGENCE_FRAMEWORK](WORLD_CLASS_TECHNICAL_DILIGENCE_FRAMEWORK_2026_04.md)
16. [VERSION_AND_SUPPLY_CHAIN_AUDIT](VERSION_AND_SUPPLY_CHAIN_AUDIT_2026_04.md)
17. [INTEGRATION_AND_ARCHITECTURE_GAP_AUDIT](INTEGRATION_AND_ARCHITECTURE_GAP_AUDIT_2026_04.md)
18. [VERIFICATION_COVERAGE_AUDIT](VERIFICATION_COVERAGE_AUDIT_2026_04.md)
19. [MATHEMATICAL_AND_RESEARCH_FACT_CHECK](MATHEMATICAL_AND_RESEARCH_FACT_CHECK_2026_04.md)
20. [LONG_HORIZON_STRATEGIC_OPTIONS](LONG_HORIZON_STRATEGIC_OPTIONS_2026_04.md)
21. [SYNAPS_VS_APS_INFIMUM](SYNAPS_VS_APS_INFIMUM_2026_04.md)
22. [MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL](MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04.md)
23. [GITHUB_COMPARABLES_BEST_PRACTICES](GITHUB_COMPARABLES_BEST_PRACTICES_2026_04.md)
24. [GITHUB_PUBLIC_EXPORT_AUDIT](GITHUB_PUBLIC_EXPORT_AUDIT_2026_04.md)
25. [HYPERDEEP_AUDIT_REPORT](HYPERDEEP_AUDIT_REPORT_2026_04.md)

---

### Sources

1. Asprova: [asprova.com](https://www.asprova.com/en/). DELMIA Ortems/Quintiq: [3ds.com/delmia](https://www.3ds.com/products/delmia) (vendor-reported, accessed 2026-04-01).
2. Google OR-Tools v9.15: [github.com/google/or-tools](https://github.com/google/or-tools) (accessed 2026-04-01).
3. NIST AI RMF 1.0: [nist.gov/ai-rmf](https://www.nist.gov/artificial-intelligence/ai-risk-management-framework). NIST SP 800-82 Rev. 3: OT security.