---
title: "SynAPS Claim Evidence Register 2026-04"
status: "active"
version: "1.1.0"
last_updated: "2026-04-04"
date: "2026-04-04"
tags: [synaps, claims, evidence, register, diligence]
mode: "reference"
---

# SynAPS Claim Evidence Register 2026-04

> **Confidence levels (C1 / C2 / C3) and evidence tiers are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-04
Status: active
Scope: explicit registry of what SynAPS currently claims, what evidence supports each claim, what could falsify it, and what would be required to upgrade it

## How To Read This Register

Before using a confidence label, classify the statement itself:

- `CURRENT CORE`: repository-backed capability implemented and verifiable today
- `CURRENT SUPPORTING`: current benchmark, packaging, trust, or control-plane surface that supports diligence
- `CURRENT BOUNDED`: a true statement only when kept inside an explicit limit
- `TARGET / ROADMAP`: useful architecture direction, but not current implementation
- `NOT CLAIMED`: should not be promoted into the active investor narrative

Confidence labels from the glossary still apply. The truth class above simply prevents roadmap language from being mistaken for implemented software.

## Current Claims

| Claim surface | Truth class | Current confidence | Evidence now | Falsification trigger | Upgrade condition |
| --- | --- | --- | --- | --- | --- |
| SynAPS is a deterministic-first scheduling kernel and APS foundation | CURRENT CORE | C2 | [../../README.md](../../README.md), `docs/architecture/02_CANONICAL_FORM.md`, `TECHNICAL_VERIFICATION_REPORT_2026_04.md` | active code no longer ships deterministic scheduling paths or docs start claiming full vertical product parity | cross-domain benchmark families or pilot evidence |
| SynAPS currently ships CP-SAT, GREED, incremental repair, and LBBD solver paths | CURRENT CORE | C2 | `synaps/solvers/`, `synaps/portfolio.py`, `tests/`, `TECHNICAL_VERIFICATION_REPORT_2026_04.md` | one of the named solver paths stops being runnable or verified | repeated benchmark packet over larger instance families |
| SynAPS includes a minimal TypeScript BFF that validates contracts and bridges to the Python kernel | CURRENT SUPPORTING | C2 | `control-plane/README.md`, `schema/contracts/`, [../../README.md](../../README.md) | the control plane stops validating schemas or begins duplicating solver logic | stronger auth, orchestration, and operator surfaces |
| SynAPS has reproducible benchmark and public-review surfaces suitable for conservative technical diligence | CURRENT SUPPORTING | C2 | `BENCHMARK_EVIDENCE_PACKET_2026_04.md`, `benchmark/README.md`, `SUPPORT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CITATION.cff` | benchmark commands drift, trust docs break, or active docs contradict repo reality | repeated-run benchmark families and stronger release provenance |
| SynAPS is industry-agnostic at the kernel and schema level, not yet at deployment-proof product scope | CURRENT BOUNDED | C2 | [../../README.md](../../README.md), `docs/architecture/02_CANONICAL_FORM.md`, `schema/examples/` | schema cannot represent materially different planning examples or active docs overstate deployment scope | multiple domain benchmark families or field pilots |
| SynAPS uses bounded advisory framing rather than autonomy-first execution claims | CURRENT BOUNDED | C2 | [../../README.md](../../README.md), `INVESTOR_DILIGENCE_PACKET_2026_04.md`, `COMPLIANCE_TRUST_MATRIX_2026_04.md` | active docs begin claiming autonomous industrial execution without bounded oversight | deployment-grade oversight evidence |
| The repository is prepared for conservative external technical review | CURRENT SUPPORTING | C2 | repo-root trust docs, investor router, claim register, technical verification report | broken links, missing trust docs, stale verification, or contradictory claims | DOI-backed releases and stronger public benchmark evidence |

## Target Or Explicitly Bounded Areas

| Area | Truth class | Current status | Why it is not claimable yet | Required upgrade evidence |
| --- | --- | --- | --- | --- |
| Hardware-aware acceleration such as Rust bridges, AVX-512, or zero-copy IPC | TARGET / ROADMAP | design and research direction only | no active implementation or measured benchmark delta in the current repo | code, integration docs, and benchmark evidence |
| Event-sourced orchestration and anti-corruption boundaries | TARGET / ROADMAP | minimal BFF exists, full orchestration layer does not | current control plane is intentionally thin | implemented services plus integration tests |
| Advisory ML or LLM layer | TARGET / ROADMAP | research framing only | no active advisory runtime is shipped in the repository | bounded implementation with guardrails and evaluation |
| Air-gapped provenance and signed offline release train | PARTIAL / TARGET | conservative trust docs exist, but full offline provenance is not delivered | no signed SBOM or attestation lane is implemented in-repo | reproducible offline build, provenance, and verification evidence |
| ROI uplift or incumbent parity | NOT CLAIMED | no field data or transparent head-to-head packet | current evidence is repository-level, not plant-level | before/after pilot evidence and auditable comparison studies |

## Use Rule

When adding any new investor-facing statement, answer five questions first:

1. Is this `CURRENT CORE`, `CURRENT SUPPORTING`, `CURRENT BOUNDED`, `TARGET / ROADMAP`, or `NOT CLAIMED`?
2. What current evidence supports it?
3. What would falsify it?
4. What would be needed to upgrade it?
5. Does the sentence read like present-tense implementation when it is really only target architecture?

If those answers are missing, the claim should not be promoted into the active investor packet.

## Bottom Line

The strength of the SynAPS package comes from explicit claim boundaries, not from maximizing the claim set.

This register exists to keep that discipline intact as the project evolves.