# SynAPS Documentation Map

Language: **EN** | [RU](README_RU.md)

This directory is the public router for SynAPS technical documentation.

Start here if you want the larger system context around the current scheduling core.

## Fast paths

1. Start with [../README.md](../README.md) for the repository boundary and quick-start commands.
2. Go to [../benchmark/README.md](../benchmark/README.md) if you want reproducible solver evidence.
3. Go to [../control-plane/README.md](../control-plane/README.md) if you want the TypeScript runtime boundary.
4. Go to [partners/README.md](partners/README.md) only if you need the optional partner and diligence layer.

## Architecture

- [01_OVERVIEW.md](architecture/01_OVERVIEW.md)
- [02_CANONICAL_FORM.md](architecture/02_CANONICAL_FORM.md)
- [03_SOLVER_PORTFOLIO.md](architecture/03_SOLVER_PORTFOLIO.md)
- [04_DATA_MODEL.md](architecture/04_DATA_MODEL.md)
- [05_DEPLOYMENT.md](architecture/05_DEPLOYMENT.md)
- [06_LANGUAGE_AND_RUNTIME_STRATEGY.md](architecture/06_LANGUAGE_AND_RUNTIME_STRATEGY.md)
- [07_RUNTIME_CONTRACT.md](architecture/07_RUNTIME_CONTRACT.md)

## Domain Parametrization

- [DOMAIN_CATALOG.md](domains/DOMAIN_CATALOG.md)
- [aerospace.md](domains/aerospace.md)
- [electronics.md](domains/electronics.md)
- [energy.md](domains/energy.md)
- [food_beverage.md](domains/food_beverage.md)
- [logistics.md](domains/logistics.md)
- [metallurgy.md](domains/metallurgy.md)
- [pharmaceutical.md](domains/pharmaceutical.md)
- [data_center.md](domains/data_center.md)

## Evolution Tracks

- [CROSS_VECTOR_INTEGRATION.md](evolution/CROSS_VECTOR_INTEGRATION.md)
- [V1_DIGITAL_TWIN_DES.md](evolution/V1_DIGITAL_TWIN_DES.md)
- [V2_LLM_COPILOT.md](evolution/V2_LLM_COPILOT.md)
- [V3_FEDERATED_LEARNING.md](evolution/V3_FEDERATED_LEARNING.md)
- [V4_QUANTUM_READINESS.md](evolution/V4_QUANTUM_READINESS.md)

## Research Notes

- [SYNAPS_OSS_STACK_2026.md](../research/SYNAPS_OSS_STACK_2026.md)
- [SYNAPS_UNIVERSAL_ARCHITECTURE.md](../research/SYNAPS_UNIVERSAL_ARCHITECTURE.md)
- [SYNAPS_AIR_GAPPED_OFFLINE.md](../research/SYNAPS_AIR_GAPPED_OFFLINE.md)

Legacy blueprint and whitepaper narrative files are no longer part of the active research route.

## Audit Reports

- [ACADEMIC_TECHNICAL_REPORT_2026_04.md](audit/ACADEMIC_TECHNICAL_REPORT_2026_04.md) — comprehensive academic-level audit: formal problem classification, solver portfolio analysis, competitive positioning, and actionable recommendations.
- [DISSERTATION_AUDIT_REPORT.md](audit/DISSERTATION_AUDIT_REPORT.md)

## Validation and Evidence

- [benchmark/README.md](../benchmark/README.md)
- [benchmark/README_RU.md](../benchmark/README_RU.md)
- [control-plane/README.md](../control-plane/README.md)
- [control-plane/README_RU.md](../control-plane/README_RU.md)
- [README.md](../README.md)
- [README_RU.md](../README_RU.md)
- [PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md](PUBLIC_GITHUB_POST_PUSH_CHECKLIST.md)
- [CONTRIBUTING.md](../CONTRIBUTING.md)
- [SECURITY.md](../SECURITY.md)

## Optional Partner Pack

`docs/partners/` contains the optional SynAPS diligence packet.

The engineering surface is complete without that subtree, so removing it must not affect the code, tests, benchmark harness, or package build.

Use [partners/README.md](partners/README.md) as the partner router. It now points to the reduced active packet and to the archive boundary for older or duplicate materials.