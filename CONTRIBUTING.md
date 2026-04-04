# Contributing to SynAPS

Thank you for contributing to SynAPS.

This repository is a public research and engineering surface for a scheduling and resource-orchestration engine. Keep contributions reproducible, technically bounded, and aligned with what the repository implements today.

## Read First

Before opening an issue or pull request, read:

1. `README.md`
2. `docs/README.md`
3. `benchmark/README.md`
4. `SUPPORT.md`
5. `SECURITY.md`

## Good Contribution Types

| Area | Examples |
| --- | --- |
| Domain parametrization | Add a new industry vertical in `docs/domains/` with realistic constraints |
| Solver improvements | Improve heuristics, decomposition, feasibility, or repair logic |
| Benchmark evidence | Add instances or improve reproducibility in `benchmark/` |
| Documentation | Clarify architecture boundaries, tutorials, or translation quality |
| Packaging and CI | Strengthen release, security, and validation surfaces |
| Bug reports | Reproducible issues in solver, schema, packaging, or docs |

## Getting Started

1. Fork the repository.
2. Create a focused branch, for example `feat/my-contribution` or `fix/reproducible-bug`.
3. Install the development environment: `python -m pip install -e ".[dev]"`.
4. Run the relevant validation commands before opening a pull request.
5. Keep the diff scoped to one problem or proposal.

## Validation Baseline

For most code changes, run:

```bash
pytest tests/ -v
ruff check synaps tests benchmark --select F,E9
python -m build
twine check dist/*
```

If you change solver behavior, also include benchmark evidence or a clear explanation of why no benchmark delta is expected.

## Domain Parametrizations

For a new industry vertical:

1. add or extend the relevant file under `docs/domains/`;
2. update `docs/domains/DOMAIN_CATALOG.md` if the new vertical should appear in the catalog;
3. add a realistic example in `schema/examples/` when the change affects the canonical input surface;
4. include at least one benchmark instance in `benchmark/instances/` when possible.

## Code Style

- Python: use Ruff-compatible formatting and linting.
- SQL: prefer lowercase keywords and `snake_case` identifiers.
- Docs: keep claims evidence-backed and avoid describing roadmap items as already shipped behavior.

## Commit Messages

Prefer [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat(solver): add lns neighborhood for setup minimization
fix(schema): correct operation duration validation
docs(domains): add semiconductor fab parametrization
ci(release): add trusted publishing workflow
```

## Pull Request Expectations

1. explain what changed and why;
2. include the validation you ran;
3. avoid secrets, private datasets, or customer artifacts;
4. update docs if public behavior, public claims, or contribution flow changed.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
