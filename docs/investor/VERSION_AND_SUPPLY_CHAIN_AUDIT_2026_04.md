---
title: "SynAPS Version and Supply-Chain Audit 2026-04"
status: "active"
version: "1.1.0"
last_updated: "2026-04-04"
date: "2026-04-04"
tags: [synaps, versions, supply-chain, sbom, provenance, investor]
mode: "evidence"
---

# SynAPS Version and Supply-Chain Audit 2026-04

> **Terms are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: April 2026 audit of runtime versions, dependency freshness, SBOM posture, provenance signals, and release-trust depth relevant to investor-facing technical diligence

## Goal

This document answers a narrow but increasingly important diligence question:

How trustworthy is the current SynAPS software supply chain relative to April 2026 expectations?

It does not claim full closure.

It identifies what already exists, what is outdated, and what is still missing.

## External Guidance Used

1. GitHub Docs, GitHub security features;
2. GitHub Docs, artifact attestations and SBOM attestation guidance;
3. GitHub Docs, dependency review guidance;
4. OpenSSF Scorecard;
5. SLSA build-level guidance;
6. official release/version feeds from Node.js, npm registry, and PyPI.

## Repo-Local Evidence Used

1. `package.json`;
2. `.github/workflows/ci.yml`;
3. `.github/workflows/cd.yml`;
4. current Python environment manifest;
5. `_npm_outdated_2026_04_02.json`;
6. `_synaps_pip_outdated_2026_04_02.json`;
7. `_official_versions_npm_2026_04_02.json`;
8. `_official_versions_core_2026_04_02.json`.

## Current Strengths

The repo already has more supply-chain and release-trust structure than a typical early technical startup repository.

Verified positives:

1. CycloneDX SBOM generation is present in CI and CD;
2. release-time build provenance attestation is present in CD via `actions/attest@v4`;
3. release-time SBOM attestation is present in CD via `actions/attest@v4`;
4. container-image vulnerability scanning is present via Trivy in CI and CD;
5. a release supply-chain receipt is generated and uploaded as an artifact;
6. a dedicated verification script exists: `npm run verify:release:supply-chain`.

This means SynAPS is not starting from zero on release trust.

## JavaScript And Runtime Version Matrix

| Surface | Repo state | Official April 2026 reference | Audit view |
| --- | --- | --- | --- |
| Node runtime in CI | `20.x` | `v20.20.2` latest Node 20 LTS line | stable line chosen, but not pinned to exact patch |
| Node runtime in CD | `20` | `v20.20.2` latest Node 20 LTS line | same gap, even looser pinning |
| `@modelcontextprotocol/sdk` | `1.27.1` | `1.29.0` | modestly stale |
| `@aws-sdk/client-s3` | `3.980.0` | `3.1022.0` | stale but not structurally alarming |
| `@opentelemetry/sdk-node` | `0.57.2` | `0.214.0` | materially stale and one of the most significant gaps |
| `openai` | `4.28.0` | `6.33.0` | major-version lag, likely requires migration campaign |
| `eslint` | `9.39.2` | `10.1.0` | moderate gap |
| `express` | manifest `^4.18.2`, installed tree `4.22.1` | `5.2.1` | major upgrade exists, but not automatically a defect because Express 5 migration can be non-trivial |

## SynAPS Python And OR Version Matrix

Two different facts need to be separated.

1. the current Python environment manifest mostly declares lower bounds, not exact pinned versions.
2. the currently configured SynAPS environment shows only two directly observed outdated Python packages in the local outdated report.

### Declared lower bounds versus official releases

| Surface | Declared SynAPS bound | Official April 2026 reference | Audit view |
| --- | --- | --- | --- |
| Python | `>=3.12` | current verified local runtime `3.13.7`; latest upstream line beyond that | acceptable minimum, not reproducibility-grade pinning |
| `ortools` | `>=9.10` | `9.15.6755` | lower bound lags current line and does not prove tested exact version |
| `highspy` | `>=1.8` | `1.13.1` | lower bound stale relative to current upstream |
| `torch` | `>=2.6` | `2.11.0` | lower bound stale relative to current upstream |
| `torchrl` | `>=0.6` | `0.11.1` | lower bound stale relative to current upstream |

