# Pharmaceutical Domain Guide

> **Scope**: Batch manufacturing, fill-finish, packaging, and regulated process scheduling under GxP constraints.

<details><summary>🇷🇺 Краткое описание</summary>

Фармацевтика использует ту же каноническую задачу, но SDST здесь определяется очисткой, валидацией и риском перекрестной контаминации. Вместо печей и ковшей важны реакторы, CIP/SIP, cleanroom-классы, hold time и полная прослеживаемость партии.
</details>

---

## 1. Domain Frame

Jobs are batches, work orders, formulation campaigns, packaging orders, or QC release queues. Work centers include reactors, granulators, tablet presses, fill-finish lines, sterilizers, packaging cells, and quality-control stations.

## 2. SDST Mapping

| Canonical setup concept | Pharmaceutical realization |
|-------------------------|----------------------------|
| State-to-state change | Product family change, potency class shift, allergen change |
| Setup time | CIP, SIP, line clearance, environmental qualification |
| Material loss | Line flush, rejected intermediate, expired hold material |
| Energy penalty | Sterilization, HVAC stabilization, cleanroom recovery |

## 3. State Dictionary

| State | Meaning |
|-------|---------|
| `idle` | Equipment is validated and available |
| `processing` | Batch step is active |
| `setup` | Cleaning, sterilization, or line clearance is active |
| `quarantine` | Waiting for QC release or deviation resolution |
| `maintenance` | Planned calibration or maintenance window |

## 4. Setup Matrix Semantics

The setup matrix usually depends on:

- active ingredient family and potency band
- allergen or contamination risk class
- cleanroom grade and microbial risk
- container, blister, or vial format
- cleaning validation recipe and minimum hold time

Transition penalties should capture both elapsed cleaning time and the business cost of discarding in-process material that cannot be re-used.

## 5. Auxiliary Resources

Typical auxiliary resources:

- QA and QC reviewers
- cleanroom slots
- sterilization capacity
- validated tooling kits
- formulation operators with qualification constraints

## 6. KPI Palette

- batch release lead time
- on-time order completion
- cleanroom utilization
- validation-driven downtime
- deviation count and rework rate
- shelf-life loss from excessive waiting

## 7. Compliance and Regulatory Context

Common frameworks:

- GMP / GxP
- FDA 21 CFR Part 11
- EU Annex 1 for sterile manufacturing
- ALCOA+ data integrity expectations

## 8. Example Parametrization

Reference schema example: [pharmaceutical.json](../../schema/examples/pharmaceutical.json)

Suggested `domain_attributes` fields:

- `product_family`
- `potency_class`
- `cleanroom_grade`
- `cip_recipe`
- `shelf_life_hours`
- `batch_traceability_required`
