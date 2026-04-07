---
title: "SynAPS Pilot KPI Protocol 2026-04"
status: "active"
version: "1.0.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, pilot, kpi, protocol, partner]
mode: "how-to"
---

# SynAPS Pilot KPI Protocol 2026-04

> **Confidence levels (C1 / C2 / C3) are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: minimum measurement discipline required to convert SynAPS from a C2 internal-evidence thesis into a stronger pilot-backed evidence story

## Goal

Prevent weak pilot storytelling.

The aim of a pilot is not merely to show that SynAPS can run.

The aim is to generate before-and-after evidence that can survive partner and technical scrutiny.

## Pilot Eligibility

A pilot candidate should satisfy all of the following:

1. repeated scheduling cadence, not one-off bespoke planning;
2. measurable setup, bottleneck, tardiness, or replanning pain;
3. historical baseline data available for at least four weeks;
4. a bounded operational scope where intervention effects can be observed;
5. agreement on what data can be logged and disclosed.

## Core KPI Set

### Operational KPIs

| KPI | Why it matters | Direction |
| --- | --- | --- |
| Weighted tardiness | captures service-level degradation and schedule miss cost | lower is better |
| Total setup minutes | measures changeover burden | lower is better |
| Replan latency | measures operational responsiveness under disruption | lower is better |
| Throughput / completed orders | measures whether optimization preserves or increases output | higher is better |
| Schedule stability | measures operational churn between revisions | lower is better |
| Manual override count | measures planner trust and system usability | lower is better |

### Optional economic KPIs

| KPI | When to use |
| --- | --- |
| Energy cost per schedule window | tariff-sensitive or energy-constrained sites |
| Scrap / material loss | recipe, metallurgy, or yield-sensitive flows |
| Expedited order rate | high rush-order volatility environments |
| Planner-hours per replan | teams where manual scheduling time is material |

## Measurement Design

### Baseline window

1. minimum `4` weeks of pre-pilot baseline data;
2. same scope, routing logic, and shift policy as the pilot window where possible;
3. document known disruptions, shutdowns, seasonal anomalies, and manual interventions.

### Pilot window

1. preferred `8-12` weeks;
2. record exactly when SynAPS recommendations are advisory-only versus operator-applied;
3. tag any periods where the plant ran in degraded or exceptional mode.

## Evidence Rules

1. keep raw logs or exported summaries for every reported KPI;
2. define each KPI formula before the pilot starts;
3. avoid mixing multiple facility types into one headline number unless normalized;
4. separate software effect from unrelated process changes whenever possible;
5. document excluded periods instead of silently dropping bad data.

## Promotion Criteria

SynAPS should not promote a pilot into stronger external evidence unless all of the following are true:

1. no feasibility or safety regressions occurred in the pilot scope;
2. at least one core KPI improved materially without harming the others;
3. the comparison window and formula definitions are documented;
4. operator exceptions and manual overrides are logged;
5. the customer permits the evidence claim in some usable form, even if anonymized.

## Suggested Materiality Thresholds

These are suggested decision thresholds, not currently proven promises:

1. `>=10%` reduction in weighted tardiness or setup minutes;
2. `>=15%` improvement in replanning latency;
3. no negative throughput trade-off beyond an agreed tolerance band;
4. measurable reduction in manual replanning effort where that burden exists.

All thresholds remain C1 hypotheses until pilot data exists.

## Reporting Template

Each pilot summary should include:

1. site type and operational scope;
2. planning cadence;
3. baseline and pilot window dates;
4. KPI formulas;
5. before-and-after table;
6. confounders and exclusions;
7. customer disclosure status;
8. claim confidence tag.

## What This Protocol Changes

This protocol does not create pilot evidence by itself.

It does something narrower and necessary:

1. it defines the minimum measurement discipline for future pilots;
2. it reduces the risk of weak or non-comparable KPI claims;
3. it creates a path from technical proof to external validation.