### Currently observed Python outdated packages in the local SynAPS environment

| Package | Current | Latest | Audit view |
| --- | --- | --- | --- |
| `protobuf` | `6.33.6` | `7.34.1` | major-version lag |
| `pydantic_core` | `2.41.5` | `2.45.0` | moderate freshness gap |

## Supply-Chain Trust Matrix

| Dimension | Current state | Audit verdict |
| --- | --- | --- |
| CycloneDX SBOM generation | present in CI and CD | STRONG PARTIAL |
| SBOM attestation | present in CD | STRONG PARTIAL |
| Build provenance attestation | present in CD | STRONG PARTIAL |
| Trivy container scan | present in CI and CD | PARTIAL-STRONG |
| Release receipt | present in CD | PARTIAL |
| Attestation verification gate | receipt documents `gh attestation verify`, but workflow does not enforce it as a blocking step | OPEN GAP |
| Dependency review on pull requests | present (SHA-pinned v4.9.0, 2026-04-04) | CLOSED |
| Python SBOM and Python supply-chain CI for the current SynAPS codebase | not present | OPEN GAP |
| Exact runtime pinning in GitHub workflows | not present | OPEN GAP |
| Signed commits and signed tags evidence | not visible in repo governance surfaces | OPEN GAP |

## SLSA And OpenSSF Interpretation

The current repository is best described as having a **partial hosted-build provenance posture**.

In practical terms:

1. CD already looks closer to a partial SLSA Build L2-style posture than to an ad hoc release process because provenance and SBOM attestations are emitted by a hosted platform;
2. however, verification is not yet enforced in the workflow itself, runtime/tool versions are not pinned tightly enough for strong reproducibility, and Python coverage is incomplete;
3. therefore the repo should not currently present itself as having a mature or closed supply-chain posture.

From an OpenSSF-style repository health perspective, the strongest visible positives are:

1. public trust files exist;
2. security and supply-chain thinking are explicit;
3. workflows use pinned action SHAs in many critical places;
4. SBOM and attestation mechanics are already present.

The strongest negatives are:

1. stale critical libraries remain;
2. ~~PR-time dependency review is missing~~ — **CLOSED** (SHA-pinned `dependency-review-action@v4.9.0` on 2026-04-04);
3. exact release verification is not yet a gate;
4. SynAPS Python code is not covered by the same supply-chain depth as the rest of the codebase.

## Highest-Priority Remediation Sequence

### Priority 1

1. pin GitHub workflow Node versions to an exact maintained Node 20 patch instead of `20.x` and `20`;
2. ~~add GitHub dependency-review action to pull requests~~ — **CLOSED** (SHA-pinned `v4.9.0` on 2026-04-04);
3. add a blocking attestation-verification step in CD using `gh attestation verify`.

### Priority 2

1. add Python CI for the current SynAPS codebase with at least `pytest`, `pip-audit` or equivalent, and Python SBOM generation;
2. create a focused dependency freshness campaign for the highest-risk stale libraries, especially OpenTelemetry and the OpenAI SDK;
3. document signed-release expectations for tags and release governance.

### Priority 3

1. move from loose lower bounds toward more reproducible Python environment constraints for publication-grade SynAPS benchmarking;
2. expose linked-artifacts or equivalent attestation-consumption guidance in the public release story;
3. add a small release-trust appendix to the investor pack once the first two priority layers are actually closed.

## Investor Interpretation

The correct investor-safe reading is:

1. this repository already shows uncommon maturity for an early technical product thesis because SBOMs, attestations, and supply-chain scripting are present;
2. the supply-chain story is materially better than a README-only startup repository;
3. it is still incomplete enough that the team should frame it as an active hardening program, not a closed trust problem.

## Bottom Line

SynAPS currently has a **credible but incomplete** version and supply-chain posture.

It is strong enough to signal engineering seriousness.

It is not yet strong enough to support claims of release-trust closure, dependency-fresh production hygiene, or fully investor-grade software supply-chain maturity.