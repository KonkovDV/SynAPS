---
title: "SynAPS Compliance and Trust Matrix 2026-04"
status: "active"
version: "1.0.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, compliance, trust, ai-act, nist]
mode: "reference"
---

# SynAPS Compliance and Trust Matrix 2026-04

> **Terms and confidence labels are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: framework-alignment matrix for trust, on-prem deployment, and pre-compliance positioning

## Purpose

This matrix does not claim certification.

It translates official framework implications into an honest view of what SynAPS can say today, what is only preparatory, and what remains open.

## Official Sources Used

1. NIST AI Risk Management Framework 1.0
2. NIST SP 800-82 Rev. 3, Guide to Operational Technology Security
3. European Commission AI Act overview for Regulation (EU) 2024/1689
4. Google OR-Tools job shop guidance for deterministic scheduling foundations

## Matrix

| Dimension | Official implication | Current SynAPS posture | Current status | Upgrade condition |
| --- | --- | --- | --- | --- |
| Deterministic scheduling foundation | OR-Tools job shop guidance centers precedence, no-overlap, task completion, and makespan minimization as the core scheduling logic | SynAPS keeps deterministic scheduling and CP-SAT-style exact framing as the planning backbone | PARTIAL but credible | broader benchmark and industrial-sized runtime evidence |
| AI risk management posture | NIST AI RMF is voluntary but expects trustworthiness considerations in design, development, use, and evaluation | investor docs and architecture story keep AI advisory and bounded rather than autonomous | PREPARATORY | operational risk processes, model monitoring, and evidence of use |
| Human oversight | AI Act high-risk systems require appropriate human oversight | SynAPS explicitly frames AI as advisory and planner-facing | PREPARATORY-STRONG | runtime oversight controls and operator workflow evidence |
| Traceability and documentation | AI Act high-risk systems require detailed documentation and logging for traceability | SynAPS now has strong documentation, verification reports, and claim boundaries, but not audited runtime traceability | PARTIAL | production trace logs, retained event history, and deployment documentation |
| Dataset quality and risk mitigation | AI Act high-risk systems require adequate risk controls and high-quality datasets | no deployer-grade data governance evidence exists yet | OPEN | data lineage, dataset governance, and documented validation policies |
| Robustness, cybersecurity, and accuracy | AI Act high-risk systems require robustness, cybersecurity, and accuracy; OT guidance emphasizes operational safety | internal tests and documentation exist, but no audited cybersecurity or field reliability evidence exists | OPEN | security control mapping, incident handling, and audited resilience evidence |
| OT performance, reliability, and safety | NIST SP 800-82 stresses that OT security must preserve performance, reliability, and safety | SynAPS is positioned as on-prem or perimeter-controlled by default for critical sites | PREPARATORY | deployment-grade architecture, degraded-mode validation, and field evidence |
| Transparency to users and deployers | AI Act transparency rules require clear disclosure when needed to preserve trust | investor and technical docs already disclose advisory AI boundaries and current proof limits | PARTIAL-STRONG | runtime user-facing disclosure and deployment labeling rules |
| Post-market monitoring and incident reporting | AI Act high-risk systems require post-market monitoring and serious incident reporting | no such operating evidence exists because there is no current market deployment claim | OPEN | pilot and deployment governance program |
| GPAI obligations | EU rules on GPAI emphasize transparency and systemic-risk management for providers of GPAI models | SynAPS is not positioning itself as a GPAI provider; it positions local or bounded LLMs as advisory subcomponents | NOT THE CORE CLAIM | only becomes material if SynAPS starts shipping its own GPAI provider role |

## What This Matrix Does Not Justify

The existence of a framework-alignment matrix does **not** justify statements such as:

1. "AI Act compliant";
2. "NIST compliant";
3. "regulator-ready";
4. "certified for industrial deployment".

What it does justify is a narrower statement:

SynAPS is being framed in a way that is more compatible with trustworthy and bounded industrial AI expectations than an autonomy-first or black-box positioning would be.

## Investor Interpretation

For investors, the matrix supports three useful conclusions:

1. the team understands the difference between framework alignment and certification;
2. the current product thesis is compatible with human oversight and deterministic fallback expectations;
3. the remaining gaps are operational evidence gaps, not merely writing gaps.

## Bottom Line

SynAPS currently has a **trust-aware preparatory posture**, not a compliance-ready posture.

That is the academically correct and investor-safe statement for April 2026.