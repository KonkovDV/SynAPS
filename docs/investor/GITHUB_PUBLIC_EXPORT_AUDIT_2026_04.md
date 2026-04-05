---
title: "SynAPS GitHub Public Export Audit 2026-04"
status: "active"
version: "1.3.0"
last_updated: "2026-04-05"
date: "2026-04-05"
tags: [synaps, github, audit, publication, investor]
mode: "evidence"
---

# SynAPS GitHub Public Export Audit 2026-04

> **Terms are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-04
Status: active
Scope: standalone SynAPS publication readiness for external GitHub review and investor-facing technical diligence

## Goal

Convert the current SynAPS documentation and repository structure into a conservative public GitHub surface that is legible to external reviewers without widening product claims.

## External Guidance Used

1. GitHub Docs, README guidance: repository README should explain what the project does, why it is useful, how to get started, where to get help, and who maintains it.
2. GitHub Docs, community profile guidance: recommended community-health files and valid issue template metadata are visible in the public community checklist.
3. GitHub Docs, security policy guidance: `SECURITY.md` should state supported versions and vulnerability reporting instructions.
4. GitHub Docs, private vulnerability reporting guidance: public repositories can expose a private disclosure button when the setting is enabled.
5. GitHub Docs, security features guidance: dependency graph, SPDX SBOM export, rulesets, secret scanning, and artifact attestations are GitHub-side capabilities with plan-dependent availability.
6. GitHub Docs, repository topics guidance: topics should be lowercase, hyphenated, and intentionally curated.
7. GitHub Docs, CODEOWNERS guidance: owners must be valid users or teams with write access.
8. GitHub Docs, Dependabot guidance: version updates should be configured in `.github/dependabot.yml`.
9. OpenSSF Scorecard as a public trust benchmark for repository hygiene.
10. Citation File Format guidance: `CITATION.cff` is rendered by GitHub and provides machine-readable citation metadata.
11. GitHub Docs, rulesets guidance: public repositories on GitHub Free can use rulesets and layer them with branch protection.

## External Analogs Reviewed

The following public repositories were reviewed as practical startup-grade comparison surfaces:

1. `supabase/supabase`
2. `PostHog/posthog`
3. `airbytehq/airbyte`
4. `calcom/cal.com`

These were used as analogs for visible GitHub presentation patterns, not as product or architecture templates.

## Repo-Local Surfaces Used

1. `README.md`, `SUPPORT.md`, `SECURITY.md`, `CONTRIBUTING.md`, and `CITATION.cff` as the public trust boundary.
2. `docs/investor/` as the active SynAPS investor evidence pack.
3. `docs/README.md` and local architecture docs as the current technical entrypoint.
4. `.github/workflows/**`, `.github/dependabot.yml`, issue templates, and `pyproject.toml` as the publication and supply-chain surfaces.

## Current Public Baseline

| Surface | Current state | Audit view |
| --- | --- | --- |
| Root README and Russian mirror | present and now bounded around current implementation | CLOSED |
| Public trust files (`LICENSE`, `SECURITY.md`, `SUPPORT.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CITATION.cff`) | present at repo root | CLOSED |
| Issue templates and PR template | present under `.github/ISSUE_TEMPLATE/` and `.github/PULL_REQUEST_TEMPLATE.md` | CLOSED |
| Dependabot config | present for `pip` and `github-actions` | PARTIAL |
| Review and trust workflows | CI, dependency review, CodeQL, Scorecards, and release workflows are present | CLOSED |
| Investor router | present as an optional diligence surface under `docs/investor/` | CLOSED |
| Public GitHub post-push checklist | present at `docs/PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md` | CLOSED |
| Conservative export boundary | public engineering entrypoints do not depend on parent workspace files | CLOSED |

## Observed Public State After Push

Direct review of the public `KonkovDV/SynAPS` repository on 2026-04-05 showed:

