# SynAPS — Audit Delta And Execution Plan (2026-04-25)

> **Date**: 2026-04-25
> **Scope**: reconcile April 2026 audit claims with the live repository state, then execute the highest-confidence next improvement.
> **Status**: Phase A executed in this session.

---

## 1. Evidence Reviewed

- `docs/audit/ACADEMIC_TECHNICAL_REPORT_2026_04.md`
- `docs/audit/SYNAPS_UPDATED_STRATEGIC_RECOMMENDATIONS_2026_04.md`
- `.github/workflows/release.yml`
- `.github/workflows/codeql.yml`
- `.github/workflows/scorecards.yml`
- `README.md`
- `README_RU.md`
- `SECURITY.md`

---

## 2. Audit Delta

### 2.1 Already Wired In The Repository

The April 2026 reports correctly identified publication and security themes, but two important capabilities are already present in the checked-in repository automation:

1. **OIDC publishing workflow already exists**.
   `release.yml` already supports:
   - tag-triggered builds on `v*`;
   - manual `build-only`, `testpypi`, and `pypi` dispatch modes;
   - TestPyPI and PyPI publication through `pypa/gh-action-pypi-publish` with `id-token: write`.

2. **Scorecards automation already exists**.
   `scorecards.yml` already runs OSSF Scorecards and uploads SARIF results into GitHub code scanning.

These are not future design intentions; they are live workflow files in the repository.

### 2.2 Verified Remaining Gap

The strongest still-open workflow gap is narrower than the reports suggested:

1. **CodeQL coverage was limited to Python only**.
   Before this session, `codeql.yml` analyzed only `python`, while the repository also ships:
   - a TypeScript control-plane under `control-plane/`;
   - a Rust native acceleration crate under `native/synaps_native/`.

2. **Public docs under-described the real security automation surface**.
   The README and security documentation did not clearly say that the repository already carries pinned code-scanning and supply-chain workflows.

### 2.3 Non-Code Gaps Still Outside This Session

These gaps remain real, but were not the first execution target for this slice:

1. **Operational tag/release usage**: the workflow exists, but public GitHub releases and tags still need to be cut and maintained.
2. **Benchmark external validity**: public benchmark-suite comparisons against literature baselines remain a roadmap item.
3. **Strict-lane environment capture**: benchmark artifacts should store runtime/version metadata alongside seeds and solver parameters.

---

## 3. Executed Plan

### Phase A — Execute Now

Goal: close the verified workflow gap with the smallest coherent change set.

Actions executed:

1. Expand `CodeQL` from a single-language Python workflow to a matrix covering:
   - `python`
   - `javascript-typescript`
   - `rust`
2. Keep explicit per-language categories in SARIF uploads.
3. Synchronize public docs so the README and security policy reflect the actual automation surface.

### Phase B — Next Logical Slice

1. Document the release/tag playbook for `v0.1.0-alpha.N` and make the first public release path operationally explicit.
2. Add provenance and artifact-governance notes for release outputs.

### Phase C — Reproducibility Hardening

1. Capture environment metadata for strict-lane benchmark artifacts:
   - Python version
   - OR-Tools version
   - HiGHS version
   - NumPy version
   - OS and CPU summary
2. Record these alongside seeds, solver configuration, and timing summaries.

---

## 4. Session Outcome

This session executed **Phase A**.

Result:

1. Code scanning now matches the real multi-language repository surface more closely.
2. The public documentation no longer understates the already-wired security automation.
3. The next highest-value gap is now operational release usage, not missing publishing automation.

---

## 5. Residual Audit Note

Repository code can prove the presence of workflows, but it cannot by itself prove external repository settings or usage state.

Examples of settings that still require GitHub-side confirmation:

1. whether Private Vulnerability Reporting is enabled;
2. whether secret scanning and push protection are enabled;
3. whether public releases and tags have actually been published.