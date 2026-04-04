---
title: "SynAPS Claim Evidence Register 2026-04"
status: "active"
version: "1.0.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, claims, evidence, register, diligence]
mode: "reference"
---

# SynAPS Claim Evidence Register 2026-04

> **Confidence levels (C1 / C2 / C3) and evidence tiers (E1–E7) are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: explicit registry of what SynAPS currently claims, what evidence supports each claim, what could falsify it, and what would be required to upgrade it

## Active Claims

| Claim | Current confidence | Evidence now | Falsification trigger | Upgrade condition |
| --- | --- | --- | --- | --- |
| SynAPS is an industry-agnostic APS kernel thesis | C2 | `PITCH_MEMO.md`, `EVIDENCE_BASE.md`, schema materials, domain examples | schema cannot represent materially different domain examples or docs overstate current scope | successful cross-domain benchmark families or pilots |
| SynAPS keeps deterministic scheduling as the backbone | C2 | core technical overview, OR-Tools framing, benchmark and test evidence | runtime paths rely only on opaque model recommendations with no deterministic scheduling logic | broader exact/repair benchmark packet |
| SynAPS has working technical evidence | C2 | `TECHNICAL_VERIFICATION_REPORT_2026_04.md`, current technical materials | tests or smoke benchmark stop passing | repeated verification across broader instance classes |
| SynAPS has a working benchmark harness | C2 | `BENCHMARK_EVIDENCE_PACKET_2026_04.md`, benchmark protocol, smoke run | benchmark harness cannot run reproducibly in current workspace | medium and large repeated-run packet |
| SynAPS now has a source-backed initial market model | C2 hybrid | `MARKET_MODEL_2026_04.md` with official denominators and explicit assumptions | official denominator is wrong or assumptions are hidden as facts | region- and sector-sliced official denominators plus pilot-backed pricing |
| SynAPS uses advisory AI rather than autonomy-first execution in current messaging | C2 | `PITCH_MEMO.md`, `EVIDENCE_BASE.md`, `COMPLIANCE_TRUST_MATRIX_2026_04.md` | public materials begin claiming autonomous decision execution without bounded oversight | deployment-grade operator oversight evidence |
| The repository is prepared for conservative technical diligence | C2 | root documentation files, docs closure, investor router, comparables study | broken links, missing files, stale verification, or contradictory claims | DOI-backed releases and stronger public benchmark evidence |

## Non-Claimed Or Explicitly Bounded Areas

| Area | Current status | Why it is not claimable yet | Required upgrade evidence |
| --- | --- | --- | --- |
| Full-suite APS parity | NOT CLAIMED | incumbent scope is broader than current SynAPS kernel | expanded product scope and deployment evidence |
| ROI uplift versus incumbents | NOT CLAIMED | no pilot KPI evidence | before/after pilot data |
| Benchmark leadership | NOT CLAIMED | only smoke-level live proof exists | broad publishable benchmark family |
| Regulator-ready or audit-ready deployment | NOT CLAIMED | framework alignment is not certification | control mapping, audits, and field operations |
| Dependency-fresh production posture | NOT CLAIMED | current audits still show outdated packages | dedicated upgrade and compatibility program |

## Use Rule

When adding any new investor-facing statement, answer four questions first:

1. Is this an active claim, a bounded non-claim, or a roadmap hypothesis?
2. What current evidence supports it?
3. What would falsify it?
4. What would be needed to upgrade it?

If those answers are missing, the claim should not be promoted into the active investor packet.

## Bottom Line

The strength of the SynAPS package comes from explicit claim boundaries.

This register exists to keep that discipline intact as the project evolves.