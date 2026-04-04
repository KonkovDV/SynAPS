---
name: Bug report
about: Report a reproducible problem in the SynAPS solver, schema, package, or docs
title: "[BUG] "
labels: bug
---

## Summary

## Affected surface

- [ ] Solver
- [ ] Schema / canonical form
- [ ] Benchmark harness
- [ ] Packaging / install
- [ ] Documentation / publication surface

## Minimal reproduction

1.
2.
3.

## Input or dataset

Provide the smallest **sanitized** input that reproduces the issue.

## Expected behavior

## Actual behavior

## Validation already run

```text
pytest tests/ -v
ruff check synaps tests benchmark
mypy synaps
```

## Environment

- Python version:
- OS:
- SynAPS version/commit:
- Install method (`pip install -e .`, wheel, source checkout, etc.):

## Additional context

Do **not** include secrets, private customer data, or public exploit details. If the problem is security-sensitive, use `SECURITY.md` instead of a public issue.
