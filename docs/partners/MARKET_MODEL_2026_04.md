---
title: "SynAPS Market Model 2026-04"
status: "active"
version: "1.1.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, market, tam, sam, som, partner]
mode: "reference"
---

# SynAPS Market Model 2026-04

> **Terms and confidence labels (C1 / C2 / C3) are defined in [GLOSSARY](GLOSSARY_2026_04.md).**

Date: 2026-04-02
Status: active
Scope: initial source-backed TAM, SAM, and SOM model for SynAPS using official industrial statistics plus explicit pricing and penetration assumptions

## Purpose

This document closes the previous zero-model state.

It does not pretend to be a final commercial market study.

It provides a transparent, auditable first model with:

1. official macro anchors for manufacturing scale;
2. official U.S. establishment counts for a bottom-up operational denominator;
3. explicit internal pricing and penetration assumptions;
4. conservative, base, and upside scenarios.

## Method

The model uses a hybrid approach:

1. **top-down macro context** from World Bank manufacturing value-added data;
2. **bottom-up operational TAM/SAM/SOM** from U.S. Census manufacturing establishment counts;
3. **internal pricing assumptions** for SynAPS annual software contract value per site;
4. **explicit uncertainty flags** where the denominator is official but the pricing and wedge assumptions remain internal hypotheses.

## Official Source Anchors

### Manufacturing value-added context

| Region | Latest non-null year used | Official value |
| --- | --- | --- |
| World | 2024 | `$16.64T` manufacturing value added |
| European Union | 2024 | `$2.79T` manufacturing value added |
| United States | 2021 | `$2.50T` manufacturing value added |

Source basis:

1. World Bank indicator `NV.IND.MANF.CD`;
2. World = `WLD`;
3. European Union = `EUU`;
4. United States = `USA`.

### U.S. manufacturing establishment base

Official U.S. Census County Business Patterns 2022, NAICS `31-33` Manufacturing:

| Segment | Establishments |
| --- | ---: |
| All manufacturing establishments | `285,500` |
| 100 to 249 employees | `16,807` |
| 250 to 499 employees | `5,727` |
| 500 to 999 employees | `2,254` |
| 1,000+ employees | `1,011` |
| **Total 100+ employees** | **`25,799`** |

Interpretation:

The `25,799` establishments with `100+` employees are the current best official U.S. denominator for SynAPS's initial bottom-up operational market model.

They are not all immediate buyers, but they form a serious industrial base for a scheduling-kernel thesis.

## Assumptions

### Pricing assumptions

These are internal pricing hypotheses, not external market facts.

| Scenario | Annual software contract value per site |
| --- | ---: |
| Conservative | `$40,000` |
| Base | `$80,000` |
| Upside | `$150,000` |

These values intentionally exclude one-time implementation services so that the model does not blur ARR with integration revenue.

### Target wedge assumptions

Not every manufacturing establishment with `100+` employees is a near-term SynAPS fit.

The initial commercial wedge is assumed to be plants where setup losses, bottlenecks, auxiliary resources, and replanning pressure make APS economics meaningful.

| Scenario | Share of 100+ employee manufacturing establishments treated as commercially relevant |
| --- | ---: |
| Conservative | `10%` |
| Base | `20%` |
| Upside | `30%` |

These wedge fractions are internal hypotheses pending sector-sliced official counts and pilot discovery.

## TAM

### Macro TAM context

The World Bank figures do **not** translate directly into software revenue.

They provide macro context showing that SynAPS is aimed at a very large industrial value base rather than a marginal niche.

### Bottom-up operational TAM

Formula:

`U.S. operational TAM = official 100+ employee manufacturing establishments x annual software ACV per site`

| Scenario | Sites | ACV | Operational TAM |
| --- | ---: | ---: | ---: |
| Conservative | `25,799` | `$40,000` | `$1.032B` |
| Base | `25,799` | `$80,000` | `$2.064B` |
| Upside | `25,799` | `$150,000` | `$3.870B` |

Interpretation:

This is a U.S.-only operational software TAM anchored to an official plant denominator.

It is more credible than a vague global software-market claim, even though it remains assumption-led on pricing.

## SAM

Formula:

`SAM = official 100+ employee manufacturing establishments x target wedge fraction x annual software ACV`

| Scenario | Wedge sites | ACV | SAM |
| --- | ---: | ---: | ---: |
| Conservative | `2,580` | `$40,000` | `$103.2M` |
| Base | `5,160` | `$80,000` | `$412.8M` |
| Upside | `7,740` | `$150,000` | `$1.161B` |

Interpretation:

The base-case SAM assumes SynAPS initially targets roughly one fifth of the official U.S. `100+` employee manufacturing base.

That is still a large commercial wedge without assuming universal applicability from day one.

## SOM

Formula:

`SOM = base-case SAM site count x realistic early penetration rate x annual software ACV`

For the first commercial phase, the model uses penetration against the **base-case** SAM site count of `5,160`.

| Scenario | Penetration of base-case SAM | Sites | Base ACV | SOM |
| --- | ---: | ---: | ---: | ---: |
| Conservative | `0.5%` | `26` | `$80,000` | `$2.08M` |
| Base | `1.0%` | `52` | `$80,000` | `$4.16M` |
| Upside | `2.0%` | `103` | `$80,000` | `$8.24M` |

Interpretation:

This frames an early commercial SOM as dozens, not thousands, of sites.

That is a more credible partner posture for an early industrial kernel than aggressive share assumptions.

## Confidence Table

| Model component | Confidence | Why |
| --- | --- | --- |
| World and EU manufacturing macro context | C3 | official World Bank data |
| U.S. manufacturing establishment denominator | C3 | official U.S. Census data |
| 100+ employee site focus | C2 | operationally sensible targeting rule, but still a strategic filter |
| Wedge fraction assumptions | C1 | internal commercial assumption, not externally validated yet |
| ACV assumptions | C1 | internal packaging hypothesis, not priced through pilots yet |
| U.S. operational TAM output | C2 | official denominator plus internal ACV assumptions |
| SAM and SOM outputs | C1-C2 hybrid | official denominator plus internal targeting and penetration assumptions |

## What This Model Improves

1. SynAPS no longer has a zero-state market model;
2. the denominator is now official and inspectable;
3. the assumptions are separated cleanly from the official data;
4. partners can challenge the assumptions without disputing the raw industrial base.

## What Still Needs Improvement

1. Europe-specific establishment counts for a second regional bottom-up layer;
2. sector-sliced counts for high-complexity verticals such as pharma, electronics, and multi-stage discrete manufacturing;
3. pilot-backed pricing and packaging evidence;
4. services and implementation revenue model as a separate layer from software ARR;
5. win-rate and sales-cycle assumptions grounded in actual pipeline learning.

## Sources

1. World Bank indicator `NV.IND.MANF.CD` for `WLD`, `EUU`, and `USA`;
2. U.S. Census County Business Patterns 2022, NAICS `31-33` Manufacturing.