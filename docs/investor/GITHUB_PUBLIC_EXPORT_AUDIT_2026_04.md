---
title: "SynAPS GitHub Public Export Audit 2026-04"
status: "active"
version: "1.1.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, github, audit, publication, investor]
mode: "evidence"
---

# SynAPS GitHub Public Export Audit 2026-04

> **Terms are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: standalone SynAPS publication readiness for external GitHub review and investor-facing technical diligence

## Goal

Convert the current SynAPS documentation and repository structure into a conservative public GitHub surface that is legible to external reviewers without widening product claims.

## External Guidance Used

1. GitHub Docs, README guidance: repository README should explain what the project does, why it is useful, how to get started, where to get help, and who maintains it.
2. GitHub Docs, community profile guidance: recommended community-health files and valid issue template metadata are visible in the public community checklist.
3. GitHub Docs, security policy guidance: `SECURITY.md` should state supported versions and vulnerability reporting instructions.
4. GitHub Docs, private vulnerability reporting guidance: public repositories can expose a private disclosure button when the setting is enabled.
5. GitHub Docs, repository topics guidance: topics should be lowercase, hyphenated, and intentionally curated.
6. GitHub Docs, CODEOWNERS guidance: owners must be valid users or teams with write access.
7. GitHub Docs, artifact attestation guidance: provenance and SBOM attestations should stay verifiable in Actions.
8. GitHub Docs, Dependabot guidance: version updates should be configured in `.github/dependabot.yml`.
9. OpenSSF Scorecard as a public trust benchmark for repository hygiene.
10. Citation File Format guidance: `CITATION.cff` is rendered by GitHub and provides machine-readable citation metadata.

## Repo-Local Surfaces Used

1. `README.md`, `SUPPORT.md`, `SECURITY.md`, `CONTRIBUTING.md`, and `CITATION.cff` as the public trust boundary.
2. `docs/investor/` as the active SynAPS investor evidence pack.
3. `docs/README.md` and local architecture docs as the current technical entrypoint.
4. `.github/workflows/**` and `pyproject.toml` as the publication and supply-chain surfaces.

## Verified Findings

| Surface | Status before this audit | Action | Result |
| --- | --- | --- | --- |
| Root README | present, but generic for external investors | add explicit public/investor routing | improved |
| `CONTRIBUTING.md` | already present | keep and route to it | retained |
| `LICENSE` | already present | keep and route to it | retained |
| `SECURITY.md` | missing | add root security policy | closed |
| `CODE_OF_CONDUCT.md` | missing | add root conduct policy | closed |
| `SUPPORT.md` | missing | add root support routing | closed |
| `CITATION.cff` | missing | add root citation metadata | closed |
| `CONTRIBUTING.md` | present but too internal and oversized for public entry use | rewrite into a concise public router | closed |
| issue templates | present but internal and not public-review ready | replace with bug, feature, and safe security templates plus chooser config | closed |
| PR template | present but narrow and internal to one technical slice | rewrite into generic public PR template | closed |
| SynAPS investor index | missing | add `docs/investor/README.md` | closed |
| Publication audit artifact | missing | add this file | closed |
| `Dependabot` config | missing | add `.github/dependabot.yml` for `npm`, `github-actions`, and `docker` | closed |
| GitHub settings baseline | missing | add `docs/quality/PUBLIC_GITHUB_SETTINGS_BASELINE_2026_04.md` | closed |
| Export manifest boundary | too broad for a standalone public snapshot | tighten to self-contained public surfaces | closed |
| Root public routers | linked to excluded startup or agent-control-plane surfaces | rewrite into public-safe routers | closed |
| SynAPS temporary merge task | obsolete one-shot residue | remove from `.vscode/tasks.json` | closed |
| SynAPS temporary merge script | obsolete one-shot residue | delete `scripts/temp-merge-synaps.ps1` | closed |

## Cable-Donor Cleanup Status

Targeted searches for the following cable-donor markers were run against the active SynAPS publication surfaces:

1. `Москабельмет`
2. `МОСИТЛАБ`
3. `CableBench`
4. `Cable Justice`
5. `кабельный завод`
6. `cable production`
7. `cable factory`

Observed result:

