---
title: "SynAPS Benchmark Evidence Packet 2026-04"
status: "active"
version: "1.1.0"
last_updated: "2026-04-04"
date: "2026-04-04"
tags: [synaps, benchmark, evidence, investor]
mode: "reference"
---

# SynAPS Benchmark Evidence Packet 2026-04

> **Terms and confidence labels are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-04
Status: active
Scope: investor-facing benchmark evidence policy and current benchmark proof state for SynAPS

## Goal

Turn "we have a benchmark harness" into a more rigorous evidence surface.

This document defines what current benchmark evidence exists and what would be required for a publishable benchmark packet suitable for stronger external claims.

## Current Verified Evidence

Freshly verified in the workspace:

1. the current pytest suite passed `120/120`;
2. canonical smoke benchmark on `tiny_3x3.json` ran successfully;
3. `GREED` produced a feasible schedule with makespan `106.67` minutes;
4. `CPSAT-10` produced an optimal schedule with makespan `82.0` minutes;
5. on that smoke instance, `CPSAT-10` beat `GREED` by `24.67` minutes or approximately `23.1%` in makespan;
6. the active benchmark evidence is still a smoke-instance proof surface, not a broad publication-grade benchmark family.

These results are recorded in `TECHNICAL_VERIFICATION_REPORT_2026_04.md`.

## Current Gap-To-Optimality Status

The benchmark evidence currently supports only one transparent exact-versus-heuristic delta:

- `tiny_3x3.json`: `GREED` feasible at `106.67` minutes, `CPSAT-10` optimal at `82.0` minutes.

That is enough to show that the exact solver can materially beat the current greedy baseline on at least one verified instance.

It is not enough to claim a generalized gap-to-optimality story across instance families.

Still missing from the active evidence layer:

1. repeated `GREED` versus `CPSAT-*` tables for small and medium classes;
2. distribution statistics for any stochastic or timeout-sensitive regime;
3. auxiliary-resource-heavy benchmark cases called out as first-class evidence;
4. transparent external baseline comparisons beyond the smoke run.

## What This Evidence Supports

The current benchmark evidence supports only these narrow claims:

1. SynAPS has a working benchmark harness;
2. the solver stack runs end-to-end on the canonical smoke instance;
3. exact solving can materially outperform the current greedy baseline on at least one verified tiny instance.

## What It Does Not Support

The current benchmark evidence does **not** yet support:

1. broad benchmark leadership;
2. externally validated superiority across industrial-size instances;
3. performance claims against named APS vendors;
4. generalized runtime or quality claims across domains;
5. a fully quantified gap-to-optimality narrative for the current portfolio.

## Publication-Grade Benchmark Requirements

For SynAPS to upgrade benchmark claims from internal proof to stronger external evidence, the packet should include:

1. multiple benchmark families, not just one smoke instance;
2. classical FJSP/FJSP-SDST references where conversion is valid;
3. medium and large SynAPS-native instances;
4. repeated runs and distribution statistics for stochastic regimes;
5. hardware disclosure;
6. solver timeouts and configuration disclosure;
7. transparent comparison against baseline heuristics and open exact baselines;
8. instance files and command lines sufficient for reproduction.

## Minimum External Packet Structure

1. **Instance table**: source, size, SDST presence, auxiliary-resource presence, domain tag;
2. **Solver table**: config, timeout, seed policy, deterministic vs stochastic status;
3. **Primary KPI table**: makespan, tardiness, setup, feasibility rate, wall time;
4. **Statistics table**: median, IQR, min, max, number of runs;
5. **Ablation notes**: greedy-only, CP-SAT-only, repair path, auxiliary-resource path;
6. **Repro appendix**: exact commands and environment summary.

## Promotion Rule For Stronger Claims

SynAPS should not use benchmark language stronger than C2 unless all of the following are true:

1. at least one benchmark family beyond the smoke instance is included;
2. repeated-run statistics are reported where randomness exists;
3. hardware and timeout policy are disclosed;
4. results are reproducible from repository artifacts;
5. claim language avoids named-commercial-superiority unless the comparison is transparent and auditable.

## Recommended Next Build-Out

1. publish medium-instance repeated runs for `GREED`, `CPSAT-10`, and `CPSAT-60`;
2. add a structured result table for at least tiny, small, and medium classes;
3. add an auxiliary-resource-heavy case where the truth-gate semantics matter;
4. add an explicit gap-to-optimality comparison lane with fixed timeout policy and disclosed hardware;
5. keep the benchmark packet linked from the investor diligence router as a bounded smoke-evidence surface until stronger data exists.