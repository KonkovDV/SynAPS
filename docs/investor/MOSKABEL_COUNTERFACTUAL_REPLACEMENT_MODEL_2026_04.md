---
title: "Moskabel Counterfactual Replacement Model 2026-04"
status: "active"
version: "1.0.0"
last_updated: "2026-04-02"
date: "2026-04-02"
tags: [synaps, aps-infimum, moskabel, economic-model, counterfactual]
mode: "reference"
---

# Moskabel Counterfactual Replacement Model 2026-04

> **Terms and confidence labels are defined in [GLOSSARY](GLOSSARY_2026_04.md).** | [ГЛОССАРИЙ (RU)](GLOSSARY_2026_04_RU.md)

Language: EN | [RU](MOSKABEL_COUNTERFACTUAL_REPLACEMENT_MODEL_2026_04_RU.md)

Date: 2026-04-02
Status: active
Scope: evidence-bounded model for evaluating the economics of deploying SynAPS instead of APS Infimum at Moskabel

## 1. Purpose

This document answers a narrow but difficult question:

What is the academically defensible estimate of economic value if Moskabel were to deploy SynAPS **instead of** APS Infimum?

This is a **counterfactual replacement model**, not a record of actual realized savings.

## 2. Why This Model Is Needed

A casual comparison would be misleading.

APS Infimum and SynAPS differ on three axes at once:

1. product maturity;
2. evidence visibility;
3. deployment context.

APS Infimum is stronger on current operational embedding.

SynAPS is stronger on open technical proof.

A serious investor therefore needs a model that separates:

1. direct plant economics;
2. replacement cost;
3. platform-option value;
4. evidence confidence.

## 3. Evidence Classes Used

| Class | Description | Use here |
| --- | --- | --- |
| E1 | Public product pages | APS Infimum pricing, product packaging, benefit statements |
| E2 | Public lecture-slide evidence provided during diligence | APS Infimum architecture and planning-scale signals |
| E3 | Open code and tests | SynAPS current codebase and test evidence |
| E4 | Repo-grounded investor and methods docs | claim boundaries, market framing, verification status |
| E5 | Internal scenario assumptions | migration-cost scenarios and risk-adjusted thresholds |

Rule:

1. E1-E4 constrain the factual baseline.
2. E5 is used only for decision modeling and is clearly labeled as assumption rather than fact.

## 4. Public APS Infimum Facts Used In The Model

### 4.1 Product-surface facts

Public MOSITLAB surfaces indicate:

1. APS Infimum is sold as `APS Infimum` with a public starting price of `888,000 RUB/year`;
2. it is positioned as an optimal planning system for cable production;
3. it is integrated into a broader ecosystem that includes MES, CoMod, RFID, and adjacent manufacturing tools;
4. it is presented as suitable for both single-plant and manufacturing-holding contexts.

### 4.2 Public operating-context facts

Public APS Infimum product pages describe a cable-production context with approximately:

1. `400-500` employees;
2. `~20B RUB/year` turnover;
3. `~600` nomenclature positions.

### 4.3 Public economic claims

Publicly visible APS Infimum claims include:

| Public claim | Source type | Interpretation |
| --- | --- | --- |
| `23M RUB` in `Q1 2024` | product page | lower-band direct financial signal |
| `+14%` productivity | product page | operational uplift claim |
| `+8%` net profit | product page | financial outcome claim |
| `-46%` changeover time losses | product page | strong operational lever |
| `-12%` WIP | product page | inventory-cycle lever |
| `-11%` average order fulfillment time | product page | lead-time lever |
| `27 days / ~1.2B RUB per year` | lecture slide | management-headline enterprise gain |
| `~1.4B RUB per year` | product page headline | broader enterprise-gain headline |

## 5. Public SynAPS Facts Used In The Model

SynAPS currently proves:

1. open schema and domain parametrization templates;
2. visible solver baseline;
3. bounded repair logic;
4. benchmark harness;
5. `27/27` passing tests;
6. a working smoke benchmark path.

SynAPS does **not** yet prove:

1. Moskabel-specific deployment;
2. live MES or 1C integration at Moskabel;
3. operator-facing UI parity with APS Infimum;
4. plant-level KPI uplift on a cable factory;
5. audited superiority over APS Infimum.

