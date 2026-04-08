---
title: "SynAPS Public GitHub Post-Push Checklist"
status: "active"
version: "1.1.0"
last_updated: "2026-04-05"
tags: [synaps, github, publication, checklist]
---

# SynAPS Public GitHub Post-Push Checklist

Use this checklist after pushing the standalone SynAPS repository to a new public GitHub repository.

This document is intentionally operational. It tells you what to configure in GitHub after the files are already in place.

## 1. Repository Metadata

1. Set the repository description to a short engineering-first summary of SynAPS.
Recommended current value:
`Deterministic-first scheduling and resource-orchestration engine for MO-FJSP-SDST-ARC planning problems.`
2. Set the homepage only if you have a real public landing page or product/docs site. If not, leave it empty instead of pointing to a GitHub blob URL.
3. Add curated repository topics in lowercase, hyphenated form.
Recommended baseline:
`advanced-planning-scheduling`, `scheduling`, `optimization`, `operations-research`, `constraint-programming`, `job-shop-scheduling`, `manufacturing`, `resource-orchestration`, `cp-sat`, `python`, `typescript`, `decision-support`
4. Confirm the default branch is `master` for the current public SynAPS repository, or update this checklist if you intentionally rename it.

### Metadata Quality Gate

Use the About panel the way well-maintained OSS repositories do:

1. one-sentence category-first description, not a manifesto;
2. topics that classify domain plus method plus runtime;
3. homepage only when it is a real owned surface;
4. no partner language in the About panel.

## 2. Community Profile

1. Confirm GitHub renders `README.md`, `LICENSE`, `SECURITY.md`, `SUPPORT.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `CITATION.cff`.
2. Open the repository community profile and verify there are no missing recommended files.
3. Check that issue templates and the pull request template appear correctly in the GitHub UI.
4. If you later enable `Discussions`, keep it as a community or roadmap surface only if someone will actually moderate it.

## 3. Security Settings

1. Enable dependency graph.
2. Enable Dependabot alerts.
3. Enable Dependabot security updates.
4. Enable private vulnerability reporting.
5. Ensure maintainers watch security alert notifications.
6. Enable secret scanning and push protection if your GitHub plan supports them.

## 4. Actions And Trust

1. Confirm Actions are enabled for the repository.
2. Verify these workflows are visible and enabled:
   - `CI`
   - `Dependency Review`
   - `CodeQL`
   - `Scorecards`
   - `Release`
3. Keep Actions permissions least-privilege. Do not widen token scopes unless a concrete workflow requires it.
4. If you plan to publish packages, create GitHub environments for `testpypi` and `pypi` before using the release workflow.
5. Wait for one successful run on `master` before making those checks required in rulesets or branch protection.

## 5. Rulesets Or Branch Protection

1. Require pull requests before merge.
2. Disable force pushes to `master`.
3. Disable branch deletion for the protected default branch.
4. Require the main CI checks and dependency review once the first PR run has established stable check names.
Typical required checks:
   - `lint`
   - `test (3.12)`
   - `test (3.13)`
   - `build-distributions`
   - `dependency-review`
5. Require linear history if that matches your release discipline.
6. Do not enable CODEOWNERS-based review until you have verified public owners with write access.

## 6. Release Path

1. If you only want GitHub publication for now, keep release workflow use to `build-only`.
2. If you want package publication later, configure PyPI Trusted Publishing for the `pypi` environment.
3. Test the release workflow with `workflow_dispatch` before relying on tag-driven release publication.
4. Verify uploaded artifacts and attestations in the GitHub UI after the first release rehearsal.
5. Publish a first GitHub Release once you have a stable tag and changelog-worthy delta; strong OSS startup repos use visible releases as a trust signal, not just raw commits.

## 7. First Public Smoke Check

1. Clone the public repository into a clean directory.
2. Run:

```bash
python -m pip install -e ".[dev]"
pytest tests -q
ruff check synaps tests benchmark --select F,E9
python -m build
python -m twine check dist/*
python -m benchmark.run_benchmark benchmark/instances/tiny_3x3.json --solvers GREED --compare
```

3. Confirm the repository works without any parent workspace files.

## 8. Optional Private Material

1. Keep any local-only commercial or partner material outside the public technical route.
2. If such material exists locally, ensure it stays gitignored and untracked before public publication.

## 9. Things Not To Claim

Do not infer from publication alone that SynAPS is:

1. production-hardened for all deployments;
2. regulator-ready;
3. pilot-validated for ROI;
4. benchmark-superior to named incumbents across a broad public dataset.

Those are separate proof tracks.

## 10. Startup-Grade Optional Upgrades

These are good next steps, not launch blockers:

1. enable `Discussions` only when you are ready to answer roadmap and community questions there;
2. publish a first tagged release once the release workflow and changelog story are real;
3. add a homepage only when there is a real SynAPS landing page, docs site, or product page;
4. consider a public roadmap or status surface later, but only if it can stay current.