1. the repository is public and the default branch is `master`;
2. `README.md`, `README_RU.md`, `SUPPORT.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `CITATION.cff` are visible in the root tree;
3. `Security policy` renders correctly in the GitHub UI;
4. `SUPPORT.md` renders correctly in the GitHub UI;
5. the issue-template chooser is present, but anonymous viewers are redirected to sign-in before they can create an issue, which is normal GitHub behavior;
6. the About panel is still missing description, homepage, and topics;
7. no GitHub Releases are published yet;
8. no GitHub Packages are published yet.

One operational nuance also appeared during verification: immediately after rapid consecutive pushes, GitHub's repository HTML and root README blob page can lag behind the branch tip for a short time while `raw.githubusercontent.com` and file-history views already expose the newest content. That is a GitHub rendering lag, not a repository-state failure.

## Best-Practice Patterns From Strong OSS Startup Repositories

The analog repositories above converge on a small number of repeatable public-surface patterns:

1. **Clear About panel**: a short category-first description, curated topics, and a real homepage link where available;
2. **Truthful README boundary**: current product or OSS truth is separated from roadmap, cloud, or enterprise narratives;
3. **Visible trust surfaces**: support, security, contribution, and code-of-conduct pages are first-class, not buried;
4. **Releases as trust signals**: mature open-source startups make releases visible in GitHub, not just in commit history;
5. **Community routing**: community and support channels are explicit instead of making users guess whether they should use Issues, Discussions, docs, Discord, Slack, or email.

SynAPS now matches the third pattern well and the second pattern reasonably well. The main remaining gap is the first and fourth pattern: About-panel metadata and release visibility.

## Boundary Discipline

The current standalone repository uses the right public order of operations:

1. root README first, as the engineering truth boundary;
2. docs and benchmark routers second;
3. investor materials only as an optional diligence layer;
4. no claim that publication alone makes the repository production-ready.

This matters because the public GitHub surface is not just a file inventory. It is also a claim-discipline surface.

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
2. inside `docs/investor/`, the only active-surface hits are the self-referential marker list in this audit file itself;
3. active investor narrative files such as `README.md`, `PITCH_MEMO_2026_04.md`, `CLAIM_EVIDENCE_REGISTER_2026_04.md`, and `MARKET_COMPETITION_REPORT_2026_04.md` do not contain those donor markers.

Additional verification showed that the current legacy archive surface is empty.

Verdict: active SynAPS investor-facing surfaces are already industry-agnostic. The required cleanup was removal of obsolete migration residue rather than content rewrite.

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

## GitHub Security Baseline Interpretation

The important distinction is between repository files and GitHub-side capabilities.

Repository files already in place:

1. trust and community-health docs;
2. review and release workflows;
3. issue and pull request templates;
4. conservative public routers.

GitHub-side capabilities that can strengthen the public repo after push:

1. dependency graph and SPDX SBOM export;
2. Dependabot alerts and security updates;
3. private vulnerability reporting;
4. secret scanning and push protection, where plan support exists;
5. rulesets or branch protection requiring CI and dependency review;
6. optional artifact attestations, if the future release workflow adopts them.

The current export audit treats those as post-push platform settings, not as already-closed repository facts.

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
5. set final public metadata in the About panel.
Recommended current description:
`Deterministic-first scheduling and resource-orchestration engine for MO-FJSP-SDST-ML-ARC planning problems.`
Recommended current topics:
`advanced-planning-scheduling`, `scheduling`, `optimization`, `operations-research`, `constraint-programming`, `job-shop-scheduling`, `manufacturing`, `resource-orchestration`, `cp-sat`, `python`, `typescript`, `decision-support`
Recommended homepage:
leave empty until a real SynAPS landing page or docs site exists;
6. use GitHub's dependency graph to export an SPDX SBOM once the repo is public;
7. defer `CODEOWNERS` until the final public owners are verified.

Optional but high-value follow-through once the basic settings are stable:

1. enable `Discussions` only if maintainers are ready to moderate them;
2. publish a first GitHub Release after the next stable tagged milestone;
3. add a homepage only when there is a real public docs or product surface to link to.

## Current Publication Verdict

`PUBLIC_GITHUB_READY_WITH_CONSERVATIVE_BOUNDARIES`

Meaning:

1. the repository is now structurally fit for conservative public GitHub review;
2. the SynAPS investor pack is explicitly navigable;
3. trust and governance surfaces are visible at the repository root;
4. evidence boundaries remain explicit rather than implied;
5. GitHub-side security features are treated as follow-through settings, not as already-shipped repository guarantees.

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
6. Python SBOM, provenance, and vulnerability-scanning coverage for the current SynAPS codebase;
7. optional npm freshness coverage for the minimal TypeScript sidecar.