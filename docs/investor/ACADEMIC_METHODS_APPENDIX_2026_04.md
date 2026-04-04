---
title: "SynAPS Academic Methods Appendix 2026-04"
status: "active"
version: "1.1.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, methods, academic, diligence, reproducibility]
mode: "explanation"
---

# SynAPS Academic Methods Appendix 2026-04

> **Terms, confidence labels (C1 / C2 / C3), and evidence tiers (E1–E7) are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: methodological appendix for the SynAPS investor and diligence package

## 1. Purpose

This appendix explains how the current SynAPS investor packet was constructed.

Its goal is to make the package academically legible, falsifiable, and reproducible rather than merely persuasive.

## 2. Research Questions

The current package tries to answer five bounded questions:

1. Is the SynAPS product thesis technically coherent?
2. Is the current public GitHub presentation trustworthy and inspectable?
3. What evidence exists today in the current SynAPS codebase?
4. What can be claimed now versus later?
5. Is there at least one source-backed initial market model rather than pure conjecture?

## 3. Evidence Hierarchy

| Tier | Evidence class | Examples used in the packet | Intended use |
| --- | --- | --- | --- |
| E1 | Official standards and public frameworks | NIST AI RMF, NIST SP 800-82, EU AI Act summary | trust, risk, and compliance framing |
| E2 | Official statistics | World Bank manufacturing value-added, U.S. Census CBP establishment counts | market-model denominators |
| E3 | Official technical documentation | Google OR-Tools job shop guidance | deterministic scheduling baseline |
| E4 | Public vendor positioning | Asprova, DELMIA Ortems, DELMIA Quintiq | competition boundary and buyer baseline |
| E5 | Public open-source comparables | Supabase, PostHog, Airbyte, Cal.com | GitHub presentation and diligence patterns |
| E6 | Internal repository verification | docs closure, architecture quick tests, quick test rail, SynAPS pytest and benchmark runs | current technical evidence |
| E7 | Roadmap or strategy hypotheses | pricing, wedge assumptions, pilot thresholds | clearly labeled C1 assumptions only |

Rule:

Higher-tier evidence may constrain lower-tier claims.

Lower-tier evidence may not overrule higher-tier evidence.

## 4. Claim Confidence Model

The package uses the SynAPS claim-confidence convention:

1. **C1 Hypothesis**: strategic or commercial assumption without sufficient external or runtime evidence;
2. **C2 Internal Evidence**: supported by repository artifacts, tests, logs, or bounded technical proof;
3. **C3 External Validation**: supported by pilots, third-party benchmarks, audited controls, or official external sources.

Important distinction:

An official denominator combined with internal pricing assumptions yields a hybrid state, not pure C3. That is why the current market model remains partially C2 even though its raw inputs are official.

## 5. Methods By Surface

### 5.1 Product-thesis method

The product thesis was evaluated by triangulating:

1. SynAPS architecture and research docs;
2. Google OR-Tools job shop documentation as the canonical scheduling reference;
3. public incumbent positioning from Asprova, DELMIA Ortems, and DELMIA Quintiq.

Decision rule:

If a claim exceeded the scope shown by current SynAPS evidence or contradicted the scope visible in incumbent baselines, it was downgraded or excluded.

### 5.2 Market-model method

The initial market model uses a hybrid top-down plus bottom-up method.

Top-down:

`manufacturing macro context <- World Bank NV.IND.MANF.CD`

Bottom-up:

`operational denominator <- U.S. Census CBP establishments, NAICS 31-33`

Commercial projection:

`TAM = official site denominator × ACV`

`SAM = official site denominator × wedge fraction × ACV`

`SOM = SAM site count × early penetration rate × ACV`

Constraint:

Only the denominator is official. ACV, wedge fraction, and early penetration remain internal hypotheses until commercial evidence exists.

### 5.3 Verification method

The package distinguishes between project-level verification and direct SynAPS technical verification.

Standalone verification used:

1. `python -m pytest`
2. `ruff check synaps tests benchmark --select F,E9`
3. `python -m build`
4. `twine check dist/*`
5. `python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED --compare`

### 5.4 GitHub-comparables method

The comparable-repo study did not treat public READMEs as proof of business success.

They were used only for:

1. repository routing patterns;
2. support and trust-surface design;
3. open-core disclosure patterns;
4. docs and roadmap visibility;
5. self-host versus managed-boundary communication.

## 6. Threats To Validity

### 6.1 Market-model threats

1. U.S. manufacturing establishments are only one geography;
2. the `100+ employees` threshold is an operational targeting filter, not a universal truth;
3. ACV assumptions are not yet field-validated;
4. market size is not the same thing as reachable commercial demand.

### 6.2 Benchmark threats

1. the currently cited live runtime result is a smoke benchmark, not a broad benchmark family;
2. tiny-instance results cannot justify general superiority claims;
3. hardware-normalized repeated-run evidence is still pending.

### 6.3 Compliance threats

1. framework alignment is not the same as compliance certification;
2. documentation and intent do not substitute for audited controls;
3. AI Act high-risk obligations depend on concrete use-case classification and deployment context.

### 6.4 Presentation threats

1. GitHub presentation quality can increase trust, but it cannot replace pilots or external validation;
2. a clean diligence packet can still overstate readiness if claim boundaries are not enforced.

## 7. Reproducibility Summary

The current packet is reproducible in three layers:

1. public-source layer: official docs, standards, statistics, and public repositories;
2. repository-verification layer: docs closure and previously refreshed repo verification results;
3. SynAPS technical layer: fresh pytest and smoke benchmark commands recorded in the technical verification report.

## 8. Practical Use

Use this appendix when:

1. an investor or reviewer asks how the package was constructed;
2. someone challenges the market model assumptions;
3. someone mistakes preparatory compliance work for certification;
4. the team needs to upgrade a claim from C1 to C2 or C3.

## 9. Bottom Line

The SynAPS investor pack is strongest when treated as a structured research-and-diligence artifact.

Its value comes from explicit evidence hierarchy, explicit uncertainty, and reproducible technical evidence.