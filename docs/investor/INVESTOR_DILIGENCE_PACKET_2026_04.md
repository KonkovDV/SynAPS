---
title: "SynAPS Investor Diligence Packet 2026-04"
status: "active"
version: "1.2.1"
last_updated: "2026-04-05"
date: "2026-04-05"
tags: [synaps, investor, diligence, github, verification]
mode: "reference"
---

# SynAPS - Investor Diligence Packet

> **Terms and confidence labels (C1 / C2 / C3) are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-04
Status: active
Scope: technical diligence packet for SynAPS - what is proven, what is only target architecture, and how to verify the difference

## 1. Executive Position

SynAPS is currently strongest as a **C2 deterministic scheduling kernel thesis** - backed by runnable code, passing tests, benchmark and packaging surfaces, and a minimal TypeScript control-plane boundary.

It is weaker as a deployed vertical APS product with proven pilot economics, plant integration, or independently audited incumbent comparisons.

Five narrow claims hold up today:

1. A deterministic scheduling kernel with exact, heuristic, and bounded repair paths.
2. Real, verifiable technical artifacts: schema, solver portfolio, tests, benchmark harness, contracts, and packaging surfaces.
3. A minimal network-facing BFF that validates checked-in contracts and delegates execution to the Python kernel.
4. A public review surface with support, security, contribution, and citation docs.
5. An explicit boundary between what the repository proves today and what remains target architecture.

**What this packet does not prove yet:** field ROI, market-validated pricing, full-suite parity versus named incumbents, hardware-aware acceleration as shipped code, air-gapped release maturity, or regulator-ready deployment.

## 2. Why Now

1. APS incumbents still sell constraint-based scheduling, rescheduling, and integration - not autonomy-first execution.
2. Google OR-Tools job shop guidance confirms precedence, no-overlap constraints, and makespan minimization as the standard deterministic scheduling baseline.
3. NIST SP 800-82 and current GitHub/SLSA guidance both reward transparent, auditable, bounded industrial software rather than inflated roadmap claims.
4. That makes a repository like SynAPS more legible when it stays disciplined about current proof versus target thesis.

## 3. What Exists Today

### 3.1 What you can verify technically

| Artifact | Location | What it shows |
|---------|----------|---------------|
| Canonical schema + runtime contracts | `schema/`, `schema/contracts/`, `synaps/model.py` | Domain-parameterized data model and checked-in request/response contracts |
| Python solver portfolio + repair | `synaps/`, `synaps/solvers/`, `tests/` | CP-SAT, GREED, LBBD, incremental repair, and routed execution |
| Benchmark harness + protocol | `benchmark/`, `benchmark/README.md` | Reproducible benchmark commands and instance tiers |
| Minimal TypeScript BFF | `control-plane/`, `control-plane/README.md` | Schema validation, Python bridge, and thin network boundary |
| Public trust docs | repo root | `SUPPORT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CITATION.cff` for external review |

### 3.2 Investor and GitHub documentation

The active diligence route now centers on a smaller number of evidence-bearing documents:

