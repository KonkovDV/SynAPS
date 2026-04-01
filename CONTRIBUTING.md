# Contributing to Syn-APS

Thank you for your interest in contributing to Syn-APS — an open, universal Advanced Planning & Scheduling platform.

## Ways to Contribute

| Area | Examples |
|------|---------|
| **Domain parametrizations** | Add a new industry vertical (see `docs/domains/`) |
| **Solver improvements** | New heuristics, metaheuristics, or exact solvers |
| **Benchmark instances** | Realistic problem instances for testing |
| **Documentation** | Translations, tutorials, architecture clarifications |
| **Bug reports** | Reproducible issues with solver, schema, or tooling |

## Getting Started

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-contribution`
3. Install the solver environment: `pip install -e ".[dev]"`
4. Run tests: `pytest`
5. Submit a Pull Request

## Code Style

- **Python**: [Ruff](https://docs.astral.sh/ruff/) for linting and formatting
- **SQL**: Lowercase keywords, `snake_case` identifiers
- **Docs**: Markdown with Mermaid diagrams where helpful

## Domain Parametrizations

To add a new industry vertical:

1. Create `docs/domains/NN_DOMAIN_NAME.md` following the existing template
2. Add a JSON example in `schema/examples/`
3. Update the domain catalog index in `docs/domains/00_CATALOG.md`
4. Include at least one benchmark instance in `benchmark/instances/`

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(solver): add LNS neighborhood for setup minimization
fix(schema): correct CHECK constraint on operation duration
docs(domains): add semiconductor fab parametrization
```

## Review Process

- All PRs require at least one review
- Solver changes must include benchmark results
- Schema changes must include migration SQL

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
