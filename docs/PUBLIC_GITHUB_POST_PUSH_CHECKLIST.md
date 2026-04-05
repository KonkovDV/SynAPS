---
title: "SynAPS Public GitHub Post-Push Checklist"
status: "active"
version: "1.0.0"
last_updated: "2026-04-03"
tags: [synaps, github, publication, checklist]
---

# SynAPS Public GitHub Post-Push Checklist

Use this checklist after pushing the standalone SynAPS repository to a new public GitHub repository.

This document is intentionally operational. It tells you what to configure in GitHub after the files are already in place.

## 1. Repository Metadata

1. Set the repository description to a short engineering-first summary of SynAPS.
2. Set the homepage if you have a real public landing page. If not, leave it empty.
3. Add curated repository topics in lowercase, hyphenated form.
Recommended baseline:
`aps`, `scheduling`, `optimization`, `operations-research`, `constraint-programming`, `manufacturing`, `job-shop-scheduling`, `python`
4. Confirm the default branch is `master` for the current public SynAPS repository, or update this checklist if you intentionally rename it.

## 2. Community Profile

1. Confirm GitHub renders `README.md`, `LICENSE`, `SECURITY.md`, `SUPPORT.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, and `CITATION.cff`.
2. Open the repository community profile and verify there are no missing recommended files.
3. Check that issue templates and the pull request template appear correctly in the GitHub UI.

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

## 8. Optional Investor Pack Decision

1. If you want a pure engineering-only public repo, remove `docs/investor/` before the first public push and rebuild the export.
2. If you keep `docs/investor/`, treat it as an optional diligence packet rather than the primary technical entrypoint.

## 9. Things Not To Claim

Do not infer from publication alone that SynAPS is:

1. production-hardened for all deployments;
2. regulator-ready;
3. pilot-validated for ROI;
4. benchmark-superior to named incumbents across a broad public dataset.

Those are separate proof tracks.