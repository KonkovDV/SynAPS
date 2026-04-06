---
title: "SynAPS Verification Coverage Audit 2026-04"
status: "active"
version: "1.3.1"
last_updated: "2026-04-05"
date: "2026-04-05"
tags: [synaps, verification, tests, audit, investor]
mode: "evidence"
---

# SynAPS Verification Coverage Audit 2026-04

> **Terms are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-04
Status: active
Scope: fresh verification snapshot for the current SynAPS investor and technical-diligence surfaces across project-level and core-technical proof paths (updated after Phase 2 code hardening and CI supply-chain fixes)

## Goal

This document records what was actually re-run during the April 2026 audit pass and what remains outside fresh execution evidence.

## Freshly Confirmed Checks

### Standalone-repository checks

| Check | Fresh result | Evidence basis |
| --- | --- | --- |
| Python `pytest` | PASS / REFRESH NEEDED | active evidence pack still records an earlier `149/149` full-suite pass; current repository collection now reaches `175` tests across 26 modules |
| runtime contract + CLI tests | PASS | dedicated contract, request-CLI, and orchestration tests passed |
| TypeScript control-plane tests | PASS | BFF request validation, mock flow, and real Python bridge integration passed |
| TypeScript control-plane build | PASS | isolated Fastify BFF compiled cleanly |
| `ruff check synaps tests benchmark --select F,E9` | PASS | targeted standalone lint gate - zero violations |
| `python -m build` | PASS | sdist and wheel built successfully |
| `twine check dist/*` | PASS | built artifacts passed packaging metadata validation |
| benchmark smoke: `tiny_3x3` | PASS | GREED feasible on the smoke instance |

### Structural separation checks

| Check | Fresh result | Evidence basis |
| --- | --- | --- |
| optional `docs/investor/` subtree removal rehearsal | PASS | code, build, benchmark, and export checks stayed green without the subtree |
| standalone export dry-run | PASS | export builder resolved the standalone tree without parent-repo reads |

## Boundary Note

This standalone verification surface intentionally excludes parent-monorepo commands and control-plane rails. The claims below rely on direct SynAPS proof paths only.

## What This Verification Snapshot Supports

Based on the fresh runs above, the repository currently supports these narrower statements:

1. documentation closure is functioning;
2. the core SynAPS technical surface remains runnable and testable;
3. the package build and metadata surfaces are publication-ready;
4. the benchmark harness still executes at least the smoke comparison path;
5. the investor subtree is optional rather than a runtime dependency;
6. a bounded runtime invocation contract now exists at the repository level;
7. a minimal network-facing control-plane proof now exists;
8. all 6 CI workflow action references are pinned to commit SHAs (supply-chain hardening completed 2026-04-04);
9. the canonical form objective table now includes implementation status per term, documenting which objectives (T, S, M) are implemented and which (B, R, E) remain roadmap.

## What It Does Not Yet Support

This verification snapshot does not by itself support claims such as:

1. broad benchmark superiority;
2. production-grade deployment hardening closure;
3. a fully productized SynAPS runtime with first-class deployment interfaces;
4. full release-trust closure across all build and dependency surfaces.

## Fresh Blind Spots

1. no fresh broad benchmark family beyond the smoke instance was re-run in this pass;
2. the current investor-safe supply-chain story is still partial even though release attestations and SBOM surfaces now exist;
3. the current public proof still does not show production deployment evidence for the new networked control-plane surface;
4. the suite has expanded to 175 collected tests, but this snapshot does not yet contain a newly recorded `175/175` full-suite pass artifact.

## Bottom Line

The current verification picture is strong enough for a C2 diligence posture.

It is not broad enough to justify stronger external claims without additional benchmark, integration, and release-trust evidence.