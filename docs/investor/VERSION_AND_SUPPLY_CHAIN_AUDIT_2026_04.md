---
title: "SynAPS Version and Supply-Chain Audit 2026-04"
status: "active"
version: "1.2.0"
last_updated: "2026-04-04"
date: "2026-04-04"
tags: [synaps, versions, supply-chain, sbom, provenance, investor]
mode: "evidence"
---

# SynAPS Version and Supply-Chain Audit 2026-04

> **Terms are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Date: 2026-04-04
Status: active
Scope: April 2026 audit of runtime versions, dependency freshness, SBOM posture, provenance signals, and release-trust depth relevant to investor-facing technical diligence

## Goal

This document answers a narrow but increasingly important diligence question:

How trustworthy is the current SynAPS software supply chain relative to April 2026 expectations?

It does not claim full closure.

It identifies what already exists, what is outdated, and what is still missing.

## External Guidance Used

1. GitHub Docs, GitHub security features;
2. GitHub Docs, dependency graph and SPDX SBOM export guidance;
3. GitHub Docs, dependency review guidance;
4. OpenSSF Scorecard;
5. SLSA build-level guidance;
6. official release/version feeds from PyPI and npm registry where relevant.

## Repo-Local Evidence Used

1. `pyproject.toml`;
2. `control-plane/package.json`;
3. `.github/workflows/ci.yml`;
4. `.github/workflows/dependency-review.yml`;
5. `.github/workflows/codeql.yml`;
6. `.github/workflows/scorecards.yml`;
7. `.github/workflows/release.yml`;
8. `.github/dependabot.yml`;
9. current standalone verification notes in `TECHNICAL_VERIFICATION_REPORT_2026_04.md`.

## Current Strengths

The standalone SynAPS repository already has more supply-chain and release-trust structure than a typical early technical startup repository.

Verified positives:

1. Python-first CI runs lint, tests, and distribution builds on hosted GitHub Actions runners;
2. dependency review is enforced on dependency-relevant pull requests via `actions/dependency-review-action@v4.9.0`;
3. CodeQL analysis is present for Python;
4. OSSF Scorecards analysis is present;
5. release workflow builds distributions and supports trusted publishing to TestPyPI and PyPI;
6. Dependabot is configured for `pip` and `github-actions` ecosystems.

This means SynAPS is not starting from zero on release trust.

## Python And Runtime Baseline

| Surface | Repo state | Official April 2026 reference | Audit view |
| --- | --- | --- | --- |
| Python declaration | `>=3.12` | current verified local runtime `3.13.7` | compatible baseline, but not a reproducibility-grade exact pin |
| CI test matrix | `3.12`, `3.13` | current supported repo matrix | healthy compatibility signal |
| `ortools` | `>=9.10` | newer upstream line exists | lower-bound declaration, not an exact tested pin |
| `highspy` | `>=1.8` | newer upstream line exists | lower-bound declaration, not an exact tested pin |
| `pydantic` | `>=2.9` | newer upstream line exists | reasonable baseline, but still not exact pinning |
| `numpy` | `>=2.1` | newer upstream line exists | acceptable lower bound, not reproducibility-grade locking |

The key interpretation is simple: SynAPS currently declares compatibility floors.

That is enough for an alpha engineering surface, but it is weaker than lockfile- or constraints-based reproducibility for publication-grade benchmarking.

## Optional TypeScript Sidecar Baseline

The TypeScript control-plane is a real but intentionally thin sidecar, not the main supply-chain surface of the repository.

| Surface | Repo state | Audit view |
| --- | --- | --- |
| `fastify` | `^5.8.2` | modern dependency for the minimal BFF |
| `ajv` | `^8.17.1` | current JSON schema validation baseline |
| `typescript` | `^5.9.3` | current development baseline |
| npm update automation | no dedicated npm stanza in `.github/dependabot.yml` | open freshness gap for the optional sidecar |

## Current Freshness Interpretation

This audit deliberately avoids turning lower bounds into false "current version" claims.