## 6. First Critical Finding: APS Infimum's Public Economics Are Useful But Not Fully Reconciled

The public APS Infimum evidence contains a meaningful inconsistency.

### 6.1 Annualized direct-effect floor

If `23M RUB` in `Q1 2024` is annualized mechanically:

$$23M \times 4 = 92M \text{ RUB/year}$$

Relative to the publicly stated `~20B RUB/year` turnover base:

$$92M / 20B = 0.46\%$$

### 6.2 Headline enterprise-gain band

The lecture-slide and product-page annual figures imply:

1. `1.2B / 20B = 6.0%` of turnover;
2. `1.4B / 20B = 7.0%` of turnover.

### 6.3 Interpretation rule

This model therefore uses two APS Infimum baselines:

1. **lower-band direct-capture floor**: `92M RUB/year`;
2. **management-headline value band**: `1.2B-1.4B RUB/year`.

The model does **not** collapse those numbers into a single false-precision estimate.

## 7. Decision Equation

Let:

1. $B_A$ = annual benefit of APS Infimum;
2. $B_S$ = annual benefit of SynAPS after stabilization;
3. $C_0$ = one-time replacement and integration cost;
4. $L$ = transition and disruption cost;
5. $r$ = discount rate;
6. $H$ = decision horizon.

Replacement is economically justified only if:

$$
NPV = -(C_0 + L) + \sum_{t=2}^{5}\frac{(B_S - B_A)}{(1+r)^t} > 0
$$

This model uses:

1. a five-year decision horizon;
2. one stabilization year before steady-state benefit counts;
3. a `15%-20%` discount range.

## 8. Scenario Assumptions For Replacing APS Infimum With SynAPS

These are not public facts. They are disciplined C1 modeling assumptions.

### 8.1 Minimal replacement scenario

Assumption set:

1. limited scope replacement;
2. existing plant interfaces are relatively reusable;
3. low disruption during transition.

| Cost block | Assumption |
| --- | ---: |
| Integration and mapping | `45M RUB` |
| Validation and shadow testing | `15M RUB` |
| Training and change management | `10M RUB` |
| Temporary disruption cost | `20M RUB` |
| Total replacement burden | `90M RUB` |

### 8.2 Base replacement scenario

Assumption set:

1. meaningful UI and operator-surface work is needed;
2. cable-domain calibration must be hardened;
3. a real dual-run validation period is required.

| Cost block | Assumption |
| --- | ---: |
| Integration and data mapping | `70M RUB` |
| Operator and analytics surface hardening | `20M RUB` |
| Validation and shadow-mode program | `20M RUB` |
| Training and process adaptation | `10M RUB` |
| Temporary disruption cost | `40M RUB` |
| Total replacement burden | `160M RUB` |

### 8.3 Full replacement scenario

Assumption set:

1. deeper stack replacement;
2. support, security, and operations hardening must be built to production grade;
3. change risk is materially higher.

| Cost block | Assumption |
| --- | ---: |
| Integration and domain adaptation | `100M RUB` |
| Operator surface and analytics | `30M RUB` |
| Security, support, and runtime hardening | `20M RUB` |
| Long validation program | `30M RUB` |
| Training and rollout overhead | `20M RUB` |
| Temporary disruption cost | `50M RUB` |
| Total replacement burden | `250M RUB` |

## 9. Threshold Annual Incremental Benefit Required

Given the assumptions above, SynAPS must produce the following **additional annual value above APS Infimum** for replacement to break even.

| Scenario | Required incremental annual benefit at 15% | Required incremental annual benefit at 20% |
| --- | ---: | ---: |
| Minimal | `36.3M RUB/year` | `41.7M RUB/year` |
| Base | `64.4M RUB/year` | `74.2M RUB/year` |
| Full | `100.7M RUB/year` | `115.9M RUB/year` |

Turnover-normalized interpretation:

| Scenario | Threshold as % of `~20B RUB/year` turnover |
| --- | ---: |
| Minimal | `0.18%-0.21%` |
| Base | `0.32%-0.37%` |
| Full | `0.50%-0.58%` |

## 10. What Total SynAPS Annual Benefit Would Be Needed?