1. the core SynAPS code and research surfaces returned no matches;
2. inside `docs/investor/`, the only matches are the self-referential marker list in this audit file;
3. active investor narrative files such as `README.md`, `PITCH_MEMO.md`, `EVIDENCE_BASE.md`, and `MARKET_COMPETITION_REPORT_2026_04.md` do not contain those donor markers.

Additional verification showed that the current legacy archive surface is empty.

Verdict: active SynAPS investor-facing surfaces are already industry-agnostic. The required cleanup was removal of obsolete migration residue rather than content rewrite.

## Dependency Freshness Audit

### SynAPS Python environment

`pip list --outdated --format=json` in the configured SynAPS environment reports `2` outdated packages:

1. `protobuf` `6.33.6 -> 7.34.1`
2. `pydantic_core` `2.41.5 -> 2.45.0`

### Freshness verdict

The repository is **not** yet on the latest software versions across the board.

This publication-hardening task intentionally records the freshness gap instead of applying mass upgrades. Even the current Python gaps should be handled through a focused compatibility pass rather than folded into publication work.

## Verification Run

Fresh standalone verification executed during the publication-hardening pass produced these results:

1. Python `pytest` -> passed for the current standalone SynAPS test suite;
2. `ruff check synaps tests benchmark --select F,E9` -> passed;
3. `python -m build` -> passed;
4. `twine check dist/*` -> passed;
5. benchmark smoke run on `benchmark/instances/tiny_3x3.json` -> passed;
6. optional `docs/investor/` subtree removal rehearsal -> passed for tests, build, benchmark, and export dry-run.

These checks confirm that the publication hardening surfaces are not only structurally present, but also validated against the current standalone repository state.

## Community Health Hardening

Second-pass hardening used current GitHub guidance for issue templates, template chooser config, and pull request templates.

Applied outcomes:

1. public bug, feature, and security issue templates now replace internal-only templates;
2. the issue chooser now disables blank issues for non-maintainers, while the security template itself redirects sensitive reports to `SECURITY.md`;
3. the PR template now asks for summary, rationale, validation, and claim-boundary review instead of a narrow internal DI-only checklist;
4. `CONTRIBUTING.md` now acts as a concise public router instead of mixing contribution workflow with deep internal operational detail.

## Public Export Boundary Hardening

The publication path now uses a more conservative curated boundary.

Applied outcomes:

1. internal AI control-plane routers and startup evidence packs stay outside the default engineering export;
2. root public routers were rewritten so they no longer point at excluded startup or agent-control-plane files;
3. the curated snapshot now includes `Dependabot`, dependency-review configuration, and the public GitHub settings baseline;
4. local build artifacts and unrelated parent-workspace files stay outside the default engineering export.

## CODEOWNERS Decision

Current GitHub documentation requires CODEOWNERS entries to point to valid users or teams with write access.

This repository does not currently expose a verified public maintainer handle or team slug in the workspace artifacts, so a `CODEOWNERS` file was intentionally **not** added in this pass. Adding one without validated owners would create broken review routing and false governance signals.

## Manual GitHub Settings Still Required

The repository files now encode the trust baseline that can live in Git, but several platform settings still need to be enabled in GitHub after publication.

Required manual follow-through:

1. enable dependency graph, Dependabot alerts, and Dependabot security updates;
2. enable private vulnerability reporting and security-alert notifications for maintainers;
3. enable secret scanning and push protection for the public repository;
4. require dependency review and the main CI checks in rulesets or branch protection;
5. add repository topics and final public metadata;
6. defer `CODEOWNERS` until the final public owners are verified.

## Current Publication Verdict

`PUBLIC_GITHUB_READY_WITH_BOUNDARIES`

Meaning:

1. the repository is now structurally fit for conservative public GitHub review;
2. the SynAPS investor pack is explicitly navigable;
3. trust and governance surfaces are visible at the repository root;
4. evidence boundaries remain explicit rather than implied.

## What This Verdict Does Not Mean

1. no claim of launch readiness;
2. no claim of regulator-ready status;
3. no claim of pilot-proven ROI;
4. no claim that dependency freshness is fully closed.

## Remaining Gaps

1. customer-side pilot evidence beyond the protocol design;
2. broader benchmark packet with publishable head-to-head comparisons;
3. dedicated dependency-upgrade program for the current codebase;
4. public repository settings still need to be enabled in GitHub after the first push;
5. stronger ownership routing once verified public maintainers are declared;
6. Python supply-chain coverage for the current SynAPS codebase.