- [INVESTOR_DILIGENCE_PACKET](INVESTOR_DILIGENCE_PACKET_2026_04.md) - bounded read order
- [CLAIM_EVIDENCE_REGISTER](CLAIM_EVIDENCE_REGISTER_2026_04.md) - auditable claim registry
- [TECHNICAL_VERIFICATION_REPORT](TECHNICAL_VERIFICATION_REPORT_2026_04.md) - current engineering proof
- [BENCHMARK_EVIDENCE_PACKET](BENCHMARK_EVIDENCE_PACKET_2026_04.md) - benchmark truth boundary
- [MARKET_MODEL](MARKET_MODEL_2026_04.md) - source-backed market sizing
- Repository-root files: `SUPPORT.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `CITATION.cff`

## 4. Current Verification Snapshot (April 2026)

| Check | Result | Evidence |
|-------|--------|----------|
| Python `pytest` | PASS / REFRESH NEEDED | `TECHNICAL_VERIFICATION_REPORT_2026_04.md` records an earlier `149/149` full-suite pass, while the current repository now collects `175` tests |
| Benchmark smoke run | PASS | `TECHNICAL_VERIFICATION_REPORT_2026_04.md` records `tiny_3x3` GREED and `CPSAT-10` results |
| Minimal control-plane boundary | PRESENT | `control-plane/README.md` documents schema validation plus Python bridge |
| Public trust surfaces | PRESENT | `SUPPORT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CITATION.cff` are present at repo root |
| Supply-chain and export posture | PARTIAL | see `VERSION_AND_SUPPLY_CHAIN_AUDIT_2026_04.md` and `GITHUB_PUBLIC_EXPORT_AUDIT_2026_04.md` |

This is enough to support conservative technical diligence.

It is not enough to support product-superiority, deployment-maturity, or plant-operations claims.

## 5. Product Boundary

**What SynAPS is today:**

1. A deterministic scheduling kernel and APS platform foundation.
2. Exact plus heuristic plus bounded repair solver paths.
3. A minimal contract-validated control-plane boundary above the Python kernel.
4. A repository that is inspectable enough for conservative technical review.
5. A roadmap that is kept separate from current implementation claims.

**What SynAPS is not today:**

1. A full-suite supply-chain planning replacement.
2. A proven ROI winner versus Asprova, Ortems, or Quintiq.
3. A hardware-accelerated industrial autonomy stack.
4. A regulatory-certified deployment package.
5. A production-hardened plant deployment with audited release provenance.

## 6. Competitive Positioning

| Incumbent | What they sell | SynAPS implication |
|-----------|---------------|-------------------|
| Asprova | Finite-capacity scheduling, visual management, broad integration | Confirms the buyer baseline for realistic scheduling |
| DELMIA Ortems | Constraint-based scheduling, what-if analysis, ERP integration | Confirms local replanning as table stakes |
| DELMIA Quintiq | End-to-end supply-chain planning and optimization | Sets a scope ceiling SynAPS should not yet claim to match |

> All incumbent claims are vendor-reported from public product pages, not independently audited.

## 7. Investor Readiness Scorecard

| Dimension | Status | Notes |
|-----------|--------|-------|
| Product thesis clarity | **CLOSED** | Clear kernel thesis - what's claimed matches what's shown |
| GitHub presentation | **CLOSED** | Root README, security, support, citation files in place |
| Internal technical proof | **CLOSED (bounded)** | Schema, solver portfolio, benchmark harness, minimal BFF, an earlier `149/149` full-suite pass, and a current 175-test collection boundary |
| Competitive positioning | **CLOSED** | Explicit boundary, no full-suite parity claim |
| Academic legibility | **STRONG PARTIAL** | Citation metadata, methods appendix, claim register - no DOI release yet |
| Claim tracking | **CLOSED** | Active register with falsification triggers |
| Mathematical coherence | **STRONG PARTIAL** | Canonical form, solver portfolio, benchmark protocol verified |
| Market model | **PARTIAL** | Official denominators exist; pricing/wedge are C1 assumptions |
| Pilot evidence | **OPEN** | No field deployment data - protocol exists, data does not |
| Regulatory evidence | **PARTIAL** | Trust matrix exists; audited controls do not |
| Dependency freshness | **OPEN** | 2 outdated Python packages still remain |
| External benchmark | **PARTIAL** | Smoke evidence exists; broad publishable family does not |
| Control-plane boundary | **CLOSED** | Thin TypeScript BFF is present and explicitly bounded |
| Supply-chain posture | **PARTIAL** | Trust docs and baseline audits exist; stronger provenance still remains roadmap work |

## 8. What Investors Can Take Away

1. SynAPS has moved from concept memo to runnable, inspectable code.
2. The strongest current story is deterministic scheduling plus bounded repair plus explicit claim discipline.
3. The repository is easier to diligence technically than many early industrial software projects because the trust boundary is written down.
4. The main remaining gaps are external validation, broader benchmark families, and deployment maturity.

## 9. What This Packet Intentionally Omits

- Fundraising amount or valuation language.
- Fabricated customer pipeline or pilot logos.
- Vanity metrics or unverifiable traction claims.
- Market numbers without source attribution.

## 10. Recommended Read Order

**Fast summary:**
1. [INVESTOR_ONE_PAGER](INVESTOR_ONE_PAGER_2026_04.md)
2. [INVESTOR_DECK](INVESTOR_DECK_2026_04.md)

**Evidence core:**
3. [CLAIM_EVIDENCE_REGISTER](CLAIM_EVIDENCE_REGISTER_2026_04.md)
4. [TECHNICAL_VERIFICATION_REPORT](TECHNICAL_VERIFICATION_REPORT_2026_04.md)
5. [BENCHMARK_EVIDENCE_PACKET](BENCHMARK_EVIDENCE_PACKET_2026_04.md)
6. [MARKET_MODEL](MARKET_MODEL_2026_04.md)

**Read as needed:**
7. [COMPLIANCE_TRUST_MATRIX](COMPLIANCE_TRUST_MATRIX_2026_04.md)
8. [PILOT_KPI_PROTOCOL](PILOT_KPI_PROTOCOL_2026_04.md)
9. [VERIFICATION_COVERAGE_AUDIT](VERIFICATION_COVERAGE_AUDIT_2026_04.md)
10. [SYNAPS_VS_APS_INFIMUM](SYNAPS_VS_APS_INFIMUM_2026_04.md)
11. [MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL](MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04.md)
12. [GITHUB_PUBLIC_EXPORT_AUDIT](GITHUB_PUBLIC_EXPORT_AUDIT_2026_04.md)
13. [INTEGRATION_AND_ARCHITECTURE_GAP_AUDIT](INTEGRATION_AND_ARCHITECTURE_GAP_AUDIT_2026_04.md)

---

### Sources

1. Asprova: [asprova.com](https://www.asprova.com/en/). DELMIA Ortems/Quintiq: [3ds.com/delmia](https://www.3ds.com/products/delmia) (vendor-reported, accessed 2026-04-01).
2. Google OR-Tools job shop guide: [developers.google.com/optimization/scheduling/job_shop](https://developers.google.com/optimization/scheduling/job_shop) (accessed 2026-04-04).
3. GitHub security features: [docs.github.com](https://docs.github.com/en/code-security/getting-started/github-security-features) (accessed 2026-04-04).
4. SLSA build levels: [slsa.dev/spec/v1.0/levels](https://slsa.dev/spec/v1.0/levels) (accessed 2026-04-04).
5. NIST SP 800-82 Rev. 3: [csrc.nist.gov/pubs/sp/800/82/r3/final](https://csrc.nist.gov/pubs/sp/800/82/r3/final) (accessed 2026-04-04).