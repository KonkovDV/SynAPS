# Release Policy

## Scope

This policy defines release readiness for SynAPS public tags.

## Versioning

- Use SemVer tags: vMAJOR.MINOR.PATCH
- Breaking contract changes require MAJOR version bump.
- Backward-compatible feature additions require MINOR bump.
- Fix-only changes require PATCH bump.

## Pre-Release Baseline

Before creating a release tag:

1. pytest tests pass;
2. strict mypy checks pass;
3. distribution build and metadata checks pass (`python -m build`, `twine check dist/*`);
4. README and governance docs reflect shipped behavior;
5. no unresolved critical security findings.

## Evidence Requirements

Release notes should include:

- commit range;
- validation commands executed;
- known limitations and non-claims;
- contract or schema changes, if any.

## Publication Guardrails

- Do not publish tags containing secrets or private datasets.
- Keep release artifacts reproducible from repository state.
- Treat benchmark claims as artifact-bound measurements, not universal guarantees.
