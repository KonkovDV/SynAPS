---
title: "SynAPS Mathematical and Research Fact-Check 2026-04"
status: "active"
version: "1.0.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, mathematics, research, benchmark, fact-check, investor]
mode: "evidence"
---

# SynAPS Mathematical and Research Fact-Check 2026-04

> **Terms and confidence labels are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: investor-safe fact-check of the current SynAPS mathematical formalism, solver claims, and research foundations

## Goal

This document draws a hard line between:

1. what SynAPS already supports as a mathematical and research thesis;
2. what is only partially evidenced;
3. what should still be treated as a future proof obligation.

## Evidence Used

1. canonical form documentation;
2. solver portfolio documentation;
3. benchmark protocol;
4. `docs/investor/HYPERDEEP_AUDIT_REPORT_2026_04.md`;
5. `docs/investor/TECHNICAL_VERIFICATION_REPORT_2026_04.md`;
6. `docs/investor/PITCH_MEMO.md`;
7. official OR-Tools job-shop guidance already used in the SynAPS evidence stack as the deterministic baseline reference.

## What Is Well-Supported Today

### 1. A real canonical formalization exists

SynAPS is not only a product story.

It has an explicit mathematical problem class: `MO-FJSP-SDST-ML-ARC`.

The current repository documents:

1. sets and indices;
2. decision variables;
3. precedence constraints;
4. no-overlap with setup times;
5. machine and auxiliary-resource capacity constraints;
6. a multi-term objective function;
7. a robust extension;
8. an incremental-repair formalization.

That is enough to support a C2 statement that the product kernel is mathematically coherent.

### 2. The deterministic baseline is the real execution backbone

The current architectural rule remains sound and internally consistent:

1. deterministic solvers execute;
2. ML advises;
3. feasibility remains a hard gate;
4. human override remains final authority.

This is compatible with both the current solver surfaces and the official OR-Tools-style job-shop baseline that centers precedence, no-overlap, and exact scheduling logic.

### 3. The solver portfolio story is technically coherent

The current docs support a bounded but credible solver narrative:

1. constructive heuristic lane for fast feasible schedules;
2. exact CP-SAT lane for bottlenecks and higher-quality solves;
3. incremental repair for bounded local replanning;
4. decomposition and routing concepts for larger-scale solving.

This supports the claim that SynAPS is aiming at a hybrid solver portfolio rather than a single-algorithm product.

### 4. Benchmark methodology exists as a real protocol

The benchmark layer is not imaginary.

The repo contains:

1. standard instance classes;
2. dataset families;
3. KPI definitions;
4. statistical-rigor rules;
5. baseline configurations;
6. report format;
7. reproducibility commands.

This is enough to support the narrower statement that SynAPS has a publication-minded benchmark protocol.

## What Is Only Partially Supported

### 1. Auxiliary-resource semantics are not yet uniformly proven across all constructive paths

The strongest current wording remains the cautious one already used elsewhere in the pack.

Auxiliary-resource and material semantics are formalized and truth-gated, but they are not yet proven as fully solver-native across every current constructive path.

### 2. LBBD and broader decomposition claims remain architecture-first, evidence-second

The decomposition story is plausible and well-motivated.

What is still missing is a broad live evidence packet showing that the decomposition path delivers superior results across medium, large, and industrial-size instances inside the current codebase.

### 3. The benchmark protocol is stronger than the current benchmark packet

The protocol itself is sophisticated.

The live proof remains narrower:

1. smoke benchmark execution is confirmed;
2. broad benchmark families are not yet published as a current evidence packet;
3. therefore the benchmark methodology is ahead of the benchmark evidence.

### 4. The ML advisory layer is mostly a research and architecture claim, not a current deployed proof layer

The advisory surfaces are well described.

That does not yet amount to field-validated model governance or production-grade ML effectiveness evidence.

## What Should Not Yet Be Claimed

The current evidence does **not** justify statements such as:

1. mathematically proven superiority over incumbent APS systems;
2. full solver-native closure of every modeled constraint across every runtime path;
3. industrial-scale latency and quality guarantees;
4. production-grade robust optimization evidence;
5. empirically validated ML advisory gains in live customer operations.

## Current Reliability Of The Research Layer

The existing hyperdeep audit is still useful here.

Its current summary supports the narrower conclusion that:

1. major fabrication issues were already removed;
2. the remaining mathematical core is at C2 internal-evidence level;
3. the strongest remaining research gaps are breadth-of-proof gaps, not coherence-of-formalism gaps.

## Investor Interpretation

The right interpretation is not that SynAPS has already won the research case.

The right interpretation is that the project has crossed an important threshold:

it already has a serious mathematical kernel and a testable benchmark discipline, which is much stronger than a typical AI-heavy planning startup thesis.

## Bottom Line

SynAPS currently has a **credible C2 mathematical and research foundation**.

Its formalism is real, its deterministic baseline is coherent, and its benchmark protocol is serious.

Its remaining gaps are mainly about breadth, comparative evidence, and live operational validation.