If the annualized direct-effect floor for APS Infimum is the right baseline (`92M RUB/year`), then SynAPS would need to produce approximately:

| Scenario | Required SynAPS annual benefit at 15% | Required SynAPS annual benefit at 20% |
| --- | ---: | ---: |
| Minimal | `128.3M RUB/year` | `133.7M RUB/year` |
| Base | `156.4M RUB/year` | `166.2M RUB/year` |
| Full | `192.7M RUB/year` | `207.9M RUB/year` |

Interpretation:

1. even on the lowest credible APS Infimum baseline, SynAPS must exceed APS Infimum by a large margin to justify replacement;
2. on the higher `1.2B-1.4B` headline band, the absolute uplift requirement is smaller as a percentage of the existing claimed value, but the evidence burden is far higher because those figures are themselves not fully reconciled.

## 11. What Could Theoretically Create Additional Value For SynAPS?

These are hypotheses, not 2026 facts.

Possible future value sources:

1. more transparent benchmarked optimization for residual changeover losses;
2. better bounded-repair and what-if planning on top of a reusable kernel;
3. stronger cross-plant or cross-domain portability;
4. lower vendor lock-in and better inspectability for future industrial partners;
5. easier external benchmarking and research-driven improvement.

Current confidence of these as Moskabel-specific savings levers: **C1**.

## 12. What Makes Immediate Savings Unlikely?

The current limiting factors are practical rather than theoretical.

SynAPS still lacks public proof of:

1. cable-plant UI and operator workflows at APS Infimum maturity;
2. native MES, 1C, and RFID integration in the Moskabel stack;
3. live-plant data calibration of all relevant planning heuristics and priorities;
4. a plant-specific migration path that avoids execution risk.

Therefore the evidence-weighted base case is:

1. replacement burden is real;
2. incremental plant gain is unproven;
3. immediate net savings are unlikely.

## 13. Evidence-Bounded Decision Table

| Decision path | Economic judgment | Why |
| --- | --- | --- |
| Replace APS Infimum now with SynAPS | NO | current evidence does not support positive incremental NPV |
| Run SynAPS in shadow mode against live and historical plans | YES | lowest-risk way to test incremental value |
| Use SynAPS as a benchmark and scenario layer first | YES | strong fit with current open codebase and test evidence |
| Consider phased augmentation before full replacement | YES | economically rational if incremental KPI gates are met |
| Underwrite a full replacement thesis in investor materials today | NO | would overstate proof |

## 14. Highest-Standard Investor Interpretation

World-class industrial diligence in April 2026 should distinguish four things that are often mixed together in weak investment memos:

1. **direct current plant savings**;
2. **management-headline enterprise value claims**;
3. **replacement cost and transition risk**;
4. **strategic platform option value**.

This model keeps them separate.

That separation leads to one central conclusion:

The strategic value of SynAPS may be high, but the direct plant-economics case for replacing APS Infimum at Moskabel in 2026 is not yet proven.

## 15. Final Assessment

### Evidence-weighted plant view

Expected **incremental** savings for Moskabel from replacing APS Infimum with SynAPS in 2026:

1. **not positively demonstrable today**;
2. **likely negative in the near term** once replacement burden is included;
3. **potentially positive later** only if SynAPS can demonstrate additional annual value above the `36M-116M RUB/year` threshold band.

### Venture view

SynAPS remains highly investable as:

1. an open planning-kernel thesis;
2. a more portable asset than a single vertical APS product;
3. a stronger GitHub-native diligence surface than APS Infimum.

### Correct decision posture

1. invest in SynAPS as a kernel and augmentation thesis;
2. do not model Moskabel replacement savings as a current closed proof point;
3. require a shadow-mode program before any replacement-case underwriting.

## 16. Related Surfaces

1. `SYNAPS_VS_APS_INFIMUM_2026_04.md`
2. `INVESTOR_LETTER_SYNAPS_VS_APS_INFIMUM_MOSKABEL_2026_04.md`
3. `INVESTOR_DILIGENCE_PACKET_2026_04.md`
4. `ACADEMIC_METHODS_APPENDIX_2026_04.md`
5. `CLAIM_EVIDENCE_REGISTER_2026_04.md`