What can be said safely:

1. the Python project is version-bounded and CI-tested across two Python versions;
2. the optional TypeScript sidecar has a modern package surface;
3. the repo is not yet managed through exact pinned constraints or lockfiles for reproducible release builds;
4. npm update automation does not yet cover the optional TypeScript sidecar.

## Supply-Chain Trust Matrix

| Dimension | Current state | Audit verdict |
| --- | --- | --- |
| Hosted CI for lint, tests, and builds | present in `.github/workflows/ci.yml` | STRONG PARTIAL |
| Dependency review on pull requests | present in `.github/workflows/dependency-review.yml` | CLOSED |
| CodeQL security analysis | present in `.github/workflows/codeql.yml` | STRONG PARTIAL |
| OSSF Scorecards analysis | present in `.github/workflows/scorecards.yml` | PARTIAL-STRONG |
| Trusted publishing release workflow | present in `.github/workflows/release.yml` | PARTIAL-STRONG |
| GitHub dependency graph / SBOM export baseline | available as a GitHub-side capability once the public repo is configured | PARTIAL |
| In-repo SBOM generation | not present | OPEN GAP |
| Artifact attestations / provenance emission | not present | OPEN GAP |
| Attestation verification gate | not present | OPEN GAP |
| Python vulnerability scanning such as `pip-audit` | not present | OPEN GAP |
| Exact runtime pinning or lockfile-grade reproducibility | not present | OPEN GAP |
| Dependabot coverage for the optional TypeScript sidecar | not present | OPEN GAP |

## SLSA And OpenSSF Interpretation

The current repository should **not** claim a concrete SLSA build level today.

In practical terms:

1. GitHub-hosted CI/CD, dependency review, CodeQL, and Scorecards are real trust signals;
2. trusted publishing to PyPI improves release hygiene;
3. but SLSA Build L1 and above require provenance to exist, and the current workflows do not emit provenance or attestations;
4. therefore the correct framing is "hosted CI/CD with meaningful security signals," not "SLSA-attested release pipeline."

From an OpenSSF-style repository health perspective, the strongest visible positives are:

1. public trust files exist;
2. security and supply-chain thinking are explicit;
3. workflows use pinned action SHAs in many critical places;
4. dependency review, CodeQL, and Scorecards are already present.

The strongest negatives are:

1. no in-repo SBOM or provenance emission exists yet;
2. no Python vulnerability scanning gate is present;
3. exact release reproducibility is not yet modeled through constraints or lockfiles;
4. the optional TypeScript sidecar is outside current Dependabot coverage.

## Highest-Priority Remediation Sequence

### Priority 1

1. add Python vulnerability scanning such as `pip-audit` or equivalent to hosted CI;
2. add an npm stanza for `control-plane/` to `.github/dependabot.yml` if the TypeScript sidecar remains active;
3. decide whether benchmark-grade reproducibility requires a constraints file or lockfile strategy.

### Priority 2

1. add SBOM generation for the Python package and, if retained, the optional TypeScript sidecar;
2. expose GitHub dependency graph and SPDX SBOM export as part of the public release checklist;
3. document signed-release expectations for tags and release governance.

### Priority 3

1. add provenance and artifact attestations if the eventual public repository tier and release path justify them;
2. add a verification gate for any future attestation or provenance layer;
3. add a small release-trust appendix to the investor pack once the first two priority layers are actually closed.

## Investor Interpretation

The correct investor-safe reading is:

1. this repository already shows uncommon maturity for an early technical product thesis because hosted CI/CD, dependency review, CodeQL, Scorecards, and trusted publishing are present;
2. the supply-chain story is materially better than a README-only startup repository;
3. it is still incomplete enough that the team should frame it as an active hardening program, not a closed trust problem.

## Bottom Line

SynAPS currently has a **credible but incomplete** version and supply-chain posture.

It is strong enough to signal engineering seriousness.

It is not yet strong enough to support claims of release-trust closure, SBOM/provenance maturity, or fully investor-grade software supply-chain hardening.