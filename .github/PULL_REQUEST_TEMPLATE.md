## What

<!-- Focused summary of the change -->

## Why

<!-- Problem statement, motivation, issue reference, or benchmark gap -->

## Type

- [ ] Solver improvement
- [ ] Schema or data-model change
- [ ] New domain parametrization
- [ ] Documentation or publication surface
- [ ] Benchmark or evidence update
- [ ] CI / packaging / release tooling

## Validation

Required GitHub checks on `master` (branch protection): `lint`,
`contract-schema-drift`, `typecheck`, `test-fast (3.12)`, `test-fast (3.13)`,
`benchmark-smoke`, `control-plane`. `test-slow` is post-merge only and is
not a PR gate.

- [ ] `pytest tests/ -m "not slow"`
- [ ] `ruff check synaps tests benchmark --select F,E9`
- [ ] `python -m build`
- [ ] `twine check dist/*`

## Additional checks

- [ ] Benchmark evidence attached or summarized if solver behavior changed
- [ ] Public docs updated if user-facing claims or workflows changed
- [ ] No secrets, customer data, or proprietary datasets added to the diff
