---
title: "SynAPS Productization and Architecture Gap Audit 2026-04"
status: "active"
version: "1.2.0"
last_updated: "2026-04-03"
date: "2026-04-03"
tags: [synaps, architecture, integration, audit, investor]
mode: "evidence"
---

# SynAPS Productization and Architecture Gap Audit 2026-04

> **Terms are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-03
Status: active
Scope: fact-check of the architectural relationship between the current SynAPS technical evidence and a deployable SynAPS product/runtime

## Goal

This audit answers a simple but crucial diligence question:

How far has SynAPS progressed from a validated scheduling kernel to a deployable, first-class product/runtime?

## Evidence Used

1. `docs/investor/PITCH_MEMO.md`;
2. `docs/investor/INVESTOR_DILIGENCE_PACKET_2026_04.md`;
3. `docs/investor/TECHNICAL_VERIFICATION_REPORT_2026_04.md`;
4. `docs/investor/WORLD_CLASS_TECHNICAL_DILIGENCE_FRAMEWORK_2026_04.md`;
5. `docs/investor/CLAIM_EVIDENCE_REGISTER_2026_04.md`.

## Verified Findings

### 1. SynAPS does have validated core technical surfaces

Verified examples:

1. a universal schema and domain examples;
2. a working Python solver baseline;
3. bounded repair logic;
4. a benchmark harness and published research documentation.

This proves that SynAPS is beyond concept stage and already has real technical substance.

### 2. Those technical surfaces are not the same thing as a deployable product/runtime

Validated technical surfaces do not, by themselves, prove product runtime maturity.

They do not yet establish operator-facing workflows, deployment boundaries, stable integration contracts, or productionized service interfaces.

### 3. A bounded invocation contract and a minimal networked control-plane now exist, but full product/runtime surfaces still do not

Verified evidence now exists for:

1. explicit request and response schemas for deterministic solve and bounded repair;
2. package-level execution helpers for those contracts;
3. CLI entrypoints that execute those contracts directly;
4. a TypeScript BFF package exposing a minimal HTTP invocation surface over the Python kernel.

However, verified evidence is still missing for:

1. production deployment evidence for that networked boundary;
2. a public deployment architecture that shows how SynAPS is exposed to operators or external systems;
3. integration surfaces for ERP, MES, or adjacent plant systems implemented as current proof rather than roadmap;
4. operator UI evidence or workflow-level runtime surfaces;
5. end-to-end product integration tests covering invocation, execution, and result delivery.

### 4. The current investor-facing SynAPS narrative is largely honest about this boundary

`PITCH_MEMO.md` already states that the repository currently captures SynAPS as a venture thesis and architecture-mathematical formalization rather than a fully realized APS runtime.

That is consistent with the code evidence.

## Safe Architectural Statement

As of April 2026, the strongest accurate statement is:

SynAPS is a validated scheduling-kernel codebase with strong technical proof, an explicit invocation contract, and a minimal network-facing control-plane proof, but it is not yet evidenced as a fully productized APS runtime with first-class deployment and integration surfaces.

## Architecture Gap Map

| Missing surface | Why it matters |
| --- | --- |
| production-hardened product API / service boundary | request/response schemas and a minimal BFF now exist, but deployment-facing transport is still not proven as a product surface |
| explicit polyglot runtime split | without a frozen language boundary, UI, solver, and ML concerns will drift back into one opaque runtime |
| service boundary and packaging | without packaging, the kernel cannot be consumed predictably |
| application/runtime orchestration path | without an execution path, there is no deployable product behavior |
| ERP/MES integration surface | without an adapter layer, plant-system participation remains narrative-only |
| operator-facing workflow surface | without an interface, no production user can invoke SynAPS planning directly |
| end-to-end product tests | without tests, any productization claim stays narrative-only |

## Upgrade Path

The smallest sound productization path would be:

1. define a stable planning contract for deterministic plan generation and bounded repair;
2. preserve and version that contract as the only supported invocation boundary;
3. freeze the runtime split between control plane, optimizer, and native hot-path kernels;
4. harden the new bounded service boundary into a production-grade transport surface;
5. add one product-facing workflow for operators or integrating systems;
6. add end-to-end tests and runtime latency evidence.

## Investor Interpretation

This gap is not fatal.

It simply changes the correct narrative.

The investable statement today is about a strong kernel thesis and unusually disciplined documentation, not about completed productization.

## Bottom Line

The main architectural risk is not that SynAPS lacks technical proof.

The main architectural risk is that the bridge from technical proof to deployable product capability is still only partially implemented.

That bridge should be treated as a first-order roadmap item, not as solved architecture.