---
title: "SynAPS Hyperdeep Audit Report 2026-04"
status: "active"
version: "2.1.0"
last_updated: "2026-04-05"
date: "2026-04-05"
tags: [synaps, investor, audit, fact-check, evidence]
mode: "evidence"
---

# SynAPS Hyperdeep Audit Report 2026-04

Date: 2026-04-05
Status: active
Scope: readable deep-fact-check summary for the April 2026 SynAPS investor and research surfaces

For the preserved raw historical snapshot that previously occupied this path, see [../../archive/investor-2026-04-slimming/HYPERDEEP_AUDIT_REPORT_2026_04.md](../../archive/investor-2026-04-slimming/HYPERDEEP_AUDIT_REPORT_2026_04.md).

## What This File Is

This file is not the primary entry point for first-pass diligence.

It is the optional deep-evidence layer for readers who want the April 2026 fact-check result without the mis-encoded historical wording that used to sit at this path.

Use this document when you need the tightest summary of:

1. what the deep audit actually checked;
2. what high-severity corrections were required;
3. what the current repository truth still supports today;
4. what remains open even after the audit.

## Executive Outcome

| Metric | Current reading |
| --- | --- |
| total claims and checks reviewed across the audit passes | 63 |
| fabricated or non-verifiable literature claims found and corrected | 3 |
| material data or metadata corrections applied | 9 |
| literature-reference coverage reached by the audit | 26/48, or about 54% |
| current aligned solver-test status | 120/120 tests passing |
| current aligned benchmark evidence | verified smoke result on `tiny_3x3` only |

The current investor-safe interpretation is unchanged:

- SynAPS supports **C2 internal evidence** for a deterministic scheduling-kernel thesis;
- it does **not** yet support C3 claims for pilot ROI, field deployment maturity, or broad benchmark superiority;
- the deep audit strengthened trust mainly by removing fabricated or overstated claims, not by closing the external proof gap.

## Highest-Severity Corrections Confirmed By The Audit

### 1. GLM-5.1 was not a valid product/version claim

The earlier pack used `GLM-5.1` language that was not defensible from public sources.

The corrected safe wording is:

- `GLM-5` when referring to the cloud/API model line;
- `GLM-4-32B` when referring to an on-prem candidate.

### 2. Three literature references were treated as fabricated or non-verifiable in their prior form

The audit flagged and replaced three high-risk references in the literature layer:

1. the old GLM series citation block;
2. the prior ATCS journal/reference wording;
3. the prior HGAT-FJSP citation wording.

The active investor and research surfaces now route through corrected, verifiable references instead of repeating the earlier wording.

### 3. Hardware capability rows were overstated or mixed across generations

The audit corrected or bounded claims around:

1. D-Wave Advantage2 qubit counts;
2. IBM gate-model processor rows;
3. pgvector/HNSW wording that previously blurred extension capability with native PostgreSQL GPU semantics.

## What The Audit Confirms Today

The deep audit does confirm the following narrower technical story:

1. the repository contains a real deterministic solver portfolio rather than presentation-only architecture;
2. the repository exposes a real schema and contract layer;
3. the repository includes reproducible verification surfaces and benchmark commands;
4. the current active investor docs can be constrained to current proof versus target architecture with explicit evidence boundaries.

## What The Audit Does Not Close

Even after the fact-check pass, the following remain open:

1. pilot-backed ROI and before/after factory metrics;
2. broad benchmark families with repeated runs across size tiers;
3. product-runtime maturity comparable to a deployed vertical APS suite;
4. regulator-ready or audited industrial deployment controls;
5. independently verified superiority over named incumbents.

## Current Benchmark Boundary

The active benchmark wording was tightened after this audit stream.

What the current repository truth supports safely:

- on `tiny_3x3`, `GREED` records `106.67` minutes;
- on the same instance, `CPSAT-10` records `82.0` minutes;
- that is a makespan improvement of approximately `23.1%`.

What the current repository truth does not yet support safely as an active default claim:

- broad benchmark leadership;
- publication-grade medium/large instance superiority;
- investor-facing percentage claims that generalize beyond the verified smoke-instance route.

For the current benchmark boundary, use [BENCHMARK_EVIDENCE_PACKET_2026_04.md](BENCHMARK_EVIDENCE_PACKET_2026_04.md) together with [TECHNICAL_VERIFICATION_REPORT_2026_04.md](TECHNICAL_VERIFICATION_REPORT_2026_04.md).

## Literature-Check Boundary

The deep audit raised reference quality materially, but it did not produce full exhaustiveness.

The practical interpretation is:

1. the checked subset is good enough to remove the most dangerous fabricated or overconfident claims;
2. the remaining unchecked references are not automatically invalid, but they should not be treated as zero-risk;
3. the strongest investor path should still rely on the claim register and technical verification surfaces before relying on deep research framing.

## Recommended Reading Order From Here

If you reached this file and want to continue from the safest current evidence stack, read next:

1. [CLAIM_EVIDENCE_REGISTER_2026_04.md](CLAIM_EVIDENCE_REGISTER_2026_04.md)
2. [TECHNICAL_VERIFICATION_REPORT_2026_04.md](TECHNICAL_VERIFICATION_REPORT_2026_04.md)
3. [VERIFICATION_COVERAGE_AUDIT_2026_04.md](VERIFICATION_COVERAGE_AUDIT_2026_04.md)
4. [MATHEMATICAL_AND_RESEARCH_FACT_CHECK_2026_04.md](MATHEMATICAL_AND_RESEARCH_FACT_CHECK_2026_04.md)

## Bottom Line

The deep audit made the SynAPS documentation set more defensible by removing fabrication, correcting metadata, and tightening the claim boundary.

It did not convert the project into a field-proven APS product.

That is exactly why this file now exists in a shorter, cleaner form: the value of the audit is disciplined truth, not inflated confidence.